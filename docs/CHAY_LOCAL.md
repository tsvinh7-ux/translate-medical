# Chạy bằng API hay chạy LOCAL: đánh giá MedCrab và hai phương án triển khai

## 1. Đánh giá MedCrab (github.com/pnnbao97/MedCrab)

**Thành phần**
- **DeepSeek-OCR**: chuyển trang PDF/ảnh thành markdown.
- **MedCrab-1.5B**: Qwen2.5-1.5B được tinh chỉnh để dịch y khoa Anh→Việt.
- Giao diện Gradio, xử lý từng trang. Văn bản được chia đoạn ≤150 từ và dịch bằng một prompt cố định.

**Theo README của tác giả:** BLEU 42–46, COMET 0,68–0,72, METEOR 37–40 trên "đoạn y khoa phức tạp 100–150 từ". Đây là số tự công bố; tập kiểm thử và phiên bản thang đo không được nêu nên không kiểm chứng độc lập được.

**Mức độ kiểm thử trong phiên làm việc này:** môi trường chạy của mình bị chặn truy cập HuggingFace theo chính sách mạng, nên **chưa tải được trọng số để chạy model**. Mình đã làm hai việc thay thế:
- đọc toàn bộ mã nguồn;
- chấm **mẫu đầu ra do tác giả công bố** (`test/input.txt` → `test/output.txt`, 790 từ, 31 câu) bằng bộ kiểm tra của MedTrans, cộng với đọc đối chiếu.

| Hạng mục | Kết quả trên mẫu của tác giả |
|---|---|
| Nửa đầu văn bản | Dịch tốt, đúng thuật ngữ (đái tháo đường týp 2, tế bào β, phối tử–thụ thể, stress lưới nội chất…) |
| **Bỏ sót** | Mất "CRISPR" (máy MedTrans tự phát hiện); mất "Importantly", "human", "tumor necrosis factor-α", "next-generation… approaches… management" |
| **Sai nghĩa** | "longitudinal" → "theo dõi"; "Machine learning" → "học máy tính"; "Finally" → "Tóm lại"; "perturbations" → "rối loạn" (đúng là "can thiệp/làm nhiễu") |
| **Lỗi chữ** | "kiểu genkiểu hình", "oxy hóakhử", "m TOR" |
| **Không nhất quán** | Lúc "ĐTĐ týp 2", lúc "T2DM"; lúc "tế bào β", lúc "β-cell"; "apoptosis" vừa dịch vừa để nguyên |
| Văn phong | Nửa sau rút gọn kiểu điện tín, thiếu từ nối ("tương quan giảm hấp thu glucose") |
| **Giấy phép** | **CC BY-NC 4.0**: cấm dùng thương mại nếu chưa được tác giả cho phép |

**Kết luận**
- MedCrab là **máy dịch nháp local nhanh, nhẹ** (≈3–4 GB VRAM), hữu ích để đọc hiểu.
- Model 1,5B **không đạt chuẩn xuất bản nếu đứng một mình**: còn bỏ ý, sai nghĩa và thiếu nhất quán.
- Model này cũng **không làm được các bước kiểm soát** mà MedTrans cần: theo chỉ dẫn, khoá thuật ngữ, trả JSON, chấm MQM, kiểm toán từng câu.
- MedTrans đã tích hợp MedCrab làm **bước dịch nháp** (hồ sơ `local_fast`, hoặc định tuyến `translate: medcrab`). Các bước kiểm soát chất lượng do model mạnh hơn đảm nhiệm.
- **Muốn dùng thương mại phải xin phép tác giả.**

## 2. Tinh chỉnh (fine-tune) model local như Qwen có đạt chuẩn không?

**Có thể đạt chất lượng tốt nếu đủ ba điều kiện:**
1. **Model đủ lớn:** từ khoảng 14B; khuyến nghị 32B trở lên cho hiệu đính và chấm điểm. Model 1,5–7B dịch được câu, nhưng yếu ở đoạn dài, ở việc tuân thủ termbase, và ở vai trò giám khảo.
2. **Dữ liệu song ngữ chất lượng cao, đúng chuyên ngành:** khoảng 20.000–100.000 cặp đoạn, kèm thuật ngữ bắt buộc. Lệnh `python -m medtrans finetune` xuất sẵn dữ liệu đúng định dạng.
3. **Vẫn giữ quy trình kiểm soát của MedTrans:** termbase khoá, kiểm toán trung thành, chấm MQM. Tinh chỉnh giúp **bản dịch đầu** tốt hơn, nhưng không thay được cổng chất lượng.

**Lưu ý pháp lý về dữ liệu huấn luyện**
- Điều khoản thương mại của Anthropic (mục D.4) **không cho dùng dịch vụ để huấn luyện mô hình AI cạnh tranh** nếu chưa được chấp thuận.
- Vì vậy `finetune` mặc định **chỉ xuất cặp câu do người dịch/duyệt**: bản dịch sách đã xuất bản (nhập TMX) và đoạn sửa tay.
- Chỉ bật `--include-machine` (gồm cả bản dịch do Claude chứng nhận) sau khi pháp chế hoặc Anthropic xác nhận.
- Bản quyền văn bản sách dùng làm dữ liệu huấn luyện cũng cần được hợp đồng cho phép.

## 3. Hai phương án triển khai (cùng một giao diện và quy trình MedTrans)

| | **Phương án A – API (Claude)** | **Phương án B – LOCAL** |
|---|---|---|
| Hồ sơ | `draft`, `economy`, `balanced`, `premium` | `local_fast` (MedCrab nháp), `local_quality` (Qwen 32B+ đầy đủ quy trình) |
| Chất lượng | Cao nhất. Có tra cứu web, đọc morat bằng hình ảnh, sửa OCR bằng hình ảnh | `local_quality`: tốt nếu model ≥32B. Không tra web (nên khoá termbase trước). Đọc morat bằng hình ảnh chỉ khi có model thị giác (Qwen2.5-VL) |
| Chi phí | Trả theo token (dự báo ở mục Phân tích) | Không trả phí API; chi phí là đầu tư GPU và điện năng |
| Bảo mật | Gửi nội dung tới Anthropic (không dùng để huấn luyện) | **Dữ liệu không rời máy**, chạy được không cần Internet |
| Tốc độ | Theo hạn mức API; 32 luồng thì bản cao cấp mất 3–7 giờ/1.000 trang A4 | Theo GPU (xem bảng dưới) |

**Phương án lai `hybrid`** (khuyến nghị khi đã có GPU): model local dịch nháp, Claude hiệu đính, chấm MQM và kiểm toán trung thành. Cách này giữ nguyên cổng chất lượng của API và giảm khoảng 40% chi phí so với `premium` (dự báo trên 1.000 trang A4: ~257–551 USD so với ~464–994 USD).

### Phần cứng gợi ý cho phương án Local (ước tính, cần đo lại trên máy thật)

| Cấu hình | Chạy được | Thông lượng tham khảo | 1.000 trang A4 |
|---|---|---|---|
| GPU 8 GB (RTX 3060/4060) | MedCrab-1.5B (`local_fast`) | vài trăm token/giây (vLLM xử lý theo lô) | bản nháp ~1–3 giờ |
| GPU 24 GB (RTX 3090/4090) | Qwen3-32B lượng tử 4-bit (~20 GB) qua Ollama/llama.cpp | ~30–60 token/giây | `local_quality` mất vài ngày |
| 2×48 GB / 1×80 GB (A6000, A100, H100) với vLLM | Qwen 32B–72B, xử lý theo lô | 500–2.000+ token/giây | `local_quality` mất ~4–15 giờ |
| Mac Apple Silicon 64–128 GB | Qwen 32B (MLX / llama.cpp) | ~15–30 token/giây | Phù hợp bản nháp, chạy thử |

Sau khi chạy, công cụ đo **tốc độ thực tế** và cập nhật dự báo. Khai báo `llm.local.throughput_tokens_per_sec` để dự báo sát ngay từ đầu.

## 4. Cài đặt phương án Local

### 4.1 Model mạnh qua Ollama (đơn giản nhất)
```bash
# cài Ollama: https://ollama.com
ollama pull qwen3:32b            # hoặc model mới hơn cùng dòng
ollama serve                     # API chuẩn OpenAI tại http://localhost:11434/v1
python -m medtrans local-check   # kiểm tra kết nối
python -m medtrans translate sach.pdf --profile local_quality
```

### 4.2 Hiệu năng cao qua vLLM (máy chủ GPU)
```bash
pip install vllm
vllm serve Qwen/Qwen3-32B --port 8000 --max-model-len 32768
# config.yaml: llm.local.base_url = http://<may-chu>:8000/v1 ; llm.local.model = Qwen/Qwen3-32B
```

### 4.3 MedCrab làm máy dịch nháp
```bash
vllm serve pnnbao-ump/MedCrab-1.5B --port 8001          # cần GPU ≥ 4 GB
python -m medtrans translate sach.pdf --profile local_fast        # bản nháp hoàn toàn local
python -m medtrans translate sach.pdf --profile hybrid            # nâng cấp: Claude kiểm định
```
Không có GPU: đặt `llm.medcrab.engine: transformers` (cần `pip install torch transformers`; chạy CPU rất chậm).

### 4.4 Định tuyến tuỳ ý từng công đoạn
```yaml
llm:
  provider: local            # backend chính
  routes:
    translate: medcrab       # dịch nháp bằng MedCrab
    evaluate: anthropic      # chỉ chấm điểm bằng Claude
    fidelity: anthropic
```

## 5. Quy trình tinh chỉnh khuyến nghị
1. Tích luỹ dữ liệu người dịch/duyệt: nhập TMX từ sách đã xuất bản, sửa tay trong tab Duyệt.
2. `python -m medtrans finetune --domain cardiology` sinh ra `train.jsonl` và `val.jsonl`, mỗi mẫu kèm thuật ngữ bắt buộc.
3. Tinh chỉnh LoRA/QLoRA bằng Unsloth, LLaMA-Factory hoặc Axolotl:
   - Qwen3-14B với QLoRA: GPU 24 GB;
   - Qwen3-32B với QLoRA: GPU 48–80 GB.
   - 1–3 epoch, learning rate khoảng 1e-4–2e-4.
4. Phục vụ model đã tinh chỉnh bằng vLLM (`--enable-lora`) hoặc chuyển sang GGUF cho Ollama.
5. **Hiệu chuẩn** (`python -m medtrans calibrate mau.pdf --profiles local_quality,hybrid,premium`) để so **điểm MQM và xác suất đạt chuẩn** với Claude **trên cùng một giám khảo tham chiếu**. Chỉ chuyển sang local khi số đo cho thấy đạt yêu cầu.

## Nguồn
- MedCrab: https://github.com/pnnbao97/MedCrab
- Model: https://huggingface.co/pnnbao-ump/MedCrab-1.5B
- Điều khoản thương mại Anthropic: https://www.anthropic.com/legal/commercial-terms
