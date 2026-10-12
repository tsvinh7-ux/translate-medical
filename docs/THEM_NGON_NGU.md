# Thêm ngôn ngữ nguồn mới → tiếng Việt

MedTrans được thiết kế theo **cặp ngôn ngữ**. Đích luôn là tiếng Việt. Hiện **Anh → Việt** đã hoàn thiện và được kiểm thử. Các ngôn ngữ nguồn khác (Pháp, Đức, Trung, Nhật, Nga…) có thể cắm thêm **mà không phải sửa quy trình chính**.

## Những gì phụ thuộc ngôn ngữ (đã tách riêng)

| Thành phần | Vị trí | Dùng để |
|---|---|---|
| Hồ sơ ngôn ngữ `LangProfile` | `medtrans/languages.py` | Tên trong prompt, mã OCR, cách viết số, từ phủ định, từ thông dụng (phát hiện sót chưa dịch), mẫu chú thích hình/bảng, mẫu mục tài liệu tham khảo |
| Quy tắc giữ nguyên riêng | `data/preserve_rules.<mã>.yaml` (tuỳ chọn) | Ngoại lệ viết tắt và quy ước chuyển đổi riêng. Nếu không có file riêng, máy dùng `preserve_rules.yaml` |
| Thuật ngữ, bộ nhớ dịch | CSDL, cột `src_lang` | Mỗi ngôn ngữ nguồn có từ điển và bộ nhớ dịch riêng, không lẫn nhau |
| Prompt | `medtrans/prompts.py` | Dùng `{SRC}` / `{SRC_SHORT}`, tự thay bằng tên ngôn ngữ |

## Các bước thêm một ngôn ngữ (ví dụ tiếng Pháp)

1. Cài gói OCR cho ngôn ngữ đó: `tesseract-ocr-fra` (Windows: chọn *French* khi cài).
2. Thêm hồ sơ vào `medtrans/languages.py`:
   ```python
   FR = LangProfile(
       code="fr", name_vi="tiếng Pháp", short_vi="Pháp", tesseract="fra", number_style="comma_decimal",
       negation=re.compile(r"\b(ne|n'|pas|jamais|sans|contre-indiqu\w*|éviter|aucun\w*)\b", re.I),
       stopwords=frozenset({"le", "les", "des", "du", "et", "est", "sont", "pour", "avec", "dans", "chez",
                            "patients", "traitement", "maladie", "qui", "que", "une", "sur", "par"}),
       caption=re.compile(r"^\s*(Figure|Fig\.|Tableau|Encadré)\s*[\dA-Z]", re.I),
       references=re.compile(r"^\s*(\d+\.?\s*)?(Références|Bibliographie)\s*$", re.I),
       ready=False,
   )
   PROFILES["fr"] = FR
   ```
3. Tuỳ chọn: tạo `data/preserve_rules.fr.yaml` với ngoại lệ và quy ước riêng, ví dụ `Figure → Hình`, `et coll. → và cs.`.
4. Nhập từ điển: `python -m medtrans glossary import tu_dien_phap_viet.xlsx --lang fr --domain cardiology`.
5. Dịch thử: `python -m medtrans translate livre.pdf --lang fr --pages 1-10`. Xem điểm MQM trong báo cáo, tinh chỉnh `stopwords` và `negation` nếu máy báo lỗi giả, rồi đặt `ready=True`.

Ngôn ngữ chữ tượng hình (Trung, Nhật, Hàn) cần thêm bộ tách từ cho phần khớp thuật ngữ (`tokenizer="cjk"`). Phần này sẽ được phát triển khi bổ sung các ngôn ngữ đó.
