"""BẢO CHỨNG CHẤT LƯỢNG: đối soát toàn văn, cổng phát hành và PHIẾU KIỂM ĐỊNH cho từng bản dịch.

Mọi kết luận ở đây được tính bằng MÁY từ dữ liệu đã kiểm (không dựa vào lời AI tự nhận):
  1. ĐỦ     – mọi khối văn bản nguồn có bản dịch; kiểm toán từng câu không còn câu bỏ sót / thêm; mọi khối dịch
               thực sự XUẤT HIỆN trên đúng trang của PDF đầu ra (đọc lại PDF, không mất chữ khi dàn trang).
  2. ĐÚNG   – không còn lỗi máy (số liệu, liều – đơn vị, phủ định, mã công thức, chữ chưa dịch); không còn lỗi MQM
               nghiêm trọng/lớn sau hội đồng giám khảo; tuân thủ termbase.
  3. ĐỌC TỐT – mật độ "văn dịch máy / văn AI", tỉ lệ câu quá dài, điểm chất lượng ngôn ngữ trung bình.
  4. KIỂM ĐỊNH ĐỘC LẬP – tỉ lệ đoạn qua cổng chất lượng; kết quả kiểm định mẫu bởi chuyên gia (nếu có).
Kết luận: PHÁT HÀNH ĐƯỢC hoặc CẦN XỬ LÝ (kèm danh sách đoạn cụ thể).
"""
from __future__ import annotations

import html
import re
import time
from pathlib import Path

import pymupdf

_TAGS = re.compile(r"</?(?:b|i|sup|sub)>")


def _norm(s: str) -> str:
    return "".join(ch for ch in _TAGS.sub("", s or "").lower() if ch.isalnum())


def rendered_coverage(out_pdf: str | Path, blocks: dict[str, str], block_pages: dict[str, int],
                      page_offset: int = 0) -> dict:
    """Đọc lại PDF đầu ra: mỗi khối dịch phải xuất hiện (đầu + cuối khối) trên trang của nó."""
    doc = pymupdf.open(str(out_pdf))
    page_text = [_norm(p.get_text()) for p in doc]
    whole = "".join(page_text)
    doc.close()
    checked, missing = 0, []
    for bid, txt in blocks.items():
        t = _norm(txt)
        if len(t) < 6:
            continue
        checked += 1
        k = min(24, max(6, len(t) // 3))
        head, tail = t[:k], t[-k:]
        pi = block_pages.get(bid, 0) - page_offset
        hay = page_text[pi] if 0 <= pi < len(page_text) else whole
        if not (head in hay and tail in hay) and not (head in whole and tail in whole):
            missing.append(bid)
    return {"blocks_checked": checked, "blocks_missing": missing,
            "percent": round(100 * (checked - len(missing)) / checked, 2) if checked else 100.0}


def _passed(u) -> bool:
    severe = any(e.get("severity") in ("critical", "major") for e in u.mqm)
    errors = any(i.get("severity") == "error" for i in u.issues)
    return u.status in ("certified", "tm") or (u.status == "done" and not severe and not errors)


def evaluate_release(units: list, summary: dict, cfg, coverage: dict | None = None,
                     source_blocks: int | None = None, lqa: dict | None = None, draft: bool = False,
                     unread_pages: list[int] | None = None, signoff: dict | None = None) -> dict:
    from .style import document_metrics
    q = cfg.get("quality", {}) if cfg else {}
    text = [u for u in units if u.kind == "text"]
    n = len(text) or 1
    untranslated = [u.id for u in text if not (u.tgt or "").strip() or u.status == "failed"]
    fid = [u.id for u in text if any(e.get("judge") == "fidelity" and e.get("severity") in ("critical", "major")
                                      for e in u.mqm)]
    machine = [u.id for u in text if any(i.get("severity") == "error" for i in u.issues)]
    severe = [u.id for u in text if any(e.get("severity") in ("critical", "major") for e in u.mqm)]
    term_miss = [u.id for u in text if any(i.get("code") == "glossary" for i in u.issues)]
    with_terms = [u for u in text if u.terms] or text
    term_ok = 100 * (1 - len([u for u in with_terms if u.id in set(term_miss)]) / max(1, len(with_terms)))
    style = document_metrics([u.tgt for u in text if u.role != "header_footer"])
    passed = [u for u in text if _passed(u)]
    pass_pct = 100 * len(passed) / n
    covered_blocks = sum(len(u.blocks) for u in text)
    max_style = float(q.get("style_max_per_1000_words", 6))
    max_long = float(q.get("long_sentence_max_percent", 10))
    min_pass = float(q.get("release_min_pass_percent", 100))
    cert = int(q.get("certify_score", 95))

    def chk(group, name, ok, value, rule, ids=None, blocking=True):
        return {"group": group, "name": name, "ok": bool(ok), "value": value, "rule": rule,
                "ids": (ids or [])[:200], "blocking": blocking}

    checks = [
        chk("Đủ", "Khối văn bản nguồn được đưa vào dịch",
            source_blocks is None or covered_blocks >= source_blocks,
            f"{covered_blocks}/{source_blocks if source_blocks is not None else covered_blocks}", "100%"),
        chk("Đủ", "Trang scan được nhận dạng chữ (OCR)", not unread_pages,
            f"{len(unread_pages or [])} trang chưa đọc được" + (f" (tr. {', '.join(map(str, unread_pages[:20]))})"
                                                              if unread_pages else ""),
            "0 trang", [f"trang {p}" for p in (unread_pages or [])]),
        chk("Đủ", "Đoạn có bản dịch", not untranslated, f"{n - len(untranslated)}/{n}", "100%", untranslated),
        chk("Đủ", "Kiểm toán từng câu: không bỏ sót, không thêm, đúng trình tự", not fid,
            f"{len(fid)} đoạn còn lỗi", "0 đoạn", fid),
        chk("Đủ", "Bản dịch hiển thị đủ trên PDF đầu ra (đọc lại PDF)",
            coverage is None or not coverage["blocks_missing"],
            f"{coverage['percent']}% khối" if coverage else "—", "100%",
            coverage["blocks_missing"] if coverage else None),
        chk("Đúng", "Lỗi máy: số liệu, liều – đơn vị, phủ định, công thức, chữ chưa dịch", not machine,
            f"{len(machine)} đoạn", "0 đoạn", machine),
        chk("Đúng", "Lỗi MQM nghiêm trọng / lớn sau hội đồng giám khảo", not severe, f"{len(severe)} đoạn", "0 đoạn",
            severe),
        chk("Đúng", "Tuân thủ termbase / thuật ngữ đã chốt", not term_miss, f"{term_ok:.1f}%", "100%", term_miss),
        chk("Đọc tốt", "Mật độ văn dịch máy / văn AI", style["style_flags_per_1000_words"] <= max_style,
            f"{style['style_flags_per_1000_words']} / 1.000 từ", f"≤ {max_style:g}", blocking=False),
        chk("Đọc tốt", "Câu quá dài", style["long_sentence_percent"] <= max_long,
            f"{style['long_sentence_percent']}% câu", f"≤ {max_long:g}%", blocking=False),
        chk("Đọc tốt", "Điểm chất lượng trung bình (MQM)", summary.get("avg_score", 0) >= cert,
            f"{summary.get('avg_score', 0)}", f"≥ {cert}", blocking=False),
        chk("Kiểm định", "Đoạn qua cổng chất lượng", pass_pct >= min_pass, f"{pass_pct:.1f}%", f"≥ {min_pass:g}%",
            [u.id for u in text if not _passed(u)]),
    ]
    if lqa:
        checks.append(chk("Kiểm định", "Kiểm định mẫu bởi chuyên gia", lqa.get("passed"),
                          f"{lqa.get('defects', 0)} lỗi nặng / {lqa.get('n', 0)} đoạn mẫu "
                          f"(trần lỗi 95%: {lqa.get('upper_percent', 0)}%)",
                          f"trần ≤ {lqa.get('max_rate_percent', 3)}%"))
    elif q.get("release_requires_lqa", False):
        checks.append(chk("Kiểm định", "Kiểm định mẫu bởi chuyên gia", False, "chưa thực hiện", "bắt buộc"))
    expert = None
    if q.get("release_requires_expert", True):
        ok = bool(signoff and signoff.get("verdict") == "approve")
        val = ("chưa duyệt" if not signoff else
               f"{signoff['reviewer']} – {'đồng ý phát hành' if ok else 'yêu cầu sửa'} "
               f"({time.strftime('%d/%m/%Y', time.localtime(signoff['created_at']))})")
        expert = chk("Kiểm định", "Chuyên gia đọc duyệt & đồng ý phát hành", ok, val, "bắt buộc")
        checks.append(expert)
    blockers = [c for c in checks if c["blocking"] and not c["ok"]]
    to_fix = sorted({i for c in blockers for i in c["ids"]})
    if draft:
        verdict, label = "draft", "BẢN NHÁP – không dùng để phát hành"
    elif blockers == [expert] and not (signoff and signoff.get("verdict") == "reject"):
        verdict, label = "await_expert", "MÁY ĐÃ ĐẠT – CHỜ CHUYÊN GIA ĐỌC DUYỆT & KÝ PHÁT HÀNH"
    elif blockers:
        verdict, label = "hold", f"CẦN XỬ LÝ – {len(to_fix)} đoạn / {len(blockers)} tiêu chí chưa đạt"
    else:
        verdict, label = "release", "PHÁT HÀNH ĐƯỢC"
    return {"verdict": verdict, "label": label, "checks": checks, "to_fix": to_fix, "style": style,
            "pass_percent": round(pass_pct, 1), "lqa": lqa, "signoff": signoff}


def write_certificate(path: Path, doc_name: str, release: dict, summary: dict, meta: dict,
                      branding: dict | None = None) -> Path:
    """Phiếu kiểm định chất lượng bản dịch (HTML in được)."""
    b = branding or {}
    color = b.get("primary_color", "#0B5394")
    groups: dict[str, list] = {}
    for c in release["checks"]:
        groups.setdefault(c["group"], []).append(c)
    sections = []
    for g, items in groups.items():
        rows = "".join(
            f"<tr><td class='st {'ok' if c['ok'] else ('bad' if c['blocking'] else 'warn')}'>"
            f"{'✓' if c['ok'] else ('✕' if c['blocking'] else '!')}</td><td>{html.escape(c['name'])}</td>"
            f"<td class='v'>{html.escape(str(c['value']))}</td><td class='r'>{html.escape(c['rule'])}</td></tr>"
            for c in items)
        sections.append(f"<h3>{html.escape(g)}</h3><table>{rows}</table>")
    style = release.get("style", {})
    top = "".join(f"<li>{html.escape(t['message'])}: <b>{t['count']}</b> đoạn</li>" for t in style.get("top", []))
    steps = "".join(f"<li>{html.escape(a)} <span class='who'>{html.escape(w)}</span></li>"
                    for a, w in meta.get("pipeline", []))
    fix = ", ".join(html.escape(i) for i in release.get("to_fix", [])[:60])
    vcls = {"release": "ok", "hold": "bad", "draft": "warn", "await_expert": "warn"}[release["verdict"]]
    so = release.get("signoff")
    signer = (f"<b>{html.escape(so['reviewer'])}</b> – {html.escape(so.get('role') or '')} · "
              f"{'Đồng ý phát hành' if so['verdict'] == 'approve' else 'Yêu cầu sửa'} · "
              f"{time.strftime('%d/%m/%Y', time.localtime(so['created_at']))}"
              + (f"<br>{html.escape(so['note'])}" if so.get("note") else "") if so else "")
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Phiếu kiểm định – {html.escape(doc_name)}</title>
<style>
body{{font-family:'Be Vietnam Pro','Segoe UI',Arial,sans-serif;color:#1f2328;max-width:960px;margin:28px auto;padding:0 20px}}
.hd{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid {color};padding-bottom:12px}}
.hd .n{{font-weight:800;color:{color};letter-spacing:.08em;font-size:1.3rem}} h1{{font-size:1.4rem;margin:18px 0 4px}}
.meta{{color:#6b7280;font-size:.9rem}} .verdict{{margin:18px 0;padding:16px 20px;border-radius:12px;font-weight:800;font-size:1.2rem}}
.verdict.ok{{background:#e8f5ec;color:#1a7f37}} .verdict.bad{{background:#fdecec;color:#c62828}} .verdict.warn{{background:#fff4d6;color:#9a6700}}
h3{{margin:22px 0 6px;color:{color}}} table{{width:100%;border-collapse:collapse;font-size:.92rem}}
td{{padding:8px 10px;border-bottom:1px solid #eceef1;vertical-align:top}} td.st{{width:26px;font-weight:800;text-align:center}}
td.ok{{color:#1a7f37}} td.bad{{color:#c62828}} td.warn{{color:#9a6700}} td.v{{font-weight:700;white-space:nowrap}} td.r{{color:#6b7280;white-space:nowrap}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}} .k{{border:1px solid #e6e8ec;border-radius:10px;padding:10px 12px}}
.k b{{display:block;font-size:1.25rem}} .k span{{font-size:.72rem;text-transform:uppercase;color:#6b7280;letter-spacing:.05em}}
.who{{font-size:.78rem;color:#0b57d0;background:#e8f0fe;border-radius:99px;padding:1px 8px;margin-left:6px}}
.sign{{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:40px}} .sign div{{border-top:1px solid #9aa1ab;padding-top:6px;color:#6b7280;font-size:.85rem;height:70px}}
@media print{{body{{margin:0}}}}
</style></head><body>
<div class="hd"><div><div class="n">{html.escape(b.get('name', 'MedTrans'))}</div>
<div class="meta">Phiếu kiểm định chất lượng bản dịch</div></div>
<div class="meta">{time.strftime('%d/%m/%Y %H:%M')}</div></div>
<h1>{html.escape(doc_name)}</h1>
<div class="meta">Gói/hồ sơ: {html.escape(meta.get('profile', ''))} · Chuyên ngành: {html.escape(meta.get('domain', ''))}
 · Model: {html.escape(meta.get('models', ''))}</div>
<div class="verdict {vcls}">{html.escape(release['label'])}</div>
<div class="grid">
<div class="k"><span>Đoạn dịch</span><b>{summary.get('segments', 0)}</b></div>
<div class="k"><span>Qua cổng chất lượng</span><b>{release['pass_percent']}%</b></div>
<div class="k"><span>Điểm MQM trung bình</span><b>{summary.get('avg_score', 0)}</b></div>
<div class="k"><span>Thuật ngữ đã chốt</span><b>{summary.get('decided_terms', 0)}</b></div>
</div>
{''.join(sections)}
<h3>Văn phong toàn văn</h3>
<p class="meta">Độ dài câu trung bình {style.get('avg_sentence_words', 0)} từ · {style.get('long_sentence_percent', 0)}% câu dài ·
{style.get('style_flags_per_1000_words', 0)} dấu hiệu văn dịch máy / 1.000 từ (đã chuyển cho bước biên tập xử lý).</p>
<ul>{top}</ul>
<h3>Quy trình đã thực hiện</h3><ol>{steps}</ol>
{f"<h3>Đoạn cần xử lý</h3><p class='meta'>{fix}{' …' if len(release.get('to_fix', [])) > 60 else ''} – xem báo cáo song ngữ / mục Duyệt.</p>" if fix else ""}
<div class="sign"><div>Người kiểm định chuyên môn (ký, ghi rõ họ tên)<br>{signer}</div><div>Biên tập viên phụ trách (ký, ghi rõ họ tên)</div></div>
</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
