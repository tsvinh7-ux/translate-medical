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

- Chi phí được tính theo **toàn văn (full text)**, cụ thể là số ký tự thực tế cần dịch, **không tính theo trang**. Danh mục tài liệu tham khảo, công thức và số trang được giữ nguyên nên không bị tính. Đoạn **lặp lại trong tài liệu** và đoạn **khớp 100% bộ nhớ dịch đã chứng nhận** cũng không tốn token.
- Để dễ hình dung, quy đổi **1 trang A4 ≈ 3.000 ký tự** (khoảng 450–500 từ tiếng Anh). Sách y khoa khổ lớn 2 cột tương đương khoảng 1,5–2 trang A4/trang.
- Mục **📊 Phân tích tài liệu** (kiểu SDL Trados) cho biết số từ, số trang A4 quy đổi, phân bổ theo mức khớp và **số từ quy đổi** (weighted), cùng dự báo chi phí và thời gian theo từng hồ sơ.

## 3. Hồ sơ chất lượng / chi phí và dự báo (1 trang A4 = 3.000 ký tự)

| Hồ sơ | Model | Quy trình | Chi phí / trang A4 | 1.000 trang A4: chi phí | 1.000 trang A4: thời gian (luồng mặc định) | … với 32 luồng |
|---|---|---|---|---|---|---|
| **Bản thô nhanh** | Haiku 5.5, effort low | Chỉ dịch + kiểm tra máy + thuật ngữ toàn văn | ~0,001–0,002 USD | ~1–2 USD | 6–14 phút (32 luồng) | 6–14 phút |
| **Tiết kiệm** | Sonnet 5.5, medium | Dịch, biên tập, 1 giám khảo, kiểm toán trung thành, biên tập toàn văn | ~0,10–0,21 USD | ~95–205 USD | 2–4,5 giờ (12 luồng) | 45 phút–1 giờ 45 phút |
| **Cân bằng** | Opus 5.5, high | + hiệu đính chuyên môn, đọc morat bằng hình ảnh 1 vòng | ~0,30–0,64 USD | ~300–645 USD | 9–21 giờ (8 luồng) | 2,3–5,2 giờ |
| **Xuất bản cao cấp** (mặc định) | Opus 5.5, xhigh | Đầy đủ: 2 giám khảo, 3 vòng, đọc morat 2 vòng | ~0,46–0,99 USD | ~465–995 USD | 16–37 giờ (6 luồng) | 3–7 giờ |

- Đây là **dự báo ban đầu**, chưa đo trên tài liệu thật. Sau mỗi lần dịch, công cụ **tự đo** tốc độ thực tế để hiệu chỉnh dự báo.
- Dùng mục **🎯 Hiệu chuẩn** trên 10–20 trang mẫu để có **số đo thật** cho từng hồ sơ: điểm MQM, **xác suất đạt chuẩn kèm khoảng tin cậy 95%**, chi phí và thời gian mỗi trang A4. Kết quả này hiển thị ngay khi chọn hồ sơ cho dự án mới.
- **"Bản thô → nâng cấp":** dịch bản thô trước để đọc và duyệt nhanh, sau đó chạy hồ sơ cao hơn trên cùng tài liệu. Hồ sơ cao hơn **dùng lại bản thô làm điểm xuất phát** (bỏ bước dịch lại từ đầu) rồi đi tiếp hiệu đính, biên tập, giám khảo và kiểm toán.

### Có dịch được 1.000 trang trong 5 phút không?
- **Bản thô: gần được.** Ước tính 6–14 phút với 32 luồng song song. Muốn xuống khoảng 5 phút cần khoảng 50–100 luồng, tức hạn mức API rất cao. Nếu hạn mức thấp, API trả lỗi giới hạn và công cụ tự chờ rồi thử lại, nên thời gian dài hơn.
- **Bản xuất bản chuẩn: không.** Mỗi đoạn phải qua 6–9 lượt xử lý tuần tự: dịch → hiệu đính → biên tập → 2 giám khảo → kiểm toán → (sửa, chấm lại) → đọc morat. Với 32 luồng, cần khoảng 3–7 giờ cho 1.000 trang.
- **Cách làm hiệu quả nhất:** bản thô trong vài phút để đọc và duyệt nội dung, rồi nâng cấp chạy nền (qua đêm). Hàng đợi cho phép theo dõi, tạm dừng và tiếp tục.

## 4. Năng lực xử lý (đo thực tế trên máy 4 nhân, phần chạy trên máy, chưa tính thời gian chờ API)

| Hạng mục | Kết quả đo |
|---|---|
| Phân tích bố cục 1.000 trang (7,4 MB) | ~7 giây, ~770 MB RAM |
| Phân tích kiểu Trados 1.000 trang | ~7 giây |
| Toàn bộ quy trình 1.000 trang (API giả lập): dàn trang song song, đọc ảnh trang, báo cáo | ~2,7 phút, ~0,9 GB RAM |
| OCR trang scan | ~0,6 giây/trang (song song 4 nhân), tức ~10 phút cho 1.000 trang scan |

- **Kích thước file:** giao diện nhận file tới **2 GB mỗi file**. Phần xử lý trên máy chạy theo dòng chảy (không nạp toàn bộ ảnh vào RAM), nên sách 1.000–3.000 trang hoặc file vài trăm MB vẫn chạy được trên máy 8–16 GB RAM.
- **Nhiều file cùng lúc:** tải nhiều file vào **hàng đợi**. Mặc định xử lý 1 tài liệu một lúc, và mỗi tài liệu đã chạy đa luồng bên trong. Có thể tăng `queue.parallel_jobs` nếu hạn mức API cho phép.
- **Giới hạn thực sự là hạn mức API** (số yêu cầu và số token mỗi phút), không phải máy. Tăng `translation.workers` theo hạn mức của tài khoản.

## 5. Chọn nhà cung cấp AI (Claude, OpenAI, Gemini…)

- Các model hàng đầu của cả ba hãng đều dịch Anh → Việt tốt. Khác biệt cụ thể với **sách y khoa của bạn** chỉ đo được bằng **thử nghiệm mù trên chính tài liệu của bạn**, không nên dựa vào bảng xếp hạng chung.
- MedTrans hiện xây trên Claude vì các lý do sau:
  - JSON có cấu trúc chặt (máy cưỡng chế được từng câu);
  - suy luận thích ứng;
  - tra cứu web tích hợp;
  - đọc hình ảnh (đọc morat, sửa OCR);
  - prompt caching;
  - ngữ cảnh 1 triệu token.

  Kiến trúc đã tách lớp gọi model (`llm.provider`), nên có thể bổ sung module OpenAI/Gemini nếu cần.
- **Đề xuất:** dùng chức năng **Hiệu chuẩn** (cùng một giám khảo tham chiếu, cùng mẫu) để so sánh khách quan. Nếu muốn so thêm OpenAI/Gemini, cần thêm module kết nối và API key của hãng đó; kết quả sẽ hiển thị trong cùng bảng hiệu chuẩn.

## 6. Lộ trình tối ưu

1. Hiệu chuẩn 10–20 trang mẫu mỗi chuyên ngành với 3 hồ sơ (Tiết kiệm / Cân bằng / Cao cấp).
2. Chọn hồ sơ có **xác suất đạt chuẩn** đủ cao với chi phí thấp nhất. Ví dụ: nếu "Cân bằng" đạt khoảng 95% (KTC95 90–98%) và rẻ hơn khoảng 35%, dùng hồ sơ này cho sách phổ thông và giữ "Cao cấp" cho phần lâm sàng/dược.
3. Bộ nhớ dịch và kho thuật ngữ càng giàu thì sách sau càng rẻ và nhanh hơn (phần lặp lại và khớp 100% không tốn token).
4. Hướng tiếp theo: Batch API (giảm 50% giá, không gấp) cho hồ sơ nâng cấp chạy qua đêm.
