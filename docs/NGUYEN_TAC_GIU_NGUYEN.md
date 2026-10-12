# Nguyên tắc giữ nguyên và chuyển đổi khi dịch y khoa Anh → Việt

Bộ nguyên tắc này được chương trình **đọc trực tiếp** từ `data/preserve_rules.yaml`. File này được dùng vào 3 việc:

1. **Che trước khi gửi AI.** Các mục nhóm A được thay bằng mã `⟦n⟧`, nên AI không nhìn thấy nội dung và không thể làm sai.
2. **Đưa vào prompt.** Toàn bộ nguyên tắc được đưa vào hướng dẫn cho AI dịch và AI biên tập.
3. **Kiểm tra tự động sau khi dịch.** Bản dịch thiếu, sai hoặc đổi các mục nhóm B, C sẽ bị báo lỗi và gửi đi dịch lại.

Bạn muốn sửa hay thêm quy tắc thì sửa `data/preserve_rules.yaml`, không cần sửa code.

---

## Nhóm A: Che bằng mã giữ chỗ, khôi phục nguyên văn sau khi dịch

| Loại | Ví dụ | Xử lý |
|---|---|---|
| URL | `https://www.who.int/...` | Giữ nguyên tuyệt đối |
| Email | `editor@journal.org` | Giữ nguyên |
| DOI | `doi:10.1056/NEJMoa1409077` | Giữ nguyên |
| ISBN, PMID, PMCID, mã thử nghiệm NCT | `NCT01035255` | Giữ nguyên |
| Công thức toán dùng font toán (TeX, Cambria Math…) | `∑ xᵢ / n` | Giữ nguyên ký hiệu, giữ cả chỉ số trên/dưới |
| Khối công thức độc lập (≥50% ký tự là font toán) | phương trình đánh số | **Không đụng tới**, giữ nguyên vị trí trên trang |

## Nhóm B: AI phải giữ nguyên văn (máy kiểm tra lại)

| Loại | Ví dụ | Ghi chú |
|---|---|---|
| Chữ viết tắt in hoa | ECG, MRI, COPD, HIV, LVEF | Lần đầu xuất hiện có thể ghi kèm nghĩa: *điện tâm đồ (ECG)* (theo `abbreviation_policy`) |
| Ký hiệu gen, protein, xét nghiệm, dấu ấn | BRCA1, HbA1c, CD4+, HER2, IL-6, TNF-α | Không viết lại, không thêm dấu cách |
| Phân loại TNM | T2N0M0, pT1a | |
| Mã ICD-10 / ATC | I21.4, C10AA05 | |
| Trích dẫn tài liệu tham khảo | [12], [3–5] | |
| Công thức hoá học | NaHCO3, CO2, Ca2+ | |
| Tên khoa học sinh vật (chữ nghiêng) | *Staphylococcus aureus* | Giữ tiếng Latin và chữ nghiêng |
| Tên riêng | tác giả, tạp chí, tên thử nghiệm (SPRINT, PARADIGM-HF) | |
| Biệt dược / tên thương mại | Entresto®, Lipitor® | |
| Danh mục tài liệu tham khảo | toàn bộ mục *References* | Chỉ dịch tiêu đề mục thành "Tài liệu tham khảo" |

Một số từ in hoa **không** bị coi là viết tắt, ví dụ tiêu đề in hoa như INTRODUCTION hay TABLE, hoặc số La Mã. Danh sách ngoại lệ nằm trong `must_keep_exceptions`.

## Nhóm C: Đơn vị đo giữ ký hiệu quốc tế, không đổi đơn vị, không quy đổi

`mg, g, kg, µg, mcg, mL, L, dL, mmol/L, mEq, IU, U/L, mmHg, cmH2O, kPa, %, °C, Gy, mSv, kcal, mg/kg, mg/dL, mL/min, µg/kg/min…`

Máy kiểm tra từng **cặp số và đơn vị**. Ví dụ bản gốc có `40 mg` thì bản dịch bắt buộc có `40 mg`. Nếu thành `4 mg` hoặc `40 g` thì máy báo lỗi và gửi dịch lại.

Đơn vị thời gian thì **được dịch**: h → giờ, min → phút, s → giây, d → ngày, wk → tuần.

## Nhóm D: Quy ước chuyển đổi

| Nội dung | Bản gốc | Bản dịch |
|---|---|---|
| Số thập phân (`number_format: vi`) | 0.5 mg; 1,000 | 0,5 mg; 1.000 |
| Số hiệu chương, mục, hình, bảng | Figure 3.1, Section 2.4.1 | Hình 3.1, Mục 2.4.1 (giữ dấu chấm) |
| Hình / Bảng / Chương / Khung / Phụ lục | Figure / Table / Chapter / Box / Appendix | Hình / Bảng / Chương / Khung / Phụ lục |
| Trích dẫn tác giả | Smith et al. | Smith và cs. |
| Thống kê | p < 0.05; 95% CI; mean ± SD | p < 0,05; KTC 95%; trung bình ± ĐLC |
| Tần suất dùng thuốc | q.d. / b.i.d. / t.i.d. / q.i.d. | 1 / 2 / 3 / 4 lần/ngày |
| Đường dùng | PO / IV / IM / SC | đường uống / tiêm tĩnh mạch / tiêm bắp / tiêm dưới da |
| Tên hoạt chất (`drug_name_style: duoc_thu`) | amoxicillin, epinephrine | amoxicilin, adrenalin (theo Dược thư Quốc gia) |
| Tổ chức có tên Việt chính thức | World Health Organization | Tổ chức Y tế Thế giới |
| Thang điểm, phân loại | Glasgow, NYHA class II | giữ tên riêng, dịch phần mô tả: NYHA độ II |

## Những gì máy KHÔNG BAO GIỜ được làm

- Thay đổi, làm tròn hoặc quy đổi bất kỳ giá trị số nào.
- Bỏ hay đảo nghĩa phủ định (*not recommended*, *contraindicated*, *avoid*). Máy có bước kiểm tra riêng cho lỗi này.
- Đổi mức độ khuyến cáo. *should*, *may*, *must*, *is recommended* phải ra đúng sắc thái: *nên*, *có thể*, *phải*, *được khuyến cáo*.
- Tự thêm giải thích không có trong bản gốc.
