# Vietlott2 — dữ liệu, thống kê và dự đoán tham khảo

Website tĩnh chạy trên GitHub Pages, kèm script Python tự đồng bộ kết quả. Dự án hỗ trợ:

- **Power 6/55** — 6 số chính và số phụ.
- **Mega 6/45** — 6 số chính.
- **Lotto 5/35** — 5 số chính và 1 số đặc biệt (1–12), có thể trùng số chính; quay lúc 13h và 21h mỗi ngày.

## Thành phần chính

- `index.html` — giao diện dò vé, thống kê, lịch sử, dự đoán tham khảo, backtest và bộ đếm.
- `server.py` — đồng bộ nhiều nguồn, đối chiếu kết quả, cập nhật ODS và tạo `data.js`.
- `655.ods`, `645.ods`, `535.ods` — dữ liệu gốc, kỳ mới nhất ở hàng đầu.
- `data.js` — dữ liệu được sinh cho website; không sửa thủ công.
- `.github/workflows/update.yml` — lịch chạy đồng bộ tự động.
- `tests/` — kiểm tra tính toàn vẹn của dữ liệu ODS.

## Chạy cục bộ

```bash
python3 server.py
```

Mở `http://localhost:8000`.

Lệnh đồng bộ một lần và dựng lại dữ liệu giao diện:

```bash
python3 server.py --sync-once
python3 server.py --build
```

Chạy kiểm tra dữ liệu:

```bash
python3 -m unittest discover -s tests -v
```

## Cách hiểu backtest

Backtest trong tab Dự đoán sử dụng **walk-forward**: tại mỗi kỳ lịch sử được kiểm tra, bộ dự đoán chỉ được nhìn các kỳ đã xảy ra trước kỳ đó. Báo cáo hiển thị số trúng trung bình và tỷ lệ đạt ít nhất 2, 3, 4 số chính; với game có số phụ/số đặc biệt thì báo riêng tỷ lệ dự đoán đúng số đó. Phương pháp `Ngẫu nhiên thuần` là đối chứng mô phỏng; mốc xác suất ngẫu nhiên lý thuyết được tính theo phân phối siêu bội.

Backtest lịch sử không chứng minh khả năng dự đoán kỳ tương lai. Các kỳ quay độc lập; tần suất quá khứ, số nóng/lạnh và mô hình tổng hợp không làm thay đổi xác suất cơ bản của một dãy số hợp lệ.

## Nguồn dữ liệu và xác minh

`server.py` lấy kết quả từ các nguồn được cấu hình theo từng game. Kết quả chỉ được ghi khi các nguồn khớp; nếu chỉ có một nguồn thì áp dụng thời gian chờ dự phòng; nếu nguồn mâu thuẫn thì không tự ghi kỳ đó. Cần kiểm tra log đồng bộ khi workflow báo lỗi.

Đây là dự án cá nhân, không phải website chính thức của Vietlott. Nội dung dự đoán chỉ mang tính tham khảo/giải trí.
