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
    page_range = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        page_range = (int(a), int(b or a))
    tr = Translator(cfg)
    res = tr.run(args.pdf, out_dir=args.out, domain=args.domain, page_range=page_range)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_estimate(cfg, args) -> None:
    from .translator import estimate
    print(json.dumps(estimate(args.pdf, cfg.get_path("llm.model")), ensure_ascii=False, indent=2))


def cmd_glossary(cfg, args) -> None:
    from .glossary import export_csv, import_file
    db = _db(cfg)
    if args.action == "import":
        n = import_file(db, args.file, default_domain=args.domain or cfg.get_path("translation.domain"))
        print(f"Đã nhập {n} thuật ngữ.")
    elif args.action == "export":
        n = export_csv(db, args.file, status=None if args.all else "approved")
        print(f"Đã xuất {n} thuật ngữ ra {args.file}")
    elif args.action == "add":
        db.upsert_term(args.en, args.vi, args.domain or cfg.get_path("translation.domain"),
                       keep_original=args.keep, note=args.note or "")
        print("Đã thêm.")
    elif args.action == "list":
        rows = db.terms(status="candidate" if args.candidates else "approved")
        for r in rows[: args.limit]:
            print(f"#{r['id']:<6} [{r['domain']}] {r['en']}  →  {r['vi']}   ({r['source']}) {r['note'][:80]}")
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
        n = tm.import_tmx(db, p, domain) if p.suffix.lower() == ".tmx" else tm.import_bilingual_table(db, p, domain)
        print(f"Đã nhập {n} cặp câu vào bộ nhớ dịch.")
    elif args.action == "export":
        n = tm.export_tmx(db, args.file, domain=args.domain, min_quality=args.min_quality)
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


def cmd_ui(cfg, args) -> None:
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
    p.set_defaults(fn=cmd_glossary)

    p = sub.add_parser("tm", help="Bộ nhớ dịch (TMX)")
    p.add_argument("action", choices=["import", "export", "stats"])
    p.add_argument("file", nargs="?")
    p.add_argument("--domain")
    p.add_argument("--min-quality", type=int, default=85)
    p.set_defaults(fn=cmd_tm)

    p = sub.add_parser("domain", help="Quy ước văn phong theo chuyên ngành")
    p.add_argument("domain")
    p.add_argument("--file", help="File .txt/.md chứa quy ước")
    p.set_defaults(fn=cmd_domain)

    sub.add_parser("ui", help="Mở giao diện web trên localhost").set_defaults(fn=cmd_ui)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    args.fn(cfg, args)


if __name__ == "__main__":
    main()
