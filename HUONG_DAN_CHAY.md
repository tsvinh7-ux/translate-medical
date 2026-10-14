# Hướng dẫn chạy DMAG MedTrans trên máy tính (bản dành cho người dùng)

## A. Chuẩn bị (làm một lần)

| # | Việc cần làm | Ghi chú |
|---|---|---|
| 1 | Cài **Python 3.10 trở lên**: https://www.python.org/downloads/ | Windows: ở màn hình đầu tiên **tick "Add Python to PATH"** rồi bấm *Install Now* |
| 2 | Cài **Tesseract OCR** (để đọc PDF scan) | Windows: bản UB Mannheim https://github.com/UB-Mannheim/tesseract/wiki, giữ thư mục cài mặc định. macOS: `brew install tesseract`. Ubuntu: `sudo apt install tesseract-ocr`. Không cài thì trang scan sẽ không đọc được chữ; chữ trong hình sẽ do AI đọc (tốn thêm token). |
| 3 | Lấy **Claude API key**: https://console.anthropic.com → *API Keys* → *Create Key* | Nạp tiền vào tài khoản (*Billing*) trước khi dịch |
| 4 | Tải mã nguồn: trên GitHub bấm **Code → Download ZIP**, giải nén vào một thư mục, ví dụ `D:\MedTrans` | Đặt ở ổ còn trống ≥ 5 GB |
| 5 | (Tuỳ chọn) Cài **Ollama**: https://ollama.com rồi chạy `ollama pull qwen3:8b` | Chỉ cần khi dùng phương thức **AI Local + API hỗ trợ** |

## B. Chạy

1. **Windows:** mở thư mục, **nháy đúp `run_windows.bat`**.
   **macOS/Linux:** mở Terminal tại thư mục, chạy `./run_mac_linux.sh`.
2. Lần đầu, script tự cài mọi thứ trong vài phút (cần Internet), rồi mở trình duyệt tại **http://localhost:8501**.
3. Vào **Cấu hình & hệ thống**:
   - dán API key vào ô *Claude API key* rồi bấm **Lưu & kiểm tra**;
   - xem bảng kiểm tra: mọi mục ✓ (hoặc ! ở mục tuỳ chọn) là **sẵn sàng**.
4. Vào **Dự án mới**:
   1. Tải file PDF lên. Hệ thống quét ngay: số trang, số từ, thuật ngữ, phần dùng lại từ bộ nhớ dịch.
   2. Chọn **Phương thức**: *AI Local + API hỗ trợ* hoặc *API hoàn toàn*.
   3. Chọn **Phạm vi**: Dịch thuật ngữ → Dịch thô → Dịch + Biên tập → + Hiệu đính → Trọn gói xuất bản (có đọc morat).
   4. Xem **dự toán chi phí và thời gian**, rồi bấm **Đưa vào hàng đợi**.
5. Mục **Hàng đợi & tiến độ**:
   - theo dõi trực tiếp; có thể tạm dừng, tiếp tục hoặc huỷ;
   - khi xong, tải **PDF tiếng Việt**, **Báo cáo song ngữ** và **Phiếu kiểm định**.
6. Muốn dừng chương trình: đóng cửa sổ đen (Windows) hoặc bấm Ctrl+C (macOS/Linux). Chạy lại: nháy đúp `run_windows.bat`. Lần sau khởi động trong vài giây.

## C. Quy trình khuyến nghị cho một cuốn sách

1. **Thử 10–20 trang** với gói *Trọn gói xuất bản*: dùng ô *Phạm vi trang*, ví dụ `1-20`. Xem chất lượng và phiếu kiểm định.
2. **Termbase:**
   1. Chạy gói *Dịch thuật ngữ* cho cả cuốn.
   2. Tải file Excel termbase, gửi chuyên gia kiểm tra.
   3. Nhập lại ở mục **Termbase dự án** và **Khoá**.
3. **Dịch chính thức** cả cuốn với gói đã chọn. Bật "Dừng sau quét thuật ngữ…" nếu muốn chắc chắn termbase đã khoá trước.
4. **Duyệt chuyên gia** (bắt buộc trước khi phát hành): vào mục **Duyệt & can thiệp** → tab *Duyệt toàn văn & ký phát hành*.
   1. Xuất **gói duyệt song ngữ** (Excel) và gửi chuyên gia.
   2. Chuyên gia đọc và ghi bản sửa / nhận định.
   3. **Nhập lại** gói đã duyệt.
   4. Chuyên gia **ký "Đồng ý phát hành"**.
5. Hệ thống dựng lại PDF và phiếu kiểm định có chữ ký. Phiếu ghi **PHÁT HÀNH ĐƯỢC** thì chuyển cho bộ phận thiết kế.
6. Sau vài cuốn của cùng chuyên ngành: vào mục **Chuyên ngành & văn phong** → *Phân tích & đề xuất quy tắc* để hệ thống học cách sửa của chuyên gia, rồi duyệt các quy tắc.

## D. Khi gặp sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Cửa sổ báo "Chưa cài Python" | Cài Python (mục A.1), nhớ tick *Add Python to PATH*, rồi chạy lại |
| "Cài đặt thất bại" | Kiểm tra Internet, chạy lại `run_windows.bat` |
| Mục Claude API báo ✕ | Kiểm tra lại key, xem tài khoản đã nạp tiền chưa (console.anthropic.com → Billing) |
| Tesseract báo "!" | Cài Tesseract (mục A.2) rồi bấm *Kiểm tra lại toàn bộ* |
| Trình duyệt không tự mở | Mở tay địa chỉ http://localhost:8501 |
| Công việc báo "Lỗi" | Mục Hàng đợi → **↻ Chạy lại**. Các đoạn đã dịch được giữ, không tốn tiền dịch lại |
| Kiểm tra toàn diện | Mở cửa sổ lệnh tại thư mục, chạy `.venv\Scripts\python -m medtrans doctor` |

Dữ liệu (kho thuật ngữ, bộ nhớ dịch, kết quả) nằm trong thư mục `workspace/`. Hãy **sao lưu thư mục này định kỳ**.
