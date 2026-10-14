# Chuyên ngành, học văn phong và duyệt chuyên gia

## 1. Một lõi chung + gói chuyên ngành (không tách hệ thống riêng)

Nha khoa, gây mê hồi sức, tim mạch… **dùng chung một lõi dịch**. Lõi này gồm quy trình dịch – hiệu đính – biên tập – giám khảo – kiểm toán – cổng phát hành. Mỗi chuyên ngành có thêm một **gói chuyên ngành** (`data/domains/<mã>.yaml`) gồm:

| Thành phần | Tác dụng |
|---|---|
| Thuật ngữ nền | Được nạp vào kho thuật ngữ của chuyên ngành, ưu tiên hơn thuật ngữ chung |
| Quy ước văn phong | Đưa vào lời dặn cho AI dịch, hiệu đính và biên tập. Ví dụ nha khoa: ký hiệu răng FDI giữ nguyên; "crown" là *thân răng* khi nói giải phẫu, là *mão răng* khi nói phục hình |
| Điểm giám khảo soát kỹ | Giám khảo lâm sàng soát kỹ những điểm riêng của ngành. Ví dụ gây mê: liều theo cân nặng, phân biệt gây mê và gây tê, xử trí biến cố |
| Kế thừa (`parents`) | Chuyên ngành hẹp tự dùng thêm dữ liệu chung, nhưng dữ liệu riêng được ưu tiên |
| Bộ nhớ dịch, quy tắc đã học, hiệu chuẩn | Lưu tách theo chuyên ngành |

**Vì sao không tách thành hệ thống riêng?**
- Mỗi lần nâng cấp lõi thì mọi chuyên ngành cùng được hưởng.
- Kiến thức chung (dược, giải phẫu, thống kê) không bị chia nhỏ.
- Mỗi chuyên ngành vẫn có dữ liệu và quy tắc riêng.

Có sẵn 5 gói: Y học đại cương, **Nha khoa – Răng Hàm Mặt**, **Gây mê hồi sức**, Tim mạch, Ung thư học.

**Thêm chuyên ngành mới:**
1. Sao chép `data/domains/dentistry.yaml`, đổi `key`, `name_vi`, `aliases` rồi điền nội dung.
2. Chạy `python -m medtrans init` để nạp thuật ngữ.
3. Chuyên ngành chưa có gói vẫn chạy được: hệ thống dùng dữ liệu chung, bộ nhớ dịch và quy tắc vẫn lưu riêng theo tên chuyên ngành.

Thuật ngữ nền trong các gói là thuật ngữ phổ biến. **Chuyên gia nên rà lại** ở mục *Kho thuật ngữ* trước khi dùng cho sách thương mại.

**Có cần model AI riêng cho từng chuyên ngành không?** Với Claude thì không cần: gói chuyên ngành cùng bộ nhớ dịch là đủ. Với AI chạy local, khi đã có đủ dữ liệu người duyệt của một chuyên ngành (vài chục nghìn cặp câu), có thể tinh chỉnh thêm một **LoRA nhỏ cho chuyên ngành đó** (`python -m medtrans finetune --domain dentistry`). Nên làm sau, không phải ngay từ đầu.

## 2. Làm giàu văn phong: dùng ngay từ cuốn đầu, càng dùng càng tốt

Cách này giống *Translation Memory* của SDL Trados, nhưng học được **cả cách chuyên gia sửa**, không chỉ học câu đã dịch:

| Nguồn | Khi nào có | Tác dụng |
|---|---|---|
| **TMX từ Trados** của các sách đã xuất bản | Ngay hôm nay (nhập ở mục *Bộ nhớ dịch*) | Câu khớp được dùng lại miễn phí; câu tương tự làm tham khảo; vài cặp câu người dịch được đưa vào lời dặn làm **văn phong mẫu** |
| **Bản sửa của chuyên gia** (mục Duyệt, duyệt toàn văn, kiểm định mẫu) | Từ cuốn đầu tiên | Mỗi chỗ sửa được ghi lại dạng *trước → sau*. Câu đã sửa vào bộ nhớ dịch với nguồn "người" |
| **Quy tắc học được** | Sau khoảng vài chục chỗ sửa trong một chuyên ngành | Mục *Chuyên ngành & văn phong* → **Phân tích & đề xuất quy tắc**: AI rút ra quy tắc lặp lại (có ít nhất 3 ví dụ) → bạn **duyệt** → áp cho mọi bản dịch sau. Quy tắc thuật ngữ được đưa thẳng vào kho thuật ngữ |

Như vậy **không cần đợi nhiều đợt sách**. Nhập TMX cũ là có văn phong mẫu ngay. Sau mỗi cuốn được chuyên gia sửa, hệ thống học thêm. Số chỗ chuyên gia phải sửa ở các cuốn sau sẽ giảm dần, và có thể đo được bằng thống kê trong phiếu duyệt.

## 3. Quy trình phát hành chuẩn: máy → chuyên gia → thiết kế

```
Dịch (trọn gói) ─► Phiếu kiểm định: "MÁY ĐÃ ĐẠT – CHỜ CHUYÊN GIA ĐỌC DUYỆT & KÝ PHÁT HÀNH"
   ─► Xuất gói duyệt song ngữ (Excel, theo thứ tự sách) ─► chuyên gia đọc, sửa, ghi nhận định
   ─► Nhập lại: áp bản sửa + ghi vào bộ nhớ dịch + dữ liệu học văn phong
   ─► Chuyên gia ký "Đồng ý phát hành" ─► hệ thống dựng lại PDF + phiếu kiểm định có chữ ký
   ─► "PHÁT HÀNH ĐƯỢC" ─► chuyển thiết kế
```

Quy trình nằm ở mục *Duyệt & can thiệp* → *Kiểm định độc lập bởi chuyên gia* → tab **Duyệt toàn văn & ký phát hành**.

Chữ ký chuyên gia là **bắt buộc** theo mặc định (`quality.release_requires_expert: true`). Nếu chuyên gia chọn "Yêu cầu sửa tiếp", bản dịch ở trạng thái *CẦN XỬ LÝ*.
