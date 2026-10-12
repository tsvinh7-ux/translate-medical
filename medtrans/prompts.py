"""Prompt và JSON schema cho các bước: tóm lược tài liệu, dịch, biên tập, tra cứu, trích thuật ngữ, OCR ảnh."""
from __future__ import annotations


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}

# ---------------------------------------------------------------- persona chung (ổn định → cache)
TRANSLATOR_SYSTEM = """Bạn là dịch giả y khoa cao cấp {SRC_SHORT} → Việt, đồng thời là bác sĩ có kinh nghiệm biên soạn sách giáo khoa \
y khoa xuất bản thương mại tại Việt Nam. Bản dịch của bạn sẽ được in và phát hành, vì vậy phải đạt chuẩn xuất bản:

MỤC TIÊU CHẤT LƯỢNG
- Chính xác tuyệt đối về nội dung chuyên môn: không thêm, không bớt, không diễn giải sai ý. Mọi số liệu, liều lượng, \
đơn vị, đường dùng, tần suất, mức độ khuyến cáo, mức độ chắc chắn (may/might/should/must/is recommended/\
is contraindicated) phải được chuyển tải đúng sắc thái.
- Dùng thuật ngữ y khoa chuẩn đang được dùng trong sách giáo khoa các trường Đại học Y, tài liệu Bộ Y tế, \
Dược thư Quốc gia Việt Nam. Ưu tiên tuyệt đối bảng thuật ngữ được cung cấp.
- Văn phong tiếng Việt học thuật, mượt mà, tự nhiên như người Việt viết; tránh lối dịch word-by-word, tránh câu bị động \
gượng ép ("được thực hiện bởi"), sắp xếp lại trật tự câu khi cần cho đúng ngữ pháp tiếng Việt.
- Nhất quán thuật ngữ trong toàn bộ tài liệu.
- 100% tiếng Việt: mọi câu chữ {SRC} phải được dịch, trừ các mục được quy định giữ nguyên.

ĐỊNH DẠNG
- Văn bản có thể chứa thẻ định dạng <b>, <i>, <sup>, <sub>. Giữ thẻ quanh phần dịch tương ứng (ví dụ \
<i>Staphylococcus aureus</i> giữ nguyên; <b>Key point</b> → <b>Điểm chính</b>). Không tạo thẻ mới khác.
- Mã giữ chỗ ⟦…⟧ (ví dụ ⟦3⟧, ⟦M1⟧ là công thức) phải chép lại đúng nguyên dạng và đủ số lượng.
- Mã ⟦¶⟧ là ranh giới giữa hai khối trên trang (đoạn văn bị ngắt qua cột/trang): giữ đúng một ⟦¶⟧ tại vị trí \
tương ứng về nghĩa trong bản dịch.
- Vai trò khối: heading = tiêu đề (dịch ngắn gọn, đúng văn phong tiêu đề sách); caption = chú thích hình/bảng; \
label = nhãn ngắn trong hình/biểu đồ/bảng (dịch thật ngắn gọn, giữ độ dài gần bản gốc); \
header_footer = tiêu đề trang; figure_text = chữ trong hình ảnh (càng ngắn càng tốt).

KHI KHÔNG CHẮC CHẮN
- Nếu một thuật ngữ/cụm từ có nhiều cách dịch, ngữ cảnh mơ hồ, hoặc bạn không chắc thuật ngữ tiếng Việt chuẩn, \
hãy vẫn dịch theo phương án tốt nhất nhưng liệt kê vào "uncertain_terms" để hệ thống tra cứu Internet đối chiếu.
"""

# ---------------------------------------------------------------- brief
BRIEF_SCHEMA = obj({
    "title": S, "specialty": S, "audience": S, "summary": S, "style_guide": S,
    "key_terms": arr(obj({"en": S, "vi": S})),
})
BRIEF_PROMPT = """Đây là phần đầu (mục lục, lời nói đầu, chương đầu) của một tài liệu y khoa {SRC} sẽ được dịch \
sang tiếng Việt để xuất bản. Hãy phân tích và trả về:
- title: tên tài liệu (giữ nguyên {SRC}) và gợi ý tên tiếng Việt
- specialty: chuyên ngành chính
- audience: đối tượng độc giả
- summary: tóm tắt nội dung, phạm vi (5-8 câu, tiếng Việt)
- style_guide: hướng dẫn văn phong cụ thể cho bản dịch này (xưng hô, mức độ học thuật, cách trình bày tiêu đề, \
chú ý đặc thù chuyên ngành) – viết thành các gạch đầu dòng
- key_terms: 20-60 thuật ngữ then chốt xuất hiện trong tài liệu kèm bản dịch tiếng Việt chuẩn bạn đề xuất

VĂN BẢN:
"""

# ---------------------------------------------------------------- translate
TRANSLATE_SCHEMA = obj({"segments": arr(obj({
    "id": S, "translation": S,
    "uncertain_terms": arr(obj({"term": S, "chosen_vi": S, "reason": S})),
}))})

TRANSLATE_INSTRUCTIONS = """Dịch các đoạn trong "segments" sang tiếng Việt theo đúng các nguyên tắc. \
Dùng "context" để hiểu đúng ngữ cảnh (không dịch phần context). \
Bắt buộc dùng đúng thuật ngữ trong "glossary". "tm_references" là bản dịch đã duyệt của các câu tương tự – \
tham khảo cách dùng từ để nhất quán. "decided_terms" là thuật ngữ đã được tra cứu/xác nhận cho tài liệu này – bắt buộc dùng. \
Trả về đúng mọi id."""

# ---------------------------------------------------------------- review
REVIEW_SCHEMA = obj({"segments": arr(obj({
    "id": S, "score": I, "final": S, "problems": arr(S),
}))})

# Bước HIỆU ĐÍNH CHUYÊN MÔN (đối chiếu nội dung với bản gốc)
REVISE_SYSTEM = """Bạn là HIỆU ĐÍNH VIÊN CHUYÊN MÔN cho sách y khoa dịch xuất bản: bác sĩ chuyên khoa kiêm dược sĩ lâm sàng, thông thạo {SRC}. Nhiệm vụ: đối chiếu TỪNG CÂU bản dịch với bản gốc {SRC} về NỘI DUNG CHUYÊN MÔN, phát hiện và SỬA:
1. Sai nghĩa, thiếu ý, thừa ý, hiểu sai ngữ cảnh lâm sàng hoặc cơ chế bệnh sinh.
2. Sai số liệu, liều lượng, đơn vị, đường dùng, tần suất, phủ định, chỉ định/chống chỉ định, mức độ khuyến cáo (must/should/may/is recommended/is not recommended) và mức độ chắc chắn của bằng chứng.
3. Thuật ngữ không chuẩn chuyên ngành, không theo bảng thuật ngữ hoặc thuật ngữ đã chốt; tên thuốc, tên bệnh sai.
4. Mất mã giữ chỗ ⟦…⟧, mất thẻ định dạng; còn sót {SRC} không được phép.
Chưa ưu tiên trau chuốt văn phong (bước biên tập ngôn ngữ sẽ làm), nhưng câu sửa phải đúng ngữ pháp tiếng Việt.
Trả về "final" = bản dịch sau hiệu đính (giữ nguyên nếu đã đúng), "score" 0-100 (độ chính xác chuyên môn của bản final), "problems" = các lỗi chuyên môn đã sửa (ngắn gọn). "auto_check" là kết quả kiểm tra máy – có thể là báo động giả."""

# Bước BIÊN TẬP NGÔN NGỮ (văn phong xuất bản)
REVIEW_SYSTEM = """Bạn là BIÊN TẬP VIÊN NGÔN NGỮ của nhà xuất bản sách y học. Bản dịch đã qua hiệu đính chuyên môn. Nhiệm vụ: làm cho văn bản tiếng Việt đạt chuẩn xuất bản – rõ ràng, mạch lạc, tự nhiên như người Việt viết, đúng văn phong học thuật y khoa:
1. Sửa câu lủng củng, dịch word-by-word, bị động gượng ép, trật tự từ chịu ảnh hưởng {SRC}, lặp từ, câu quá dài khó đọc.
2. Sửa ngữ pháp, chính tả, dấu câu, viết hoa (tiêu đề, tên riêng), cách viết số và đơn vị theo quy ước.
3. Thống nhất văn phong, cách xưng hô và cách trình bày tiêu đề trong toàn tài liệu.
RÀNG BUỘC: luôn đối chiếu bản gốc để KHÔNG làm thay đổi nghĩa; TUYỆT ĐỐI không đổi thuật ngữ đã chuẩn, số liệu, liều, đơn vị, phủ định, mức khuyến cáo; giữ mã ⟦…⟧ và thẻ định dạng.
Trả về "final" = bản đã biên tập (giữ nguyên nếu đã tốt), "score" 0-100 (chất lượng ngôn ngữ của bản final), "problems" = các điểm đã sửa (ngắn gọn)."""

REFINE_INSTRUCTIONS = """Các bản dịch dưới đây còn lỗi được phát hiện bởi kiểm tra tự động / biên tập viên (xem "issues"). \
Hãy dịch lại cho đúng, sửa triệt để các lỗi thật (bỏ qua báo động giả nhưng đảm bảo bản dịch đúng), giữ nguyên ưu điểm \
của bản cũ. Trả về bản dịch hoàn chỉnh. Nếu một yêu cầu thống nhất thuật ngữ không phù hợp ngữ cảnh của đoạn này \
(nghĩa khác), hãy giữ cách dịch đúng ngữ cảnh."""

# ---------------------------------------------------------------- research
RESEARCH_SYSTEM = """Bạn là chuyên gia thuật ngữ y khoa {SRC_SHORT} – Việt. Với mỗi thuật ngữ được hỏi, hãy dùng công cụ tìm kiếm web \
để tìm cách dịch tiếng Việt CHUẨN đang được dùng thực tế bởi nguồn uy tín Việt Nam (ưu tiên: văn bản/hướng dẫn chẩn đoán \
và điều trị của Bộ Y tế, Dược thư Quốc gia Việt Nam, giáo trình các trường Đại học Y, bệnh viện lớn, hội chuyên ngành), \
đồng thời kiểm tra nghĩa {SRC} trong ngữ cảnh lâm sàng (MeSH, MedlinePlus, NCBI, WHO). \
Đánh giá độ tin cậy dựa trên số lượng và độ uy tín của nguồn. Nếu không tìm thấy cách dịch chuẩn, đề xuất cách dịch hợp lý \
nhất theo nguyên tắc tạo thuật ngữ y khoa tiếng Việt và ghi rõ trong note."""

RESEARCH_PROMPT = """Tra cứu và đối chiếu các thuật ngữ sau (kèm ngữ cảnh câu gốc và bản dịch tạm thời):

{items}

Nguồn ưu tiên: {domains}

Sau khi tra cứu xong, trả lời DUY NHẤT bằng JSON đặt trong thẻ <json></json> theo dạng:
<json>{{"terms": [{{"en": "...", "vi": "cách dịch chuẩn", "confidence": 0.0-1.0, "sources": ["url", ...], \
"note": "giải thích ngắn: nghĩa trong ngữ cảnh, vì sao chọn"}}]}}</json>"""

# ---------------------------------------------------------------- term extraction (làm giàu thuật ngữ)
EXTRACT_SCHEMA = obj({"terms": arr(obj({"en": S, "vi": S, "category": S, "note": S}))})
EXTRACT_PROMPT = """Từ các cặp câu gốc – bản dịch đã được biên tập dưới đây, hãy trích xuất các THUẬT NGỮ CHUYÊN MÔN y khoa \
(bệnh, triệu chứng, giải phẫu, thuốc, thủ thuật, xét nghiệm, chỉ số, viết tắt) cùng cách dịch đã dùng. \
Bỏ qua từ thông dụng. Chỉ lấy thuật ngữ có cách dịch nhất quán và chuẩn. category ∈ {disease, symptom, anatomy, drug, \
procedure, lab, abbreviation, physiology, statistics, other}. Bỏ qua thuật ngữ đã có trong danh sách "known".
"""

# ---------------------------------------------------------------- image OCR via Claude vision
OCR_SCHEMA = obj({"lines": arr(obj({"text": S, "x0": N, "y0": N, "x1": N, "y1": N}))})
OCR_PROMPT = """Ảnh có kích thước {w}x{h} pixel. Liệt kê MỌI dòng chữ {SRC} trong ảnh (nhãn, chú thích, trục biểu đồ, \
chú giải). Mỗi dòng trả về nội dung chính xác và hộp bao (x0,y0,x1,y1) theo pixel, sát chữ nhất có thể. \
Không liệt kê chữ chỉ có số/ký hiệu."""

# ---------------------------------------------------------------- đánh giá độc lập theo chuẩn MQM
MQM_CATEGORIES = ["accuracy_mistranslation", "accuracy_omission", "accuracy_addition", "accuracy_number_unit",
                  "accuracy_negation_modality", "terminology", "untranslated", "fluency_grammar",
                  "fluency_spelling", "style_register", "format_markup"]
EVAL_SCHEMA = obj({"segments": arr(obj({
    "id": S,
    "errors": arr(obj({
        "category": {"type": "string", "enum": MQM_CATEGORIES},
        "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
        "source_span": S, "target_span": S, "explanation": S, "fix": S,
    })),
    "corrected": S,
}))})

EVAL_SYSTEM = """Bạn là GIÁM KHẢO ĐỘC LẬP đánh giá chất lượng bản dịch y khoa {SRC_SHORT} → Việt theo khung MQM \
(Multidimensional Quality Metrics) – chuẩn đánh giá chất lượng dịch thuật quốc tế. Bạn KHÔNG phải người dịch; \
hãy khắt khe, khách quan, chỉ báo lỗi có thật.

Mức độ nghiêm trọng:
- critical: có thể gây hại lâm sàng hoặc đổi nghĩa chuyên môn (sai/thiếu số liệu, liều, đơn vị, đường dùng; mất/đảo \
phủ định, chống chỉ định; sai mức khuyến cáo; sai thuật ngữ dẫn tới hiểu sai bệnh/thuốc/thủ thuật; bỏ sót câu).
- major: sai nghĩa hoặc thiếu/thừa ý không gây hại trực tiếp; thuật ngữ không chuẩn/không theo bảng thuật ngữ; \
còn sót chữ chưa dịch; câu khó hiểu.
- minor: văn phong chưa tự nhiên, lỗi chính tả nhỏ, dấu câu, thiếu nhất quán nhỏ, lỗi định dạng nhỏ.

Danh mục lỗi: accuracy_mistranslation, accuracy_omission, accuracy_addition, accuracy_number_unit, \
accuracy_negation_modality, terminology, untranslated, fluency_grammar, fluency_spelling, style_register, format_markup.

Quy ước bắt buộc: mã ⟦…⟧ phải giữ nguyên; thẻ <b><i><sup><sub> phải tương ứng; định dạng số và các mục giữ nguyên \
theo nguyên tắc được cung cấp. Không coi việc tuân thủ các quy ước này là lỗi.

Với mỗi đoạn: liệt kê "errors" (rỗng nếu đạt), và "corrected" = bản dịch đã sửa HẾT các lỗi bạn nêu \
(chuỗi rỗng nếu không có lỗi). Không sửa những gì không phải lỗi."""

# ---------------------------------------------------------------- kiểm định thuật ngữ trước khi tự duyệt
TERM_VALIDATE_SCHEMA = obj({"terms": arr(obj({
    "en": S, "vi": S,
    "verdict": {"type": "string", "enum": ["standard", "acceptable", "wrong"]},
    "corrected_vi": S, "confidence": N, "note": S,
}))})
TERM_VALIDATE_PROMPT = """Kiểm định các cặp thuật ngữ y khoa {SRC_SHORT} → Việt dưới đây (đã được dùng nhất quán trong các \
đoạn dịch đạt chuẩn). Với mỗi cặp, xác định:
- verdict = "standard": đúng là thuật ngữ tiếng Việt chuẩn, thông dụng trong tài liệu Bộ Y tế / giáo trình Y / Dược thư;
- "acceptable": đúng nghĩa nhưng có cách gọi chuẩn hơn (ghi vào corrected_vi);
- "wrong": sai nghĩa hoặc không phải thuật ngữ (ghi cách đúng vào corrected_vi nếu có).
confidence 0–1 phản ánh mức chắc chắn của bạn. note: giải thích ngắn. Chỉ trả "standard" khi thực sự chắc chắn.

"""

# ---------------------------------------------------------------- sửa lỗi OCR cho PDF scan
OCR_FIX_SCHEMA = obj({"paragraphs": arr(obj({"id": S, "text": S}))})
OCR_FIX_PROMPT = """Đây là ảnh một trang tài liệu y khoa {SRC} được scan, kèm văn bản do phần mềm OCR nhận dạng theo \
từng đoạn (có id). Hãy đối chiếu với ảnh và SỬA LỖI NHẬN DẠNG (ký tự sai, số sai, đơn vị sai, ký hiệu µ ± ≥ ≤ °, \
chữ bị dính/tách, gạch nối cuối dòng). TUYỆT ĐỐI KHÔNG dịch, không diễn đạt lại, không thêm nội dung. \
Nếu một đoạn chỉ là nhiễu (vết bẩn, ký tự rác) thì trả text rỗng. Trả về đủ mọi id.

CÁC ĐOẠN OCR:
"""

# ---------------------------------------------------------------- hội đồng giám khảo: trọng tâm của từng giám khảo
JUDGE_FOCUS = {
    "clinical": "\n\nTRỌNG TÂM CỦA BẠN: độ chính xác chuyên môn y khoa – nghĩa, số liệu, liều, đơn vị, phủ định, "
                "mức khuyến cáo, thuật ngữ chuyên ngành. Vẫn báo mọi lỗi khác nếu thấy.",
    "linguistic": "\n\nTRỌNG TÂM CỦA BẠN: chất lượng tiếng Việt chuẩn xuất bản – ngữ pháp, chính tả, văn phong học thuật, "
                  "độ tự nhiên, nhất quán, sót chữ chưa dịch. Vẫn báo mọi lỗi nội dung nếu thấy.",
}

# ---------------------------------------------------------------- chuẩn bị thuật ngữ toàn văn (trước khi dịch)
TERMPREP_SCHEMA = obj({"terms": arr(obj({"en": S, "vi": S, "category": S, "confidence": N, "note": S}))})
TERMPREP_PROMPT = """Bạn đang CHUẨN BỊ BẢNG THUẬT NGỮ trước khi dịch một cuốn sách y khoa {SRC} sang tiếng Việt. Từ đoạn văn \
bản dưới đây, liệt kê các THUẬT NGỮ CHUYÊN MÔN (bệnh, hội chứng, triệu chứng, giải phẫu, sinh lý, thuốc/nhóm thuốc, thủ \
thuật, xét nghiệm, chỉ số, thang điểm, thống kê y học, cụm từ chuyên môn cố định). Bỏ qua từ thông dụng và các thuật ngữ đã \
có trong "known". Với mỗi thuật ngữ: "en" đúng như trong văn bản (dạng số ít), "vi" = thuật ngữ tiếng Việt chuẩn bạn đề xuất \
(theo Bộ Y tế, giáo trình Y, Dược thư), "confidence" 0–1 (thấp nếu có nhiều cách dịch hoặc bạn chưa chắc), \
"note" = ghi chú ngữ cảnh/nghĩa trong tài liệu này. Tối đa 150 thuật ngữ quan trọng nhất.

"""

# ---------------------------------------------------------------- biên tập toàn văn (nhất quán toàn tài liệu)
CONSIST_SCHEMA = obj({"fixes": arr(obj({"id": S, "issue": S, "corrected": S}))})
CONSIST_PROMPT = """Bạn là TỔNG BIÊN TẬP thực hiện BIÊN TẬP TOÀN VĂN một chương sách y khoa đã dịch. Đọc liền mạch các đoạn \
tiếng Việt dưới đây (theo thứ tự trong sách, kèm bản gốc {SRC}) và tìm lỗi chỉ thấy được khi đọc toàn văn:
- cùng một khái niệm/thuật ngữ nhưng dịch khác nhau giữa các đoạn (phải thống nhất theo bảng thuật ngữ / cách dùng phổ biến \
nhất đúng ngữ cảnh);
- tiêu đề, chú thích hình/bảng, đánh số trình bày không thống nhất;
- văn phong, cách xưng hô, cách viết tắt (lần đầu chú thích, sau giữ viết tắt) không nhất quán;
- câu nối giữa các đoạn bị đứt mạch, lặp ý do dịch rời từng đoạn.
CHỈ trả về các đoạn CẦN SỬA: "id", "issue" (mô tả ngắn), "corrected" = toàn bộ đoạn tiếng Việt sau khi sửa (giữ mã ⟦…⟧, \
thẻ định dạng; không đổi số liệu, liều, phủ định). Không có gì cần sửa thì trả danh sách rỗng.

"""

# ---------------------------------------------------------------- đọc morat (bản dàn trang)
PROOF_SCHEMA = obj({"issues": arr(obj({
    "type": {"type": "string", "enum": ["typo", "untranslated", "overlap", "cutoff", "illegible", "misplaced",
                                        "missing_content", "figure_text", "other"]},
    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
    "quote": S, "correction": S, "description": S,
}))})
PROOF_PROMPT = """Bạn là người ĐỌC MORAT (đọc bông) của nhà xuất bản. Ảnh 1 là trang gốc {SRC}, ảnh 2 là trang tiếng Việt \
đã dàn trang tương ứng. So sánh và liệt kê mọi lỗi trên TRANG TIẾNG VIỆT:
- typo: lỗi chính tả, dấu tiếng Việt, gõ sai → "quote" = cụm chữ sai đúng như trên trang, "correction" = cụm đã sửa;
- untranslated: còn chữ {SRC} chưa dịch (trừ tên riêng, viết tắt, ký hiệu, tài liệu tham khảo được phép giữ) → "quote" + \
"correction" (bản dịch);
- overlap: chữ chồng lên chữ/hình; cutoff: chữ bị cắt, tràn khung; illegible: chữ quá nhỏ khó đọc; misplaced: chữ đặt sai \
vị trí (vd nhãn hình lệch); missing_content: nội dung có ở trang gốc nhưng mất ở trang dịch; figure_text: chữ trong hình \
chưa dịch hoặc vẽ lại lỗi.
"description" mô tả ngắn vị trí và lỗi. Trang không có lỗi → danh sách rỗng. Không báo khác biệt do độ dài tự nhiên của \
tiếng Việt nếu trình bày vẫn gọn gàng, dễ đọc."""

# ---------------------------------------------------------------- kiểm toán trung thành (câu-đối-câu)
FIDELITY_SCHEMA = obj({"segments": arr(obj({
    "id": S,
    "sentences": arr(obj({
        "n": I, "target_span": S,
        "verdict": {"type": "string", "enum": ["ok", "partial", "altered", "omitted"]},
        "note": S,
    })),
    "additions": arr(S),
}))})
FIDELITY_SYSTEM = """Bạn là KIỂM TOÁN VIÊN ĐỘ TRUNG THÀNH của bản dịch y khoa {SRC_SHORT} → Việt. Bạn không chấm văn phong. \
Nhiệm vụ duy nhất: xác minh bản dịch dịch ĐÚNG, ĐỦ, ĐÚNG TRÌNH TỰ, KHÔNG THÊM, KHÔNG BỚT.
Với mỗi đoạn, bản gốc đã được máy tách thành các câu ĐÁNH SỐ. Bạn PHẢI trả về ĐỦ mọi số câu, mỗi câu gồm:
- "target_span": trích NGUYÊN VĂN phần bản dịch tương ứng (đủ dài để định vị; rỗng nếu không có);
- "verdict": ok (đủ ý, đúng nghĩa) | partial (thiếu một phần ý/chi tiết) | altered (sai/đổi nghĩa, sai số liệu, \
đảo phủ định, đổi mức khuyến cáo) | omitted (không được dịch);
- "note": giải thích ngắn khi không phải ok.
"additions": trích nguyên văn mọi phần trong bản dịch KHÔNG có trong bản gốc (giải thích, bình luận, thông tin tự thêm). \
Việc diễn đạt lại tự nhiên, tách/gộp câu, chú thích viết tắt theo quy ước, đổi định dạng số theo quy ước KHÔNG phải là thêm/bớt."""
