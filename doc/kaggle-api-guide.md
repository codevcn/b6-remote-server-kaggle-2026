# 📘 Hướng dẫn chi tiết: Kaggle API trong Kaggle Master Controller

> Tài liệu này mô tả toàn bộ cách project sử dụng **Kaggle CLI / API** để tự động kích hoạt các notebook trên nền tảng Kaggle — từ xác thực, lệnh gọi, xử lý lỗi đến dọn dẹp.

---

## 📑 Mục lục

1. [Tổng quan cơ chế](#1-tổng-quan-cơ-chế)
2. [Xác thực Kaggle API (Multi-account)](#2-xác-thực-kaggle-api-multi-account)
3. [Quy trình 3 bước Pull → Chuẩn hóa → Push](#3-quy-trình-3-bước)
   - [Bước 1 — Pull Metadata](#bước-1--pull-metadata)
   - [Bước 2 — Pull Notebook (.ipynb)](#bước-2--pull-notebook-ipynb)
   - [Bước 3 — Chuẩn hóa Metadata & Push](#bước-3--chuẩn-hóa-metadata--push)
4. [Cấu trúc thư mục tạm (tmp/)](#4-cấu-trúc-thư-mục-tạm-tmp)
5. [Xử lý lỗi & lọc Warning](#5-xử-lý-lỗi--lọc-warning)
6. [Dọn dẹp sau khi Push](#6-dọn-dẹp-sau-khi-push)
7. [Sơ đồ luồng đầy đủ](#7-sơ-đồ-luồng-đầy-đủ)
8. [Tham chiếu lệnh CLI nhanh](#8-tham-chiếu-lệnh-cli-nhanh)

---

## 1. Tổng quan cơ chế

Project **không gọi Kaggle REST API trực tiếp** qua HTTP. Thay vào đó, nó dùng **Kaggle CLI** (thư viện `kaggle>=1.8.0`) thông qua module `subprocess` của Python để thực thi lệnh shell.

### Tại sao dùng CLI thay vì REST API trực tiếp?

| Tiêu chí | Kaggle CLI | REST API trực tiếp |
|---|---|---|
| Độ phức tạp | ✅ Thấp — lệnh đơn giản | ❌ Cao — phải tự xử lý auth, headers, multipart upload |
| Upload file `.ipynb` | ✅ CLI lo toàn bộ | ❌ Phải tự encode và upload |
| Xử lý `kernel-metadata.json` | ✅ CLI đọc tự động | ❌ Phải tự parse và gửi JSON |
| Bảo trì | ✅ Kaggle tự cập nhật | ❌ Tự xử lý nếu API thay đổi |

---

## 2. Xác thực Kaggle API (Multi-account)

### Cấu hình nhiều tài khoản

Project hỗ trợ **nhiều tài khoản Kaggle** cùng lúc, được cấu hình trong `.env` dưới dạng JSON:

```env
KAGGLE_ACCOUNTS='{"kenkunkanki": "KGAT_xxx", "hipbiquang": "KGAT_yyy", "vanphongg": "KGAT_zzz"}'
```

Khi server khởi động, biến này được parse thành dict Python:

```python
KAGGLE_ACCOUNTS = json.loads(os.getenv("KAGGLE_ACCOUNTS", "{}"))
# Kết quả: {"kenkunkanki": "KGAT_xxx", "hipbiquang": "KGAT_yyy", ...}
```

### Cơ chế Isolated Environment

Để mỗi lần gọi CLI dùng **đúng tài khoản sở hữu notebook đó**, project tạo ra một **môi trường biến môi trường riêng biệt (isolated env)** thay vì ghi đè biến toàn cục:

```python
# Trích từ KaggleService.trigger_next_notebook()

# notebook_ref ví dụ: "hipbiquang/translate-srt-flow"
username = notebook_ref.split("/")[0]    # → "hipbiquang"

# Tạo bản sao môi trường hiện tại, KHÔNG thay đổi os.environ gốc
isolated_env = os.environ.copy()
isolated_env["KAGGLE_USERNAME"] = username
isolated_env["KAGGLE_KEY"] = KAGGLE_ACCOUNTS[username]
isolated_env["PYTHONWARNINGS"] = "ignore"   # Tắt SyntaxWarning từ kaggle lib (Python 3.12)
```

Môi trường `isolated_env` này sau đó được truyền vào mỗi lần gọi `subprocess.run(..., env=isolated_env)`.

> ✅ **Tại sao cần Isolated Env?**  
> Nếu ghi đè `os.environ` trực tiếp, server xử lý nhiều webhook đồng thời có thể bị **race condition** — notebook B sẽ dùng credentials của notebook A do biến toàn cục bị ghi đè giữa chừng.

### Kiểm tra tài khoản trước khi gọi

```python
if username not in KAGGLE_ACCOUNTS:
    logger.error(
        f"Hủy lệnh chạy {notebook_ref}: Không tìm thấy API Key cho tài khoản [{username}]."
    )
    return   # Dừng ngay, không xử lý tiếp
```

---

## 3. Quy trình 3 bước

Toàn bộ logic nằm trong phương thức `KaggleService.trigger_next_notebook(notebook_ref: str)`. Với mỗi notebook cần kích hoạt, server thực hiện **3 bước tuần tự**:

```
Pull Metadata  →  Pull Notebook  →  Chuẩn hóa JSON  →  Push
```

### Bước 1 — Pull Metadata

**Mục đích:** Tải về file `kernel-metadata.json` — file cấu hình mô tả notebook (tên, loại, dataset đính kèm, GPU/CPU, v.v.).

**Lệnh CLI tương đương:**
```bash
kaggle kernels pull hipbiquang/translate-srt-flow \
    -p ./tmp/hipbiquang_translate-srt-flow \
    -m
```

**Code trong project:**
```python
pull_meta_cmd = [
    "kaggle", "kernels", "pull",
    notebook_ref,               # VD: "hipbiquang/translate-srt-flow"
    "-p", str(folder_path),     # Đường dẫn thư mục đích
    "-m",                       # Flag: chỉ pull metadata, không pull code
]
pull_meta_result = subprocess.run(
    pull_meta_cmd,
    env=isolated_env,           # Dùng credentials của đúng tài khoản
    capture_output=True,        # Bắt stdout và stderr
    text=True                   # Decode output thành string
)
```

**Flag `-m` (metadata only):**
- Chỉ tải `kernel-metadata.json`, không tải file `.ipynb`
- Giúp tách biệt 2 bước để xử lý riêng

**Output thành công:**
```
Source code and metadata downloaded to /opt/render/project/src/tmp/hipbiquang_translate-srt-flow
```

---

### Bước 2 — Pull Notebook (.ipynb)

**Mục đích:** Tải về file mã nguồn `.ipynb` của notebook. File này cần thiết vì lệnh `push` yêu cầu phải có file notebook trong thư mục.

**Lệnh CLI tương đương:**
```bash
kaggle kernels pull hipbiquang/translate-srt-flow \
    -p ./tmp/hipbiquang_translate-srt-flow
# (Không có -m → pull cả code lẫn metadata)
```

**Code trong project:**
```python
pull_nb_cmd = [
    "kaggle", "kernels", "pull",
    notebook_ref,
    "-p", str(folder_path),
    # Không có "-m" → pull file .ipynb
]
pull_nb_result = subprocess.run(
    pull_nb_cmd, env=isolated_env, capture_output=True, text=True
)
```

**Output thành công:**
```
Source code downloaded to /opt/render/project/src/tmp/hipbiquang_translate-srt-flow/translate-srt-flow.ipynb
```

> **Lưu ý:** Sau bước này, thư mục tạm sẽ có 2 file:
> ```
> tmp/hipbiquang_translate-srt-flow/
> ├── kernel-metadata.json
> └── translate-srt-flow.ipynb
> ```

---

### Bước 3 — Chuẩn hóa Metadata & Push

#### 3a. Chuẩn hóa `kernel-metadata.json`

Trước khi push, server đọc và sửa một lỗi thường gặp trong file metadata:

```python
metadata_path = folder_path / "kernel-metadata.json"
if metadata_path.exists():
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))

    # Sửa lỗi: Kaggle API trả về string "None" thay vì null JSON
    if meta.get("machine_shape") == "None":
        meta["machine_shape"] = None        # Chuyển thành null JSON thực sự

    metadata_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
```

**Tại sao cần bước này?**

Kaggle đôi khi serialize trường `machine_shape` thành chuỗi `"None"` (Python) thay vì `null` (JSON). Nếu push lên với giá trị `"None"` (string), Kaggle API sẽ báo lỗi validation vì nó expect `null` hoặc một giá trị hợp lệ.

**Ví dụ `kernel-metadata.json` trước và sau chuẩn hóa:**

```json
// TRƯỚC (lỗi)
{
  "id": "hipbiquang/translate-srt-flow",
  "language": "python",
  "kernel_type": "notebook",
  "machine_shape": "None"
}

// SAU (đúng)
{
  "id": "hipbiquang/translate-srt-flow",
  "language": "python",
  "kernel_type": "notebook",
  "machine_shape": null
}
```

#### 3b. Push để kích hoạt notebook chạy

**Mục đích:** Upload lại notebook lên Kaggle — Kaggle sẽ tự động **tạo một version mới** và **bắt đầu chạy** ngay lập tức.

**Lệnh CLI tương đương:**
```bash
kaggle kernels push -p ./tmp/hipbiquang_translate-srt-flow
```

**Code trong project:**
```python
push_cmd = [
    "kaggle", "kernels", "push",
    "-p", str(folder_path)      # Thư mục chứa .ipynb và kernel-metadata.json
]
push_result = subprocess.run(
    push_cmd, env=isolated_env, capture_output=True, text=True
)
```

**Output thành công:**
```
Kernel version 5 successfully pushed.
Please check progress at https://www.kaggle.com/code/hipbiquang/translate-srt-flow
```

---

## 4. Cấu trúc thư mục tạm (tmp/)

Với mỗi notebook được kích hoạt, server tạo một thư mục tạm riêng:

```
kaggle-master-controller/
└── tmp/
    └── {username}_{notebook-slug}/     # VD: hipbiquang_translate-srt-flow
        ├── kernel-metadata.json         # Cấu hình notebook (pull -m)
        └── {notebook-slug}.ipynb        # Mã nguồn notebook (pull)
```

**Quy tắc đặt tên thư mục:**
```python
folder_name = notebook_ref.replace("/", "_")
# "hipbiquang/translate-srt-flow" → "hipbiquang_translate-srt-flow"
folder_path = BASE_DIR / "tmp" / folder_name
```

Thư mục được tạo bằng `os.makedirs(folder_path, exist_ok=True)` — an toàn nếu đã tồn tại.

---

## 5. Xử lý lỗi & lọc Warning

### Kiểm tra returncode

Sau mỗi lệnh `subprocess.run()`, server kiểm tra `returncode`:
- `0` → thành công
- Khác `0` → lỗi, log và dừng ngay

```python
if pull_meta_result.returncode != 0:
    logger.error(
        f"Lỗi khi pull metadata {notebook_ref}:\n"
        f"  stderr: {real_stderr_meta}\n"
        f"  stdout: {pull_meta_result.stdout.strip()}"
    )
    return    # Dừng toàn bộ quy trình, không tiếp tục
```

### Lọc SyntaxWarning từ thư viện Kaggle (Python 3.12)

Thư viện `kaggle` phiên bản cũ in ra `SyntaxWarning: invalid escape sequence` khi chạy trên Python 3.12. Warning này không phải lỗi thật nhưng gây nhiễu log.

Project lọc chúng ra trước khi log:

```python
real_stderr_meta = "\n".join(
    line
    for line in pull_meta_result.stderr.splitlines()
    if "SyntaxWarning" not in line and "invalid escape sequence" not in line
).strip()
```

Ngoài ra, `isolated_env["PYTHONWARNINGS"] = "ignore"` được set để tắt warning ngay từ đầu.

### Phân biệt lỗi Fatal và Non-fatal

| Tình huống | Xử lý |
|---|---|
| `returncode != 0` | Log `ERROR` → `return` (dừng hẳn) |
| `returncode == 0` nhưng có `stderr` | Log `WARNING` → vẫn tiếp tục |
| Không có `stderr` | Log `INFO` stdout → tiếp tục |

---

## 6. Dọn dẹp sau khi Push

Sau khi push thành công (hoặc kể cả khi xảy ra exception), thư mục tạm luôn được xóa trong khối `finally`:

```python
finally:
    if "folder_path" in locals() and folder_path.exists():
        shutil.rmtree(folder_path, ignore_errors=True)
        logger.info(f"Đã dọn dẹp thư mục tạm thời: {folder_path.name}")
```

- `shutil.rmtree()` xóa toàn bộ thư mục đệ quy
- `ignore_errors=True` đảm bảo không ném exception nếu xóa thất bại
- `"folder_path" in locals()` kiểm tra biến có tồn tại không (phòng trường hợp lỗi xảy ra trước khi `folder_path` được gán)

---

## 7. Sơ đồ luồng đầy đủ

```
trigger_next_notebook("hipbiquang/translate-srt-flow")
│
├─► Parse username → "hipbiquang"
│
├─► Kiểm tra KAGGLE_ACCOUNTS["hipbiquang"]
│       ├── Không tồn tại → log ERROR → return ❌
│       └── Tồn tại → tiếp tục ✅
│
├─► Tạo isolated_env với KAGGLE_USERNAME + KAGGLE_KEY
│
├─► Tạo thư mục tmp/hipbiquang_translate-srt-flow/
│
├─► [Bước 1] kaggle kernels pull ... -m
│       ├── returncode != 0 → log ERROR → return ❌
│       └── OK → log stdout ✅
│
├─► [Bước 2] kaggle kernels pull ...
│       ├── returncode != 0 → log ERROR → return ❌
│       └── OK → log stdout ✅
│
├─► [Chuẩn hóa] Sửa machine_shape: "None" → null trong JSON
│
├─► [Bước 3] kaggle kernels push -p ...
│       ├── returncode != 0 → log ERROR → return ❌
│       └── OK → log "Kernel version X successfully pushed" ✅
│
└─► [finally] shutil.rmtree(tmp/hipbiquang_translate-srt-flow/)
```

---

## 8. Tham chiếu lệnh CLI nhanh

Dưới đây là các lệnh Kaggle CLI có thể dùng để kiểm tra thủ công từ terminal:

```bash
# Xem thông tin notebook
kaggle kernels list -u hipbiquang

# Pull chỉ metadata
kaggle kernels pull hipbiquang/translate-srt-flow -p ./test_folder -m

# Pull cả metadata lẫn code
kaggle kernels pull hipbiquang/translate-srt-flow -p ./test_folder

# Xem trạng thái chạy của notebook (sau khi push)
kaggle kernels status hipbiquang/translate-srt-flow

# Push notebook (kích hoạt chạy lại)
kaggle kernels push -p ./test_folder

# Xem output/log của lần chạy gần nhất
kaggle kernels output hipbiquang/translate-srt-flow -p ./output_folder
```

### Cấu hình thủ công credentials Kaggle CLI

Nếu cần test ngoài project, có thể set credentials bằng biến môi trường:

```bash
# Windows PowerShell
$env:KAGGLE_USERNAME = "hipbiquang"
$env:KAGGLE_KEY = "KGAT_da3c5aca3d2e5ff060051810f8c2339f"

# Linux/macOS
export KAGGLE_USERNAME="hipbiquang"
export KAGGLE_KEY="KGAT_da3c5aca3d2e5ff060051810f8c2339f"
```

Hoặc tạo file `~/.kaggle/kaggle.json`:
```json
{
  "username": "hipbiquang",
  "key": "KGAT_da3c5aca3d2e5ff060051810f8c2339f"
}
```

---

> 📁 **File liên quan:** [`src/main.py`](../src/main.py) — Class `KaggleService`, phương thức `trigger_next_notebook()` (dòng 106–240)
