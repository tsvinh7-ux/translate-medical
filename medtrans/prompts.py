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

REVIEW_SYSTEM = """Bạn là biên tập viên y khoa (bác sĩ, có kinh nghiệm thẩm định sách dịch xuất bản). Nhiệm vụ: đối chiếu \
TỪNG đoạn bản dịch với bản gốc {SRC}, phát hiện và SỬA:
1. Sai nghĩa, thiếu ý, thừa ý, hiểu sai ngữ cảnh lâm sàng.
2. Sai số liệu, liều lượng, đơn vị, phủ định, mức độ khuyến cáo.
3. Thuật ngữ không chuẩn hoặc không theo bảng thuật ngữ; thiếu nhất quán.
4. Câu văn lủng củng, dịch word-by-word, sai ngữ pháp/chính tả tiếng Việt; còn sót {SRC} không được phép.
5. Mất mã giữ chỗ ⟦…⟧, mất thẻ định dạng.
Trả về "final" = bản dịch hoàn chỉnh sau khi sửa (nếu bản dịch đã tốt thì giữ nguyên), "score" 0-100 \
(chất lượng xuất bản của bản final), "problems" = các lỗi đã phát hiện ở bản dịch ban đầu (ngắn gọn, tiếng Việt). \
"auto_check" là kết quả kiểm tra tự động bằng máy – có thể là báo động giả, hãy tự thẩm định. \
Chỉ sửa khi thực sự cần; tôn trọng văn phong tốt sẵn có."""

REFINE_INSTRUCTIONS = """Các bản dịch dưới đây còn lỗi được phát hiện bởi kiểm tra tự động / biên tập viên (xem "issues"). \
Hãy dịch lại cho đúng, sửa triệt để các lỗi thật (bỏ qua báo động giả nhưng đảm bảo bản dịch đúng), giữ nguyên ưu điểm \
của bản cũ. Trả về bản dịch hoàn chỉnh."""

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
