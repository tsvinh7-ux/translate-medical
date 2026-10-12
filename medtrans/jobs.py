"""Hàng đợi công việc chạy nền: nhiều tài liệu, theo dõi tiến độ, TẠM DỪNG / TIẾP TỤC / HUỶ, tự phục hồi.

- Mỗi công việc chạy trong luồng nền; tiến độ, công đoạn, thông điệp được ghi vào CSDL để giao diện hiển thị.
- Điểm can thiệp: đầu mỗi lô dịch, mỗi vòng chấm, mỗi cập nhật tiến độ → tạm dừng/huỷ có hiệu lực trong vài giây
  đến vài phút (lô đang chạy được hoàn tất để không mất tiền).
- Mở lại ứng dụng: công việc đang chạy dở được đưa lại vào hàng đợi và TIẾP TỤC từ điểm lưu.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from pathlib import Path

from .config import Config, apply_profile, load_config
from .db import Database

log = logging.getLogger("medtrans.jobs")

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_path TEXT, name TEXT, domain TEXT, profile TEXT, source_lang TEXT DEFAULT 'en',
    page_from INTEGER, page_to INTEGER,
    mode TEXT DEFAULT 'translate',          -- translate | scan_terms
    require_lock INTEGER DEFAULT 0,         -- chốt chặn termbase
    status TEXT DEFAULT 'queued',           -- queued | running | paused | awaiting_termbase | done | failed | cancelled
    control TEXT DEFAULT '',                -- '' | pause | cancel
    progress REAL DEFAULT 0, message TEXT DEFAULT '', job_id TEXT DEFAULT '',
    result_json TEXT DEFAULT '', error TEXT DEFAULT '',
    created_at REAL, started_at REAL, finished_at REAL
);
"""
STATUS_VI = {"queued": "Chờ", "running": "Đang chạy", "paused": "Tạm dừng", "awaiting_termbase": "Chờ khoá termbase",
             "done": "Hoàn tất", "failed": "Lỗi", "cancelled": "Đã huỷ"}


class JobCancelled(Exception):
    pass


class JobQueue:
    def __init__(self, cfg: Config, db: Database, parallel: int = 1, llm_factory=None, autostart: bool = True):
        self.cfg, self.db = cfg, db
        self.llm_factory = llm_factory
        with db._lock:
            db.conn.executescript(SCHEMA)
            # công việc đang chạy dở khi tắt ứng dụng → chạy tiếp từ điểm lưu
            db.conn.execute("UPDATE queue SET status='queued', control='' WHERE status IN ('running','paused')")
            db.conn.commit()
        self._stop = threading.Event()
        self._pick = threading.Lock()
        self.threads = []
        if autostart:
            for i in range(max(1, parallel)):
                t = threading.Thread(target=self._worker, name=f"medtrans-job-{i}", daemon=True)
                t.start()
                self.threads.append(t)

    # ------------------------------------------------------------------ API
    def submit(self, pdf_path: str | Path, domain: str, profile: str, page_range: tuple[int, int] | None = None,
               mode: str = "translate", require_lock: bool = False, source_lang: str = "en") -> int:
        cur = self.db.execute(
            "INSERT INTO queue (pdf_path, name, domain, profile, source_lang, page_from, page_to, mode, require_lock,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(pdf_path), Path(pdf_path).name, domain, profile, source_lang,
             page_range[0] if page_range else None, page_range[1] if page_range else None, mode,
             int(require_lock), time.time()))
        return cur.lastrowid

    def control(self, qid: int, action: str) -> None:
        if action == "resume":
            self.db.execute("UPDATE queue SET control='' WHERE id=?", (qid,))
        elif action == "retry":
            self.db.execute("UPDATE queue SET status='queued', control='', error='' WHERE id=?", (qid,))
        elif action == "cancel":
            self.db.execute("UPDATE queue SET control='cancel', status=CASE WHEN status='queued' THEN 'cancelled' "
                            "ELSE status END WHERE id=?", (qid,))
        elif action == "pause":
            self.db.execute("UPDATE queue SET control='pause' WHERE id=?", (qid,))

    def list(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM queue ORDER BY id DESC LIMIT ?", (limit,))]

    def get(self, qid: int) -> dict | None:
        rows = self.db.query("SELECT * FROM queue WHERE id=?", (qid,))
        return dict(rows[0]) if rows else None

    def run_pending(self) -> None:
        """Chạy đồng bộ mọi công việc đang chờ (dùng cho dòng lệnh / kiểm thử)."""
        while self._run_one():
            pass

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ worker
    def _worker(self) -> None:
        while not self._stop.is_set():
            if not self._run_one():
                time.sleep(1.5)

    def _claim(self) -> dict | None:
        with self._pick:
            rows = self.db.query("SELECT * FROM queue WHERE status='queued' ORDER BY id LIMIT 1")
            if not rows:
                return None
            row = dict(rows[0])
            self.db.execute("UPDATE queue SET status='running', started_at=?, control='' WHERE id=?",
                            (time.time(), row["id"]))
            return row

    def _check(self, qid: int) -> None:
        row = self.get(qid)
        if not row:
            return
        if row["control"] == "cancel":
            raise JobCancelled()
        if row["control"] == "pause":
            self.db.execute("UPDATE queue SET status='paused' WHERE id=?", (qid,))
            while True:
                time.sleep(1.0)
                row = self.get(qid)
                if row["control"] == "cancel":
                    raise JobCancelled()
                if row["control"] != "pause":
                    self.db.execute("UPDATE queue SET status='running' WHERE id=?", (qid,))
                    return

    def _run_one(self) -> bool:
        row = self._claim()
        if not row:
            return False
        qid = row["id"]
        from .translator import Translator
        try:
            base = Config(json.loads(json.dumps(self.cfg))) if self.cfg is not None else load_config()
            cfg = apply_profile(base, row["profile"])
            cfg["translation"]["source_lang"] = row["source_lang"] or "en"
            cfg["terminology"]["require_lock"] = bool(row["require_lock"])

            def progress(f: float, m: str) -> None:
                self.db.execute("UPDATE queue SET progress=?, message=? WHERE id=?", (round(f, 4), m, qid))
                self._check(qid)

            llm = self.llm_factory(cfg) if self.llm_factory else None
            tr = Translator(cfg, db=self.db, llm=llm, progress=progress)
            tr.control = lambda: self._check(qid)
            pr = (row["page_from"], row["page_to"]) if row["page_from"] else None
            if row["mode"] == "scan_terms":
                res = tr.scan_terms(row["pdf_path"], domain=row["domain"], page_range=pr)
            else:
                res = tr.run(row["pdf_path"], domain=row["domain"], page_range=pr)
            status = "awaiting_termbase" if res.get("status") == "awaiting_termbase" else "done"
            self.db.execute("UPDATE queue SET status=?, progress=1, result_json=?, job_id=?, finished_at=? WHERE id=?",
                            (status, json.dumps(res, ensure_ascii=False), tr.job_id, time.time(), qid))
        except JobCancelled:
            self.db.execute("UPDATE queue SET status='cancelled', finished_at=? WHERE id=?", (time.time(), qid))
        except Exception as e:  # noqa: BLE001
            log.error("Công việc %s lỗi: %s", qid, traceback.format_exc())
            self.db.execute("UPDATE queue SET status='failed', error=?, finished_at=? WHERE id=?",
                            (str(e)[:2000], time.time(), qid))
        return True
