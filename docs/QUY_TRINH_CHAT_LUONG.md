# Quy trình đảm bảo chất lượng tự động (chuẩn MQM, không cần người duyệt)

## 1. Quy trình xuất bản (tương ứng quy trình của nhà xuất bản)

| # | Công đoạn | Ai làm | Nội dung |
|---|---|---|---|
| 0 | Phân tích bản thảo | Máy | Bố cục, cột, tiêu đề, chú thích, bảng, công thức, hình. Trang **scan** được OCR theo đoạn văn, sau đó Claude đối chiếu ảnh để sửa lỗi OCR |
| 1 | **Chuẩn bị thuật ngữ toàn văn** | Claude + tra cứu web | Quét **cả cuốn** trước khi dịch, lập bảng thuật ngữ. Thuật ngữ có nhiều cách dịch hoặc chưa chắc được tra cứu nguồn uy tín rồi **chốt dùng thống nhất cho cả sách** |
| 2 | **Dịch** | Dịch giả AI | Mỗi lô dịch kèm ngữ cảnh mục, đoạn trước, thuật ngữ bắt buộc và câu đã chứng nhận tương tự |
| 3 | **Hiệu đính chuyên môn** | AI vai bác sĩ chuyên khoa kiêm dược sĩ | Đối chiếu **từng câu** với bản gốc: nghĩa, số liệu, liều, đơn vị, chỉ định/chống chỉ định, mức khuyến cáo, thuật ngữ chuyên ngành |
| 4 | **Biên tập ngôn ngữ** | AI vai biên tập viên nhà xuất bản | Văn phong xuất bản, ngữ pháp, chính tả, độ mạch lạc. **Không được đổi** nội dung chuyên môn; máy chặn mọi chỉnh sửa làm phát sinh lỗi nội dung |
| 5 | Kiểm tra máy và dịch lại | Máy + AI | Số liệu, liều–đơn vị, phủ định, ký hiệu, sót chưa dịch… Còn lỗi thì dịch lại có chỉ dẫn (tối đa 3 vòng) |
| 6 | **Hội đồng giám khảo MQM** | 2 giám khảo độc lập: chuyên môn + ngôn ngữ | Chấm theo chuẩn MQM. Còn lỗi critical/major thì sửa và chấm lại (tối đa 3 vòng). Đoạn đạt chuẩn được **tự chứng nhận** |
| 7 | **Biên tập toàn văn** | AI vai tổng biên tập | Đọc **liền mạch từng chương** để thống nhất thuật ngữ, tiêu đề, cách viết tắt và văn phong giữa các đoạn. Đoạn bị sửa phải qua hội đồng giám khảo lại |
| 8 | **Dàn trang** | Máy | Đặt chữ Việt vào đúng bố cục gốc, giữ hình, bảng và công thức |
| 9 | **Đọc morat (đọc bông)** | Máy + AI nhìn ảnh trang | So **ảnh trang gốc với ảnh trang dịch**: lỗi chính tả, sót dịch, chữ chồng/tràn/quá nhỏ, mất nội dung, chữ trong hình. Lỗi chữ được **tự sửa**; trang lỗi bố cục được **dàn lại chặt** rồi đọc lại (2 vòng) |
| 10 | Làm giàu dữ liệu và báo cáo | Máy + AI | Đoạn đạt chuẩn vào bộ nhớ dịch; thuật ngữ đủ bằng chứng được tự duyệt. Báo cáo song ngữ ghi lại toàn bộ quá trình |

Mỗi công đoạn đều **có điểm lưu**. Nếu bị ngắt, chạy lại sẽ tiếp tục từ chỗ dừng. Phần đã xử lý không bị tính tiền lại vì kết quả được lưu đệm.

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

**Điểm** = 100 − tổng phạt × 100 / số từ (tối thiểu tính trên 40 từ). Lỗi của 2 giám khảo được gộp lại; lỗi trùng chỉ tính một lần, lấy mức nặng hơn. Ví dụ: đoạn 60 từ có 1 lỗi minor đạt khoảng 98 điểm; đoạn có 1 lỗi major chỉ còn khoảng 92 điểm.

**Kết quả mỗi đoạn:**
- **Đạt chuẩn (certified):** điểm ≥ **97** (`quality.certify_score`), không còn lỗi critical/major, không còn **bất kỳ** lỗi hay cảnh báo máy nào (`strict_certify`). Đoạn được lưu vào bộ nhớ dịch ở mức *đã duyệt*, dùng lại không tốn token và làm mẫu tham khảo cho các tài liệu sau.
- **Đạt (done):** không có lỗi nặng nhưng điểm dưới ngưỡng. Đoạn vẫn được dùng trong PDF nhưng không được dùng lại tự động.
- **Còn lỗi nặng (needs_review):** còn lỗi critical hoặc lỗi máy sau mọi vòng sửa. Đoạn được đưa lên đầu báo cáo.

## 4. Tự làm giàu dữ liệu, không cần người duyệt

- **Đoạn dịch:** chỉ đoạn **đạt chuẩn MQM** mới vào bộ nhớ dịch "đã duyệt". Kho dữ liệu vì vậy chỉ tăng thêm bản dịch chất lượng cao.
- **Thuật ngữ:** mỗi cặp thuật ngữ phải vượt qua 3 lớp trước khi được tự duyệt:
  1. **Bằng chứng.** Cặp phải được dùng nhất quán trong ≥ `term_min_evidence` (3) đoạn **đạt chuẩn**. Số bằng chứng được cộng dồn qua nhiều tài liệu.
  2. **Kiểm định.** Giám khảo xác nhận đây là thuật ngữ chuẩn (`standard`) với độ tin cậy ≥ 0,9.
  3. **Không xung đột.** Thuật ngữ đã duyệt trước đó không bao giờ bị ghi đè.

  Nếu giám khảo cho rằng có cách gọi chuẩn hơn, thuật ngữ được thay bằng cách gọi đó và phải tích luỹ lại bằng chứng từ đầu.
- **Thuật ngữ tra web** được tự duyệt ngay khi có độ tin cậy ≥ 0,9 và ≥ 2 nguồn, trong đó ít nhất một nguồn uy tín (gov.vn, edu.vn, Bộ Y tế, Dược thư, WHO, NIH…).

Kết quả: càng dịch nhiều sách cùng chuyên ngành, từ điển và bộ nhớ dịch càng giàu. Bản dịch vì thế nhất quán hơn và rẻ hơn.

## 5. Cấu hình chế độ khắt khe (mặc định)

```yaml
llm:
  effort: xhigh              # max nếu muốn kỹ nhất
  review_effort: xhigh
translation:
  max_refine_rounds: 3
workflow: {revise: true, edit: true, consistency: true}
terminology: {prepass: true}
quality:
  judges: [clinical, linguistic]
  eval_rounds: 3
  certify_score: 97
  strict_certify: true
  term_min_evidence: 3
  term_min_confidence: 0.9
proof: {enabled: true, vision: true, rounds: 2}
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
