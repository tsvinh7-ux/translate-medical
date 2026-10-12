"""Hiệu chuẩn hồ sơ chất lượng/chi phí trên tài liệu mẫu của bạn.

Mỗi hồ sơ dịch cùng một tập trang mẫu (không đọc/ghi bộ nhớ dịch để so sánh công bằng). Sau đó MỘT GIÁM KHẢO
THAM CHIẾU CỐ ĐỊNH (cấu hình "premium") chấm lại toàn bộ bằng MQM + kiểm toán trung thành, cho ra:
  • điểm MQM trung bình, tỉ lệ đạt chuẩn và khoảng tin cậy 95% (Wilson), tỉ lệ còn lỗi critical;
  • chi phí & thời gian thực tế quy đổi trên mỗi trang A4.
Kết quả được lưu và hiển thị khi chọn hồ sơ cho dự án mới.
"""
from __future__ import annotations

import copy
import math
import time
from pathlib import Path

from .config import Config, apply_profile
from .db import Database
from .llm import make_llm


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def calibrate(pdf_path: str | Path, cfg: Config, db: Database, profiles: list[str],
              page_range: tuple[int, int] = (1, 10), domain: str | None = None, progress=None,
              llm_factory=None) -> list[dict]:
    from .translator import Translator
    llm_factory = llm_factory or (lambda c: make_llm(c.get("llm", {})))
    domain = domain or cfg.get_path("translation.domain", "general_medicine")
    out_dir = cfg.resolve("workspace/calibration")
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_cfg = apply_profile(cfg, "premium")
    certify = int(ref_cfg.get_path("quality.certify_score", 97))
    results = []
    for i, name in enumerate(profiles):
        say = (lambda f, m, i=i: progress and progress((i + f) / len(profiles), f"[{name}] {m}"))
        pc = apply_profile(cfg, name)
        pc["job_tag"] = f"calib_{name}"
        pc["memory"]["read_only"] = True
        pc["proof"]["enabled"] = False
        pc["output"]["bilingual_report"] = False
        tr = Translator(pc, db=db, llm=llm_factory(pc), progress=say)
        t0 = time.time()
        res = tr.run(pdf_path, out_dir=out_dir, domain=domain, page_range=page_range)
        seconds = time.time() - t0
        units = [copy.deepcopy(u) for u in tr.units if u.kind == "text" and u.tgt]
        chars = sum(len(u.plain_src) for u in units) or 1

        # giám khảo tham chiếu cố định
        rc = copy.deepcopy(ref_cfg)
        rc["job_tag"] = f"calib_{name}"
        rc["memory"]["read_only"] = True
        ref = Translator(rc, db=db, llm=llm_factory(rc), progress=say)
        ref.domain, ref.domains, ref.job_id = tr.domain, tr.domains, tr.job_id
        ref.matcher = tr.matcher
        ref.decided = dict(tr.decided)
        ref._build_systems(tr.brief)
        say(0.9, "Giám khảo tham chiếu chấm điểm...")
        for k in range(0, len(units), 20):
            ref._evaluate(units[k:k + 20], {}, rounds=1)
        passed = critical = 0
        for u in units:
            severe = [e for e in u.mqm if e.get("severity") in ("critical", "major")]
            machine = [x for x in ref._check(u) if x.severity == "error"]
            critical += any(e.get("severity") == "critical" for e in u.mqm)
            passed += (u.score >= certify and not severe and not machine)
        n = len(units)
        lo, hi = wilson(passed, n)
        cost = res["usage"]["estimated_cost_usd"]
        row = {"profile": name, "domain": domain, "model": pc.get_path("llm.model"), "segments": n,
               "avg_mqm": round(sum(u.score for u in units) / n, 1) if n else 0,
               "pass_rate": round(100 * passed / n, 1) if n else 0,
               "ci_low": round(100 * lo, 1), "ci_high": round(100 * hi, 1),
               "critical_rate": round(100 * critical / n, 1) if n else 0,
               "cost_per_a4": round(cost / chars * 3000, 4), "sec_per_a4": round(seconds / chars * 3000, 1),
               "sample": f"{Path(pdf_path).name} tr.{page_range[0]}-{page_range[1]}", "created_at": time.time()}
        db.execute(f"INSERT INTO calibration ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                   list(row.values()))
        results.append(row)
    return results
