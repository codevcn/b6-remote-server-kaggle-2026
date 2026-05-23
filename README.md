# 🎬 Kaggle Master Controller — B6 Team

> **Bộ Điều phối Trung tâm** tự động hóa chuỗi Kaggle Notebooks cho pipeline xử lý video TikTok của Team B6.

---

## 📖 Tổng quan

Server này là **"dây chuyền điều phối"** nằm giữa các Kaggle Notebook, đóng vai trò trung tâm trong hệ thống xử lý video tự động. Khi một notebook hoàn thành, nó gửi tín hiệu về server này, và server sẽ tự động kích hoạt notebook tiếp theo trong chuỗi — hoàn toàn không cần can thiệp thủ công.

Sau khi toàn bộ chuỗi hoàn tất, server gửi thông báo tổng kết đến **Telegram** của team.

### Luồng hoạt động (Pipeline)

```
┌─────────────────────────────────────────────────────────────────┐
│                     KAGGLE MASTER CONTROLLER                    │
│                  (Render.com — FastAPI Server)                  │
└─────────────────────────────────────────────────────────────────┘
         ▲ webhook          ▲ webhook          ▲ webhook
         │                 │                 │
┌────────┴───────┐ ┌───────┴───────┐ ┌───────┴───────┐
│  Notebook #1   │ │  Notebook #2  │ │  Notebook #3  │
│   (start)      │ │    (mid)      │ │    (end)      │
│  kenkunkanki/  │ │ hipbiquang/   │ │ vanphongg/    │
│  ...           │ │ translate-... │ │ omnivoice-... │
└────────────────┘ └───────────────┘ └───────────────┘
         │  completed             │  completed            │  done
         └──── trigger ──────────┘  ── trigger ──────────┘
                                                          │
                                                          ▼
                                                 📱 Telegram Bot
                                               (Thông báo hoàn tất)
```

---

## 🏗️ Kiến trúc & Cấu trúc Project

```
kaggle-master-controller/
├── src/
│   └── main.py                        # Ứng dụng FastAPI chính (toàn bộ logic)
├── scripts/
│   └── keep_render_awake.py           # Script giữ server không ngủ (ping mỗi 5 phút)
├── .env                               # Biến môi trường bí mật (KHÔNG commit lên Git)
├── .gitignore
├── requirements.txt                   # Danh sách thư viện Python
├── note.md                            # Ghi chú lệnh khởi chạy
├── keep-render-awake.cmd              # Shortcut chạy keep_render_awake.py trên Windows
└── README.md                          # File này
```

---

## ⚙️ Cơ chế hoạt động chi tiết

### 1. Nhận tín hiệu Webhook (`POST /webhook/notebook`)

Mỗi Kaggle Notebook ở cuối quá trình thực thi sẽ gửi một HTTP POST request đến endpoint này với payload JSON:

```json
{
  "job_id": "broccoli-01",
  "notebook_index_type": "start",
  "status": "completed",
  "next_notebook_ref": "hipbiquang/translate-srt-flow",
  "progress": null,
  "text_data": "Dữ liệu tùy chọn từ notebook (nếu có)"
}
```

| Field                 | Bắt buộc | Mô tả                                                        |
| --------------------- | -------- | ------------------------------------------------------------ |
| `job_id`              | ✅       | Mã định danh cho toàn bộ chuỗi công việc (VD: `broccoli-01`) |
| `notebook_index_type` | ✅       | Vị trí trong pipeline: `start` / `mid` / `end`               |
| `status`              | ✅       | Trạng thái hiện tại: `started` / `completed`                 |
| `next_notebook_ref`   | ❌       | Tham chiếu notebook tiếp theo (VD: `username/notebook-slug`) |
| `progress`            | ❌       | Tiến độ tổng thể, dùng khi kết thúc: `done`                  |
| `text_data`           | ❌       | Dữ liệu văn bản đính kèm tùy chọn từ notebook                |

### 2. Logic điều phối

```
Nhận webhook
    │
    ├─ [notebook_index_type == "start" hoặc "mid"] AND [status == "completed"]
    │       └─► Chạy ngầm: kích hoạt notebook tiếp theo qua Kaggle API
    │
    └─ [notebook_index_type == "end"] AND [progress == "done"]
            └─► Đánh dấu job hoàn tất
            └─► Gửi thông báo Telegram (kèm text_data nếu có)
```

### 3. Kích hoạt Notebook qua Kaggle API (`KaggleService`)

Khi cần chạy notebook tiếp theo, server thực hiện 3 bước tuần tự:

```
Bước 1: kaggle kernels pull <notebook_ref> -m    # Pull metadata (kernel-metadata.json)
Bước 2: kaggle kernels pull <notebook_ref>       # Pull file .ipynb
Bước 3: kaggle kernels push -p <folder>          # Push lại để kích hoạt chạy
```

> **Lưu ý:** `machine_shape: "None"` trong `kernel-metadata.json` được tự động chuẩn hóa thành `null` trước khi push để tránh lỗi từ Kaggle API.

Sau khi push xong, thư mục tạm trong `tmp/` được dọn dẹp tự động.

### 4. Thông báo Telegram

Khi job hoàn tất, bot Telegram sẽ gửi tin nhắn có dạng:

```
🎉 [B6 Team - Thông Báo Hệ Thống]

Chuỗi Notebook mang mã định danh: broccoli-01 đã được thực thi HOÀN TẤT.
Tiến độ tổng thể: DONE
Dữ liệu đính kèm từ notebook: <nội dung text_data nếu có>
```

---

## 🔑 Cấu hình & Biến môi trường

Toàn bộ thông tin nhạy cảm được lưu trong file `.env` ở thư mục gốc.

| Biến                 | Mô tả                                                | Ví dụ                          |
| -------------------- | ---------------------------------------------------- | ------------------------------ |
| `SERVER_API_KEY`     | Khóa xác thực cho mọi request vào server             | `b6-remote-server-kaggle-2026` |
| `KAGGLE_ACCOUNTS`    | JSON map tài khoản Kaggle: `{"username": "api_key"}` | `{"user1": "KGAT_xxx"}`        |
| `TELEGRAM_BOT_TOKEN` | Token của Telegram Bot (lấy từ @BotFather)           | `123456:AABBcc...`             |
| `TELEGRAM_CHAT_ID`   | ID chat/group nhận thông báo                         | `1331854393`                   |

### Ví dụ file `.env`

```env
SERVER_API_KEY='your-secret-key-here'

KAGGLE_ACCOUNTS='{"account1": "KGAT_xxx", "account2": "KGAT_yyy"}'

TELEGRAM_BOT_TOKEN='your_bot_token'
TELEGRAM_CHAT_ID='your_chat_id'
```

> ⚠️ **Quan trọng:** File `.env` đã được thêm vào `.gitignore`. **Không bao giờ** commit file này lên Git.

---

## 🔐 Xác thực API

Mọi request đến `/webhook/notebook` phải kèm header:

```
X-API-Key: <SERVER_API_KEY>
```

Nếu thiếu hoặc sai key, server sẽ trả về `403 Forbidden`.

**Ví dụ gọi từ Kaggle Notebook (Python):**

```python
import requests

SERVER_URL = "https://b6-remote-server-kaggle-2026.onrender.com"
API_KEY = "b6-remote-server-kaggle-2026"

payload = {
    "job_id": "broccoli-01",
    "notebook_index_type": "start",
    "status": "started",
}

response = requests.post(
    f"{SERVER_URL}/webhook/notebook",
    json=payload,
    headers={"X-API-Key": API_KEY},
)
print(response.json())
```

---

## 🚀 Hướng dẫn triển khai

### Cài đặt cục bộ (Local)

```bash
# 1. Clone repo
git clone <repo_url>
cd kaggle-master-controller

# 2. Tạo môi trường ảo Python
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # Linux/macOS

# 3. Cài đặt thư viện
pip install -r requirements.txt

# 4. Tạo file .env và điền thông tin cấu hình
cp .env.example .env   # (hoặc tạo thủ công)

# 5. Chạy server
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Server sẽ chạy tại: `http://localhost:8000`

### Triển khai trên Render.com

**Start Command** (cấu hình trên Render dashboard):

```bash
uvicorn src.main:app --host 0.0.0.0 --port $PORT
```

**Các bước:**

1. Push code lên GitHub
2. Tạo **Web Service** mới trên [render.com](https://render.com)
3. Kết nối với GitHub repo
4. Điền **Start Command** như trên
5. Thêm toàn bộ biến trong `.env` vào phần **Environment Variables** trên Render dashboard
6. Deploy

---

## 📡 API Reference

### `POST /webhook/notebook`

Nhận tín hiệu từ Kaggle Notebook và điều phối chuỗi công việc.

- **Auth:** `X-API-Key` header bắt buộc
- **Content-Type:** `application/json`
- **Response:**

```json
{
  "message": "Dữ liệu tín hiệu đã được máy chủ tiếp nhận thành công",
  "job_id": "broccoli-01"
}
```

---

### `GET /healthcheck`

Kiểm tra tình trạng hoạt động của server. Không yêu cầu xác thực.

- **Response:**

```json
{
  "name": "healthcheck response",
  "timestamp": "2026-05-23T09:55:02.647759+00:00"
}
```

---

## 🌙 Keep-Alive (Chống ngủ trên Render Free Tier)

Render.com ở gói miễn phí sẽ tắt server sau **15 phút không có traffic**. Để tránh điều này:

### Chạy script keep-alive thủ công (trên máy local)

```bash
# Windows: Double-click file này
keep-render-awake.cmd

# Hoặc chạy trực tiếp
python scripts/keep_render_awake.py
```

Script sẽ ping endpoint `/healthcheck` **mỗi 5 phút** và in log ra terminal.

### Dùng dịch vụ bên ngoài (Khuyến nghị)

Cấu hình **UptimeRobot** (miễn phí) để tự động ping:

- URL: `https://b6-remote-server-kaggle-2026.onrender.com/healthcheck`
- Interval: 5 phút
- Monitor type: HTTP(s)

---

## 📦 Dependencies

| Thư viện            | Phiên bản | Mục đích                               |
| ------------------- | --------- | -------------------------------------- |
| `fastapi`           | 0.111.0   | Web framework — xây dựng REST API      |
| `uvicorn[standard]` | 0.30.1    | ASGI server — chạy FastAPI             |
| `pydantic`          | 2.7.2     | Validation dữ liệu — định nghĩa schema |
| `httpx`             | 0.27.0    | HTTP client async — gọi Telegram API   |
| `kaggle`            | ≥1.8.0    | Kaggle CLI — điều phối notebooks       |
| `python-dotenv`     | 1.0.1     | Đọc biến môi trường từ file `.env`     |

---

## 📝 Nhật ký thay đổi

| Phiên bản | Ngày       | Thay đổi                                                                                                                                        |
| --------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `1.1.0`   | 2026-05-23 | Thêm field `text_data` optional trong payload; log cho notebook `end` nhất quán với `start`/`mid`; thêm `timestamp` vào response `/healthcheck` |
| `1.0.0`   | —          | Phiên bản khởi tạo: webhook điều phối, Kaggle push/pull, Telegram notification                                                                  |

---

## 👥 Team B6

Project thuộc hệ thống xử lý video TikTok tự động của **B6 Team**.
