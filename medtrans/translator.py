"""Điều phối toàn bộ quy trình dịch – xuất bản một tài liệu PDF.

Quy trình xuất bản (mỗi công đoạn có điểm lưu, chạy lại sẽ tiếp tục):
  0. Phân tích bố cục (+ OCR trang scan) → đọc tổng quan → CHUẨN BỊ THUẬT NGỮ TOÀN VĂN
  1–3. Theo từng lô: DỊCH → HIỆU ĐÍNH CHUYÊN MÔN → BIÊN TẬP NGÔN NGỮ → kiểm tra máy → HỘI ĐỒNG GIÁM KHẢO MQM
  4. BIÊN TẬP TOÀN VĂN (nhất quán giữa các đoạn/chương)
  5. DÀN TRANG → 6. ĐỌC MORAT (máy + Claude so ảnh trang) → sửa morat, dàn lại
  7. Tự làm giàu thuật ngữ & bộ nhớ dịch, báo cáo

Chi tiết vòng lô:
  1. Tra bộ nhớ dịch (TM): khớp 100% & chất lượng cao → dùng lại, không tốn token.
  2. Dịch (kèm tóm lược tài liệu, thuật ngữ bắt buộc, câu tương tự từ TM, thuật ngữ đã quyết định).
  3. Thuật ngữ AI không chắc → tra cứu Internet, đối chiếu nguồn uy tín → chốt thuật ngữ cho cả tài liệu.
  4. Kiểm tra tự động (số liệu, liều–đơn vị, phủ định, mã giữ chỗ, thuật ngữ, sót tiếng Anh...).
  5. Biên tập viên AI đối chiếu từng đoạn với bản gốc và sửa.
  6. Còn lỗi máy phát hiện → dịch lại có chỉ dẫn lỗi (tối đa N vòng).
  7. GIÁM KHẢO ĐỘC LẬP chấm theo chuẩn MQM; còn lỗi critical/major → sửa và chấm lại.
  8. Đạt chuẩn (điểm MQM ≥ ngưỡng, không lỗi nặng, không lỗi máy) → TỰ CHỨNG NHẬN vào bộ nhớ dịch.
  9. Cuối tài liệu: thuật ngữ đủ bằng chứng + qua kiểm định → TỰ DUYỆT vào từ điển (không cần người).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf
from rapidfuzz import fuzz

from . import images as img_mod
from . import prompts as P
from .config import Config
from .db import Database, normalize_text
from .glossary import TermMatcher, format_terms_for_prompt
from .languages import get_profile, localize
from .llm import LLMError, cached_system, extract_json, make_llm
from .pdf_extract import PageInfo, TextBlock, extract
from .pdf_render import find_fonts, render
from .report import write_report
from .rules import PLACEHOLDER_RE, load_rules, protect, restore
from .stages import PublishingStages
from .verify import Issue, check, has_errors

log = logging.getLogger("medtrans")
PARA = "⟦¶⟧"
# cảnh báo máy chặn chứng nhận khi quality.strict_certify bật
STRICT_WARNINGS = {"glossary", "keep_missing", "number_extra", "tags", "paragraph_marker", "length"}


@dataclass
class Unit:
    """Một đơn vị dịch: một khối, hoặc chuỗi khối nối câu qua cột/trang."""
    id: str
    page: int
    role: str
    blocks: list[TextBlock]
    src: str                         # văn bản đã che (có ⟦n⟧, ⟦¶⟧, thẻ)
    mapping: dict[str, str]
    italic_spans: list[str]
    kind: str = "text"               # text | image
    terms: list[dict] = field(default_factory=list)
    tgt: str = ""
    score: int = 0
    issues: list[dict] = field(default_factory=list)
    status: str = ""
    mqm: list[dict] = field(default_factory=list)   # lỗi MQM còn lại sau vòng chấm cuối

    @property
    def plain_src(self) -> str:
        return re.sub(r"</?(?:b|i|sup|sub)>", "", restore(self.src.replace(PARA, " "), self.mapping))


ProgressCB = Callable[[float, str], None]


class Translator(PublishingStages):
    def __init__(self, cfg: Config, db: Database | None = None, llm=None, progress: ProgressCB | None = None):
        self.cfg = cfg
        self.db = db or Database(cfg.resolve(cfg.get_path("memory.db_path", "workspace/medtrans.db")))
        self.llm = llm or make_llm(cfg.get("llm", {}))
        t = cfg.get("translation", {})
        self.lang = get_profile(t.get("source_lang", "en"))
        self.rules = load_rules(lang=self.lang.code)
        self.progress = progress or (lambda f, m: log.info("[%3d%%] %s", int(f * 100), m))
        self.number_format = t.get("number_format", "vi")
        self.decided: dict[str, dict] = {}     # thuật ngữ đã chốt cho tài liệu (en_norm → term)
        self._decided_lock = threading.Lock()
        self._research_lock = threading.Lock()

    def _p(self, text: str) -> str:
        """Prompt theo ngôn ngữ nguồn hiện tại."""
        return localize(text, self.lang)

    # ================================================================ public
    def run(self, pdf_path: str | Path, out_dir: str | Path | None = None, domain: str | None = None,
            page_range: tuple[int, int] | None = None) -> dict:
        t0 = time.time()
        pdf_path = Path(pdf_path)
        tcfg = self.cfg.get("translation", {})
        lcfg = self.cfg.get("layout", {})
        domain = domain or tcfg.get("domain", "general_medicine")
        self.domain = domain
        self.domains = list(dict.fromkeys([domain, "general_medicine"]))
        out_dir = Path(out_dir or self.cfg.resolve(self.cfg.get_path("output.dir", "workspace/output")))
        out_dir.mkdir(parents=True, exist_ok=True)

        pdf_hash = hashlib.sha1(pdf_path.read_bytes()).hexdigest()[:16]
        job_id = f"{pdf_hash}_{domain}" + ("" if self.lang.code == "en" else f"_{self.lang.code}")
        self.job_id = job_id
        self.db.job_upsert(job_id, pdf_path=str(pdf_path), pdf_hash=pdf_hash, domain=domain, status="running")

        self.progress(0.01, "Đang phân tích bố cục PDF...")
        scfg = self.cfg.get("scan", {})
        page_numbers = set(range(page_range[0] - 1, page_range[1])) if page_range else None
        pages = extract(pdf_path, min_image_px=lcfg.get("image_min_size", 120), lang=self.lang,
                        ocr_scans=scfg.get("enabled", True), scan_dpi=scfg.get("dpi", 300), page_numbers=page_numbers)
        n_scanned = sum(1 for p in pages if p.scanned)
        if n_scanned:
            self.progress(0.015, f"{n_scanned} trang scan đã được OCR theo đoạn văn")
            if scfg.get("ocr_correct", True):
                self._fix_ocr(pdf_path, [p for p in pages if p.scanned], all_pages=pages)
        self.n_scanned = n_scanned

        glossary = self.db.terms(self.domains, src_lang=self.lang.code)
        self.matcher = TermMatcher(glossary)

        brief = self._brief(pages)
        self.termprep_stats = {}
        try:
            self.termprep_stats = self._prepare_terminology(pages)
        except Exception as e:
            log.warning("Chuẩn bị thuật ngữ toàn văn lỗi (tiếp tục dịch): %s", e)
        rules_text = self.rules.prompt_text(self.number_format, tcfg.get("drug_name_style", "duoc_thu"),
                                            tcfg.get("abbreviation_policy", "first_gloss"))
        self.system_translate = cached_system(self._p(P.TRANSLATOR_SYSTEM) + "\n\n" + rules_text,
                                              self._brief_text(brief))
        self.system_review = cached_system(self._p(P.REVIEW_SYSTEM) + "\n\n" + rules_text, self._brief_text(brief))
        self.system_revise = cached_system(self._p(P.REVISE_SYSTEM) + "\n\n" + rules_text, self._brief_text(brief))
        self.system_eval = {focus: cached_system(self._p(P.EVAL_SYSTEM) + P.JUDGE_FOCUS.get(focus, "") + "\n\n" +
                                                 rules_text, self._brief_text(brief))
                            for focus in self._judges()}

        units = self._build_units(pages)
        done = self.db.segments(job_id)
        pending = []
        for u in units:
            prev = done.get(u.id)
            if prev and prev["status"] in ("certified", "done", "tm", "needs_review") and prev["src"] == u.src:
                u.tgt, u.score, u.issues, u.status = prev["tgt"], prev["score"] or 0, prev["issues"], prev["status"]
            else:
                pending.append(u)
        self.progress(0.05, f"{len(units)} đoạn cần dịch, {len(units) - len(pending)} đã có từ lần chạy trước")

        # --- TM khớp tuyệt đối
        tm_thr = self.cfg.get_path("memory.tm_min_quality", 95)
        to_translate = []
        for u in pending:
            hit = self.db.tm_exact(u.src, self.domains, src_lang=self.lang.code)
            if hit and (hit["approved"] or hit["quality"] >= tm_thr) and self.cfg.get_path(
                    "memory.tm_reuse_threshold", 100) <= 100:
                u.tgt, u.score, u.status = hit["tgt"], hit["quality"], "tm"
                self._save(u)
            else:
                to_translate.append(u)
        if len(pending) != len(to_translate):
            self.progress(0.06, f"Dùng lại {len(pending) - len(to_translate)} đoạn từ bộ nhớ dịch (0 token)")

        # --- dịch theo lô, song song
        batches = self._make_batches(to_translate, tcfg.get("batch_chars", 6000))
        total = max(1, len(batches))
        finished = 0
        workers = max(1, int(tcfg.get("workers", 3)))
        t_batch0 = time.time()
        chars_todo = sum(len(u.src) for u in to_translate)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self._process_batch, b, units): b for b in batches}
            for fut in as_completed(futs):
                batch = futs[fut]
                try:
                    fut.result()
                except Exception as e:  # lỗi một lô không làm hỏng cả tài liệu
                    log.exception("Lô lỗi")
                    for u in batch:
                        u.status, u.issues = "failed", [{"severity": "error", "code": "api", "message": str(e)}]
                        self._save(u)
                finished += 1
                el = time.time() - t_batch0
                eta = el / finished * (total - finished)
                self.progress(0.08 + 0.72 * finished / total,
                              f"Dịch → hiệu đính → biên tập → giám khảo: lô {finished}/{total} "
                              f"(còn khoảng {_fmt_dur(eta)} cho công đoạn này)")
        if batches and chars_todo > 2000:
            self.db.perf_add(self.job_id, chars_todo, time.time() - t_batch0, workers,
                             self.cfg.get_path("llm.effort", "high"))

        # --- hình ảnh
        image_repl = {}
        if lcfg.get("translate_images", True) and lcfg.get("image_ocr", "tesseract") != "off":
            image_repl = self._translate_images(pdf_path, pages, units)

        # --- biên tập toàn văn
        self.consistency_stats = {}
        if batches:
            try:
                self.consistency_stats = self._consistency_pass(units)
            except Exception as e:
                log.warning("Biên tập toàn văn lỗi (bỏ qua): %s", e)

        # --- dàn trang
        self.progress(0.88, "Dàn trang: dựng PDF tiếng Việt giữ nguyên bố cục...")
        fonts = find_fonts(lcfg)
        out_pdf = out_dir / f"{pdf_path.stem}_VI.pdf"
        if page_range:
            out_pdf = out_dir / f"{pdf_path.stem}_VI_p{page_range[0]}-{page_range[1]}.pdf"
        strict_pages: set[int] = set()
        render_stats = render(pdf_path, out_pdf, pages, self._compose_blocks(units), fonts,
                              min_scale=lcfg.get("min_font_scale", 0.6), image_replacements=image_repl)

        # --- đọc morat → sửa → dàn lại
        self.proof_log: list[dict] = []
        pcfg = self.cfg.get("proof", {})
        if pcfg.get("enabled", True):
            only = None
            for rnd in range(int(pcfg.get("rounds", 2))):
                self.progress(0.9, f"Đọc morat vòng {rnd + 1}...")
                issues = self._proof_pages(pdf_path, out_pdf, pages, render_stats, only)
                for it in issues:
                    it["round"] = rnd + 1
                self.proof_log.extend(issues)
                changed, relayout = self._apply_proof_fixes(issues, units)
                new_strict = relayout - strict_pages
                if changed:
                    self._requalify(changed)
                if not changed and not new_strict:
                    break
                strict_pages |= relayout
                render_stats = render(pdf_path, out_pdf, pages, self._compose_blocks(units), fonts,
                                      min_scale=lcfg.get("min_font_scale", 0.6), image_replacements=image_repl,
                                      strict_pages=strict_pages)
                only = relayout  # vòng sau chỉ đọc lại các trang vừa sửa
        if page_range:
            self._trim_pages(out_pdf, page_range)

        # --- tự làm giàu từ điển thuật ngữ (không cần người duyệt)
        self.enrich_stats = {}
        if self.cfg.get_path("memory.auto_enrich", True) and batches:
            self.progress(0.95, "Đang tự làm giàu từ điển thuật ngữ từ các đoạn đạt chuẩn...")
            try:
                self.enrich_stats = self._enrich_terms(units, pdf_path.name)
            except Exception as e:
                log.warning("Không làm giàu được thuật ngữ: %s", e)

        usage = self.llm.usage.as_dict(getattr(self.llm, "model", ""))
        summary = self._summary(units, render_stats, usage, time.time() - t0)
        report_path = None
        if self.cfg.get_path("output.bilingual_report", True):
            report_path = write_report(out_dir / f"{pdf_path.stem}_VI_report.html", pdf_path.name, units, summary,
                                       brief, list(self.decided.values()), self.proof_log,
                                       self.cfg.get("branding", {}))
        self.db.job_upsert(job_id, status="done", usage_json=usage)
        self.progress(1.0, "Hoàn tất")
        return {"output_pdf": str(out_pdf), "report": str(report_path) if report_path else None, **summary}

    # ================================================================ brief
    def _brief(self, pages: list[PageInfo]) -> dict:
        job = self.db.job_get(self.job_id)
        if job and job.get("brief_json"):
            brief = json.loads(job["brief_json"])
        else:
            self.progress(0.02, "AI đang đọc tổng quan tài liệu để nắm ngữ cảnh...")
            sample, n = [], 0
            for p in pages:
                for b in p.blocks:
                    if b.keep:
                        continue
                    sample.append(("## " if b.role == "heading" else "") + b.plain)
                    n += len(b.plain)
                if n > 30000:
                    break
            headings = [b.plain for p in pages for b in p.blocks if b.role == "heading"][:300]
            text = "\n".join(sample) + "\n\n### CÁC TIÊU ĐỀ TRONG TÀI LIỆU:\n" + "\n".join(headings)
            brief = self.llm.json_call(task="brief", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)),
                                       user=self._p(P.BRIEF_PROMPT) + text, schema=P.BRIEF_SCHEMA,
                                       effort=self.cfg.get_path("llm.effort", "high"), payload={})
            self.db.job_upsert(self.job_id, brief_json=brief)
        # thuật ngữ then chốt do AI đề xuất → làm thuật ngữ đã chốt (trừ khi mâu thuẫn bảng thuật ngữ đã duyệt)
        for kt in brief.get("key_terms", []):
            if not kt.get("en") or not kt.get("vi"):
                continue
            if self._in_glossary(kt["en"]):
                continue
            self.decided[normalize_text(kt["en"])] = {"en": kt["en"], "vi": kt["vi"], "source": "brief"}
            self.db.upsert_term(kt["en"], kt["vi"], self.domain, source="brief", status="candidate",
                                note="AI đề xuất khi đọc tổng quan tài liệu", overwrite=False,
                                src_lang=self.lang.code)
        return brief

    def _in_glossary(self, term: str) -> bool:
        key = normalize_text(term)
        return any(normalize_text(t["en"]) == key for t in self.matcher.find(term))

    def _brief_text(self, brief: dict) -> str:
        notes = self.db.domain_notes(self.domain)
        return ("## THÔNG TIN TÀI LIỆU ĐANG DỊCH\n"
                f"- Tên: {brief.get('title', '')}\n- Chuyên ngành: {brief.get('specialty', '')}\n"
                f"- Độc giả: {brief.get('audience', '')}\n- Tóm tắt: {brief.get('summary', '')}\n\n"
                f"## HƯỚNG DẪN VĂN PHONG RIÊNG\n{brief.get('style_guide', '')}\n"
                + (f"\n## QUY ƯỚC CỦA CHUYÊN NGÀNH ({self.domain})\n{notes}\n" if notes else ""))

    # ================================================================ units
    def _build_units(self, pages: list[PageInfo]) -> list[Unit]:
        by_id = {b.id: b for p in pages for b in p.blocks}
        units: list[Unit] = []
        for p in pages:
            for b in p.blocks:
                if b.keep or b.chain_prev:
                    continue
                chain = [b]
                while chain[-1].chain_next and chain[-1].chain_next in by_id:
                    chain.append(by_id[chain[-1].chain_next])
                parts, mapping, italics = [], {}, []
                for blk in chain:
                    t = blk.text
                    for key, val in blk.math_map.items():   # đánh số lại mã công thức cho cả chuỗi
                        new = f"⟦M{len(mapping) + 1}⟧"
                        mapping[new] = val
                        t = t.replace(key, new)
                    parts.append(t)
                    italics.extend(blk.italic_spans)
                src = f" {PARA} ".join(parts)
                src, mapping = protect(src, self.rules, mapping)
                u = Unit(id=b.id, page=b.page, role=b.role, blocks=chain, src=src, mapping=mapping,
                         italic_spans=italics)
                u.terms = self.matcher.find(u.plain_src)
                units.append(u)
        return units

    def _make_batches(self, units: list[Unit], max_chars: int) -> list[list[Unit]]:
        batches, cur, n = [], [], 0
        for u in units:
            if cur and (n + len(u.src) > max_chars or u.page - cur[0].page > 3):
                batches.append(cur)
                cur, n = [], 0
            cur.append(u)
            n += len(u.src)
        if cur:
            batches.append(cur)
        return batches

    # ================================================================ batch pipeline
    def _context_for(self, batch: list[Unit], all_units: list[Unit]) -> dict:
        idx = next(i for i, u in enumerate(all_units) if u.id == batch[0].id)
        section = ""
        for u in reversed(all_units[:idx + 1]):
            if u.role == "heading":
                section = u.plain_src
                break
        prev = [u.plain_src for u in all_units[max(0, idx - 2):idx]]
        return {"current_section": section, "preceding_text": " … ".join(prev)[-1200:]}

    def _tm_refs(self, batch: list[Unit]) -> list[dict]:
        thr = self.cfg.get_path("memory.tm_fuzzy_threshold", 75)
        refs: dict[int, dict] = {}
        for u in batch:
            if len(u.src) < 25:
                continue
            for c in self.db.tm_candidates(u.src, self.domains, limit=15, src_lang=self.lang.code):
                score = fuzz.token_sort_ratio(normalize_text(u.src), c["src_norm"])
                if score >= thr and c["id"] not in refs:
                    refs[c["id"]] = {"en": c["src"], "vi": c["tgt"], "similarity": int(score)}
        return sorted(refs.values(), key=lambda r: -r["similarity"])[:8]

    def _decided_for(self, text: str) -> list[dict]:
        low = normalize_text(text)
        with self._decided_lock:
            return [{"en": d["en"], "vi": d["vi"]} for k, d in self.decided.items() if k in low]

    def _translate_call(self, batch: list[Unit], context: dict, task: str = "translate",
                        issues: dict[str, list] | None = None) -> dict[str, dict]:
        joined = " ".join(u.plain_src for u in batch)
        terms = {t["id"]: t for u in batch for t in u.terms}
        segs = []
        for u in batch:
            s = {"id": u.id, "role": u.role, "text": u.src}
            if task == "refine":
                s["previous_translation"] = u.tgt
                s["issues"] = (issues or {}).get(u.id, [])
            segs.append(s)
        payload = {
            "context": context,
            "glossary": format_terms_for_prompt(list(terms.values())),
            "decided_terms": self._decided_for(joined),
            "tm_references": self._tm_refs(batch) if task == "translate" else [],
            "segments": segs,
        }
        instr = self._p(P.TRANSLATE_INSTRUCTIONS if task == "translate" else P.REFINE_INSTRUCTIONS)
        res = self.llm.json_call(task=task, system=self.system_translate,
                                 user=instr + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=1),
                                 schema=P.TRANSLATE_SCHEMA, effort=self.cfg.get_path("llm.effort", "high"),
                                 payload=payload)
        return {s["id"]: s for s in res.get("segments", [])}

    def _review_call(self, batch: list[Unit], auto: dict[str, list[Issue]], kind: str = "review") -> dict[str, dict]:
        """kind = "revise" (hiệu đính chuyên môn) | "review" (biên tập ngôn ngữ)."""
        terms = {t["id"]: t for u in batch for t in u.terms}
        payload = {
            "glossary": format_terms_for_prompt(list(terms.values())),
            "decided_terms": self._decided_for(" ".join(u.plain_src for u in batch)),
            "segments": [{"id": u.id, "role": u.role, "source": u.src, "translation": u.tgt,
                          "auto_check": [i.message for i in auto.get(u.id, [])]} for u in batch],
        }
        system = self.system_revise if kind == "revise" else self.system_review
        intro = ("Hiệu đính chuyên môn các đoạn sau (đối chiếu bản gốc):\n\n" if kind == "revise"
                 else "Biên tập ngôn ngữ các đoạn sau:\n\n")
        res = self.llm.json_call(task=kind, system=system,
                                 user=intro +
                                      json.dumps(payload, ensure_ascii=False, indent=1),
                                 schema=P.REVIEW_SCHEMA, effort=self.cfg.get_path("llm.review_effort", "high"),
                                 payload=payload)
        return {s["id"]: s for s in res.get("segments", [])}

    def _check_text(self, u: Unit, tgt: str) -> list[Issue]:
        cur = u.tgt
        u.tgt = tgt
        try:
            return self._check(u)
        finally:
            u.tgt = cur

    def _check(self, u: Unit) -> list[Issue]:
        issues = check(u.src, u.tgt, rules=self.rules, number_format=self.number_format, placeholders=u.mapping,
                       glossary_terms=u.terms + [dict(d, id=-1) for d in self._decided_for(u.plain_src)],
                       italic_spans=u.italic_spans, role=u.role, lang=self.lang)
        n_para = u.src.count(PARA)
        if u.tgt.count(PARA) != n_para:
            issues.append(Issue("warning", "paragraph_marker",
                                f"Cần đúng {n_para} mã {PARA}, bản dịch có {u.tgt.count(PARA)}"))
        return issues

    def _process_batch(self, batch: list[Unit], all_units: list[Unit]) -> None:
        tcfg = self.cfg.get("translation", {})
        context = self._context_for(batch, all_units)

        # 1. dịch
        res = self._translate_call(batch, context)
        uncertain: list[dict] = []
        for u in batch:
            r = res.get(u.id)
            if not r:
                continue
            u.tgt = r.get("translation", "")
            for ut in r.get("uncertain_terms", []):
                uncertain.append({**ut, "context_en": u.plain_src[:400], "segment": u.id})
        missing = [u for u in batch if not u.tgt]
        if missing:  # AI bỏ sót id → dịch lại riêng
            res2 = self._translate_call(missing, context)
            for u in missing:
                u.tgt = res2.get(u.id, {}).get("translation", "")

        # 2. tra cứu thuật ngữ chưa chắc chắn
        changed_terms = []
        if tcfg.get("web_research", True) and uncertain:
            changed_terms = self._research(uncertain)

        # 3. kiểm tra tự động
        auto = {u.id: self._check(u) for u in batch}
        for t in changed_terms:  # thuật ngữ sau tra cứu khác lựa chọn ban đầu → yêu cầu sửa
            for u in batch:
                if normalize_text(t["en"]) in normalize_text(u.plain_src):
                    auto[u.id].append(Issue("error", "research",
                                            f"Sau tra cứu: '{t['en']}' nên dịch là '{t['vi']}' ({t.get('note', '')})"))

        # 4. hiệu đính chuyên môn → 5. biên tập ngôn ngữ
        wcfg = self.cfg.get("workflow", {})
        review_mode = tcfg.get("review_mode", "always")
        steps = [k for k, on in (("revise", wcfg.get("revise", True)), ("review", wcfg.get("edit", True))) if on]
        for kind in steps:
            if kind == "review":
                auto = {u.id: self._check(u) for u in batch}
            if review_mode != "always" and not any(auto.values()):
                continue
            to_review = batch if review_mode == "always" else [u for u in batch if auto[u.id]]
            rv = self._review_call(to_review, auto, kind=kind)
            label = "Hiệu đính" if kind == "revise" else "Biên tập"
            for u in to_review:
                r = rv.get(u.id)
                if not r or not r.get("final"):
                    continue
                old = u.tgt
                u.tgt = r["final"]
                if kind == "review" and has_errors(self._check(u)) and not has_errors(self._check_text(u, old)):
                    u.tgt = old  # biên tập ngôn ngữ không được làm phát sinh lỗi nội dung
                u.score = int(r.get("score", 0))
                u.issues = u.issues + [{"severity": "info", "code": kind, "message": f"{label}: {m}"}
                                       for m in r.get("problems", [])]
        for u in batch:
            if not u.score:
                u.score = 80

        # 5. sửa lỗi còn lại
        for rnd in range(int(tcfg.get("max_refine_rounds", 2))):
            remaining = {u.id: self._check(u) for u in batch}
            bad = [u for u in batch if has_errors(remaining[u.id])]
            if not bad:
                break
            fixed = self._translate_call(bad, context, task="refine",
                                         issues={u.id: [i.message for i in remaining[u.id]] for u in bad})
            for u in bad:
                if fixed.get(u.id, {}).get("translation"):
                    u.tgt = fixed[u.id]["translation"]

        # 6. giám khảo độc lập chấm MQM → sửa lỗi nặng → chấm lại
        qcfg = self.cfg.get("quality", {})
        if qcfg.get("independent_eval", True):
            self._evaluate(batch, context, rounds=int(qcfg.get("eval_rounds", 2)))

        # 7. chứng nhận & lưu
        self._finalize(batch)

    def _finalize(self, batch: list[Unit]) -> None:
        """Gán trạng thái: certified (đạt chuẩn, vào TM đã duyệt) | done | needs_review; lưu kết quả."""
        cert = int(self.cfg.get_path("quality.certify_score", 95))
        for u in batch:
            final_issues = self._check(u)
            u.issues = [i for i in u.issues if not i.get("auto")] + [{**i.as_dict(), "auto": True}
                                                                     for i in final_issues]
            severe = [e for e in u.mqm if e.get("severity") in ("critical", "major")]
            strict_block = self.cfg.get_path("quality.strict_certify", True) and any(
                i.code in STRICT_WARNINGS for i in final_issues)
            if has_errors(final_issues) or any(e.get("severity") == "critical" for e in u.mqm):
                u.status = "needs_review"
                u.score = min(u.score, 60)
            elif u.score >= cert and not severe and not strict_block:
                u.status = "certified"
            else:
                u.status = "done"
            self._save(u)
            self.db.tm_add(u.src, u.tgt, self.domain, doc_name=self.job_id, role=u.role, quality=u.score,
                           approved=u.status == "certified", src_lang=self.lang.code)

    # ================================================================ MQM evaluation
    @staticmethod
    def mqm_score(src_plain: str, errors: list[dict]) -> int:
        """Điểm MQM: 100 − phạt/100 từ (critical 25, major 5, minor 1), tối thiểu tính trên 40 từ."""
        weights = {"critical": 25, "major": 5, "minor": 1}
        penalty = sum(weights.get(e.get("severity", "minor"), 1) for e in errors)
        words = max(40, len(src_plain.split()))
        return max(0, min(100, round(100 - penalty * 100 / words)))

    def _judges(self) -> list[str]:
        j = self.cfg.get_path("quality.judges", ["clinical", "linguistic"])
        return list(j) if j else ["clinical"]

    def _eval_call(self, batch: list[Unit], focus: str) -> dict[str, dict]:
        terms = {t["id"]: t for u in batch for t in u.terms}
        payload = {
            "glossary": format_terms_for_prompt(list(terms.values())),
            "decided_terms": self._decided_for(" ".join(u.plain_src for u in batch)),
            "segments": [{"id": u.id, "role": u.role, "source": u.src, "translation": u.tgt} for u in batch],
        }
        res = self.llm.json_call(task="evaluate", system=self.system_eval[focus],
                                 user="Đánh giá độc lập các bản dịch sau theo khung MQM:\n\n" +
                                      json.dumps(payload, ensure_ascii=False, indent=1),
                                 schema=P.EVAL_SCHEMA, effort=self.cfg.get_path("llm.review_effort", "high"),
                                 payload=payload)
        return {s["id"]: s for s in res.get("segments", [])}

    @staticmethod
    def _merge_errors(lists: list[list[dict]]) -> list[dict]:
        """Gộp lỗi của nhiều giám khảo; lỗi trùng (cùng loại, cùng cụm) chỉ tính một lần, lấy mức nặng hơn."""
        rank = {"critical": 3, "major": 2, "minor": 1}
        merged: dict[tuple, dict] = {}
        for errs in lists:
            for e in errs:
                key = (e.get("category", ""), normalize_text(e.get("target_span", ""))[:40])
                if key not in merged or rank.get(e.get("severity"), 1) > rank.get(merged[key].get("severity"), 1):
                    merged[key] = e
        return list(merged.values())

    def _evaluate(self, batch: list[Unit], context: dict, rounds: int = 2) -> None:
        """Hội đồng giám khảo độc lập (mặc định: chuyên môn + ngôn ngữ) chấm MQM; lỗi nặng → sửa → chấm lại."""
        judges = self._judges()
        pending = list(batch)
        for rnd in range(max(1, rounds)):
            if len(judges) > 1:
                with ThreadPoolExecutor(max_workers=len(judges)) as ex:
                    results = dict(zip(judges, ex.map(lambda f: self._eval_call(pending, f), judges)))
            else:
                results = {judges[0]: self._eval_call(pending, judges[0])}
            next_round = []
            for u in pending:
                per_judge = []
                corrections = []
                for focus, res in results.items():
                    r = res.get(u.id, {"errors": [], "corrected": ""})
                    errs = [{**e, "judge": focus} for e in r.get("errors", [])]
                    per_judge.append(errs)
                    if any(e.get("severity") in ("critical", "major") for e in errs) and r.get("corrected"):
                        corrections.append(r["corrected"].strip())
                errors = self._merge_errors(per_judge)
                u.mqm = errors
                u.score = self.mqm_score(u.plain_src, errors)
                severe = [e for e in errors if e.get("severity") in ("critical", "major")]
                if not severe or rnd == rounds - 1:
                    continue
                applied = False
                if len(corrections) == 1:  # chỉ một giám khảo đề xuất sửa → thử áp dụng nếu qua kiểm tra máy
                    old = u.tgt
                    u.tgt = corrections[0]
                    if has_errors(self._check(u)):
                        u.tgt = old
                    else:
                        applied = True
                if not applied:
                    fixed = self._translate_call([u], context, task="refine", issues={u.id: [
                        f"[{e['severity']}/{e['category']}] {e.get('explanation', '')} → {e.get('fix', '')}"
                        for e in severe]})
                    if fixed.get(u.id, {}).get("translation"):
                        u.tgt = fixed[u.id]["translation"]
                next_round.append(u)
            if not next_round:
                break
            pending = next_round
        for u in batch:
            u.issues = [i for i in u.issues if not i.get("code", "").startswith("mqm_")] + [
                {"severity": "error" if e.get("severity") == "critical" else
                 ("warning" if e.get("severity") == "major" else "info"),
                 "code": f"mqm_{e.get('category', '')}",
                 "message": f"[MQM {e.get('severity')} – giám khảo {e.get('judge', '')}] {e.get('explanation', '')}"}
                for e in u.mqm]

    def _save(self, u: Unit) -> None:
        self.db.segment_save(self.job_id, u.id, page=u.page, kind=u.kind, role=u.role, src=u.src, tgt=u.tgt,
                             status=u.status, score=u.score, issues=u.issues)

    # ================================================================ research
    def _research(self, uncertain: list[dict]) -> list[dict]:
        """Tra cứu web cho thuật ngữ chưa chắc; trả về thuật ngữ có kết quả KHÁC lựa chọn ban đầu."""
        todo: dict[str, dict] = {}
        changed: list[dict] = []
        for ut in uncertain:
            key = normalize_text(ut.get("term", ""))
            if not key or key in todo:
                continue
            if self._in_glossary(ut["term"]):
                continue  # đã có trong bảng thuật ngữ duyệt
            with self._decided_lock:
                if key in self.decided:
                    continue
            cached = self.db.research_get(f"{self.lang.code}:{self.domain}:{key}")
            if cached:
                self._decide(cached, ut, changed)
                continue
            todo[key] = ut
        if not todo:
            return changed
        items = "\n".join(
            f"{i + 1}. \"{ut['term']}\" – bản dịch tạm: \"{ut.get('chosen_vi', '')}\" – lý do chưa chắc: "
            f"{ut.get('reason', '')}\n   Ngữ cảnh: {ut.get('context_en', '')}" for i, ut in enumerate(todo.values()))
        domains = ", ".join(self.cfg.get_path("translation.web_preferred_domains", []))
        with self._research_lock:  # tránh tra trùng song song
            try:
                text = self.llm.research_call(
                    system=cached_system(self._p(P.RESEARCH_SYSTEM)),
                    user=self._p(P.RESEARCH_PROMPT).format(items=items, domains=domains),
                    max_uses=int(self.cfg.get_path("translation.web_research_max_uses", 5)),
                    effort=self.cfg.get_path("llm.effort", "high"), payload={"items": list(todo.values())})
                data = extract_json(text)
            except (LLMError, ValueError, json.JSONDecodeError) as e:
                log.warning("Tra cứu web thất bại: %s", e)
                return changed
        for r in data.get("terms", []) if isinstance(data, dict) else []:
            key = normalize_text(r.get("en", ""))
            if not key or not r.get("vi"):
                continue
            self.db.research_put(f"{self.lang.code}:{self.domain}:{key}", r["en"], r)
            self._decide(r, todo.get(key, {}), changed)
        return changed

    def _decide(self, r: dict, ut: dict, changed: list[dict]) -> None:
        key = normalize_text(r["en"])
        with self._decided_lock:
            self.decided[key] = {"en": r["en"], "vi": r["vi"], "source": "web",
                                 "sources": r.get("sources", []), "note": r.get("note", ""),
                                 "confidence": r.get("confidence", 0)}
        auto = self._web_term_trusted(r)
        self.db.upsert_term(r["en"], r["vi"], self.domain, source="web", status="approved" if auto else "candidate",
                            source_url=", ".join(r.get("sources", [])[:3]),
                            note=f"[tin cậy {r.get('confidence', '?')}{'; tự duyệt' if auto else ''}] "
                                 f"{r.get('note', '')}", overwrite=False, src_lang=self.lang.code)
        if ut.get("chosen_vi") and normalize_text(ut["chosen_vi"]) != normalize_text(r["vi"]):
            changed.append(r)

    def _web_term_trusted(self, r: dict) -> bool:
        """Tự duyệt thuật ngữ tra cứu web: độ tin cậy cao + ≥2 nguồn, trong đó ≥1 nguồn uy tín."""
        qcfg = self.cfg.get("quality", {})
        try:
            conf = float(r.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        sources = [s for s in r.get("sources", []) if isinstance(s, str)]
        preferred = [d.lower() for d in self.cfg.get_path("translation.web_preferred_domains", [])]
        authoritative = [s for s in sources if any(d in s.lower() for d in preferred)
                         or re.search(r"\.(gov|edu)\.vn|\.gov/|who\.int|nih\.gov", s.lower())]
        return (conf >= float(qcfg.get("web_term_min_confidence", 0.85))
                and len(sources) >= int(qcfg.get("web_term_min_sources", 2)) and len(authoritative) >= 1)

    # ================================================================ OCR correction (PDF scan)
    def _fix_ocr(self, pdf_path: Path, pages: list[PageInfo], all_pages: list[PageInfo]) -> None:
        from .scan import render_page
        doc = pymupdf.open(str(pdf_path))
        for k, p in enumerate(pages):
            if not p.blocks:
                continue
            self.progress(0.015, f"Claude đối chiếu ảnh để sửa lỗi OCR trang scan {k + 1}/{len(pages)}")
            key = f"ocrfix:{self.job_id}:{p.number}"
            res = self.db.research_get(key)
            if res is None:
                img = render_page(doc[p.number], 150)
                if max(img.size) > 2000:
                    img.thumbnail((2000, 2000))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                paras = [{"id": b.id, "text": b.plain} for b in p.blocks]
                try:
                    res = self.llm.vision_json_call(
                        task="ocr_fix", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)), image_png=buf.getvalue(),
                        prompt=self._p(P.OCR_FIX_PROMPT) + json.dumps(paras, ensure_ascii=False, indent=1),
                        schema=P.OCR_FIX_SCHEMA, payload={"paragraphs": paras})
                    self.db.research_put(key, f"page {p.number}", res)
                except Exception as e:
                    log.warning("Không sửa được OCR trang %s: %s", p.number + 1, e)
                    continue
            fixed = {x["id"]: x["text"] for x in res.get("paragraphs", [])}
            keep = []
            for b in p.blocks:
                if b.id in fixed:
                    t = fixed[b.id].strip()
                    if not t:
                        continue  # nhiễu
                    b.plain = t
                    b.text = t.replace("<", "‹").replace(">", "›") if re.search(r"</?(?:b|i|sup|sub)>", t) else t
                keep.append(b)
            p.blocks = keep
        doc.close()
        alive = {b.id for p in all_pages for b in p.blocks}
        for p in all_pages:  # gỡ liên kết nối câu tới khối nhiễu đã bỏ
            for b in p.blocks:
                if b.chain_next and b.chain_next not in alive:
                    b.chain_next = None
                if b.chain_prev and b.chain_prev not in alive:
                    b.chain_prev = None

    # ================================================================ images
    def _translate_images(self, pdf_path: Path, pages: list[PageInfo], units: list[Unit]) -> dict:
        lcfg = self.cfg.get("layout", {})
        fonts = find_fonts(lcfg)
        font_path = fonts.sans[0] or fonts.serif[0]
        doc = pymupdf.open(str(pdf_path))
        out: dict[int, tuple[int, object]] = {}
        seen: set[int] = set()
        items = [im for p in pages for im in p.images]
        for k, im in enumerate(items):
            if im.xref in seen:
                continue
            seen.add(im.xref)
            self.progress(0.8 + 0.1 * k / max(1, len(items)), f"Dịch chữ trong hình {k + 1}/{len(items)}")
            img = img_mod.load_image(doc, im.xref)
            if img is None:
                continue
            try:
                if lcfg.get("image_ocr", "tesseract") == "claude":
                    cache_key = f"ocr:{self.job_id}:{im.xref}"
                    res = self.db.research_get(cache_key)
                    if res is None:
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        res = self.llm.vision_json_call(task="image_ocr",
                                                        system=cached_system(self._p(P.TRANSLATOR_SYSTEM)),
                                                        image_png=buf.getvalue(),
                                                        prompt=self._p(P.OCR_PROMPT).format(w=img.width, h=img.height),
                                                        schema=P.OCR_SCHEMA, payload={})
                        self.db.research_put(cache_key, im.id, res)
                    lines = [img_mod.OcrLine(f"{im.id}_l{i}", ln["text"],
                                             (int(ln["x0"]), int(ln["y0"]), int(ln["x1"]), int(ln["y1"])))
                             for i, ln in enumerate(res.get("lines", []))]
                else:
                    lines = img_mod.ocr_tesseract(img, im.id, lang=self.lang.tesseract)
            except Exception as e:
                log.warning("OCR lỗi ở %s: %s", im.id, e)
                continue
            if not lines:
                continue
            # caption gần nhất làm ngữ cảnh
            cap = next((u.plain_src for u in units if u.page == im.page and u.role == "caption"), "")
            img_units = []
            for ln in lines:
                src, mapping = protect(ln.text, self.rules)
                u = Unit(id=ln.id, page=im.page, role="figure_text", blocks=[], src=src, mapping=mapping,
                         italic_spans=[], kind="image")
                u.terms = self.matcher.find(ln.text)
                img_units.append(u)
            try:
                saved = self.db.segments(self.job_id)
                todo = []
                for u in img_units:  # dùng lại kết quả đã lưu (kể cả bản đã duyệt tay)
                    prev = saved.get(u.id)
                    if prev and prev["src"] == u.src and prev["tgt"]:
                        u.tgt, u.score, u.status, u.issues = prev["tgt"], prev["score"], prev["status"], prev["issues"]
                    else:
                        todo.append(u)
                if todo:
                    ctx = {"current_section": "Chữ trong hình", "preceding_text": cap}
                    res = self._translate_call(todo, ctx)
                    for u in todo:
                        u.tgt = res.get(u.id, {}).get("translation", "")
                        u.score = 80
                    todo = [u for u in todo if u.tgt]
                    if todo and self.cfg.get_path("quality.independent_eval", True):
                        self._evaluate(todo, ctx, rounds=int(self.cfg.get_path("quality.eval_rounds", 2)))
                    self._finalize(todo)
                tr = {u.id: restore(u.tgt, u.mapping) for u in img_units}
                units.extend(img_units)
                out[im.xref] = (im.page, img_mod.redraw(img, lines, tr, font_path))
            except Exception as e:
                log.warning("Dịch hình %s lỗi: %s", im.id, e)
        doc.close()
        return out

    # ================================================================ compose / output
    def _compose_blocks(self, units: list[Unit]) -> dict[str, str]:
        out: dict[str, str] = {}
        for u in units:
            if u.kind != "text" or not u.tgt:
                continue
            n = len(u.blocks)
            parts = [p.strip() for p in u.tgt.split(PARA)]
            if len(parts) != n:
                parts = _split_proportional(u.tgt.replace(PARA, " "), [len(b.plain) for b in u.blocks])
            for b, part in zip(u.blocks, parts):
                txt = restore(part, u.mapping)
                txt = PLACEHOLDER_RE.sub("", txt)  # mã lạ còn sót
                out[b.id] = txt
        return out

    def _trim_pages(self, pdf: Path, page_range: tuple[int, int]) -> None:
        doc = pymupdf.open(str(pdf))
        doc.select(list(range(page_range[0] - 1, min(page_range[1], doc.page_count))))
        tmp = pdf.with_suffix(".tmp.pdf")
        doc.save(str(tmp), garbage=3, deflate=True)
        doc.close()
        tmp.replace(pdf)

    def _enrich_terms(self, units: list[Unit], doc_name: str) -> dict:
        """Tự làm giàu từ điển KHÔNG cần người duyệt.

        Nguồn đề xuất: thuật ngữ trích từ các đoạn ĐÃ CHỨNG NHẬN (MQM đạt chuẩn) + thuật ngữ tổng quan + tra cứu web.
        Mỗi cặp tích luỹ "bằng chứng" = số đoạn đạt chuẩn dùng nhất quán cặp đó (cộng dồn qua nhiều tài liệu).
        Đủ bằng chứng → giám khảo kiểm định thuật ngữ → "standard" & tin cậy cao → TỰ DUYỆT vào từ điển chuẩn.
        """
        qcfg = self.cfg.get("quality", {})
        min_ev = int(qcfg.get("term_min_evidence", 2))
        min_conf = float(qcfg.get("term_min_confidence", 0.85))
        lang = self.lang.code
        certified = [u for u in units if u.kind == "text" and u.status == "certified" and len(u.src) > 20]
        pairs = [(normalize_text(u.plain_src), normalize_text(self._plain_tgt(u))) for u in certified]
        approved = {normalize_text(t["en"]): t for t in self.db.terms(self.domains, src_lang=lang)}
        stats = {"proposed": 0, "validated": 0, "auto_approved": 0, "rejected": 0, "conflicts": 0}

        # a) trích thuật ngữ từ các đoạn đạt chuẩn
        proposals: dict[str, dict] = {}
        chunk, n, calls = [], 0, 0
        for u in certified + [None]:
            if u is not None and len(u.src) > 40:
                chunk.append({"src": u.plain_src, "vi": self._plain_tgt(u)})
                n += len(u.src)
            if (u is None and chunk) or n > 12000:
                res = self.llm.json_call(task="extract_terms", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)),
                                         user=self._p(P.EXTRACT_PROMPT) + "\n" + json.dumps(
                                             {"known": sorted(approved)[:400], "pairs": chunk}, ensure_ascii=False),
                                         schema=P.EXTRACT_SCHEMA, effort="medium", payload={"pairs": chunk})
                for t in res.get("terms", []):
                    if t.get("en") and t.get("vi"):
                        proposals.setdefault(normalize_text(t["en"]), {**t, "source": "learned"})
                chunk, n = [], 0
                calls += 1
                if calls >= 30:
                    break
        # b) thuật ngữ tổng quan / tra cứu web dùng trong tài liệu
        with self._decided_lock:
            for k, d in self.decided.items():
                proposals.setdefault(k, {"en": d["en"], "vi": d["vi"], "source": d.get("source", "brief"),
                                         "category": "", "note": d.get("note", "")})

        # c) cộng bằng chứng
        to_validate: list[dict] = []
        for key, t in proposals.items():
            if key in approved:
                if normalize_text(approved[key]["vi"]) != normalize_text(t["vi"]):
                    stats["conflicts"] += 1  # giữ thuật ngữ đã duyệt, không ghi đè
                continue
            vi_n = normalize_text(t["vi"])
            ev = sum(1 for s_, t_ in pairs if key in s_ and vi_n in t_)
            row = self.db.add_evidence(t["en"], t["vi"], self.domain, ev, src_lang=lang, source=t["source"],
                                       category=t.get("category", ""),
                                       note=f"Từ '{doc_name}'. {t.get('note', '')}".strip())
            stats["proposed"] += 1
            if row and row["status"] == "candidate" and (row.get("evidence") or 0) >= min_ev \
                    and normalize_text(row["vi"]) == vi_n:
                to_validate.append(row)

        # d) kiểm định độc lập rồi tự duyệt / loại
        for i in range(0, len(to_validate), 80):
            part = to_validate[i:i + 80]
            res = self.llm.json_call(
                task="validate_terms", system=cached_system(self._p(P.TRANSLATOR_SYSTEM)),
                user=self._p(P.TERM_VALIDATE_PROMPT) + json.dumps(
                    [{"en": r["en"], "vi": r["vi"], "note": r.get("note", "")} for r in part], ensure_ascii=False),
                schema=P.TERM_VALIDATE_SCHEMA, effort=self.cfg.get_path("llm.review_effort", "high"),
                payload={"terms": part})
            by_key = {normalize_text(r["en"]): r for r in part}
            for v in res.get("terms", []):
                row = by_key.get(normalize_text(v.get("en", "")))
                if not row:
                    continue
                stats["validated"] += 1
                conf = float(v.get("confidence") or 0)
                note = (f"{row.get('note', '')} [kiểm định: {v.get('verdict')} {conf:.2f}; "
                        f"bằng chứng {row.get('evidence')} đoạn đạt chuẩn] {v.get('note', '')}").strip()
                if v.get("verdict") == "standard" and conf >= min_conf:
                    self.db.set_term_status(row["id"], "approved", note=note)
                    stats["auto_approved"] += 1
                elif v.get("verdict") in ("wrong", "acceptable") and conf >= min_conf and v.get("corrected_vi"):
                    # cách dịch chuẩn hơn → thay, xoá bằng chứng cũ, chờ tích luỹ bằng chứng mới
                    self.db.upsert_term(row["en"], v["corrected_vi"], self.domain, status="candidate", note=note,
                                        source=row.get("source", "learned"), src_lang=lang)
                    self.db.execute("UPDATE glossary SET evidence=0 WHERE id=?", (row["id"],))
                    stats["rejected"] += 1
                elif v.get("verdict") == "wrong" and conf >= min_conf:
                    self.db.set_term_status(row["id"], "rejected", note=note)
                    stats["rejected"] += 1
        return stats

    def _plain_tgt(self, u: Unit) -> str:
        return re.sub(r"</?(?:b|i|sup|sub)>", "", restore(u.tgt.replace(PARA, " "), u.mapping))

    def _summary(self, units: list[Unit], render_stats: dict, usage: dict, seconds: float) -> dict:
        text_units = [u for u in units if u.kind == "text"]
        scores = [u.score for u in text_units if u.score]
        return {
            "segments": len(text_units),
            "image_text_lines": len([u for u in units if u.kind == "image"]),
            "certified": sum(1 for u in text_units if u.status == "certified"),
            "from_tm": sum(1 for u in text_units if u.status == "tm"),
            "scanned_pages": getattr(self, "n_scanned", 0),
            "term_enrichment": getattr(self, "enrich_stats", {}),
            "terminology_prep": getattr(self, "termprep_stats", {}),
            "consistency": getattr(self, "consistency_stats", {}),
            "proof": {"issues": len(getattr(self, "proof_log", [])),
                      "fixed_text": sum(1 for u in text_units for i in u.issues if i.get("code") == "proof"),
                      "relayout_pages": len({i["page"] for i in getattr(self, "proof_log", [])
                                             if i.get("type") in ("overlap", "cutoff", "illegible", "misplaced")})},
            "needs_review": sum(1 for u in text_units if u.status == "needs_review"),
            "failed": sum(1 for u in text_units if u.status == "failed"),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "decided_terms": len(self.decided),
            "render": {"blocks": render_stats["blocks"], "shrunk": render_stats["shrunk"],
                       "overflow": len(render_stats["overflow"])},
            "usage": usage,
            "seconds": round(seconds, 1),
        }


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h} giờ {m} phút" if h else f"{max(1, m)} phút"


def _split_proportional(text: str, weights: list[int]) -> list[str]:
    words = text.split(" ")
    total = sum(weights) or 1
    out, start = [], 0
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            out.append(" ".join(words[start:]))
            break
        end = start + max(1, round(len(words) * w / total))
        out.append(" ".join(words[start:end]))
        start = end
    return out


# Thời gian xử lý mặc định (giây, tuần tự) cho mỗi 1.000 ký tự nguồn ở từng công đoạn, effort "high".
# Được thay bằng số đo thực tế của máy bạn sau các lần dịch (bảng perf).
STAGE_SECONDS_PER_KCHAR = {
    "translate": 25, "revise": 20, "edit": 18, "judge_each": 14, "refine_overhead": 0.25,
    "termprep": 3, "consistency": 6,
}
EFFORT_FACTOR = {"low": 0.5, "medium": 0.75, "high": 1.0, "xhigh": 1.35, "max": 1.8}
PROOF_SECONDS_PER_PAGE = 35


def estimate(pdf_path: str | Path, model: str = "claude-opus-5-5", cfg: Config | None = None,
             db: Database | None = None) -> dict:
    """Ước tính chi phí & thời gian trước khi dịch."""
    from .llm import PRICES
    from .scan import is_scanned
    pages = extract(pdf_path, ocr_scans=False)  # không OCR khi ước tính (nhanh)
    doc = pymupdf.open(str(pdf_path))
    n_scan = sum(1 for pg in doc if is_scanned(pg))
    doc.close()
    chars = sum(len(b.plain) for p in pages for b in p.blocks if not b.keep) + n_scan * 3000
    n_img = sum(len(p.images) for p in pages)
    k = chars / 1000

    get = (lambda path, d: cfg.get_path(path, d)) if cfg else (lambda path, d: d)
    judges = len(get("quality.judges", ["clinical", "linguistic"]) or [1])
    workers = max(1, int(get("translation.workers", 3)))
    effort = EFFORT_FACTOR.get(get("llm.effort", "high"), 1.0)
    revise = get("workflow.revise", True)
    edit = get("workflow.edit", True)
    proof_on = get("proof.enabled", True) and get("proof.vision", True)

    # ---- chi phí: token vào/ra mỗi 1.000 ký tự theo số công đoạn gọi model
    calls = 1 + int(revise) + int(edit) + judges * 1.4 + 0.3      # 1.4 = vòng chấm lại; 0.3 = dịch lại
    pin, pout, _ = PRICES.get(model, PRICES["claude-opus-5-5"])
    cost = k * calls * (700 * pin + 900 * pout * effort) / 1e6
    cost += k * (300 * pin + 150 * pout) / 1e6 * 2                 # chuẩn bị thuật ngữ + biên tập toàn văn
    if proof_on:
        cost += len(pages) * (3500 * pin + 500 * pout * effort) / 1e6
    cost += n_scan * (2500 * pin + 1500 * pout) / 1e6               # sửa lỗi OCR trang scan

    # ---- thời gian
    st = STAGE_SECONDS_PER_KCHAR
    per_k = (st["translate"] + st["revise"] * revise + st["edit"] * edit + st["judge_each"] * 1.4) \
        * effort * (1 + st["refine_overhead"])
    measured = None
    if db is not None:
        rows = db.query("SELECT sec_per_kchar, workers FROM perf ORDER BY created_at DESC LIMIT 10")
        if rows:  # dùng số đo thực tế (quy về 1 luồng)
            vals = sorted(r["sec_per_kchar"] * r["workers"] for r in rows)
            measured = vals[len(vals) // 2]
            per_k = measured
    core = k * per_k / workers
    extra = k * (st["termprep"] + st["consistency"]) * effort / workers
    proof_t = len(pages) * PROOF_SECONDS_PER_PAGE * effort / workers if proof_on else 0
    total = core + extra + proof_t + n_scan * 40 / workers
    return {"pages": len(pages), "scanned_pages": n_scan, "chars": chars, "images": n_img,
            "a4_equivalent_pages": round(chars / 3000, 1),
            "estimated_cost_usd_low": round(cost * 0.7, 2), "estimated_cost_usd_high": round(cost * 1.5, 2),
            "estimated_time_low": _fmt_dur(total * 0.7), "estimated_time_high": _fmt_dur(total * 1.6),
            "time_basis": "đo thực tế trên máy này" if measured else "ước lượng mặc định (chưa có số đo)",
            "workers": workers}
