# Phần cứng cho MedTrans: nâng cấp máy hiện tại hay mua máy mới?

> Giá tham khảo **tháng 10/2026, thị trường Mỹ (USD)**. Giá đang biến động mạnh vì **khan hiếm bộ nhớ (DRAM/GDDR)**: card cao cấp tăng gấp 2–3 lần so với lúc ra mắt. Hãy hỏi giá thực tế tại Việt Nam trước khi mua.

## 1. "B" là gì? B càng cao càng tốt?

**B (billion)** là số **tỉ tham số** của model; ví dụ Qwen 27B có 27 tỉ tham số.

- **Nhìn chung, B cao hơn thì dịch tốt hơn.** Model lớn hiểu ngữ cảnh tốt hơn, tuân thủ termbase tốt hơn, ít bỏ ý và chấm điểm (vai giám khảo) đáng tin hơn.
- **Model phải nằm trọn trong VRAM của GPU.** Nếu tràn sang RAM thường, tốc độ giảm 5–20 lần. Vì vậy, **VRAM quyết định model lớn nhất máy chạy được**.
  - Quy tắc nhẩm với lượng tử 4-bit (Q4): **VRAM ≈ 0,6 GB × B**, cộng thêm 2–4 GB cho ngữ cảnh. Ví dụ model 27B cần khoảng 17–20 GB.
  - Q8 chính xác hơn Q4 một chút nhưng tốn gấp đôi VRAM.
- **Model MoE** (ví dụ "35B-A3B", "122B-A10B") chỉ kích hoạt một phần tham số mỗi lần sinh chữ, nên chạy rất nhanh. Tuy vậy vẫn phải chứa **toàn bộ** tham số trong bộ nhớ.
- **Dịch y khoa xuất bản:**
  - khoảng **27–32B dense** là ngưỡng "local tốt";
  - **dưới 14B** chỉ nên làm bản nháp;
  - **trên 70B** cải thiện thêm không nhiều so với chi phí phần cứng, vì đã có Claude xử lý đoạn khó.
- **Hai model khác họ tốt hơn một model to.** Ví dụ Qwen dịch, Gemma chấm: giám khảo không mắc cùng kiểu lỗi với người dịch. Đây là hồ sơ **`local_pro`**.

## 2. Phân vai trong hệ thống (một máy, file lấy từ máy, kết nối API khi cần)

| Vai | Chạy ở đâu | Model |
|---|---|---|
| Dùng lại TM, TMX Trados, termbase khoá, câu lặp | Máy bạn | không cần model |
| Dịch, hiệu đính, biên tập | Máy bạn (GPU) | Qwen ~27B (`llm.local`) |
| Giám khảo MQM và kiểm toán trung thành | Máy bạn (GPU) | Gemma ~31B, khác họ (`llm.local_judge`) |
| Tra web thuật ngữ chưa chắc, sửa đoạn khó, kiểm tra mẫu 10%, đọc morat bằng hình ảnh | API | Claude |
| OCR, dàn trang PDF, hàng đợi, phân tích | Máy bạn (CPU) | Tesseract, PyMuPDF |

Mọi model đều được khai báo trong `config.yaml`, nên đổi model chỉ cần sửa một dòng, không phụ thuộc một nhà cung cấp nào.

## 3. Các phương án

### Phương án 1 – Nâng cấp máy đang có (rẻ nhất, làm ngay)
- **Thay card bằng RTX 3090 24 GB đã qua sử dụng.** Giá cũ khoảng **1.000–1.450 USD** và đang tăng. Đây vẫn là card có giá trên mỗi GB VRAM tốt nhất cho AI.
- **Kiểm tra trước khi mua:**
  - nguồn **≥ 850 W chuẩn 80+ Gold**, có 2–3 đầu 8-pin;
  - vỏ máy chứa được card dài khoảng **31–33 cm**;
  - RAM nâng lên **64 GB**;
  - thêm **SSD NVMe 2 TB** cho model và kho dữ liệu.
- Core i5 đời 10 trở lên vẫn ổn: GPU gánh phần AI, còn i5 chỉ chạy OCR và dàn trang.
- **Chạy được:** `local_pro` với Qwen 27B Q4. Giám khảo Gemma phải **nạp luân phiên** với model dịch, nên chậm hơn nhưng chạy được.

### Phương án 2 – Máy trạm mới, khuyến nghị cho khối lượng sách 1.000 trang
| Linh kiện | Đề xuất | Ghi chú |
|---|---|---|
| GPU | **2× RTX 3090 24 GB (tổng 48 GB)**, hoặc **1× RTX 5090 32 GB** nếu giá về gần mức ra mắt | 48 GB cho phép **nạp sẵn cả model dịch lẫn giám khảo**. RTX 5090 đang khoảng 4.500–7.400 USD, đắt hơn nhiều so với 2× 3090 |
| CPU | AMD Ryzen 9 9900X / 9950X hoặc Intel Core Ultra 9 | Nhiều nhân giúp OCR và dàn trang song song |
| Mainboard | X870E / Z890 có **2 khe PCIe x16 cách nhau 3–4 slot** (chạy x8/x8) | Cần khi dùng 2 card |
| RAM | **128 GB DDR5** (tối thiểu 64 GB) | RAM nên ≥ 2× tổng VRAM để nạp và đổi model nhanh |
| Ổ cứng | 2 TB NVMe Gen4 cho hệ thống và model, thêm 2–4 TB cho dữ liệu và sao lưu | |
| Nguồn | **1.300–1.600 W, 80+ Platinum, ATX 3.1** | 2× 3090 có thể ăn 700 W+ khi chạy tải |
| Vỏ và làm mát | Vỏ full-tower thông gió tốt, tản nhiệt CPU AIO 360 mm | Chạy tải nhiều giờ liên tục |
| Lưu điện | UPS 1.500–2.000 VA | Tránh mất việc khi chạy dài |
| Hệ điều hành | Windows 11 + Ollama (dễ), hoặc Ubuntu 24.04 / WSL2 + **vLLM** (nhanh hơn 2–4 lần nhờ xử lý theo lô và chia model trên 2 GPU) | |

### Phương án 3 – Cao cấp (không phụ thuộc API ở phần lớn công việc)
- **NVIDIA RTX PRO 6000 Blackwell 96 GB.** Giá hiện khoảng **13.000–16.000 USD**, gấp khoảng 2 lần lúc ra mắt.
- Đi kèm RAM 192–256 GB và nguồn 1.300 W.
- Chạy được model MoE khoảng 120B, hoặc nạp sẵn nhiều model lớn ở Q8.
- **Chỉ đáng đầu tư khi** số đo hiệu chuẩn cho thấy phương án 2 vẫn phải đẩy lên Claude trên 15–20% số đoạn.

### Phương án khác – Máy nhớ hợp nhất 128 GB
- **Các máy:** NVIDIA DGX Spark (khoảng 4.700 USD), máy AMD Ryzen AI Max+ 395 (khoảng 2.600–4.500 USD).
- **Ưu điểm:** chứa được model rất lớn.
- **Nhược điểm:** băng thông bộ nhớ thấp, nên sinh chữ chậm hơn RTX 3090 khoảng 3 lần với model vừa VRAM. Ví dụ gpt-oss-120b chỉ khoảng 35 token/giây.
- **Phù hợp:** làm máy chủ giám khảo phụ, không phải máy chính.

## 4. Tốc độ dự kiến cho 1.000 trang A4 (ước tính, cần đo lại)

Toàn quy trình gồm dịch, hiệu đính, biên tập, 2 giám khảo và kiểm toán. Cả cuốn cần sinh khoảng **3–5 triệu token**.

| Cấu hình | Thông lượng tham khảo (Qwen 27B Q4) | Thời gian phần local |
|---|---|---|
| RTX 3050 8 GB (qwen3:8b, `local_cascade`) | 30–50 token/s, nhưng model nhỏ nên phải đẩy lên API nhiều | 1–2 ngày, ~25–40% đoạn đi Claude |
| 1× RTX 3090 + Ollama | ~30–35 token/s một luồng | ~1–1,5 ngày |
| 1× RTX 3090 + vLLM, theo lô | ~100–150 token/s tổng | ~6–12 giờ |
| 2× RTX 3090 + vLLM | ~200–300 token/s tổng | ~3–6 giờ |
| RTX PRO 6000 96 GB + vLLM | ~400+ token/s tổng | ~2–3 giờ |

Phần đẩy lên Claude (tra web, đoạn khó, kiểm tra mẫu, đọc morat) chạy **song song**. Sau khi có máy, chạy `python -m medtrans hw --save`: công cụ đo tốc độ thật và cập nhật dự báo trong màn Ước tính.

## 5. Tinh chỉnh (fine-tune) model riêng
- QLoRA cho model ~27B cần khoảng **24–32 GB VRAM**: một RTX 3090/5090 làm được với chuỗi ngắn, còn 48 GB thì thoải mái.
- Lần đầu nên **thuê GPU đám mây theo giờ** (A100/H100, khoảng vài chục USD mỗi lần), rồi mang model về chạy trên máy.
- Dữ liệu lấy bằng `python -m medtrans finetune`.
  - Mặc định: dữ liệu do người dịch/duyệt và TMX Trados.
  - Thêm `--include-machine` để gồm cả bản dịch máy đã chứng nhận.

## 6. Lộ trình đề xuất
1. **Ngay bây giờ:**
   - chạy `local_cascade` trên RTX 3050;
   - nhập TMX/TBX từ Trados;
   - chạy `calibrate` trên 10–20 trang mẫu để có số đo chất lượng đầu tiên.
2. **Bước 1:** mua **một RTX 3090 cũ** (thêm nguồn và RAM nếu cần), chuyển sang `local_pro`, đo lại tỉ lệ đẩy lên Claude.
3. **Bước 2:** khi khối lượng đều đặn, build **máy trạm phương án 2**, chuyển card 3090 sang và thêm card thứ hai. Chạy vLLM.
4. **Bước 3:** tinh chỉnh Qwen trên dữ liệu đã chứng nhận và kiểm tra bằng `calibrate`. Chỉ nâng lên GPU 96 GB nếu số đo chứng minh cần thiết.

## Nguồn tham khảo giá và model
- Giá RTX PRO 6000 Blackwell: https://www.tomshardware.com/pc-components/gpus/nvidia-doubles-rtx-pro-6000-blackwells-msrp-to-a-staggering-usd16-000-96gb-card-started-pre-orders-below-usd8-000-last-year
- Giá RTX 5090: https://videocardprices.com/card/nvidia-rtx-5090/
- RTX 3090 cũ cho AI: https://www.xda-developers.com/used-rtx-3090-still-best-for-local-ai-in-value/ ; https://gpudojo.com/rtx-3090
- DGX Spark và Ryzen AI Max+ 395: https://www.hardware-corner.net/nvidias-dgx-spark-digits-specs-20250319/ ; https://www.compute-market.com/blog/dgx-spark-vs-strix-halo-local-ai-2026
- Dòng model Qwen 3.6/3.8: https://en.wikipedia.org/wiki/Qwen ; Gemma: https://en.wikipedia.org/wiki/Gemma_(language_model)
