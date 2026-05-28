# 3. Đẩy code từ máy tính cá nhân lên Kaggle bằng Kaggle API

## Mục tiêu

Mục tiêu của cách này là: **sửa value của một biến trong notebook trên máy tính cá nhân trước**, sau đó mới đẩy notebook đó lên Kaggle để Kaggle chạy bản đã được chỉnh sửa.

Cách này phù hợp khi bạn có một notebook `.ipynb` chạy trên Kaggle, nhưng trước mỗi lần chạy thật bạn cần đổi một vài biến như:

```python
RUN_MODE = "prod"
HEALTHCHECK_URL = "https://example.com/healthcheck"
INTERVAL_SECONDS = 300
ENABLE_DEBUG = False
```

Thay vì mở Kaggle Notebook bằng trình duyệt rồi sửa tay, ta sẽ sửa notebook ở local bằng script, sau đó dùng Kaggle API để push notebook lên Kaggle.

---

## Ý tưởng tổng quan

Workflow sẽ là:

```text
1. Tải / lưu notebook Kaggle về máy cá nhân
2. Đánh dấu một cell config trong notebook
3. Dùng script Python sửa value trong cell config đó
4. Kiểm tra notebook local đã đổi đúng chưa
5. Dùng Kaggle API push notebook lên Kaggle
6. Kaggle tự chạy bản notebook mới vừa được push
7. Theo dõi status và tải output nếu cần
```

Điểm quan trọng: **Kaggle API không nên được hiểu như một công cụ truyền tham số runtime trực tiếp vào notebook giống `python script.py --arg value`**. Với notebook Kaggle, cách ổn định hơn là tạo sẵn một cell config trong notebook, sau đó sửa cell này trước khi push.

---

## Cấu trúc thư mục khuyến nghị

Ví dụ tạo thư mục như sau:

```text
kaggle-runner/
│
├─ main.ipynb
├─ kernel-metadata.json
├─ patch_kaggle_notebook_config.py
└─ push_to_kaggle.ps1
```

Trong đó:

| File                              | Vai trò                                                |
| --------------------------------- | ------------------------------------------------------ |
| `main.ipynb`                      | Notebook sẽ chạy trên Kaggle                           |
| `kernel-metadata.json`            | Metadata bắt buộc để Kaggle biết notebook nào cần push |
| `patch_kaggle_notebook_config.py` | Script sửa biến trong notebook trước khi push          |
| `push_to_kaggle.ps1`              | Script PowerShell để sửa biến rồi push lên Kaggle      |

---

## Bước 1: Cài Kaggle API trên máy cá nhân

Cài package Kaggle CLI:

```powershell
pip install kaggle
```

Kiểm tra lệnh `kaggle` đã dùng được chưa:

```powershell
kaggle --help
```

Nếu Windows báo không nhận lệnh `kaggle`, thường là do thư mục `Scripts` của Python chưa nằm trong `PATH`. Khi đó bạn có thể thử:

```powershell
python -m kaggle --help
```

Hoặc thêm thư mục dạng sau vào `PATH`:

```text
C:\Users\<USERNAME>\AppData\Roaming\Python\Python3xx\Scripts
```

---

## Bước 2: Cấu hình xác thực Kaggle API

Có 2 cách phổ biến.

### Cách A: Dùng lệnh đăng nhập

```powershell
kaggle auth login
```

Cách này sẽ mở quy trình đăng nhập bằng trình duyệt.

### Cách B: Dùng file `kaggle.json`

Vào Kaggle account settings, tạo API key rồi tải file `kaggle.json` về.

Trên Windows, đặt file vào:

```text
C:\Users\<USERNAME>\.kaggle\kaggle.json
```

Trên Linux/macOS, đặt file vào:

```bash
~/.kaggle/kaggle.json
```

Sau đó test:

```powershell
kaggle kernels list --mine
```

Nếu lệnh trả về danh sách notebook/kernel của bạn, nghĩa là authentication đã hoạt động.

---

## Bước 3: Chuẩn bị `kernel-metadata.json`

Trong thư mục chứa notebook, chạy:

```powershell
kaggle kernels init -p .
```

Lệnh này tạo file `kernel-metadata.json` mẫu.

Ví dụ nội dung file:

```json
{
  "id": "your-kaggle-username/my-kaggle-notebook",
  "title": "My Kaggle Notebook",
  "code_file": "main.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": "true",
  "enable_gpu": "false",
  "enable_internet": "false",
  "dataset_sources": [],
  "competition_sources": [],
  "kernel_sources": [],
  "model_sources": []
}
```

Các field quan trọng:

| Field             | Ý nghĩa                                                      |
| ----------------- | ------------------------------------------------------------ |
| `id`              | Slug của notebook trên Kaggle, dạng `username/notebook-slug` |
| `title`           | Tên notebook hiển thị trên Kaggle                            |
| `code_file`       | Tên file notebook local sẽ được push                         |
| `language`        | Với Python notebook thì để `python`                          |
| `kernel_type`     | Với `.ipynb` thì để `notebook`                               |
| `is_private`      | `true` nếu muốn notebook private                             |
| `enable_gpu`      | `true` nếu cần GPU                                           |
| `enable_internet` | `true` nếu notebook cần internet                             |

Lưu ý: `code_file` phải trỏ đúng tới file `.ipynb` bạn muốn push, ví dụ `main.ipynb`.

---

## Bước 4: Tạo cell config trong notebook

Trong `main.ipynb`, tạo một cell riêng ở đầu notebook như sau:

```python
# === KAGGLE_RUN_CONFIG ===
RUN_MODE = "dev"
HEALTHCHECK_URL = "https://default-url.com/healthcheck"
INTERVAL_SECONDS = 300
ENABLE_DEBUG = True
```

Marker quan trọng là dòng:

```python
# === KAGGLE_RUN_CONFIG ===
```

Script local sẽ tìm cell có marker này và thay toàn bộ nội dung cell bằng value mới.

Khuyến nghị:

- Đặt cell config ở gần đầu notebook.
- Không viết logic xử lý phức tạp trong cell config.
- Chỉ để assignment biến trong cell này.
- Các cell phía sau chỉ đọc lại biến đã khai báo.

Ví dụ cell phía sau dùng biến:

```python
print("RUN_MODE:", RUN_MODE)
print("HEALTHCHECK_URL:", HEALTHCHECK_URL)
print("INTERVAL_SECONDS:", INTERVAL_SECONDS)
print("ENABLE_DEBUG:", ENABLE_DEBUG)
```

---

## Bước 5: Viết script sửa value trong notebook

Tạo file `patch_kaggle_notebook_config.py`:

```python
import argparse
import json
from pathlib import Path

import nbformat

MARKER = "# === KAGGLE_RUN_CONFIG ==="


def parse_value(raw: str):
    """
    Parse value từ command line.

    Ví dụ:
    - 300       -> int
    - 1.5       -> float
    - true      -> bool True
    - false     -> bool False
    - null      -> None
    - abc       -> string "abc"
    - "prod"    -> string "prod"
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_config_source(config: dict) -> str:
    lines = [MARKER]
    lines.append("# Auto-generated by patch_kaggle_notebook_config.py")
    lines.append("# Do not edit this cell manually before automated Kaggle push.\n")

    for key, value in config.items():
        lines.append(f"{key} = {repr(value)}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Patch Kaggle notebook config cell before pushing to Kaggle."
    )
    parser.add_argument(
        "--notebook",
        required=True,
        help="Path to .ipynb file, for example: main.ipynb",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output .ipynb path. If omitted, overwrite the input notebook.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Set variable value, format: NAME=VALUE. Example: --set RUN_MODE=prod",
    )

    args = parser.parse_args()

    notebook_path = Path(args.notebook)
    output_path = Path(args.out) if args.out else notebook_path

    if not notebook_path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    config = {}
    for item in args.set:
        if "=" not in item:
            raise ValueError(f"Invalid --set value: {item}. Expected NAME=VALUE")

        key, raw_value = item.split("=", 1)
        key = key.strip()

        if not key.isidentifier():
            raise ValueError(f"Invalid Python variable name: {key}")

        config[key] = parse_value(raw_value.strip())

    if not config:
        raise ValueError("No config provided. Use --set NAME=VALUE")

    nb = nbformat.read(notebook_path, as_version=4)

    patched = False
    new_source = build_config_source(config)

    for cell in nb.cells:
        if cell.get("cell_type") == "code" and MARKER in cell.get("source", ""):
            cell["source"] = new_source
            patched = True
            break

    if not patched:
        raise RuntimeError(
            f"Cannot find config cell marker: {MARKER}. "
            "Please add this marker to a code cell in the notebook."
        )

    nbformat.write(nb, output_path)
    print(f"Patched notebook saved to: {output_path}")
    print("Updated config:")
    for key, value in config.items():
        print(f"  {key} = {repr(value)}")


if __name__ == "__main__":
    main()
```

Cài thư viện cần thiết:

```powershell
pip install nbformat
```

---

## Bước 6: Test sửa biến ở local

Ví dụ muốn đổi config thành production:

```powershell
python patch_kaggle_notebook_config.py `
  --notebook main.ipynb `
  --set RUN_MODE=prod `
  --set HEALTHCHECK_URL=https://b6-remote-server-kaggle-2026.onrender.com/healthcheck `
  --set INTERVAL_SECONDS=300 `
  --set ENABLE_DEBUG=false
```

Sau khi chạy, mở lại `main.ipynb` và kiểm tra cell config. Nó sẽ được đổi thành dạng:

```python
# === KAGGLE_RUN_CONFIG ===
# Auto-generated by patch_kaggle_notebook_config.py
# Do not edit this cell manually before automated Kaggle push.

RUN_MODE = 'prod'
HEALTHCHECK_URL = 'https://b6-remote-server-kaggle-2026.onrender.com/healthcheck'
INTERVAL_SECONDS = 300
ENABLE_DEBUG = False
```

Lưu ý cách truyền value:

| Bạn truyền                   | Python nhận được     |
| ---------------------------- | -------------------- |
| `--set INTERVAL_SECONDS=300` | `300` kiểu int       |
| `--set ENABLE_DEBUG=false`   | `False` kiểu bool    |
| `--set RATE=1.5`             | `1.5` kiểu float     |
| `--set RUN_MODE=prod`        | `'prod'` kiểu string |
| `--set RUN_MODE="prod"`      | `'prod'` kiểu string |

---

## Bước 7: Push notebook lên Kaggle

Sau khi notebook đã được patch, chạy:

```powershell
kaggle kernels push -p .
```

Lệnh này sẽ:

1. Đọc `kernel-metadata.json`.
2. Lấy file notebook được khai báo trong `code_file`.
3. Upload notebook lên Kaggle.
4. Tạo version mới cho notebook/kernel.
5. Kaggle tự bắt đầu chạy version mới đó.

Nếu muốn dùng GPU, có thể chỉnh `enable_gpu` trong `kernel-metadata.json` thành:

```json
"enable_gpu": "true"
```

Hoặc dùng option accelerator nếu Kaggle CLI của bạn hỗ trợ:

```powershell
kaggle kernels push -p . --accelerator NvidiaTeslaT4
```

---

## Bước 8: Theo dõi trạng thái notebook sau khi push

Kiểm tra status:

```powershell
kaggle kernels status your-kaggle-username/my-kaggle-notebook
```

Ví dụ:

```powershell
kaggle kernels status ohyun/my-kaggle-notebook
```

Khi notebook chạy xong, bạn có thể tải output về:

```powershell
kaggle kernels output your-kaggle-username/my-kaggle-notebook -p ./output
```

Nếu muốn ghi đè output cũ:

```powershell
kaggle kernels output your-kaggle-username/my-kaggle-notebook -p ./output -o
```

---

## Bước 9: Tạo script PowerShell chạy trọn quy trình

Tạo file `push_to_kaggle.ps1`:

```powershell
param(
    [string]$RunMode = "prod",
    [string]$HealthcheckUrl = "https://b6-remote-server-kaggle-2026.onrender.com/healthcheck",
    [int]$IntervalSeconds = 300,
    [bool]$EnableDebug = $false
)

Write-Host "Patching notebook config..."

python patch_kaggle_notebook_config.py `
  --notebook main.ipynb `
  --set RUN_MODE=$RunMode `
  --set HEALTHCHECK_URL=$HealthcheckUrl `
  --set INTERVAL_SECONDS=$IntervalSeconds `
  --set ENABLE_DEBUG=$($EnableDebug.ToString().ToLower())

if ($LASTEXITCODE -ne 0) {
    Write-Error "Patch notebook failed. Stop."
    exit 1
}

Write-Host "Pushing notebook to Kaggle..."

kaggle kernels push -p .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Kaggle push failed."
    exit 1
}

Write-Host "Done. Kaggle is now running the pushed notebook version."
```

Chạy script:

```powershell
.\push_to_kaggle.ps1 `
  -RunMode "prod" `
  -HealthcheckUrl "https://b6-remote-server-kaggle-2026.onrender.com/healthcheck" `
  -IntervalSeconds 300 `
  -EnableDebug $false
```

---

## Workflow thực tế mỗi lần muốn chạy Kaggle thật

Mỗi lần muốn chạy notebook trên Kaggle với value mới, chỉ cần làm:

```powershell
.\push_to_kaggle.ps1 `
  -RunMode "prod" `
  -HealthcheckUrl "https://b6-remote-server-kaggle-2026.onrender.com/healthcheck" `
  -IntervalSeconds 300 `
  -EnableDebug $false
```

Sau đó kiểm tra status:

```powershell
kaggle kernels status your-kaggle-username/my-kaggle-notebook
```

Và tải output nếu cần:

```powershell
kaggle kernels output your-kaggle-username/my-kaggle-notebook -p ./output -o
```

---

## Best practice

### 1. Luôn gom biến cần sửa vào một cell config duy nhất

Không nên rải biến config ở nhiều cell khác nhau vì script sẽ khó sửa chính xác.

Nên dùng:

```python
# === KAGGLE_RUN_CONFIG ===
RUN_MODE = "prod"
INTERVAL_SECONDS = 300
ENABLE_DEBUG = False
```

Không nên dùng:

```python
# cell 1
RUN_MODE = "prod"

# cell 10
INTERVAL_SECONDS = 300

# cell 27
ENABLE_DEBUG = False
```

---

### 2. Dùng marker cố định để script tìm đúng cell

Marker nên là một dòng đặc biệt, ít có khả năng bị trùng:

```python
# === KAGGLE_RUN_CONFIG ===
```

Không nên chỉ tìm theo tên biến như `RUN_MODE`, vì tên biến có thể xuất hiện ở nhiều nơi trong notebook.

---

### 3. Không để secret trực tiếp trong notebook

Không nên hard-code API key, token, password vào notebook rồi push lên Kaggle.

Không nên:

```python
OPENAI_API_KEY = "sk-xxxxx"
```

Nên dùng Kaggle Secrets nếu cần secret khi chạy trên Kaggle.

---

### 4. Luôn kiểm tra notebook sau khi patch

Trước khi push thật, có thể kiểm tra nhanh bằng cách mở notebook hoặc dùng lệnh:

```powershell
python - << 'PY'
import nbformat
nb = nbformat.read('main.ipynb', as_version=4)
for cell in nb.cells:
    if cell.cell_type == 'code' and '# === KAGGLE_RUN_CONFIG ===' in cell.source:
        print(cell.source)
        break
PY
```

Trên PowerShell thuần, có thể dùng cách đơn giản hơn:

```powershell
python -c "import nbformat; nb=nbformat.read('main.ipynb', as_version=4); [print(c.source) for c in nb.cells if c.cell_type=='code' and '# === KAGGLE_RUN_CONFIG ===' in c.source]"
```

---

### 5. Commit notebook trước khi patch nếu đang dùng Git

Nếu muốn tránh việc patch làm bẩn file gốc, có 2 hướng:

#### Hướng A: Cho phép patch trực tiếp `main.ipynb`

Sau khi chạy xong, commit lại nếu muốn lưu config đó.

#### Hướng B: Tạo bản notebook riêng để push

Ví dụ:

```powershell
python patch_kaggle_notebook_config.py `
  --notebook main.ipynb `
  --out main.kaggle.ipynb `
  --set RUN_MODE=prod
```

Sau đó sửa `kernel-metadata.json`:

```json
"code_file": "main.kaggle.ipynb"
```

Cách B giúp giữ `main.ipynb` sạch hơn, còn `main.kaggle.ipynb` là bản build để upload.

---

## Lỗi thường gặp

### Lỗi 1: `kaggle: command not found`

Nguyên nhân: Kaggle CLI chưa nằm trong `PATH`.

Cách xử lý:

```powershell
python -m kaggle --help
```

Nếu cách này chạy được, bạn có thể thay `kaggle` bằng `python -m kaggle` trong script.

---

### Lỗi 2: `403 Forbidden` hoặc lỗi authentication

Nguyên nhân thường gặp:

- Chưa login Kaggle API.
- File `kaggle.json` đặt sai vị trí.
- Token hết hạn hoặc sai.

Cách xử lý:

```powershell
kaggle auth login
```

Hoặc tải lại API token từ Kaggle settings rồi đặt lại file `kaggle.json`.

---

### Lỗi 3: `kernel-metadata.json` không hợp lệ

Kiểm tra các field quan trọng:

```json
{
  "id": "your-kaggle-username/my-kaggle-notebook",
  "code_file": "main.ipynb",
  "language": "python",
  "kernel_type": "notebook"
}
```

Đặc biệt kiểm tra:

- `id` có đúng username/slug không.
- `code_file` có đúng tên file `.ipynb` không.
- File `.ipynb` có nằm cùng thư mục với `kernel-metadata.json` không.

---

### Lỗi 4: Script không tìm thấy config cell

Thông báo có thể là:

```text
Cannot find config cell marker: # === KAGGLE_RUN_CONFIG ===
```

Cách xử lý: thêm một code cell vào notebook:

```python
# === KAGGLE_RUN_CONFIG ===
RUN_MODE = "dev"
```

Sau đó chạy lại script patch.

---

## Kết luận

Cách làm chuẩn là:

```text
Không sửa trực tiếp trên Kaggle UI
→ sửa biến trong notebook local bằng script
→ push notebook lên Kaggle bằng Kaggle API
→ Kaggle chạy bản notebook mới đã được sửa value
```

Lệnh quan trọng nhất là:

```powershell
python patch_kaggle_notebook_config.py --notebook main.ipynb --set RUN_MODE=prod
kaggle kernels push -p .
```

Nếu làm đúng, bạn có thể điều khiển value của biến trong notebook trước mỗi lần chạy Kaggle thật mà không cần mở trình duyệt để sửa tay.

---

## Nguồn tham khảo

- Kaggle CLI documentation: https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md
- Kaggle kernels command documentation: https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md
- Kaggle kernel metadata documentation: https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md
