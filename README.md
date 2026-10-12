# MedTrans: dịch tài liệu y khoa PDF Anh → Việt, giữ nguyên bố cục

Công cụ chạy **trên máy của bạn (localhost)** và gọi **Claude API** để dịch sách và báo cáo y khoa tiếng Anh sang **tiếng Việt 100%**. File kết quả là **PDF giữ nguyên bố cục gốc**, phục vụ xuất bản thương mại.

## Đáp ứng yêu cầu

| # | Yêu cầu | Cách MedTrans làm |
|---|---|---|
| 1 | Tự đối chiếu, tự đánh giá chuẩn | Máy kiểm tra số liệu, liều–đơn vị, phủ định, ký hiệu, thuật ngữ, sót chưa dịch. **AI biên tập** sửa bản dịch. **Giám khảo độc lập chấm theo chuẩn MQM**, sửa lỗi nặng rồi chấm lại. Đoạn đạt chuẩn được **tự chứng nhận**. Xem [docs/QUY_TRINH_CHAT_LUONG.md](docs/QUY_TRINH_CHAT_LUONG.md) |
| 2 | Nhập CSDL thuật ngữ trước khi dịch | CSV / Excel / TBX, theo chuyên ngành, có ưu tiên và ghi chú ngữ cảnh. Xem [docs/THUAT_NGU_VA_BO_NHO_DICH.md](docs/THUAT_NGU_VA_BO_NHO_DICH.md) |
| 3 | Nguyên tắc giữ nguyên | [docs/NGUYEN_TAC_GIU_NGUYEN.md](docs/NGUYEN_TAC_GIU_NGUYEN.md). Máy đọc trực tiếp từ `data/preserve_rules.yaml` |
| 4 | Dịch đúng bối cảnh, tra Internet khi không chắc | AI đọc tổng quan tài liệu trước khi dịch. Thuật ngữ chưa chắc được **tra cứu web** (ưu tiên nguồn Bộ Y tế, Dược thư, trường Y), có dẫn nguồn, rồi chốt dùng cho cả tài liệu |
| 5 | Dịch cả hình, biểu đồ | Biểu đồ vẽ bằng vector: dịch như chữ thường. Hình ảnh: OCR (Tesseract hoặc Claude Vision), dịch, xoá chữ cũ, vẽ chữ Việt, thay lại vào PDF |
| 6 | Giữ công thức, ký hiệu | Khối công thức toán được giữ nguyên. Ký hiệu toán nằm trong câu được bảo vệ bằng mã giữ chỗ. Chỉ số trên/dưới, chữ đậm, chữ nghiêng được giữ |
| 7, 10 | Sách bản quyền, chất lượng thương mại | Claude Opus, suy luận sâu, 3 lớp: dịch, biên tập, giám khảo MQM. Báo cáo song ngữ ghi điểm và lỗi từng đoạn. Việc duyệt tay là tuỳ chọn, không bắt buộc |
| 8 | Ưu tiên chất lượng hơn chi phí | Mặc định dùng model mạnh nhất, `effort: high`, luôn biên tập, tối đa 2 vòng sửa. Có thể nâng lên `xhigh` / `max` |
| 9 | Làm giàu thuật ngữ, bộ nhớ dịch | **Tự động, không cần người duyệt.** Chỉ đoạn đạt chuẩn MQM mới vào bộ nhớ dịch. Thuật ngữ được tự duyệt khi đủ bằng chứng từ các đoạn đạt chuẩn và qua kiểm định. Câu khớp 100% **không tốn token**. Có prompt caching |
| 11 | Tiếng Việt 100%, giữ bố cục PDF | Xoá chữ gốc nhưng giữ nền, hình, đường kẻ, rồi đặt chữ Việt đúng vị trí, đúng cỡ chữ, màu, căn lề. Thứ tự đọc đúng với trang 2 cột |
| 12 | Chạy localhost | Giao diện web `http://localhost:8501` và dòng lệnh. Chỉ cần mạng để gọi API |
| ➕ | Cặp ngôn ngữ | Anh → Việt hoàn thiện. Kiến trúc module cho phép thêm ngôn ngữ nguồn khác → Việt, xem [docs/THEM_NGON_NGU.md](docs/THEM_NGON_NGU.md) |
| ➕ | PDF scan | Tự nhận diện trang scan, OCR theo đoạn văn, Claude sửa lỗi OCR, đi qua cùng quy trình chất lượng, giữ định dạng cơ bản |

## Cài đặt (Windows / macOS / Linux)

1. Cài **Python 3.10 trở lên** từ https://www.python.org/downloads/. Trên Windows nhớ tick *Add Python to PATH*.
2. Cài **Tesseract OCR** (để dịch chữ trong hình):
   - Windows: bản cài của UB Mannheim https://github.com/UB-Mannheim/tesseract/wiki, sau đó thêm thư mục cài vào PATH.
   - macOS: `brew install tesseract`
   - Ubuntu: `sudo apt install tesseract-ocr`

   Nếu không cài Tesseract, hãy đặt `layout.image_ocr: claude` trong `config.yaml` (Claude đọc chữ trong hình, tốn thêm token) hoặc `off`.
3. Lấy **API key** tại https://console.anthropic.com. Sao chép `.env.example` thành `.env` rồi điền:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
4. Khởi động:
   - Windows: nháy đúp `run_windows.bat`
   - macOS/Linux: `./run_mac_linux.sh`

   Lần đầu chạy, script tự cài thư viện và nạp bộ thuật ngữ mẫu, sau đó mở trình duyệt tại `http://localhost:8501`.

Cài thủ công:
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m medtrans init
python -m medtrans ui
```

## Sử dụng

### Giao diện web
- **📄 Dịch tài liệu:** tải PDF lên, chọn chuyên ngành và phạm vi trang, *Ước tính chi phí*, rồi *Bắt đầu dịch*. Khi xong, tải về PDF tiếng Việt và báo cáo song ngữ.
- **✍️ Duyệt bản dịch** (tuỳ chọn): xem các đoạn chưa đạt chuẩn, sửa tay nếu muốn, rồi *Dựng lại PDF* (không tốn token).
- **📚 Thuật ngữ:** nhập file, thêm nhanh, xem thuật ngữ đang tích luỹ bằng chứng hoặc đã tự duyệt, xuất CSV.
- **🧠 Bộ nhớ dịch:** nhập và xuất TMX hoặc bảng song ngữ.
- **⚙️ Cấu hình:** quy ước văn phong theo chuyên ngành.

### Dòng lệnh
```bash
python -m medtrans estimate sach.pdf                                  # ước tính chi phí
python -m medtrans translate sach.pdf --domain cardiology --pages 1-20 # dịch thử 20 trang
python -m medtrans translate sach.pdf --domain cardiology             # dịch toàn bộ (tự tiếp tục nếu bị ngắt)
python -m medtrans translate sach.pdf --mock                          # chạy thử quy trình, không gọi API
python -m medtrans glossary import tu_dien.xlsx --domain cardiology
python -m medtrans glossary list --candidates                         # thuật ngữ đang tích luỹ bằng chứng
python -m medtrans tm import ban_dich_cu.tmx --domain cardiology
python -m medtrans tm export bo_nho.tmx
```

Kết quả nằm trong `workspace/output/`:
- `<tên>_VI.pdf`: bản tiếng Việt giữ bố cục.
- `<tên>_VI_report.html`: báo cáo song ngữ gồm điểm MQM và trạng thái từng đoạn (đạt chuẩn / đạt / còn lỗi nặng), lỗi đã phát hiện, thuật ngữ tra cứu kèm nguồn, thống kê tự làm giàu.

## Chi phí tham khảo

Với `claude-opus-5-5`, `effort: high`, biên tập và giám khảo MQM luôn bật, chi phí ước tính khoảng **0,15–0,35 USD cho một trang sách chữ dày** (≈3.500 ký tự). Một cuốn 500 trang vào khoảng **75–175 USD**. Trang scan tốn thêm một lượt Claude đọc ảnh để sửa OCR. Tài liệu càng về sau càng rẻ nhờ bộ nhớ dịch và prompt caching. Dùng `estimate` để xem số cụ thể cho từng file. Số thực tế được ghi trong báo cáo.

## Cấu trúc

```
config.yaml                  cấu hình (model, effort, quy trình, bố cục, bộ nhớ)
data/preserve_rules.yaml     nguyên tắc giữ nguyên / quy ước (máy đọc trực tiếp)
data/glossary_seed.csv       ~130 thuật ngữ y khoa mẫu
data/glossary_template.csv   mẫu file nhập thuật ngữ
medtrans/
  languages.py     hồ sơ ngôn ngữ nguồn (cặp ngôn ngữ → tiếng Việt)
  pdf_extract.py   phân tích bố cục: khối chữ, định dạng, vai trò, thứ tự đọc, công thức, hình
  scan.py          PDF scan: OCR theo đoạn, gộp đoạn, màu nền/màu chữ
  rules.py         che mã giữ chỗ / token phải giữ nguyên
  glossary.py      nhập thuật ngữ, khớp thuật ngữ trong câu
  db.py            SQLite: thuật ngữ, bộ nhớ dịch, cache tra cứu, tiến độ
  llm.py           gọi Claude: streaming, suy luận thích ứng, JSON, cache, tra web, model dự phòng
  prompts.py       prompt dịch / biên tập / tra cứu / trích thuật ngữ
  verify.py        tự đối chiếu bằng quy tắc (+ giám khảo MQM trong translator.py)
  translator.py    điều phối toàn bộ quy trình
  images.py        OCR + vẽ lại chữ trong hình
  pdf_render.py    dựng PDF tiếng Việt giữ bố cục
  report.py        báo cáo song ngữ HTML
  tm.py            nhập/xuất TMX
app.py             giao diện web localhost
tests/             kiểm thử (pytest)
```

## Lưu ý pháp lý và chuyên môn
- Công cụ dùng cho tài liệu **bạn có bản quyền dịch**.
- Hệ thống tự kiểm soát chất lượng bằng giám khảo MQM độc lập. Tuy vậy, với tài liệu dùng trực tiếp cho điều trị, nên đọc lại các đoạn mà báo cáo đánh dấu *còn lỗi nặng*.
- Nội dung tài liệu được gửi tới Anthropic API để xử lý. Không đưa dữ liệu định danh bệnh nhân vào tài liệu cần dịch.
