# Quy trình đảm bảo chất lượng dịch (chuẩn xuất bản thương mại)

## 1. Quy trình máy cho mỗi lô đoạn văn

```
PDF ─► Phân tích bố cục (cột, tiêu đề, chú thích, bảng, công thức, hình, tài liệu tham khảo)
    ─► AI đọc tổng quan tài liệu: chuyên ngành, độc giả, văn phong, thuật ngữ then chốt
    ─► Với mỗi lô ~6.000 ký tự:
         1. Tra bộ nhớ dịch (khớp 100% → dùng lại)
         2. DỊCH (Claude Opus, suy luận sâu) + ngữ cảnh mục + đoạn trước + thuật ngữ bắt buộc + câu TM tương tự
         3. Thuật ngữ chưa chắc → TRA CỨU WEB → chốt thuật ngữ → dịch lại đoạn liên quan nếu cần
         4. TỰ ĐỐI CHIẾU BẰNG MÁY (bảng bên dưới)
         5. BIÊN TẬP VIÊN AI đối chiếu song ngữ từng đoạn, sửa và chấm điểm 0–100
         6. Còn lỗi nghiêm trọng → DỊCH LẠI có chỉ dẫn lỗi (tối đa max_refine_rounds vòng)
         7. Lưu: điểm, lỗi còn lại, trạng thái (done / needs_review)
    ─► Dịch chữ trong hình (OCR → dịch → vẽ lại)
    ─► Dựng PDF tiếng Việt giữ bố cục
    ─► Báo cáo song ngữ HTML + làm giàu thuật ngữ/TM
```

## 2. Tự đối chiếu bằng máy (không tốn token)

| Kiểm tra | Mức | Phát hiện |
|---|---|---|
| Số liệu | lỗi | Thiếu hoặc sai số (đã quy đổi 0.5 ↔ 0,5; 1,000 ↔ 1.000 trước khi so) |
| Cặp số – đơn vị | lỗi | `40 mg` thành `4 mg` hay `40 g`; liều theo cân nặng `mg/kg` |
| Phủ định / chống chỉ định | lỗi | Bản gốc có *not / no / never / without / contraindicated / avoid* nhưng bản dịch không có *không / chống chỉ định / tránh…* |
| Sót tiếng Anh | lỗi | Bản dịch còn câu chữ tiếng Anh |
| Mã giữ chỗ | lỗi | Mất hoặc lặp URL, DOI, công thức |
| Ký hiệu phải giữ nguyên | cảnh báo | Mất viết tắt, ký hiệu gen, mã ICD, trích dẫn [12] |
| Thuật ngữ bắt buộc | cảnh báo | Không dùng thuật ngữ trong từ điển hoặc thuật ngữ đã chốt |
| Độ dài bất thường | cảnh báo | Bản dịch ngắn hoặc dài bất thường so với bản gốc, nghi thiếu hoặc thừa ý |
| Thẻ định dạng | cảnh báo | Mất cân bằng chữ đậm, nghiêng, chỉ số trên/dưới |

Lỗi **mức "lỗi"** khiến đoạn bị gửi dịch lại. Nếu sau các vòng sửa vẫn còn lỗi, đoạn được đánh dấu **needs_review** (cần người duyệt), giới hạn điểm tối đa 60, và hiện ở đầu báo cáo.

## 3. Cấu hình cho chất lượng cao nhất (`config.yaml`)

```yaml
llm:
  model: claude-opus-5-5     # model mạnh, mặc định
  effort: high               # nâng lên xhigh hoặc max cho sách khó (tốn hơn)
  review_effort: high
translation:
  review_mode: always        # luôn có vòng biên tập thứ 2
  max_refine_rounds: 2
  web_research: true
```

Khi tài liệu cực khó hoặc quan trọng, đặt `effort: max`. Muốn rẻ hơn mà vẫn tốt, đặt `effort: medium` và `review_mode: on_issues`.

## 4. Quy trình biên tập khuyến nghị cho sách thương mại

Máy giúp giảm 80–90% công sức, nhưng **sách y khoa xuất bản bắt buộc có người chuyên môn hiệu đính**. Quy trình đề xuất:

1. **Chuẩn bị.** Nhập từ điển chuyên ngành và TM từ các sách đã xuất bản (xem `THUAT_NGU_VA_BO_NHO_DICH.md`). Viết quy ước văn phong cho chuyên ngành.
2. **Dịch thử 10–20 trang** (`--pages 1-20`), đại diện cho các kiểu trang: chữ, bảng, hình, công thức.
3. **Bác sĩ hiệu đính đọc bản thử.** Bổ sung thuật ngữ và quy ước văn phong, duyệt thuật ngữ đề xuất. Lặp lại bước 2 nếu cần.
4. **Dịch toàn bộ.** Có thể chạy theo chương. Nếu bị ngắt giữa chừng, chạy lại sẽ **tiếp tục từ chỗ dừng**, không mất tiền dịch lại.
5. **Hiệu đính chuyên môn.** Dùng báo cáo song ngữ HTML và tab **✍️ Duyệt bản dịch**:
   - Đọc trước toàn bộ đoạn *needs_review* và đoạn điểm < 85.
   - Sửa tay trực tiếp. Bản sửa được lưu vào TM ở mức "đã duyệt" và dùng lại cho lần sau.
   - Bấm **Dựng lại PDF**. Thao tác này không tốn token.
6. **Đọc dàn trang** trên PDF: kiểm tra chữ tràn, chữ trong hình, bảng biểu.
7. **Duyệt cuối** với biên tập viên nhà xuất bản (chính tả, văn phong).

## 5. Giới hạn kỹ thuật nên biết

- **PDF scan (ảnh chụp trang):** hệ thống dịch được chữ bằng OCR, nhưng chất lượng dàn trang kém hơn PDF gốc có lớp chữ. Nên xin nhà xuất bản file PDF gốc hoặc file InDesign/XML.
- **Bố cục phức tạp** (3 cột, chữ chạy quanh hình, bảng nhiều ô gộp): đa số được xử lý theo từng khối chữ, nhưng nên kiểm tra kỹ khi đọc dàn trang.
- **Chữ trong hình:** chữ Việt được vẽ đè lên vùng nền của chữ gốc. Hình nền phức tạp (ảnh mô bệnh học có chú thích) có thể để lại vệt. Những hình này nên nhờ hoạ sĩ chỉnh lại.
- **Công thức toán:** được giữ nguyên. Từ ngữ nằm trong công thức không có font toán (ví dụ "weight", "height") sẽ được dịch.
- **Chữ nghiêng** cần font có biến thể nghiêng. Trên Windows, Times New Roman và Arial có đủ các biến thể.
- **Tiếng Việt thường dài hơn tiếng Anh 10–25%.** Hệ thống xử lý theo thứ tự: dùng khoảng trắng phía dưới khối trước, sau đó mới thu nhỏ chữ, và thu nhỏ đồng đều các khối cùng loại trên một trang. Những chỗ phải thu nhỏ nhiều được thống kê ở mục `render.overflow`.
