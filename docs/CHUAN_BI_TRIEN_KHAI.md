# Chuẩn bị triển khai: máy, API, chi phí, thời gian

## 1. Danh sách cần chuẩn bị và phê duyệt

### A. Tài khoản Claude API (bắt buộc)
| # | Hạng mục | Ghi chú |
|---|---|---|
| 1 | Tài khoản tổ chức tại **console.anthropic.com** | Dùng email công ty. Đây là tài khoản API, tách biệt với gói Claude.ai Pro/Team |
| 2 | **Nạp tiền / phương thức thanh toán** | API tính phí theo token đã dùng. Nên đặt **giới hạn chi tiêu tháng** (Spend limit) trong Console |
| 3 | **API key** | Tạo trong Console → API Keys. Dán vào file `.env` (`ANTHROPIC_API_KEY=...`). Không gửi key qua chat/email |
| 4 | Quyền dùng model **claude-opus-5-5** | Thường có sẵn. Nếu bị từ chối, đổi `llm.model` trong `config.yaml` |
| 5 | **Công cụ tìm kiếm web (web search)** được bật cho tổ chức | Cần cho bước tra cứu thuật ngữ. Nếu tổ chức tắt tính năng này, bước tra cứu sẽ báo lỗi và tự bỏ qua (vẫn dịch được). Kiểm tra trong phần cài đặt của Console |
| 6 | **Hạn mức (rate limit tier)** | Hạn mức càng cao thì chạy được càng nhiều luồng song song (`translation.workers`), nên dịch càng nhanh. Hạn mức tự tăng theo mức nạp và mức sử dụng; xem trong Console → Limits |
| 7 | Phê duyệt **chính sách dữ liệu** | Nội dung sách được gửi tới máy chủ Anthropic để xử lý. Theo điều khoản thương mại, dữ liệu API không được dùng để huấn luyện model. Nên để bộ phận pháp chế/bản quyền xác nhận việc này phù hợp với hợp đồng mua bản quyền |

Không cần thêm cổng API nào khác. OCR (Tesseract), từ điển, bộ nhớ dịch và dàn trang PDF đều chạy **trên máy của bạn**.

### B. Máy chạy localhost
| Hạng mục | Yêu cầu |
|---|---|
| Hệ điều hành | Windows 10/11, macOS hoặc Linux |
| Python | 3.10 trở lên (khuyến nghị 3.12) |
| Tesseract OCR | Bắt buộc nếu có PDF scan hoặc hình có chữ. Windows: bản cài UB Mannheim, thêm vào PATH |
| Font tiếng Việt | Windows/macOS có sẵn Times New Roman và Arial. Linux: cài `fonts-noto` hoặc `fonts-dejavu` |
| RAM / ổ đĩa | ≥ 8 GB RAM; ổ trống ≥ 5 GB (tệp tạm, CSDL, PDF kết quả) |
| Mạng | Kết nối Internet ổn định tới `api.anthropic.com`. Nếu công ty có tường lửa hoặc proxy, cần mở cổng HTTPS 443 tới địa chỉ này |
| Vận hành | Sách dài chạy nhiều giờ: tắt chế độ ngủ của máy. Nếu bị ngắt, chạy lại sẽ **tiếp tục từ chỗ dừng**, không tốn lại tiền cho phần đã xong |

Khởi động: nháy đúp `run_windows.bat` (hoặc chạy `./run_mac_linux.sh`), sau đó mở `http://localhost:8501`.

### C. Nhận diện thương hiệu DMAG (cho giao diện và báo cáo)
- Logo: file PNG nền trong suốt, đặt vào `assets/logo.png`.
- Mã màu chính và màu phụ (HEX), font chữ thương hiệu (nếu có).
- Tên hiển thị chính thức.

Sau khi có, điền vào mục `branding` trong `config.yaml`. Giao diện và báo cáo HTML sẽ tự áp dụng.

## 2. Cách tính chi phí

- Chi phí được tính theo **toàn văn (full text)**, cụ thể là số ký tự thực tế cần dịch trong tài liệu, **không tính theo số trang**. Danh mục tài liệu tham khảo, công thức, số trang được giữ nguyên nên không bị tính.
- Để dễ hình dung, quy đổi **1 trang A4 chuẩn ≈ 3.000 ký tự** (khoảng 450–500 từ tiếng Anh). Sách giáo khoa y khoa khổ lớn 2 cột thường có 4.000–6.000 ký tự/trang, tức tương đương 1,5–2 trang A4.
- Lệnh `estimate` (nút **💰 Ước tính** trên giao diện) cho ra `a4_equivalent_pages` và khoảng chi phí của từng file cụ thể.

Ước tính với cấu hình **khắt khe** mặc định (Opus, `effort: xhigh`, hiệu đính + biên tập + 2 giám khảo MQM + biên tập toàn văn + đọc morat bằng hình ảnh):

| Khối lượng | Chi phí ước tính |
|---|---|
| 1 trang A4 (3.000 ký tự) | ~0,4–0,8 USD |
| Sách 300 trang A4 | ~115–250 USD |
| Sách 500 trang A4 | ~190–410 USD |

Đây là ước lượng ban đầu, chưa đo trên tài liệu thật. Chi phí thực tế được ghi trong báo cáo sau mỗi lần dịch. Về sau, bộ nhớ dịch và prompt caching sẽ giảm chi phí cho các sách cùng chuyên ngành.

## 3. Thời gian dịch

Mỗi đoạn văn phải đi qua 6–8 lượt xử lý của Claude: dịch, hiệu đính, biên tập, 2 giám khảo, có thể thêm vòng sửa và chấm lại. Sau đó còn biên tập toàn văn và đọc morat từng trang. Vì vậy thời gian chủ yếu phụ thuộc vào **tốc độ sinh chữ của model** và **số luồng song song** mà hạn mức API cho phép.

Ước tính với 3 luồng song song (`translation.workers: 3`), cấu hình khắt khe:

| Khối lượng | Thời gian ước tính |
|---|---|
| 1 trang A4 | ~2–4,5 phút |
| 100 trang A4 | ~3,3–7,5 giờ |
| 500 trang A4 | ~16–37 giờ (có thể chạy qua đêm, dừng và tiếp tục được) |

- Tăng `workers` lên 6–8 (nếu hạn mức API đủ) thì thời gian giảm gần một nửa.
- `effort: high` thay cho `xhigh` nhanh hơn khoảng 25%. `effort: max` chậm hơn khoảng 35%.
- **Ước tính tự hiệu chỉnh:** sau mỗi lần dịch, công cụ đo tốc độ thực tế trên máy và tài khoản của bạn. Lần ước tính sau dùng số đo này (trường `time_basis` cho biết đang dùng số đo hay ước lượng mặc định).
- Trong khi dịch, thanh tiến trình hiển thị **thời gian còn lại** cho từng công đoạn.

## 4. Lộ trình tối ưu (sau khi chất lượng đã ổn định)

1. Chạy 2–3 cuốn để tích luỹ số đo thực tế: chi phí và thời gian từng công đoạn, điểm MQM, tỉ lệ đạt chuẩn.
2. Thử hạ từng nấc trên một chương mẫu và so điểm MQM với bản khắt khe:
   - `effort` xhigh → high;
   - 2 giám khảo → 1;
   - tắt đọc morat bằng hình ảnh cho các trang chỉ có chữ.

   Chỉ giữ thay đổi nào không làm giảm điểm.
3. Khi bộ nhớ dịch và từ điển đã giàu, các sách cùng chuyên ngành sẽ rẻ và nhanh hơn một cách tự nhiên.
4. Có thể dùng **Batch API** (giảm 50% giá, trả kết quả trong vòng tối đa 24 giờ) cho những sách không gấp. Đây là hướng phát triển tiếp theo.
