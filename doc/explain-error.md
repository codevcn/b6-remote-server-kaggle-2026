Viewed transcribe-audio-file-flow%20%282%29.ipynb:1-769

Đã tìm ra nguyên nhân. Đây là phân tích đầy đủ:

---

## 🔍 Nguyên nhân lỗi

### Thông báo lỗi (Cell 3, dòng 174):

```
[18:39:05] LỖI HỆ THỐNG: Không thể kết nối. Chi tiết:
HTTPSConnectionPool(host='b6-remote-server-kaggle-2026.onrender.com', port=443):
Max retries exceeded with url: /webhook/notebook
(Caused by NameResolutionError("Failed to resolve 'b6-remote-server-kaggle-2026.onrender.com'
[Errno -3] Temporary failure in name resolution"))
```

### ❌ Nguyên nhân: **Kaggle notebook bị tắt Internet**

Lỗi `[Errno -3] Temporary failure in name resolution` là lỗi **DNS không phân giải được tên miền** — tức là máy không có kết nối Internet để tra cứu địa chỉ IP của server.

Nhìn vào metadata của notebook:

```json
"isInternetEnabled": true
```

Trong file metadata có `isInternetEnabled: true`, **nhưng đây là metadata của lần chạy cũ (ngày 23/05)**. Lần chạy hiện tại (ngày 24/05) có thể notebook đã được chạy lại mà **không bật Internet**.

### ⏱️ Bằng chứng thời gian

|                                | Thời điểm                                                 |
| ------------------------------ | --------------------------------------------------------- |
| Papermill bắt đầu              | `2026-05-24T18:38:30`                                     |
| Notebook gửi webhook `started` | `18:38:33`                                                |
| Nhận lỗi DNS                   | `18:39:05` (sau 32 giây — đúng thời gian chờ timeout DNS) |

Notebook đợi đúng **32 giây** trước khi báo lỗi, tức là `requests` đã thử hết các retry mới timeout — điển hình của lỗi **không có Internet**, không phải lỗi server.

---

## ✅ Cách xác nhận & khắc phục

**Trên Kaggle khi chạy notebook:**

> **Settings → Internet → bật "Internet on"** trước khi Submit/Run.

Khi notebook được kích hoạt qua `kaggle kernels push` từ server (do pipeline tự động), cần đảm bảo trong `kernel-metadata.json` có:

```json
{
  "enable_internet": true
}
```

Nếu field này đang bị thiếu hoặc là `false`, notebook bị tắt Internet ngay từ đầu và mọi lần gọi về server đều thất bại như trên.
