"""HỌC VĂN PHONG TỪ CHUYÊN GIA – tương tự bộ nhớ dịch của SDL Trados nhưng học cả CÁCH SỬA, không chỉ câu đã dịch.

Ba nguồn tri thức, dùng NGAY từ cuốn đầu tiên (không phải đợi nhiều đợt sách):
  1. Bộ nhớ dịch (TM): câu đã được người duyệt / nhập từ TMX của sách đã xuất bản → dùng lại & làm tham khảo.
  2. Văn phong mẫu: vài cặp câu NGƯỜI dịch (đã xuất bản) cùng chuyên ngành được đưa vào lời dặn để AI bắt chước
     cách diễn đạt.
  3. Quy tắc học từ bản sửa: MỌI chỉnh sửa của chuyên gia (mục Duyệt, kiểm định mẫu, duyệt toàn văn) được ghi lại
     (trước → sau). Định kỳ AI phân tích các bản sửa, rút ra quy tắc lặp lại (≥ 3 ví dụ) → người phụ trách DUYỆT →
     quy tắc được áp cho mọi bản dịch sau của chuyên ngành đó; quy tắc thuật ngữ được đưa vào kho thuật ngữ.
"""
from __future__ import annotations

import json
import re
import time

from .db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, seg_id TEXT, domain TEXT, src TEXT, before TEXT, after TEXT,
    source TEXT, reviewer TEXT DEFAULT '', created_at REAL);
CREATE TABLE IF NOT EXISTS style_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, kind TEXT, rule TEXT, en TEXT DEFAULT '', vi TEXT DEFAULT '',
    support INTEGER DEFAULT 0, examples_json TEXT DEFAULT '[]', status TEXT DEFAULT 'proposed',
    created_at REAL, decided_at REAL);
"""
_TAGS = re.compile(r"</?(?:b|i|sup|sub)>")

LEARN_SYSTEM = """Bạn là TỔNG BIÊN TẬP của nhà xuất bản sách y học. Bạn nhận danh sách chỉnh sửa của chuyên gia trên bản dịch \
Anh → Việt (bản gốc, bản máy dịch "before", bản chuyên gia sửa "after"). Hãy rút ra các QUY TẮC LẶP LẠI mà chuyên gia áp dụng, \
để lần sau máy dịch đúng ngay từ đầu.
- Chỉ nêu quy tắc có ít nhất 3 ví dụ ủng hộ trong danh sách (support = số ví dụ); bỏ qua sửa đơn lẻ, lỗi đánh máy.
- kind = "term" khi chuyên gia thống nhất đổi cách dịch một thuật ngữ (ghi en, vi); "style" cho văn phong, cấu trúc câu, \
cách dùng từ; "format" cho cách viết số, đơn vị, viết hoa, dấu câu.
- Quy tắc viết thành câu mệnh lệnh ngắn, cụ thể, kiểm chứng được (ví dụ: "Dịch 'patients with X' là 'người bệnh X', không \
dùng 'bệnh nhân với X'"). Kèm tối đa 3 ví dụ before/after ngắn.
- Không bịa quy tắc không có trong dữ liệu."""

LEARN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["rules"],
    "properties": {"rules": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "rule", "en", "vi", "support", "examples"],
        "properties": {
            "kind": {"type": "string", "enum": ["style", "term", "format"]},
            "rule": {"type": "string"}, "en": {"type": "string"}, "vi": {"type": "string"},
            "support": {"type": "integer"},
            "examples": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["before", "after"],
                "properties": {"before": {"type": "string"}, "after": {"type": "string"}}}}}}}},
}


def _ensure(db: Database) -> None:
    with db._lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub("", s or "").replace("⟦¶⟧", " ")).strip()


def record_edit(db: Database, job_id: str, seg_id: str, domain: str, src: str, before: str, after: str,
                source: str, reviewer: str = "") -> bool:
    """Ghi lại một chỉnh sửa của người (trước → sau). Bỏ qua nếu không thực sự thay đổi."""
    if _plain(before) == _plain(after) or not _plain(after):
        return False
    _ensure(db)
    db.execute("INSERT INTO edits (job_id, seg_id, domain, src, before, after, source, reviewer, created_at) "
               "VALUES (?,?,?,?,?,?,?,?,?)", (job_id, seg_id, domain, src, before, after, source, reviewer, time.time()))
    return True


def stats(db: Database) -> list[dict]:
    _ensure(db)
    rows = db.query("SELECT domain, COUNT(*) n, MAX(created_at) last FROM edits GROUP BY domain ORDER BY n DESC")
    out = []
    for r in rows:
        rules = db.query("SELECT status, COUNT(*) n FROM style_rules WHERE domain=? GROUP BY status", (r["domain"],))
        out.append({"domain": r["domain"], "edits": r["n"], **{f"rules_{x['status']}": x["n"] for x in rules}})
    return out


def learn(db: Database, llm, domain: str, max_edits: int = 150, min_support: int = 3) -> list[dict]:
    """AI phân tích các bản sửa gần nhất của chuyên ngành → đề xuất quy tắc (trạng thái 'proposed', chờ duyệt)."""
    from .domains import chain
    _ensure(db)
    doms = chain(domain)
    rows = db.query(f"SELECT src, before, after FROM edits WHERE domain IN ({','.join('?' * len(doms))}) "
                    "ORDER BY created_at DESC LIMIT ?", (*doms, max_edits))
    if not rows:
        return []
    payload = {"edits": [{"source": _plain(r["src"])[:600], "before": _plain(r["before"])[:600],
                          "after": _plain(r["after"])[:600]} for r in rows]}
    res = llm.json_call(task="style_learn", system=[{"type": "text", "text": LEARN_SYSTEM}],
                        user="Các chỉnh sửa của chuyên gia:\n\n" + json.dumps(payload, ensure_ascii=False, indent=1),
                        schema=LEARN_SCHEMA, effort="high", payload=payload)
    existing = {re.sub(r"\W+", " ", r["rule"].lower()).strip()
                for r in db.query("SELECT rule FROM style_rules WHERE domain=?", (domain,))}
    out = []
    for r in res.get("rules", []):
        key = re.sub(r"\W+", " ", r.get("rule", "").lower()).strip()
        if not key or key in existing or int(r.get("support", 0)) < min_support:
            continue
        db.execute("INSERT INTO style_rules (domain, kind, rule, en, vi, support, examples_json, status, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (domain, r.get("kind", "style"), r["rule"], r.get("en", ""), r.get("vi", ""), int(r["support"]),
                    json.dumps(r.get("examples", [])[:3], ensure_ascii=False), "proposed", time.time()))
        existing.add(key)
        out.append(r)
    return out


def rules(db: Database, domain: str | None = None, status: str | None = None) -> list[dict]:
    _ensure(db)
    sql, params = "SELECT * FROM style_rules WHERE 1=1", []
    if domain:
        sql += " AND domain=?"
        params.append(domain)
    if status:
        sql += " AND status=?"
        params.append(status)
    out = []
    for r in db.query(sql + " ORDER BY support DESC, id", params):
        d = dict(r)
        d["examples"] = json.loads(d.pop("examples_json") or "[]")
        out.append(d)
    return out


def decide(db: Database, rule_id: int, approve: bool) -> None:
    """Duyệt / bác một quy tắc. Quy tắc thuật ngữ được duyệt → ghi vào kho thuật ngữ chuẩn của chuyên ngành."""
    _ensure(db)
    rows = db.query("SELECT * FROM style_rules WHERE id=?", (rule_id,))
    if not rows:
        return
    r = rows[0]
    db.execute("UPDATE style_rules SET status=?, decided_at=? WHERE id=?",
               ("approved" if approve else "rejected", time.time(), rule_id))
    if approve and r["kind"] == "term" and r["en"] and r["vi"]:
        db.upsert_term(r["en"], r["vi"], r["domain"], note=f"Học từ bản sửa của chuyên gia: {r['rule']}",
                       source="expert_edit", priority=80)


def rules_prompt(db: Database, domains: list[str]) -> str:
    _ensure(db)
    rows = db.query(f"SELECT rule FROM style_rules WHERE status='approved' AND kind IN ('style','format') AND domain IN "
                    f"({','.join('?' * len(domains))}) ORDER BY support DESC LIMIT 60", tuple(domains))
    if not rows:
        return ""
    return "## QUY TẮC ĐÃ HỌC TỪ BẢN SỬA CỦA CHUYÊN GIA (bắt buộc áp dụng)\n" + "\n".join(f"- {r['rule']}" for r in rows)


def exemplars(db: Database, domains: list[str], n: int = 4) -> str:
    """Văn phong mẫu: vài cặp câu NGƯỜI dịch (TMX sách đã xuất bản / chuyên gia sửa) cùng chuyên ngành."""
    rows = db.query(f"SELECT src, tgt FROM tm WHERE origin IN ('human','import') AND domain IN "
                    f"({','.join('?' * len(domains))}) AND length(src) BETWEEN 120 AND 500 "
                    "ORDER BY created_at DESC LIMIT 60", tuple(domains))
    picked = [r for r in rows if "⟦" not in r["src"].replace("⟦¶⟧", "")][:n]
    if not picked:
        return ""
    return ("## VĂN PHONG MẪU (bản dịch NGƯỜI đã xuất bản – học cách diễn đạt, KHÔNG chép nội dung)\n" +
            "\n".join(f"- EN: {_plain(r['src'])}\n  VI: {_plain(r['tgt'])}" for r in picked))
