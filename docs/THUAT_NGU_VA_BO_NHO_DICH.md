# Thuật ngữ và bộ nhớ dịch (TM): nhập dữ liệu, làm giàu, tiết kiệm token

## 1. Nhập cơ sở dữ liệu thuật ngữ trước khi dịch

### Định dạng file

Bạn có thể nhập **CSV**, **Excel (.xlsx)** hoặc **TBX** (chuẩn trao đổi thuật ngữ của Trados/memoQ). File mẫu: `data/glossary_template.csv`.

| Cột | Bắt buộc | Ý nghĩa |
|---|---|---|
| `en` | ✔ | Thuật ngữ tiếng Anh. Số nhiều được nhận tự động: *syndromes* khớp với *syndrome* |
| `vi` | ✔ | Cách dịch chuẩn |
| `domain` | | Chuyên ngành: cardiology, oncology… Mặc định `general_medicine` (dùng cho mọi chuyên ngành) |
| `category` | | disease, drug, anatomy, procedure, lab, abbreviation… |
| `note` | | Ghi chú ngữ cảnh. AI đọc ghi chú này, ví dụ: *"sensitivity: nghĩa thống kê là độ nhạy, dị ứng là quá mẫn"* |
| `keep_original` | | `1` = giữ nguyên tiếng Anh (viết tắt, tên gen, tên thử nghiệm) |
| `gloss_first` | | `1` = lần đầu ghi "Tiếng Việt (English)" |
| `case_sensitive` | | `1` = phân biệt hoa/thường. Dùng cho viết tắt dễ trùng từ thường, ví dụ *AIDS* và *aids* |
| `priority` | | 0–100. Khi hai thuật ngữ chồng nhau thì mục ưu tiên cao hơn thắng; cụm dài luôn được khớp trước |
| `source_url` | | Nguồn dẫn chứng |

Tên cột tiếng Việt cũng được chấp nhận: `tieng_anh`, `tieng_viet`, `chuyen_nganh`, `ghi_chu`, `giu_nguyen`…

### Cách nhập

- **Giao diện:** tab **📚 Thuật ngữ**, chọn *Nhập thuật ngữ từ file*.
- **Dòng lệnh:**
  ```
  python -m medtrans glossary import tu_dien_tim_mach.xlsx --domain cardiology
  python -m medtrans glossary add --en "heart failure with preserved ejection fraction" --vi "suy tim phân suất tống máu bảo tồn" --domain cardiology
  ```

### Nguồn nên dùng để xây bộ thuật ngữ ban đầu (xếp theo độ ưu tiên)

1. Thuật ngữ trong **các bản sách đã dịch và xuất bản trước đây** của bạn. Đây là nguồn khớp văn phong nhà xuất bản nhất.
2. **Hướng dẫn chẩn đoán và điều trị của Bộ Y tế** (kcb.vn, moh.gov.vn), **Dược thư Quốc gia Việt Nam** (tên hoạt chất).
3. Giáo trình các trường Đại học Y (Hà Nội, TP.HCM, Huế…), khuyến cáo của các hội chuyên ngành (Hội Tim mạch VN…).
4. Danh mục ICD-10 tiếng Việt của Bộ Y tế cho tên bệnh.

> Mẹo: nhập trước khoảng 300–1.000 thuật ngữ then chốt của chuyên ngành. Bản dịch sẽ nhất quán ngay từ trang đầu.

## 2. Khi gặp thuật ngữ khó, hệ thống tự tra cứu Internet

Khi AI dịch không chắc một thuật ngữ, hệ thống chạy các bước sau:

1. AI đánh dấu thuật ngữ đó vào `uncertain_terms`, kèm cách dịch tạm và lý do.
2. Một lượt gọi Claude riêng, có **công cụ tìm kiếm web**, đi tra cứu. Lượt này ưu tiên các nguồn uy tín của Việt Nam (Bộ Y tế, Dược thư, các trường Y, bệnh viện lớn) và đối chiếu nghĩa tiếng Anh trên MeSH, MedlinePlus, NCBI.
3. Kết quả gồm **cách dịch, độ tin cậy, đường dẫn nguồn và lý giải**. Thuật ngữ này được *chốt cho toàn tài liệu* để dùng nhất quán.
4. Nếu kết quả khác cách dịch tạm, các đoạn liên quan được tự động **dịch lại**.
5. Thuật ngữ được lưu vào CSDL ở trạng thái **"đề xuất"**, và vào bộ đệm tra cứu nên lần sau không phải tra lại.

Danh sách nguồn ưu tiên nằm ở `translation.web_preferred_domains` trong `config.yaml`.

## 3. Làm giàu dữ liệu sau mỗi tài liệu: vòng lặp học

```
 Dịch tài liệu 1 ──► thuật ngữ AI tra cứu + thuật ngữ AI tự trích ──► (bạn duyệt) ──► Từ điển chuẩn
       │                                                                                   │
       └──► các đoạn điểm ≥ 85 / đã duyệt tay ──► Bộ nhớ dịch (TM) ◄────────────────────────┘
                                                        │
 Dịch tài liệu 2 cùng chuyên ngành ◄────────────────────┘  (khớp 100% = 0 token; câu tương tự = tham khảo)
```

Sau mỗi tài liệu, hệ thống có các nguồn sau để làm giàu dữ liệu:

- **Tổng quan tài liệu.** Trước khi dịch, AI đọc phần đầu sách và đề xuất 20–60 thuật ngữ then chốt.
- **Tra cứu web.** Thuật ngữ khó được tra kèm nguồn dẫn chứng.
- **Tự học.** Sau khi dịch xong, AI trích các cặp thuật ngữ từ những đoạn đạt điểm cao (`memory.auto_learn_terms`).
- **Bạn duyệt** trong tab **📚 Thuật ngữ** → *Thuật ngữ đề xuất chờ duyệt*: tick *duyệt* hoặc *loại*. Chỉ thuật ngữ **đã duyệt** mới trở thành chuẩn bắt buộc cho các tài liệu sau. Thuật ngữ đề xuất không bao giờ ghi đè thuật ngữ đã duyệt.
- **Quy ước chuyên ngành.** Tab **⚙️ Cấu hình** cho phép ghi chú văn phong riêng từng chuyên ngành, ví dụ: *"Tim mạch: dùng 'thuốc chẹn beta', không dùng 'thuốc ức chế beta'"*.

## 4. Bộ nhớ dịch (Translation Memory) giúp tiết kiệm token

Mỗi đoạn dịch xong được lưu kèm **điểm chất lượng** do AI biên tập chấm. Đoạn bạn sửa tay được lưu với **điểm 100** và đánh dấu đã duyệt.

| Tình huống | Hệ thống làm gì | Token |
|---|---|---|
| Câu khớp **100%** với TM, điểm ≥ `tm_min_quality` (85) hoặc đã duyệt tay | Dùng lại ngay | **0** |
| Câu tương tự **≥ 75%** (`tm_fuzzy_threshold`) | Đưa bản dịch cũ vào prompt làm tham khảo văn phong và thuật ngữ | Ít hơn, nhất quán hơn |
| Câu mới | Dịch đầy đủ | Bình thường |

Những phần hay lặp lại sẽ được dùng lại, ví dụ đầu/chân trang, chú thích chuẩn, câu cảnh báo thuốc, tiêu đề mục, bảng biểu mẫu, và nội dung trùng giữa các tập hay các lần tái bản.

Ngoài TM, hệ thống còn tiết kiệm bằng **prompt caching**. Phần hướng dẫn cố định và phần tổng quan tài liệu được cache 1 giờ. Mỗi lượt gọi sau chỉ trả khoảng 5% giá cho phần này.

### Nhập và xuất TM

```
python -m medtrans tm import ban_dich_cu.tmx --domain cardiology    # từ Trados/memoQ/OmegaT
python -m medtrans tm import song_ngu.xlsx --domain cardiology      # bảng 2 cột en, vi
python -m medtrans tm export bo_nho_tim_mach.tmx --domain cardiology
python -m medtrans tm stats
```

> Nếu bạn đã có bản dịch cũ (bản Word tiếng Việt và bản PDF tiếng Anh tương ứng), hãy căn câu thành bảng 2 cột rồi nhập vào TM. Đây là cách nhanh nhất để hệ thống "học" văn phong nhà xuất bản.

## 5. Tổ chức theo chuyên ngành

Thuật ngữ và TM được lưu theo `domain`. Khi dịch một tài liệu tim mạch (`--domain cardiology`), hệ thống dùng **thuật ngữ cardiology cộng với general_medicine**. Cách tổ chức này tránh xung đột khi một từ có nghĩa khác nhau giữa các chuyên ngành.
