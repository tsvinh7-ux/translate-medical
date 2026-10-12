# Quy trình đảm bảo chất lượng tự động (chuẩn MQM, không cần người duyệt)

## 1. Quy trình cho mỗi lô đoạn văn

```
PDF ─► Phân tích bố cục (cột, tiêu đề, chú thích, bảng, công thức, hình, tài liệu tham khảo)
    │    └─ trang SCAN: OCR theo đoạn → Claude đối chiếu ảnh sửa lỗi OCR
    ─► AI đọc tổng quan tài liệu: chuyên ngành, độc giả, văn phong, thuật ngữ then chốt
    ─► Với mỗi lô ~6.000 ký tự:
         1. Tra bộ nhớ dịch: đoạn ĐÃ CHỨNG NHẬN khớp 100% → dùng lại (0 token)
         2. DỊCH: ngữ cảnh mục + đoạn trước + thuật ngữ bắt buộc + câu tương tự đã chứng nhận
         3. Thuật ngữ chưa chắc → TRA CỨU WEB → chốt cho cả tài liệu → dịch lại đoạn liên quan
         4. TỰ ĐỐI CHIẾU BẰNG MÁY (bảng mục 2)
         5. BIÊN TẬP VIÊN AI sửa văn phong và nội dung
         6. Máy còn bắt lỗi → DỊCH LẠI có chỉ dẫn (tối đa max_refine_rounds vòng)
         7. GIÁM KHẢO ĐỘC LẬP chấm theo khung MQM (mục 3)
              còn lỗi critical/major → áp bản sửa của giám khảo (nếu qua kiểm tra máy) hoặc dịch lại
              → CHẤM LẠI (eval_rounds)
         8. CHỨNG NHẬN: điểm ≥ certify_score, không lỗi nặng, không lỗi máy → bộ nhớ dịch "đã duyệt"
    ─► Dịch chữ trong hình (OCR → dịch → chấm MQM → vẽ lại)
    ─► Dựng PDF tiếng Việt giữ bố cục
    ─► TỰ LÀM GIÀU TỪ ĐIỂN từ các đoạn đạt chuẩn (mục 4) + báo cáo song ngữ HTML
```

## 2. Tự đối chiếu bằng máy (không tốn token)

| Kiểm tra | Mức | Phát hiện |
|---|---|---|
| Số liệu | lỗi | Thiếu hoặc sai số. Máy quy đổi 0.5 ↔ 0,5 và 1,000 ↔ 1.000 trước khi so |
| Cặp số – đơn vị | lỗi | `40 mg` thành `4 mg` hay `40 g`; liều theo cân nặng `mg/kg` |
| Phủ định / chống chỉ định | lỗi | Bản gốc có *not, no, never, without, contraindicated, avoid*; bản dịch không có *không, chống chỉ định, tránh…* |
| Sót chữ chưa dịch | lỗi | Bản dịch còn câu chữ ngôn ngữ nguồn |
| Mã giữ chỗ | lỗi | Mất hoặc lặp URL, DOI, công thức |
| Ký hiệu phải giữ nguyên | cảnh báo | Mất viết tắt, ký hiệu gen, mã ICD, trích dẫn [12] |
| Thuật ngữ bắt buộc | cảnh báo | Không dùng thuật ngữ trong từ điển hoặc thuật ngữ đã chốt |
| Độ dài bất thường | cảnh báo | Nghi thiếu hoặc thừa ý |
| Thẻ định dạng | cảnh báo | Mất cân bằng chữ đậm, nghiêng, chỉ số trên/dưới |

## 3. Đánh giá chuẩn MQM bởi giám khảo độc lập

MQM (Multidimensional Quality Metrics) là khung đánh giá chất lượng dịch thuật quốc tế, được dùng trong ngành dịch chuyên nghiệp và trong các kỳ đánh giá dịch máy WMT. Giám khảo là một lượt gọi Claude riêng. Lượt này chỉ thấy bản gốc và bản dịch, không thấy quá trình dịch, và được yêu cầu chấm khắt khe.

**Danh mục lỗi:** sai nghĩa · thiếu ý · thừa ý · sai số/đơn vị · sai phủ định/mức khuyến cáo · thuật ngữ · sót chưa dịch · ngữ pháp · chính tả · văn phong · định dạng.

**Mức độ và điểm phạt:**

| Mức | Ví dụ | Phạt |
|---|---|---|
| critical | sai liều, mất "chống chỉ định", sai tên thuốc/bệnh, bỏ sót câu | 25 |
| major | sai nghĩa không gây hại trực tiếp, thuật ngữ không chuẩn, câu khó hiểu | 5 |
| minor | văn phong chưa tự nhiên, chính tả nhỏ, dấu câu | 1 |

**Điểm** = 100 − tổng phạt × 100 / số từ (tối thiểu tính trên 40 từ). Ví dụ một đoạn 60 từ có 1 lỗi minor đạt khoảng 98 điểm. Đoạn có 1 lỗi major chỉ còn khoảng 92 điểm, không đạt ngưỡng 95.

**Kết quả mỗi đoạn:**
- **Đạt chuẩn (certified):** điểm ≥ 95 (`quality.certify_score`), không còn lỗi critical/major, không còn lỗi máy. Đoạn được lưu vào bộ nhớ dịch ở mức *đã duyệt*, dùng lại không tốn token và làm mẫu tham khảo cho các tài liệu sau.
- **Đạt (done):** không có lỗi nặng nhưng điểm dưới ngưỡng. Đoạn vẫn được dùng trong PDF nhưng không được dùng lại tự động.
- **Còn lỗi nặng (needs_review):** còn lỗi critical hoặc lỗi máy sau mọi vòng sửa. Đoạn được đưa lên đầu báo cáo.

## 4. Tự làm giàu dữ liệu, không cần người duyệt

- **Đoạn dịch:** chỉ đoạn **đạt chuẩn MQM** mới vào bộ nhớ dịch "đã duyệt". Kho dữ liệu vì vậy chỉ tăng thêm bản dịch chất lượng cao.
- **Thuật ngữ:** mỗi cặp thuật ngữ phải vượt qua 3 lớp trước khi được tự duyệt:
  1. **Bằng chứng.** Cặp phải được dùng nhất quán trong ≥ `term_min_evidence` (2) đoạn **đạt chuẩn**. Số bằng chứng được cộng dồn qua nhiều tài liệu.
  2. **Kiểm định.** Giám khảo xác nhận đây là thuật ngữ chuẩn (`standard`) với độ tin cậy ≥ 0,85.
  3. **Không xung đột.** Thuật ngữ đã duyệt trước đó không bao giờ bị ghi đè.

  Nếu giám khảo cho rằng có cách gọi chuẩn hơn, thuật ngữ được thay bằng cách gọi đó và phải tích luỹ lại bằng chứng từ đầu.
- **Thuật ngữ tra web** được tự duyệt ngay khi có độ tin cậy ≥ 0,85 và ≥ 2 nguồn, trong đó ít nhất một nguồn uy tín (gov.vn, edu.vn, Bộ Y tế, Dược thư, WHO, NIH…).

Kết quả: càng dịch nhiều sách cùng chuyên ngành, từ điển và bộ nhớ dịch càng giàu. Bản dịch vì thế nhất quán hơn và rẻ hơn.

## 5. Cấu hình

```yaml
llm:
  model: claude-opus-5-5
  effort: high               # xhigh / max cho sách rất khó
quality:
  independent_eval: true
  eval_rounds: 2
  certify_score: 95          # nâng lên 97–98 nếu muốn khắt khe hơn
  term_min_evidence: 2       # nâng lên 3 nếu muốn thận trọng hơn khi tự duyệt thuật ngữ
```

## 6. PDF scan

Chấp nhận dàn trang không đẹp bằng PDF gốc. Ưu tiên của chế độ này là **dịch đúng, đủ và giữ định dạng cơ bản**:

- Tự nhận diện trang scan (không có lớp chữ, ảnh phủ phần lớn trang). Máy OCR theo **đoạn văn**, tự gộp các mảnh đoạn bị Tesseract cắt nhầm và nối câu qua cột/trang.
- **Claude đối chiếu ảnh trang để sửa lỗi OCR** (số, đơn vị, ký hiệu µ ± ≥ ≤…) trước khi dịch (`scan.ocr_correct`).
- Sau đó các đoạn đi qua **đúng quy trình chất lượng như PDF thường**: thuật ngữ, tra cứu, kiểm tra máy, biên tập, chấm MQM.
- Khi dựng PDF, máy phủ màu nền lên vị trí chữ gốc rồi đặt chữ Việt vào đúng vị trí. Cỡ chữ được ước lượng, màu chữ được giữ, tiêu đề in đậm.
- Cần cài Tesseract OCR. Chất lượng OCR tốt nhất khi bản scan đạt từ 300 dpi trở lên, thẳng, rõ nét.

## 7. Giới hạn kỹ thuật

- **Bố cục phức tạp** (3 cột, chữ chạy quanh hình, bảng nhiều ô gộp) được xử lý theo từng khối chữ.
- **Chữ trong hình:** chữ Việt được vẽ đè lên vùng nền của chữ gốc. Hình nền phức tạp có thể để lại vệt.
- **Công thức toán:** giữ nguyên. Từ ngữ nằm trong công thức không có font toán sẽ được dịch.
- **Chữ nghiêng** cần font có biến thể nghiêng. Trên Windows, Times New Roman và Arial có đủ các biến thể.
- **Giám khảo AI là kiểm soát chất lượng mạnh nhưng không phải bảo đảm tuyệt đối.** Báo cáo HTML liệt kê mọi lỗi MQM đã phát hiện để bạn tra cứu khi cần.
