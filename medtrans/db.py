"""Cơ sở dữ liệu SQLite: thuật ngữ, bộ nhớ dịch (TM), cache tra cứu, tiến độ công việc."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    en TEXT NOT NULL,
    en_norm TEXT NOT NULL,
    vi TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'general_medicine',
    category TEXT DEFAULT '',          -- disease, drug, anatomy, procedure, lab, abbreviation...
    note TEXT DEFAULT '',              -- ghi chú ngữ cảnh / định nghĩa
    keep_original INTEGER DEFAULT 0,   -- 1 = giữ nguyên tiếng Anh (không dịch)
    gloss_first INTEGER DEFAULT 0,     -- 1 = lần đầu ghi "Tiếng Việt (English)"
    case_sensitive INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 50,       -- cao hơn = ưu tiên hơn khi trùng
    source TEXT DEFAULT 'manual',      -- manual | import | web | learned
    source_url TEXT DEFAULT '',
    status TEXT DEFAULT 'approved',    -- approved | candidate | rejected
    evidence INTEGER DEFAULT 0,        -- số đoạn đạt chuẩn đã dùng nhất quán cặp thuật ngữ này
    src_lang TEXT DEFAULT 'en',        -- ngôn ngữ nguồn (cột en = thuật ngữ nguồn)
    created_at REAL,
    updated_at REAL,
    UNIQUE(en_norm, domain, src_lang)
);
CREATE INDEX IF NOT EXISTS idx_gloss_status ON glossary(status);

CREATE TABLE IF NOT EXISTS tm (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    src_norm TEXT NOT NULL,
    src_hash TEXT NOT NULL,
    tgt TEXT NOT NULL,
    domain TEXT DEFAULT 'general_medicine',
    doc_name TEXT DEFAULT '',
    role TEXT DEFAULT 'body',
    quality INTEGER DEFAULT 0,         -- điểm MQM 0-100 do giám khảo độc lập chấm
    approved INTEGER DEFAULT 0,        -- 1 = đạt chuẩn chứng nhận (tự động) hoặc người duyệt xác nhận
    src_lang TEXT DEFAULT 'en',
    created_at REAL,
    UNIQUE(src_hash, domain, src_lang)
);
CREATE VIRTUAL TABLE IF NOT EXISTS tm_fts USING fts5(src_norm, content='tm', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS tm_ai AFTER INSERT ON tm BEGIN
  INSERT INTO tm_fts(rowid, src_norm) VALUES (new.id, new.src_norm);
END;
CREATE TRIGGER IF NOT EXISTS tm_ad AFTER DELETE ON tm BEGIN
  INSERT INTO tm_fts(tm_fts, rowid, src_norm) VALUES('delete', old.id, old.src_norm);
END;
CREATE TRIGGER IF NOT EXISTS tm_au AFTER UPDATE ON tm BEGIN
  INSERT INTO tm_fts(tm_fts, rowid, src_norm) VALUES('delete', old.id, old.src_norm);
  INSERT INTO tm_fts(rowid, src_norm) VALUES (new.id, new.src_norm);
END;

CREATE TABLE IF NOT EXISTS research_cache (
    key TEXT PRIMARY KEY,
    term TEXT,
    result_json TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS domain_context (
    domain TEXT PRIMARY KEY,
    style_notes TEXT DEFAULT '',      -- quy ước văn phong riêng cho chuyên ngành
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    pdf_path TEXT,
    pdf_hash TEXT,
    domain TEXT,
    status TEXT,
    brief_json TEXT,
    usage_json TEXT,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS perf (
    job_id TEXT,
    chars INTEGER,
    seconds REAL,
    sec_per_kchar REAL,               -- giây thực tế / 1.000 ký tự (đã chạy song song `workers` luồng)
    workers INTEGER,
    effort TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS segments (
    job_id TEXT,
    seg_id TEXT,
    page INTEGER,
    kind TEXT,                         -- text | image
    role TEXT,
    src TEXT,
    tgt TEXT,
    status TEXT,                       -- done | tm | failed
    score INTEGER,
    issues_json TEXT,
    updated_at REAL,
    PRIMARY KEY (job_id, seg_id)
);
"""


def normalize_text(s: str) -> str:
    """Chuẩn hoá để so khớp: NFC, gộp khoảng trắng, chữ thường."""
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace("­", "").replace("‐", "-").replace("‑", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def text_hash(s: str) -> str:
    return hashlib.sha1(normalize_text(s).encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.conn.executescript(SCHEMA)
        self._finish_migration()
        self.conn.commit()

    # ------------------------------------------------------------ migration
    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self) -> None:
        """CSDL tạo từ phiên bản cũ (chưa có src_lang/evidence) → dựng lại bảng, giữ dữ liệu."""
        self._legacy = False
        cols = self._columns("glossary")
        if cols and "src_lang" not in cols:
            self._legacy = True
            self.conn.executescript("""
                DROP INDEX IF EXISTS idx_gloss_status;
                DROP TRIGGER IF EXISTS tm_ai; DROP TRIGGER IF EXISTS tm_ad; DROP TRIGGER IF EXISTS tm_au;
                DROP TABLE IF EXISTS tm_fts;
                ALTER TABLE glossary RENAME TO glossary_old;
                ALTER TABLE tm RENAME TO tm_old;
            """)

    def _finish_migration(self) -> None:
        if not getattr(self, "_legacy", False):
            return
        g = ["en", "en_norm", "vi", "domain", "category", "note", "keep_original", "gloss_first", "case_sensitive",
             "priority", "source", "source_url", "status", "created_at", "updated_at"]
        t = ["src", "src_norm", "src_hash", "tgt", "domain", "doc_name", "role", "quality", "approved", "created_at"]
        self.conn.executescript(f"""
            INSERT OR IGNORE INTO glossary ({','.join(g)}) SELECT {','.join(g)} FROM glossary_old;
            INSERT OR IGNORE INTO tm ({','.join(t)}) SELECT {','.join(t)} FROM tm_old;
            DROP TABLE glossary_old; DROP TABLE tm_old;
        """)

    # ------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    # ------------------------------------------------------------ glossary
    def upsert_term(self, en: str, vi: str, domain: str = "general_medicine", *, category: str = "",
                    note: str = "", keep_original: bool = False, gloss_first: bool = False,
                    case_sensitive: bool = False, priority: int = 50, source: str = "manual",
                    source_url: str = "", status: str = "approved", overwrite: bool = True,
                    src_lang: str = "en") -> None:
        en = unicodedata.normalize("NFC", en.strip())
        vi = unicodedata.normalize("NFC", vi.strip())
        if not en or (not vi and not keep_original):
            return
        if keep_original and not vi:
            vi = en
        now = time.time()
        en_norm = en if case_sensitive else normalize_text(en)
        existing = self.query("SELECT id, status, source FROM glossary WHERE en_norm=? AND domain=? AND src_lang=?",
                              (en_norm, domain, src_lang))
        if existing:
            row = existing[0]
            # Không để thuật ngữ đề xuất (candidate) ghi đè thuật ngữ đã duyệt
            if not overwrite or (status == "candidate" and row["status"] == "approved"):
                return
            self.execute(
                """UPDATE glossary SET en=?, vi=?, category=?, note=?, keep_original=?, gloss_first=?,
                   case_sensitive=?, priority=?, source=?, source_url=?, status=?, updated_at=? WHERE id=?""",
                (en, vi, category, note, int(keep_original), int(gloss_first), int(case_sensitive),
                 priority, source, source_url, status, now, row["id"]))
        else:
            self.execute(
                """INSERT INTO glossary (en, en_norm, vi, domain, category, note, keep_original, gloss_first,
                   case_sensitive, priority, source, source_url, status, src_lang, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (en, en_norm, vi, domain, category, note, int(keep_original), int(gloss_first),
                 int(case_sensitive), priority, source, source_url, status, src_lang, now, now))

    def add_evidence(self, en: str, vi: str, domain: str, n: int, *, src_lang: str = "en", source: str = "learned",
                     category: str = "", note: str = "") -> dict | None:
        """Cộng bằng chứng cho cặp thuật ngữ (tạo mới ở trạng thái đề xuất nếu chưa có). Trả về bản ghi."""
        en_norm = normalize_text(en)
        rows = self.query("SELECT * FROM glossary WHERE en_norm=? AND domain=? AND src_lang=?",
                          (en_norm, domain, src_lang))
        if not rows:
            self.upsert_term(en, vi, domain, category=category, note=note, source=source, status="candidate",
                             src_lang=src_lang)
            rows = self.query("SELECT * FROM glossary WHERE en_norm=? AND domain=? AND src_lang=?",
                              (en_norm, domain, src_lang))
            if not rows:
                return None
        row = dict(rows[0])
        if normalize_text(row["vi"]) == normalize_text(vi):
            self.execute("UPDATE glossary SET evidence = evidence + ?, updated_at=? WHERE id=?",
                         (n, time.time(), row["id"]))
            row["evidence"] = (row.get("evidence") or 0) + n
        return row

    def terms(self, domains: Iterable[str] | None = None, status: str | None = "approved",
              src_lang: str | None = "en") -> list[dict]:
        sql = "SELECT * FROM glossary WHERE 1=1"
        params: list[Any] = []
        if src_lang:
            sql += " AND src_lang=?"
            params.append(src_lang)
        if status:
            sql += " AND status=?"
            params.append(status)
        if domains:
            d = list(domains)
            sql += f" AND domain IN ({','.join('?' * len(d))})"
            params.extend(d)
        sql += " ORDER BY priority DESC, length(en) DESC"
        return [dict(r) for r in self.query(sql, params)]

    def set_term_status(self, term_id: int, status: str, note: str | None = None) -> None:
        if note is None:
            self.execute("UPDATE glossary SET status=?, updated_at=? WHERE id=?", (status, time.time(), term_id))
        else:
            self.execute("UPDATE glossary SET status=?, note=?, updated_at=? WHERE id=?",
                         (status, note, time.time(), term_id))

    def delete_term(self, term_id: int) -> None:
        self.execute("DELETE FROM glossary WHERE id=?", (term_id,))

    # ------------------------------------------------------------ TM
    def tm_add(self, src: str, tgt: str, domain: str, *, doc_name: str = "", role: str = "body",
               quality: int = 0, approved: bool = False, src_lang: str = "en") -> None:
        h = text_hash(src)
        now = time.time()
        existing = self.query("SELECT id, quality, approved FROM tm WHERE src_hash=? AND domain=? AND src_lang=?",
                              (h, domain, src_lang))
        if existing:
            row = existing[0]
            # Không ghi đè bản đã được người duyệt bằng bản máy có điểm thấp hơn
            if row["approved"] and not approved:
                return
            if not approved and row["quality"] > quality:
                return
            self.execute("UPDATE tm SET tgt=?, quality=?, approved=?, doc_name=?, role=? WHERE id=?",
                         (tgt, quality, int(approved), doc_name, role, row["id"]))
        else:
            self.execute(
                """INSERT INTO tm (src, src_norm, src_hash, tgt, domain, doc_name, role, quality, approved, src_lang,
                   created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (src, normalize_text(src), h, tgt, domain, doc_name, role, quality, int(approved), src_lang, now))

    def tm_exact(self, src: str, domains: Iterable[str], src_lang: str = "en") -> dict | None:
        d = list(domains)
        rows = self.query(
            f"SELECT * FROM tm WHERE src_hash=? AND src_lang=? AND domain IN ({','.join('?' * len(d))}) "
            "ORDER BY approved DESC, quality DESC LIMIT 1", [text_hash(src), src_lang, *d])
        return dict(rows[0]) if rows else None

    def tm_candidates(self, src: str, domains: Iterable[str], limit: int = 30, src_lang: str = "en") -> list[dict]:
        words = [w for w in re.findall(r"[^\W\d_][\w\-]{3,}", normalize_text(src))][:12]
        if not words:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in dict.fromkeys(words))
        d = list(domains)
        rows = self.query(
            f"""SELECT tm.* FROM tm_fts JOIN tm ON tm.id = tm_fts.rowid
                WHERE tm_fts MATCH ? AND tm.src_lang=? AND tm.domain IN ({','.join('?' * len(d))})
                ORDER BY bm25(tm_fts) LIMIT ?""", [fts_query, src_lang, *d, limit])
        return [dict(r) for r in rows]

    def tm_stats(self) -> dict:
        r = self.query("SELECT COUNT(*) n, SUM(approved) a, AVG(quality) q FROM tm")[0]
        return {"segments": r["n"] or 0, "approved": r["a"] or 0, "avg_quality": round(r["q"] or 0, 1)}

    # ------------------------------------------------------------ research cache
    def research_get(self, key: str) -> dict | None:
        rows = self.query("SELECT result_json FROM research_cache WHERE key=?", (key,))
        return json.loads(rows[0]["result_json"]) if rows else None

    def research_put(self, key: str, term: str, result: dict) -> None:
        self.execute("INSERT OR REPLACE INTO research_cache (key, term, result_json, created_at) VALUES (?,?,?,?)",
                     (key, term, json.dumps(result, ensure_ascii=False), time.time()))

    # ------------------------------------------------------------ domain context
    def domain_notes(self, domain: str) -> str:
        rows = self.query("SELECT style_notes FROM domain_context WHERE domain=?", (domain,))
        return rows[0]["style_notes"] if rows else ""

    def set_domain_notes(self, domain: str, notes: str) -> None:
        self.execute("INSERT OR REPLACE INTO domain_context (domain, style_notes, updated_at) VALUES (?,?,?)",
                     (domain, notes, time.time()))

    # ------------------------------------------------------------ jobs / segments
    def job_upsert(self, job_id: str, **fields: Any) -> None:
        now = time.time()
        if not self.query("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)):
            self.execute("INSERT INTO jobs (job_id, created_at, updated_at) VALUES (?,?,?)", (job_id, now, now))
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            self.execute(f"UPDATE jobs SET {k}=?, updated_at=? WHERE job_id=?", (v, now, job_id))

    def perf_add(self, job_id: str, chars: int, seconds: float, workers: int, effort: str) -> None:
        self.execute("INSERT INTO perf (job_id, chars, seconds, sec_per_kchar, workers, effort, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (job_id, chars, seconds, seconds / max(1, chars) * 1000, workers,
                                                effort, time.time()))

    def job_get(self, job_id: str) -> dict | None:
        rows = self.query("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        return dict(rows[0]) if rows else None

    def segment_save(self, job_id: str, seg_id: str, *, page: int, kind: str, role: str, src: str, tgt: str,
                     status: str, score: int = 0, issues: list | None = None) -> None:
        self.execute(
            """INSERT OR REPLACE INTO segments (job_id, seg_id, page, kind, role, src, tgt, status, score,
               issues_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, seg_id, page, kind, role, src, tgt, status, score,
             json.dumps(issues or [], ensure_ascii=False), time.time()))

    def segments(self, job_id: str) -> dict[str, dict]:
        rows = self.query("SELECT * FROM segments WHERE job_id=?", (job_id,))
        out = {}
        for r in rows:
            d = dict(r)
            d["issues"] = json.loads(d.pop("issues_json") or "[]")
            out[d["seg_id"]] = d
        return out
