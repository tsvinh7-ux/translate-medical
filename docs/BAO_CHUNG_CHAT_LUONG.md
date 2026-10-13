# Bảo chứng chất lượng: trả lời câu hỏi "AI dịch có đúng, đủ, chuẩn như người không?"

**Nguyên tắc:** không yêu cầu ai *tin* AI. Mỗi bản dịch phải đi kèm **bằng chứng kiểm chứng được**:
- con số do **máy** tính từ dữ liệu, không phải lời AI tự nhận;
- một **phiếu kiểm định** in được, có chỗ ký;
- khi cần, kết quả **chuyên gia đọc mẫu ngẫu nhiên** hoặc **thử nghiệm mù người – máy**.

Thứ tự ưu tiên: **chất lượng dịch thuật → hiệu suất, tiến độ → hình thức**. Hình thức chỉ cần đủ để bộ phận thiết kế nhận ra bố cục gốc khi dàn trang lại.

## 1. ĐỦ: không thêm, không bớt, đúng trình tự, giữ cấu trúc

| Lớp kiểm soát | Cách làm | Ai kiểm |
|---|---|---|
| Tách câu đánh số | Mỗi đoạn nguồn được máy tách thành câu có số thứ tự. Kiểm toán viên AI độc lập phải chỉ ra vị trí của **từng câu** trong bản dịch. | Máy + AI độc lập |
| Cưỡng chế | Câu không được ánh xạ thì coi là **bị bỏ sót** (lỗi critical). Phần thêm vào là lỗi major. Đảo trình tự là lỗi major. Còn lỗi thì không được chứng nhận. | Máy |
| Kiểm tra số lượng | Số câu, số liệu, cặp số – đơn vị, mã công thức ⟦M⟧, mốc đoạn ⟦¶⟧, thẻ in đậm/nghiêng, độ dài bất thường. | Máy, không tốn token |
| Đối soát toàn văn | Mọi khối văn bản nguồn phải có đơn vị dịch. **Đọc lại PDF đầu ra** để xác nhận mọi khối dịch thực sự hiển thị trên đúng trang, không mất chữ khi dàn trang. | Máy |
| Cấu trúc | Tiêu đề, đoạn, chú thích, bảng, hình giữ vai trò và vị trí như bản gốc. Thiết kế nhận ra ngay form gốc. | Máy |

## 2. ĐÚNG: đúng nội dung, đúng ngữ cảnh chuyên môn

| Lớp kiểm soát | Cách làm |
|---|---|
| Đọc tổng quan trước khi dịch | AI nắm chủ đề, đối tượng độc giả, văn phong của cả tài liệu, rồi mới dịch từng đoạn. Bản tóm tắt này đi kèm mọi lần gọi AI. |
| Termbase khoá trước | Quét toàn văn, trích thuật ngữ, chuyên gia kiểm tra Excel/TBX rồi **khoá**. Bản dịch chính thức buộc dùng đúng thuật ngữ đã khoá. |
| Tra cứu khi chưa chắc | Thuật ngữ AI báo chưa chắc được tra web theo nguồn ưu tiên (Bộ Y tế, Dược thư Quốc gia, giáo trình Đại học Y…) và lưu nguồn kèm theo. |
| Hiệu đính chuyên môn | Một vai AI riêng đối chiếu bản gốc như bác sĩ hiệu đính: liều, chỉ định, phủ định, mức khuyến cáo. |
| Hội đồng 2 giám khảo độc lập | Giám khảo lâm sàng và giám khảo ngôn ngữ chấm theo khung **MQM**. Có lỗi nặng thì sửa rồi chấm lại, tối đa 3 vòng. |
| Kiểm tra máy | Số liệu, liều – đơn vị, phủ định ("không", "chống chỉ định"), chữ chưa dịch, ký hiệu phải giữ nguyên. |

## 3. ĐỌC TỐT: văn phong xuyên suốt, thuật ngữ đồng bộ, đọc là hiểu

| Lớp kiểm soát | Cách làm |
|---|---|
| **Văn phong nhà xuất bản** (`data/style_vi.yaml`) | Quy tắc văn phong được đưa vào lời dặn cho dịch, hiệu đính và biên tập. Nhà xuất bản tự sửa file này, không cần sửa mã. |
| **Bộ dò "văn dịch máy / văn AI"** | Máy dò các dấu hiệu:<br>• "một cách + tính từ";<br>• bị động "được … bởi";<br>• mở câu bằng "Nó";<br>• sáo ngữ "đóng vai trò quan trọng", cụm đệm kiểu AI;<br>• thừa từ, chuỗi "của" dài;<br>• bị động dày;<br>• câu quá dài.<br>Từng đoạn có dấu hiệu được chuyển cho **bước biên tập sửa**; mật độ toàn văn được ghi vào phiếu kiểm định. |
| Biên tập toàn văn | Sau khi dịch xong, AI đọc liền mạch từng phần lớn của sách để thống nhất cách gọi, văn phong và cách trình bày tiêu đề. |
| Một khái niệm, một cách gọi | Termbase khoá cộng thuật ngữ đã chốt trong tài liệu. Đoạn lặp lại dùng chung một bản dịch. Bộ nhớ dịch chỉ nhận đoạn đã đạt chuẩn. |

## 4. CỔNG PHÁT HÀNH và PHIẾU KIỂM ĐỊNH

Mỗi bản dịch xuất kèm `<tên>_VI_QA.html`, gọi là **Phiếu kiểm định chất lượng bản dịch**. Phiếu ghi:
- kết luận: **PHÁT HÀNH ĐƯỢC**, **CẦN XỬ LÝ** (kèm danh sách đoạn cụ thể) hoặc **BẢN NHÁP**;
- từng tiêu chí của Đủ, Đúng, Đọc tốt, Kiểm định, mỗi tiêu chí có giá trị đo và ngưỡng;
- quy trình đã chạy và công cụ đảm nhiệm từng bước;
- ô ký cho người kiểm định và biên tập viên.

Màn **Hàng đợi** hiển thị kết luận này ngay cạnh nút tải PDF. Ngưỡng chỉnh trong `config.yaml → quality`:

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `release_min_pass_percent` | 100 | % đoạn phải qua cổng chất lượng |
| `style_max_per_1000_words` | 6 | Mật độ dấu hiệu văn dịch máy tối đa |
| `long_sentence_max_percent` | 10 | % câu quá dài tối đa |
| `release_requires_lqa` | false | Bắt buộc chuyên gia kiểm định mẫu mới cho phát hành |

## 5. Chứng minh cho người không tin AI: chuyên gia kiểm chứng, công sức tối thiểu

**Kiểm định mẫu ngẫu nhiên (quy tắc "0 lỗi chấp nhận"):** chuyên gia chỉ cần đọc một mẫu ngẫu nhiên. Nếu mẫu không có lỗi nặng thì với độ tin cậy 95%, tỉ lệ đoạn lỗi nặng của **toàn bộ** sách không vượt ngưỡng. Số đoạn cần đọc **không phụ thuộc độ dài sách**:

| Ngưỡng lỗi nặng tối đa | Số đoạn cần đọc (tin cậy 95%) |
|---|---|
| 5% | 59 |
| 3% | 99 |
| 2% | 149 |
| 1% | 299 |

Cách làm:
1. Vào mục **Duyệt & can thiệp → Kiểm định độc lập**, hoặc chạy `python -m medtrans lqa sample sach.pdf`.
2. Gửi file Excel cho chuyên gia. File có sẵn danh sách chọn Đạt/Lỗi, mức lỗi và loại lỗi.
3. Nhập lại file đã chấm. Hệ thống tính **trần tỉ lệ lỗi 95%** và kết luận ĐẠT/CHƯA ĐẠT, đồng thời **áp bản sửa** vào bản dịch và bộ nhớ dịch với nguồn "người".
4. Dựng lại PDF. Phiếu kiểm định sẽ có thêm dòng "Kiểm định mẫu bởi chuyên gia".

**Thử nghiệm mù người – máy:** dùng các chương đã có bản dịch người (nhập TMX từ sách đã xuất bản).
- Hệ thống trộn bản người và bản máy, ẩn nguồn gốc. Chuyên gia chấm như nhau.
- Sau khi chấm, mở khoá để so sánh % đạt, % lỗi nặng và điểm của **người** và **máy**.
- Đây là bằng chứng thuyết phục nhất khi trình bày với hội đồng, đối tác hoặc nhà xuất bản.

Quy trình bám các chuẩn ngành dịch thuật:
- **ISO 17100**: dịch, rồi người thứ hai hiệu đính;
- **ISO 18587**: hậu biên tập bản dịch máy;
- **ISO 5060 / MQM**: đánh giá chất lượng bản dịch theo loại và mức lỗi.

Trong MedTrans, vai hiệu đính và giám khảo do các AI độc lập đảm nhiệm, còn chuyên gia **kiểm chứng bằng mẫu thống kê** thay vì đọc lại toàn bộ.

## 6. Độc lập, không phụ thuộc một AI nào (lộ trình)

**Hiện tại:** chạy **một mô thức chuẩn** (Claude, hoặc Local + Claude hỗ trợ). Khung dự phòng đã có sẵn trong mã nhưng **tắt** mặc định.

| Kịch bản | Cách xoay | Cấu hình |
|---|---|---|
| Nhà cung cấp chính lỗi hoặc quá tải | Tự chuyển sang nhà cung cấp kế tiếp cho lần gọi đó, rồi thử lại nhà cung cấp chính ở lần sau | `llm.failover: [openai, local]` |
| Muốn kiểm toán chéo khác hãng | Model hãng khác kiểm toán bản dịch của Claude (hoặc ngược lại) | `llm.routes: {fidelity: openai}` |
| Mất Internet, cần bảo mật tuyệt đối | Chạy toàn bộ trên máy | Hồ sơ `local_pro` / `local_quality` |
| Đổi sang model mới tốt hơn | Sửa một dòng `model:` trong cấu hình, rồi chạy **Hiệu chuẩn** để so sánh trên cùng giám khảo tham chiếu trước khi dùng | `llm.providers.*` |

Mọi nhà cung cấp có API chuẩn OpenAI đều dùng được: OpenAI, Gemini, DeepSeek, máy chủ riêng (vLLM).
- Khoá API đặt trong `.env`.
- Lệnh `python -m medtrans providers` kiểm tra khoá, model và kết nối.

Dù kết quả đến từ AI nào, **cùng một cổng kiểm soát** vẫn áp dụng: kiểm tra máy, hội đồng giám khảo, kiểm toán từng câu, cổng phát hành. Vì vậy chất lượng không phụ thuộc vào việc dùng AI nào.

**Giai đoạn kế tiếp (đề xuất):**
1. Điền model và khoá cho 1–2 nhà cung cấp dự phòng.
2. Chạy `calibrate` để có số đo chất lượng của từng nhà cung cấp trên sách của bạn.
3. Bật `failover`.
4. Bật kiểm toán chéo khác hãng cho sách quan trọng.
