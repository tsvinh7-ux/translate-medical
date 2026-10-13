"""Dòng lệnh: python -m medtrans <lệnh> ...  (xem: python -m medtrans -h)"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from .config import ROOT, load_config
from .db import Database


def _db(cfg) -> Database:
    return Database(cfg.resolve(cfg.get_path("memory.db_path", "workspace/medtrans.db")))


def cmd_init(cfg, args) -> None:
    from .glossary import import_file
    db = _db(cfg)
    n = import_file(db, ROOT / "data" / "glossary_seed.csv", overwrite=False)
    print(f"Đã khởi tạo CSDL tại {db.path} và nạp {n} thuật ngữ mẫu.")


def cmd_translate(cfg, args) -> None:
    from .translator import Translator
    if args.mock:
        cfg["llm"]["provider"] = "mock"
    if args.lang:
        cfg["translation"]["source_lang"] = args.lang
    if args.require_termbase:
        cfg["terminology"]["require_lock"] = True
    from .config import apply_profile
    from .plans import mode_for
    name = f"plan:{args.plan}" if args.plan else args.profile
    cfg = apply_profile(cfg, name)
    page_range = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        page_range = (int(a), int(b or a))
    tr = Translator(cfg)
    if mode_for(name or "") == "scan_terms":
        res = tr.scan_terms(args.pdf, out_dir=args.out, domain=args.domain, page_range=page_range)
    else:
        res = tr.run(args.pdf, out_dir=args.out, domain=args.domain, page_range=page_range)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_estimate(cfg, args) -> None:
    from .translator import estimate
    print(json.dumps(estimate(args.pdf, cfg.get_path("llm.model"), cfg=cfg, db=_db(cfg)), ensure_ascii=False, indent=2))


def cmd_glossary(cfg, args) -> None:
    from .glossary import export_csv, import_file
    db = _db(cfg)
    if args.action == "import":
        n = import_file(db, args.file, default_domain=args.domain or cfg.get_path("translation.domain"),
                        src_lang=args.lang)
        print(f"Đã nhập {n} thuật ngữ.")
    elif args.action == "export":
        n = export_csv(db, args.file, status=None if args.all else "approved")
        print(f"Đã xuất {n} thuật ngữ ra {args.file}")
    elif args.action == "add":
        db.upsert_term(args.en, args.vi, args.domain or cfg.get_path("translation.domain"),
                       keep_original=args.keep, note=args.note or "", src_lang=args.lang)
        print("Đã thêm.")
    elif args.action == "list":
        rows = db.terms(status="candidate" if args.candidates else "approved", src_lang=args.lang)
        for r in rows[: args.limit]:
            print(f"#{r['id']:<6} [{r['domain']}] {r['en']}  →  {r['vi']}   ({r['source']}, bằng chứng "
                  f"{r.get('evidence', 0)}) {r['note'][:80]}")
        print(f"... tổng {len(rows)}")
    elif args.action == "approve":
        if args.all:
            for r in db.terms(status="candidate"):
                db.set_term_status(r["id"], "approved")
            print("Đã duyệt toàn bộ thuật ngữ đề xuất.")
        else:
            for i in args.ids:
                db.set_term_status(int(i), "approved")
            print("Đã duyệt.")
    elif args.action == "reject":
        for i in args.ids:
            db.set_term_status(int(i), "rejected")
        print("Đã loại.")


def cmd_tm(cfg, args) -> None:
    from . import tm
    db = _db(cfg)
    domain = args.domain or cfg.get_path("translation.domain")
    if args.action == "import":
        p = Path(args.file)
        n = tm.import_tmx(db, p, domain, src_lang=args.lang) if p.suffix.lower() == ".tmx" else \
            tm.import_bilingual_table(db, p, domain, src_lang=args.lang)
        print(f"Đã nhập {n} cặp câu vào bộ nhớ dịch.")
    elif args.action == "export":
        n = tm.export_tmx(db, args.file, domain=args.domain, min_quality=args.min_quality, src_lang=args.lang)
        print(f"Đã xuất {n} cặp câu ra {args.file}")
    elif args.action == "stats":
        print(json.dumps(db.tm_stats(), ensure_ascii=False, indent=2))


def cmd_domain(cfg, args) -> None:
    db = _db(cfg)
    if args.file:
        db.set_domain_notes(args.domain, Path(args.file).read_text(encoding="utf-8"))
        print("Đã lưu quy ước chuyên ngành.")
    else:
        print(db.domain_notes(args.domain) or "(chưa có)")


def cmd_analyze(cfg, args) -> None:
    from .analysis import analyze, export_xlsx
    res = analyze(args.pdf, cfg, _db(cfg), domain=args.domain)
    out = Path(args.out or Path(args.pdf).with_name(Path(args.pdf).stem + "_analysis.xlsx"))
    export_xlsx(res, out)
    t = res["totals"]
    print(f"{res['file']['name']}: {res['file']['pages_analyzed']} trang, {t['words']} từ cần dịch "
          f"({t['a4_pages']} trang A4), quy đổi {t['weighted_words']} từ, {res['terms']['unique']} thuật ngữ")
    for b in res["bands"]:
        print(f"  {b['label']:<30} {b['segments']:>7} đoạn {b['words']:>9} từ {b['percent']:>6}%")
    from .plans import ENGINES, SCOPES, matrix
    counts = {"pages": res["file"]["pages_analyzed"], "chars": t["chars"], "weighted_chars": t["weighted_chars"],
              "scanned": res["file"]["scanned_pages"], "images": res["file"]["images"]}
    mtx = matrix(cfg, counts, _db(cfg))
    print("\nDỰ TOÁN THEO GÓI (chi phí API · thời gian):")
    print(f"  {'Phạm vi':<30}" + "".join(f"{ENGINES[e]['label']:<44}" for e in ENGINES))
    for s in SCOPES:
        cells = [f"${m['estimated_cost_usd_low']}–{m['estimated_cost_usd_high']} · "
                 f"{m['estimated_time_low']}–{m['estimated_time_high']}" for m in (mtx[(e, s['key'])] for e in ENGINES)]
        print(f"  {s['label']:<30}" + "".join(f"{c:<44}" for c in cells))
    print("  (chạy: python -m medtrans translate file.pdf --plan local:revise | api:publish:w32 ...)")
    for p in res.get("profiles", []):
        print(f"  [{p['label']}] ${p['estimated_cost_usd_low']}–{p['estimated_cost_usd_high']} · "
              f"{p['estimated_time_low']}–{p['estimated_time_high']}")
    print(f"Báo cáo: {out}")


def cmd_terms(cfg, args) -> None:
    from .config import apply_profile
    from .translator import Translator
    if args.action == "scan":
        if args.mock:
            cfg["llm"]["provider"] = "mock"
        res = Translator(apply_profile(cfg, args.profile)).scan_terms(args.pdf, domain=args.domain)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        from .termbase import lock, read_xlsx
        from .translator import job_id_for, pdf_hash_of
        domain = args.domain or cfg.get_path("translation.domain")
        job = job_id_for(pdf_hash_of(args.pdf), domain, cfg.get_path("translation.source_lang", "en"))
        print(lock(_db(cfg), job, read_xlsx(args.xlsx), domain))


def cmd_calibrate(cfg, args) -> None:
    from .calibrate import calibrate
    a, _, b = args.pages.partition("-")
    rows = calibrate(args.pdf, cfg, _db(cfg), args.profiles.split(","), page_range=(int(a), int(b or a)),
                     domain=args.domain, progress=lambda f, m: print(f"[{int(f * 100):3d}%] {m}"),
                     ref_profile=args.judge)
    for r in rows:
        print(f"{r['profile']:<10} MQM {r['avg_mqm']:>5} · đạt chuẩn {r['pass_rate']}% (KTC95 {r['ci_low']}–"
              f"{r['ci_high']}%) · ${r['cost_per_a4']}/A4 · {r['sec_per_a4']} s/A4")


def cmd_finetune(cfg, args) -> None:
    from .finetune import export_jsonl
    if args.include_machine:
        print("Lưu ý: dữ liệu gồm cả bản dịch máy đã chứng nhận – chủ sở hữu tự chịu trách nhiệm tuân thủ điều khoản "
              "nhà cung cấp API (Anthropic Commercial Terms, mục D.4).")
    print(json.dumps(export_jsonl(_db(cfg), args.out, domain=args.domain, include_machine=args.include_machine,
                                  min_quality=args.min_quality), ensure_ascii=False, indent=2))


def cmd_local_check(cfg, args) -> None:
    """Kiểm tra kết nối máy chủ model local & MedCrab."""
    import httpx2
    for name in ("local", "local_judge", "medcrab"):
        c = cfg.get_path(f"llm.{name}", {}) or {}
        url = (c.get("base_url") or "").rstrip("/")
        try:
            r = httpx2.get(f"{url}/models", timeout=5, trust_env=False)
            models = [m.get("id") for m in r.json().get("data", [])]
            print(f"[OK] {name}: {url} – model sẵn có: {models}")
        except Exception as e:  # noqa: BLE001
            print(f"[--] {name}: {url} – chưa kết nối được ({e.__class__.__name__})")


def cmd_hw(cfg, args) -> None:
    """Tư vấn phần cứng + đo tốc độ model local thật (nếu máy chủ local đang chạy)."""
    from .config import DEFAULT_CONFIG
    from .hardware import bench, detect, recommend, save_throughput
    info = detect()
    rec = recommend(info)
    print(f"Hệ điều hành: {info['os']}\nCPU: {info['cpu']}\nRAM: {info['ram_gb']} GB")
    print("GPU: " + (", ".join(f"{g['name']} ({g['vram_gb']} GB)" for g in info["gpus"]) or "không phát hiện GPU NVIDIA"))
    print(f"\n→ Mức: {rec['tier']}\n→ Model local đề xuất: {rec['local_model']}\n→ Hồ sơ đề xuất: {rec['profile']}"
          f"\n→ Ghi chú: {rec['note']}")
    if rec.get("upgrade"):
        print(f"→ Nâng cấp kế tiếp: {rec['upgrade']} (xem docs/PHAN_CUNG.md)")
    try:
        b = bench(cfg)
        print(f"\nĐo thật model local '{b['model']}': {b['tokens_per_sec']} token/giây "
              f"({b['output_tokens']} token / {b['seconds']} s), JSON hợp lệ: {b['json_ok']}")
        print(f"Bản dịch thử: {b['sample_translation']}")
        if args.save:
            save_throughput(DEFAULT_CONFIG, b["tokens_per_sec"])
            print("Đã lưu tốc độ đo được vào config.yaml (llm.local.throughput_tokens_per_sec).")
    except Exception as e:  # noqa: BLE001
        print(f"\n(Chưa đo được model local: {e}. Cài Ollama và chạy: ollama pull {rec['local_model'].split()[0]})")


def cmd_ui(cfg, args) -> None:
    from .branding import write_streamlit_theme
    write_streamlit_theme(cfg)
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.address", "localhost"])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="medtrans", description="Dịch tài liệu y khoa PDF Anh → Việt, giữ bố cục")
    ap.add_argument("--config", help="Đường dẫn config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Khởi tạo CSDL và nạp thuật ngữ mẫu").set_defaults(fn=cmd_init)

    p = sub.add_parser("translate", help="Dịch một file PDF")
    p.add_argument("pdf")
    p.add_argument("--domain", help="Chuyên ngành (cardiology, oncology, ...)")
    p.add_argument("--pages", help="Chỉ dịch các trang, ví dụ 1-10")
    p.add_argument("--out", help="Thư mục kết quả")
    p.add_argument("--mock", action="store_true", help="Chạy thử không gọi API")
    p.add_argument("--lang", help="Ngôn ngữ nguồn (mặc định theo config, hiện có: en)")
    p.add_argument("--profile", help="Hồ sơ chất lượng/chi phí: draft | economy | balanced | premium")
    p.add_argument("--plan", help="Gói chuẩn <phương thức>:<phạm vi>[:w<luồng>] – phương thức: local | api; phạm vi: "
                                  "termbase | draft | edit | revise | publish (vd local:revise, api:publish:w32)")
    p.add_argument("--require-termbase", action="store_true", help="Dừng sau quét thuật ngữ, chờ khoá termbase")
    p.set_defaults(fn=cmd_translate)

    p = sub.add_parser("estimate", help="Ước tính chi phí")
    p.add_argument("pdf")
    p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("glossary", help="Quản lý thuật ngữ")
    p.add_argument("action", choices=["import", "export", "add", "list", "approve", "reject"])
    p.add_argument("file", nargs="?")
    p.add_argument("--en")
    p.add_argument("--vi")
    p.add_argument("--note")
    p.add_argument("--keep", action="store_true", help="Giữ nguyên tiếng Anh")
    p.add_argument("--domain")
    p.add_argument("--candidates", action="store_true", help="Liệt kê thuật ngữ đề xuất chờ duyệt")
    p.add_argument("--all", action="store_true")
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--lang", default="en", help="Ngôn ngữ nguồn của thuật ngữ")
    p.set_defaults(fn=cmd_glossary)

    p = sub.add_parser("tm", help="Bộ nhớ dịch (TMX)")
    p.add_argument("action", choices=["import", "export", "stats"])
    p.add_argument("file", nargs="?")
    p.add_argument("--domain")
    p.add_argument("--min-quality", type=int, default=95)
    p.add_argument("--lang", default="en", help="Ngôn ngữ nguồn")
    p.set_defaults(fn=cmd_tm)

    p = sub.add_parser("domain", help="Quy ước văn phong theo chuyên ngành")
    p.add_argument("domain")
    p.add_argument("--file", help="File .txt/.md chứa quy ước")
    p.set_defaults(fn=cmd_domain)

    p = sub.add_parser("analyze", help="Phân tích tài liệu (số từ, mức khớp, lặp lại, thuật ngữ, dự báo)")
    p.add_argument("pdf")
    p.add_argument("--domain")
    p.add_argument("--out", help="File Excel kết quả")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("terms", help="Termbase dự án: scan (quét & xuất Excel) | lock (nhập Excel đã kiểm tra & khoá)")
    p.add_argument("action", choices=["scan", "lock"])
    p.add_argument("pdf")
    p.add_argument("xlsx", nargs="?")
    p.add_argument("--domain")
    p.add_argument("--profile")
    p.add_argument("--mock", action="store_true")
    p.set_defaults(fn=cmd_terms)

    p = sub.add_parser("calibrate", help="Hiệu chuẩn hồ sơ trên trang mẫu (MQM, xác suất đạt chuẩn, chi phí, thời gian)")
    p.add_argument("pdf")
    p.add_argument("--pages", default="1-10")
    p.add_argument("--profiles", default="economy,balanced,premium")
    p.add_argument("--judge", default="premium", help="Hồ sơ của giám khảo tham chiếu (premium | local_quality)")
    p.add_argument("--domain")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("finetune", help="Xuất dữ liệu JSONL để tinh chỉnh model local (LoRA)")
    p.add_argument("--out", default="workspace/finetune")
    p.add_argument("--domain")
    p.add_argument("--min-quality", type=int, default=95)
    p.add_argument("--include-machine", action="store_true",
                   help="Gồm cả bản dịch máy đã chứng nhận (đạt cổng MQM + kiểm toán trung thành)")
    p.set_defaults(fn=cmd_finetune)

    sub.add_parser("local-check", help="Kiểm tra kết nối model local / MedCrab").set_defaults(fn=cmd_local_check)

    p = sub.add_parser("hw", help="Tư vấn phần cứng & đo tốc độ model local thật trên máy")
    p.add_argument("--save", action="store_true", help="Lưu tốc độ đo được vào config.yaml")
    p.set_defaults(fn=cmd_hw)

    sub.add_parser("ui", help="Mở giao diện web trên localhost").set_defaults(fn=cmd_ui)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    args.fn(cfg, args)


if __name__ == "__main__":
    main()
