"""Báo cáo song ngữ HTML để biên tập viên duyệt: điểm chất lượng, lỗi phát hiện, thuật ngữ đã tra cứu."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

STATUS_VI = {"certified": "đạt chuẩn", "done": "đạt", "tm": "từ bộ nhớ dịch", "needs_review": "cần xem",
             "failed": "lỗi API"}
ROLE_VI = {"heading": "Tiêu đề", "body": "Nội dung", "caption": "Chú thích", "label": "Nhãn",
           "header_footer": "Đầu/chân trang", "figure_text": "Chữ trong hình"}


def _clean(s: str) -> str:
    return html.escape(re.sub(r"</?(?:b|i|sup|sub)>", "", s or ""))


def write_report(path: Path, doc_name: str, units: list, summary: dict, brief: dict, decided: list[dict]) -> Path:
    from .rules import restore
    rows = []
    order = {"needs_review": 0, "failed": 0, "done": 1, "certified": 2, "tm": 3}
    for u in sorted(units, key=lambda u: (order.get(u.status, 1), u.page)):
        tgt = restore(u.tgt.replace("⟦¶⟧", " ¶ "), u.mapping)
        issues = "".join(
            f'<li class="{html.escape(i.get("severity", ""))}">{html.escape(i.get("message", ""))}</li>'
            for i in u.issues)
        cls = "bad" if u.status in ("needs_review", "failed") else ("tm" if u.status in ("tm", "certified") else "")
        rows.append(
            f'<tr class="{cls}"><td>{u.page + 1}</td><td>{ROLE_VI.get(u.role, u.role)}<br><small>{u.id}</small></td>'
            f'<td>{_clean(u.plain_src)}</td><td>{_clean(tgt)}</td>'
            f'<td class="score">{u.score}<br><small>{STATUS_VI.get(u.status, u.status)}</small></td>'
            f'<td><ul>{issues}</ul></td></tr>')
    terms = "".join(
        f'<tr><td>{html.escape(d.get("en", ""))}</td><td>{html.escape(d.get("vi", ""))}</td>'
        f'<td>{html.escape(d.get("source", ""))}</td><td>{html.escape(str(d.get("confidence", "")))}</td>'
        f'<td>{" ".join(f"<a href={html.escape(s)!r}>[{k + 1}]</a>" for k, s in enumerate(d.get("sources", [])))}'
        f' {html.escape(d.get("note", ""))}</td></tr>' for d in decided)
    usage = summary.get("usage", {})
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Báo cáo dịch – {html.escape(doc_name)}</title>
<style>
:root {{ --bg:#fff; --fg:#1d1d1f; --mut:#666; --line:#ddd; --bad:#fdecec; --tm:#eef6ff; --err:#b00020; --warn:#a15c00; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16171a; --fg:#e8e8ea; --mut:#9a9aa0; --line:#33343a;
  --bad:#3a1f22; --tm:#1d2a3a; --err:#ff7b8a; --warn:#ffb454; }} }}
body {{ font-family: "Segoe UI", Roboto, Arial, sans-serif; background:var(--bg); color:var(--fg); margin:0 16px 40px; }}
h1 {{ font-size:1.4rem; }} table {{ border-collapse:collapse; width:100%; font-size:.9rem; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; vertical-align:top; text-align:left; }}
th {{ position:sticky; top:0; background:var(--bg); }} tr.bad {{ background:var(--bad); }} tr.tm {{ background:var(--tm); }}
td.score {{ font-weight:600; text-align:center; }} li.error {{ color:var(--err); }} li.warning {{ color:var(--warn); }}
li.info {{ color:var(--mut); }} ul {{ margin:0; padding-left:18px; }} .kpi {{ display:flex; flex-wrap:wrap; gap:12px; }}
.kpi div {{ border:1px solid var(--line); border-radius:8px; padding:8px 12px; }} .wrap {{ overflow-x:auto; }}
</style></head><body>
<h1>Báo cáo dịch: {html.escape(doc_name)}</h1>
<p>{html.escape(brief.get("title", ""))} — {html.escape(brief.get("specialty", ""))}</p>
<div class="kpi">
<div>Số đoạn: <b>{summary.get("segments")}</b></div>
<div>Điểm MQM TB: <b>{summary.get("avg_score")}</b>/100</div>
<div>Đạt chuẩn (tự chứng nhận): <b>{summary.get("certified")}</b></div>
<div>Trang scan: <b>{summary.get("scanned_pages", 0)}</b></div>
<div>Thuật ngữ tự duyệt: <b>{summary.get("term_enrichment", {}).get("auto_approved", 0)}</b></div>
<div>Còn lỗi nặng: <b>{summary.get("needs_review")}</b></div>
<div>Lỗi API: <b>{summary.get("failed")}</b></div>
<div>Dùng lại từ TM: <b>{summary.get("from_tm")}</b></div>
<div>Dòng chữ trong hình: <b>{summary.get("image_text_lines")}</b></div>
<div>Chi phí ước tính: <b>${usage.get("estimated_cost_usd", 0)}</b></div>
<div>Thời gian: <b>{summary.get("seconds")} s</b></div>
</div>
<h2>Thuật ngữ đã chốt cho tài liệu (tra cứu web / tổng quan)</h2>
<div class="wrap"><table><tr><th>Tiếng Anh</th><th>Tiếng Việt</th><th>Nguồn</th><th>Tin cậy</th><th>Ghi chú / dẫn chứng</th></tr>
{terms}</table></div>
<h2>Đối chiếu song ngữ (đoạn cần duyệt hiển thị trước)</h2>
<div class="wrap"><table><tr><th>Trang</th><th>Loại</th><th>Bản gốc</th><th>Bản dịch</th><th>Điểm</th><th>Ghi chú kiểm tra</th></tr>
{''.join(rows)}</table></div>
<p><small>Thống kê token: {html.escape(json.dumps(usage, ensure_ascii=False))}</small></p>
</body></html>"""
    path.write_text(page, encoding="utf-8")
    return path
