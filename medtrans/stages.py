"""Các công đoạn xuất bản ngoài vòng dịch từng lô (dùng như mixin cho Translator):

  • Chuẩn bị thuật ngữ toàn văn – trước khi dịch: quét cả cuốn, chốt thuật ngữ (tra web nếu chưa chắc).
  • Biên tập toàn văn          – sau khi dịch: đọc liền mạch từng chương, sửa thiếu nhất quán giữa các đoạn.
  • Đọc morat (đọc bông)       – sau khi dàn trang: kiểm tra từng trang PDF (máy + Claude nhìn ảnh trang gốc
                                 và trang dịch), tự sửa lỗi chữ, dàn lại trang lỗi bố cục.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pymupdf

from . import prompts as P
from .db import normalize_text
from .llm import cached_system
from .rules import restore
from .verify import has_errors

if TYPE_CHECKING:  # pragma: no cover
    from .translator import Unit

log = logging.getLogger("medtrans.stages")
TAGS = re.compile(r"</?(?:b|i|sup|sub)>")


class PublishingStages:
    # ============================================================ 1. chuẩn bị thuật ngữ toàn văn
    def _prepare_terminology(self, pages) -> dict:
        tcfg = self.cfg.get("terminology", {})
        if not tcfg.get("prepass", True):
            return {}
        texts = [b.plain for p in pages for b in p.blocks if not b.keep]
        full = "\n".join(texts)
        if not full.strip():
            return {}
        size = int(tcfg.get("chunk_chars", 40000))
        chunks, cur, n = [], [], 0
        for t in texts:
            if cur and n + len(t) > size:
                chunks.append("\n".join(cur))
                cur, n = [], 0
            cur.append(t)
            n += len(t)
        if cur:
            chunks.append("\n".join(cur))
        known = sorted({t["en"] for t in self.matcher.find(full)})[:600]

        def run(idx_chunk):
            idx, chunk = idx_chunk
            key = f"termprep:{self.job_id}:{hashlib.sha1(chunk.encode()).hexdigest()[:12]}"
            cached = self.db.research_get(key)
            if cached is not None:
                return cached
            res = self.llm.json_call(
                task="termprep", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)),
                user=self._p(P.TERMPREP_PROMPT) + json.dumps({"known": known, "text": chunk}, ensure_ascii=False),
                schema=P.TERMPREP_SCHEMA, effort=self.cfg.get_path("llm.effort", "high"), payload={"text": chunk})
            self.db.research_put(key, f"termprep {idx}", res)
            return res

        self.progress(0.025, f"Chuẩn bị thuật ngữ toàn văn: quét {len(chunks)} phần tài liệu...")
        with ThreadPoolExecutor(max_workers=max(1, int(self.cfg.get_path("translation.workers", 3)))) as ex:
            results = list(ex.map(run, enumerate(chunks)))

        props: dict[str, list[dict]] = defaultdict(list)
        for res in results:
            for t in res.get("terms", []):
                if t.get("en") and t.get("vi"):
                    props[normalize_text(t["en"])].append(t)
        full_norm = normalize_text(full)
        uncertain_below = float(tcfg.get("uncertain_below", 0.85))
        decided, uncertain = 0, []
        rows: dict[str, dict] = {}

        def context_of(term: str) -> str:
            m = re.search(r"[^.\n]*" + re.escape(term) + r"[^.\n]*", full, re.I)
            return (m.group(0).strip() if m else "")[:300]

        # thuật ngữ đã có trong kho chuẩn cũng đưa vào termbase dự án để kiểm tra một thể
        for t in self.matcher.find(full):
            k = normalize_text(t["en"])
            rows[k] = {"en": t["en"], "vi": t["vi"], "freq": full_norm.count(k), "category": t.get("category", ""),
                       "confidence": 1.0, "origin": "glossary", "note": t.get("note", ""), "context": context_of(t["en"]),
                       "sources": t.get("source_url", "")}
        for key, items in props.items():
            if self._in_glossary(items[0]["en"]):
                continue
            freq = full_norm.count(key)
            votes = Counter(normalize_text(i["vi"]) for i in items)
            best_norm, _ = votes.most_common(1)[0]
            best = max((i for i in items if normalize_text(i["vi"]) == best_norm),
                       key=lambda i: float(i.get("confidence") or 0))
            conf = float(best.get("confidence") or 0)
            with self._decided_lock:
                self.decided.setdefault(key, {"en": best["en"], "vi": best["vi"], "source": "termprep",
                                              "confidence": conf, "note": best.get("note", "")})
            decided += 1
            rows[key] = {"en": best["en"], "vi": best["vi"], "freq": freq, "category": best.get("category", ""),
                         "confidence": conf, "origin": "termprep", "note": best.get("note", ""),
                         "variants": " / ".join(dict.fromkeys(i["vi"] for i in items)) if len(votes) > 1 else "",
                         "context": context_of(best["en"])}
            self.db.upsert_term(best["en"], best["vi"], self.domain, category=best.get("category", ""),
                                note=f"Chuẩn bị thuật ngữ toàn văn. {best.get('note', '')}", source="termprep",
                                status="candidate", overwrite=False, src_lang=self.lang.code)
            if (len(votes) > 1 or conf < uncertain_below) and freq >= 1:
                m = re.search(r"[^.\n]*" + re.escape(best["en"]) + r"[^.\n]*", full, re.I)
                uncertain.append({"term": best["en"], "chosen_vi": best["vi"], "freq": freq,
                                  "reason": ("nhiều cách dịch: " + " / ".join(i["vi"] for i in items[:3]))
                                  if len(votes) > 1 else f"độ tin cậy {conf:.2f}",
                                  "context_en": (m.group(0).strip() if m else "")[:400]})
        researched = 0
        if self.cfg.get_path("translation.web_research", True) and uncertain:
            uncertain.sort(key=lambda u: -u["freq"])
            uncertain = uncertain[: int(tcfg.get("research_max_terms", 150))]
            self.progress(0.03, f"Tra cứu web {len(uncertain)} thuật ngữ chưa chắc chắn...")
            for i in range(0, len(uncertain), 12):
                group = uncertain[i:i + 12]
                with self._decided_lock:
                    for g in group:  # bỏ chốt tạm để _research được phép quyết định
                        self.decided.pop(normalize_text(g["term"]), None)
                self._research(group)
                with self._decided_lock:
                    for g in group:  # tra cứu thất bại → giữ phương án tốt nhất để đảm bảo nhất quán
                        self.decided.setdefault(normalize_text(g["term"]),
                                                {"en": g["term"], "vi": g["chosen_vi"], "source": "termprep"})
                researched += len(group)
            with self._decided_lock:  # cập nhật termbase dự án theo kết quả tra cứu
                for g in uncertain:
                    k = normalize_text(g["term"])
                    d = self.decided.get(k)
                    if d and k in rows and d.get("source") == "web":
                        rows[k].update(vi=d["vi"], origin="web", confidence=d.get("confidence", 0),
                                       sources=", ".join(d.get("sources", [])[:3]),
                                       note=(d.get("note") or rows[k]["note"]))
        self.db.job_terms_save(self.job_id, list(rows.values()))
        return {"chunks": len(chunks), "terms": decided, "researched": researched, "termbase_rows": len(rows)}

    # ============================================================ 2. biên tập toàn văn
    def _consistency_pass(self, units: list["Unit"]) -> dict:
        ccfg = self.cfg.get("workflow", {})
        if not ccfg.get("consistency", True):
            return {}
        text_units = [u for u in units if u.kind == "text" and u.tgt and u.status != "failed"]
        if not text_units:
            return {}
        size = int(ccfg.get("consistency_chunk_chars", 20000))
        chunks, cur, n = [], [], 0
        for u in text_units:
            if cur and (n + len(u.src) + len(u.tgt) > size or (u.role == "heading" and n > size * 0.6)):
                chunks.append(cur)
                cur, n = [], 0
            cur.append(u)
            n += len(u.src) + len(u.tgt)
        if cur:
            chunks.append(cur)
        by_id = {u.id: u for u in text_units}
        self.progress(0.84, f"Biên tập toàn văn: đọc liền mạch {len(chunks)} phần để thống nhất...")

        def run(chunk):
            terms = {t["id"]: t for u in chunk for t in u.terms}
            from .glossary import format_terms_for_prompt
            payload = {
                "glossary": format_terms_for_prompt(list(terms.values())),
                "decided_terms": self._decided_for(" ".join(u.plain_src for u in chunk)),
                "segments": [{"id": u.id, "role": u.role, "source": u.src, "vi": u.tgt} for u in chunk],
            }
            body = json.dumps(payload, ensure_ascii=False, indent=1)
            key = f"consist:{self.job_id}:{hashlib.sha1(body.encode()).hexdigest()}"
            cached = self.db.research_get(key)
            if cached is not None:
                return cached
            res = self.llm.json_call(task="consistency", system=self.system_review,
                                     user=self._p(P.CONSIST_PROMPT) + body, schema=P.CONSIST_SCHEMA,
                                     effort=self.cfg.get_path("llm.review_effort", "high"), payload=payload)
            self.db.research_put(key, "consistency", res)
            return res

        with ThreadPoolExecutor(max_workers=max(1, int(self.cfg.get_path("translation.workers", 3)))) as ex:
            results = list(ex.map(run, chunks))
        changed = []
        for res in results:
            for fx in res.get("fixes", []):
                u = by_id.get(fx.get("id"))
                new = (fx.get("corrected") or "").strip()
                if not u or not new or new == u.tgt:
                    continue
                old = u.tgt
                u.tgt = new
                if has_errors(self._check(u)):
                    u.tgt = old  # bản sửa làm phát sinh lỗi máy → bỏ
                    continue
                u.issues = u.issues + [{"severity": "info", "code": "consistency",
                                        "message": f"Biên tập toàn văn: {fx.get('issue', '')}"}]
                changed.append(u)
        if changed:  # đoạn đã sửa phải qua hội đồng giám khảo lại trước khi chứng nhận
            self._requalify(changed)
        return {"chunks": len(chunks), "fixed": len(changed)}

    def _requalify(self, changed: list["Unit"]) -> None:
        if self.cfg.get_path("quality.independent_eval", True):
            for i in range(0, len(changed), 25):
                part = changed[i:i + 25]
                self._evaluate(part, {}, rounds=int(self.cfg.get_path("quality.eval_rounds", 2)))
        self._finalize(changed)

    # ============================================================ 3. đọc morat
    def _proof_pages(self, src_pdf, out_pdf, pages, render_stats: dict, only: set[int] | None = None) -> list[dict]:
        pcfg = self.cfg.get("proof", {})
        issues: list[dict] = []
        # 3a. kiểm tra bằng máy
        for o in render_stats.get("overflow", []):
            if o.get("scale", 1) < 0.5:
                issues.append({"page": o["page"] - 1, "type": "illegible", "severity": "major", "source": "auto",
                               "description": f"Khối {o['block']} phải thu nhỏ còn {o['scale']:.0%}"})
        for ov in render_stats.get("overlaps", []):
            issues.append({"page": ov["page"] - 1, "type": "overlap", "severity": "major", "source": "auto",
                           "description": f"Khối {ov['blocks']} chồng lấn"})
        doc = pymupdf.open(str(out_pdf))
        kept_text = defaultdict(str)
        for p in pages:
            kept_text[p.number] = " ".join(b.plain for b in p.blocks if b.keep)
        for p in pages:
            if only is not None and p.number not in only or p.scanned:
                continue
            words = re.findall(r"[A-Za-z]+", doc[p.number].get_text())
            kept = set(re.findall(r"[A-Za-z]+", kept_text[p.number]))
            left = [w for w in words if w.lower() in self.lang.stopwords and w not in kept
                    and w.lower() not in ("can", "may", "than", "an", "do", "to", "in", "the", "be", "it", "at",
                                          "as", "but", "or", "by", "if", "not")]
            if len(left) >= 4:
                issues.append({"page": p.number, "type": "untranslated", "severity": "major", "source": "auto",
                               "description": f"Còn chữ chưa dịch trên trang: {left[:8]}"})
        doc.close()

        # 3b. Claude đọc morat: so ảnh trang gốc với trang dịch
        if pcfg.get("vision", True):
            dpi = int(pcfg.get("dpi", 100))
            src = pymupdf.open(str(src_pdf))
            out = pymupdf.open(str(out_pdf))
            todo = [p for p in pages if (only is None or p.number in only) and
                    (p.blocks or p.images)]

            def run(p, a, b):
                key = f"proof:{self.job_id}:{hashlib.sha1(a + b).hexdigest()}"
                cached = self.db.research_get(key)
                if cached is not None:
                    return cached["issues"]
                try:
                    res = self.llm.vision_multi_json_call(
                        task="proof", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)), images=[a, b],
                        prompt=self._p(P.PROOF_PROMPT), schema=P.PROOF_SCHEMA, payload={"page": p.number})
                except Exception as e:
                    log.warning("Đọc morat trang %s lỗi: %s", p.number + 1, e)
                    return []
                found = [{**i, "page": p.number, "source": "vision"} for i in res.get("issues", [])]
                self.db.research_put(key, f"proof p{p.number}", {"issues": found})
                return found

            # sinh ảnh trang dần dần (dòng chảy), giới hạn số trang đang xử lý → tiết kiệm bộ nhớ
            workers = max(1, int(self.cfg.get_path("translation.workers", 3)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                inflight = []
                for k, p in enumerate(todo):
                    a = src[p.number].get_pixmap(dpi=dpi).tobytes("png")
                    b = out[p.number].get_pixmap(dpi=dpi).tobytes("png")
                    inflight.append(ex.submit(run, p, a, b))
                    if len(inflight) >= workers * 2:
                        issues.extend(inflight.pop(0).result())
                    if k % 10 == 0:
                        self.progress(0.92, f"Đọc morat: trang {k + 1}/{len(todo)}")
                for f in inflight:
                    issues.extend(f.result())
            src.close()
            out.close()
        return issues

    def _apply_proof_fixes(self, issues: list[dict], units: list["Unit"]) -> tuple[list["Unit"], set[int]]:
        """Sửa lỗi chữ (typo/chưa dịch) trực tiếp vào đoạn; trả về các đoạn đã sửa và các trang cần dàn lại."""
        changed: dict[str, "Unit"] = {}
        relayout: set[int] = set()
        text_units = [u for u in units if u.tgt]
        for it in issues:
            if it.get("type") in ("overlap", "cutoff", "illegible", "misplaced"):
                relayout.add(it["page"])
                continue
            quote, corr = (it.get("quote") or "").strip(), (it.get("correction") or "").strip()
            if it.get("type") not in ("typo", "untranslated", "figure_text") or not quote or not corr or quote == corr:
                continue
            for u in text_units:
                if u.page != it["page"] and not any(b.page == it["page"] for b in u.blocks):
                    continue
                if quote in u.tgt:
                    old = u.tgt
                    u.tgt = u.tgt.replace(quote, corr, 1)
                    if has_errors(self._check(u)):
                        u.tgt = old
                        continue
                    u.issues = u.issues + [{"severity": "info", "code": "proof",
                                            "message": f"Đọc morat: '{quote}' → '{corr}'"}]
                    changed[u.id] = u
                    relayout.add(it["page"])
                    break
        return list(changed.values()), relayout

    def _plain(self, u: "Unit") -> str:
        return TAGS.sub("", restore(u.tgt.replace("⟦¶⟧", " "), u.mapping))
