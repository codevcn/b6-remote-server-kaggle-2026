import os
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Literal, Optional, Dict

from fastapi import FastAPI, HTTPException, BackgroundTasks, Security, Depends
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

from datetime import datetime, timezone  # <--- THÊM DÒNG NÀY

# ==========================================
# 1. ĐỊNH VỊ ĐƯỜNG DẪN & NẠP BIẾN MÔI TRƯỜNG (.ENV)
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(
        f"[{Path(__file__).name}] Nạp cấu hình từ tệp .env thành công tại: {env_path}"
    )
else:
    print(
        f"[{Path(__file__).name}] Cảnh báo: Không tìm thấy tệp .env, hệ thống sẽ sử dụng biến môi trường của Remote Server."
    )

# ==========================================
# 1b. CẤU HÌNH ỨNG DỤNG (APP CONFIG)
# ==========================================
CONFIG_PATH = BASE_DIR / "src" / "configs" / "configs.json"


def _load_config() -> dict:
    """Đọc cấu hình từ configs.json. Trả về dict mặc định nếu file không tồn tại hoặc bị lỗi."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"active_job_id": None}


def _save_config(config: dict) -> None:
    """Ghi cấu hình xuống file configs.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )


server_config: Dict = _load_config()

# ==========================================
# 2. CẤU HÌNH & GHI NHẬT KÝ (CONFIG & LOGGING)
# ==========================================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
logger = logging.getLogger("RemoteCoordinator")


class _TrimmedFileHandler(logging.FileHandler):
    """
    FileHandler tùy chỉnh: ghi log vào file và tự động cắt bớt khi file vượt
    quá ngưỡng (max_lines + trim_buffer), chỉ giữ lại max_lines dòng mới nhất.
    """

    def __init__(
        self, filename, max_lines: int = 300, trim_buffer: int = 100, **kwargs
    ):
        self.max_lines = max_lines
        self.trim_buffer = trim_buffer
        super().__init__(filename, mode="a", encoding="utf-8", **kwargs)

    def emit(self, record):
        super().emit(record)
        self._trim_if_needed()

    def _trim_if_needed(self):
        try:
            with open(self.baseFilename, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Chỉ ghi lại file khi số dòng vượt quá ngưỡng (tránh I/O liên tục)
            if len(lines) > self.max_lines + self.trim_buffer:
                with open(self.baseFilename, "w", encoding="utf-8") as f:
                    f.writelines(lines[-self.max_lines :])
        except Exception:
            pass  # Không để lỗi file I/O làm crash server


# --- Gắn file handler vào root logger để bắt log của mọi thành phần ---
_LOG_FILE_PATH = BASE_DIR / "runtime.log"
_log_formatter = logging.Formatter(
    "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
_file_handler = _TrimmedFileHandler(str(_LOG_FILE_PATH), max_lines=300, trim_buffer=100)
_file_handler.setFormatter(_log_formatter)
logging.getLogger().addHandler(_file_handler)

logger.info(f"File log runtime đang được ghi tại: {_LOG_FILE_PATH}")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SERVER_API_KEY = os.getenv("SERVER_API_KEY", "secret-key-cua-ban")

kaggle_accounts_str = os.getenv("KAGGLE_ACCOUNTS", "{}")
try:
    KAGGLE_ACCOUNTS = json.loads(kaggle_accounts_str)
    logger.info(
        f"Đã nạp thành công cấu hình cho {len(KAGGLE_ACCOUNTS)} tài khoản Kaggle."
    )
except json.JSONDecodeError:
    logger.error(
        "Lỗi nghiêm trọng: Biến KAGGLE_ACCOUNTS không đúng định dạng JSON chuẩn."
    )
    KAGGLE_ACCOUNTS = {}


# ==========================================
# 3. KHAI BÁO CẤU TRÚC DỮ LIỆU (SCHEMAS)
# ==========================================
class NotebookPayload(BaseModel):
    job_id: str = Field(
        ..., description="Mã định danh đại diện cho toàn bộ chuỗi công việc"
    )
    notebook_index_type: Literal["start", "mid", "end"] = Field(
        ..., description="Vị trí của notebook trong chuỗi"
    )
    status: Literal["started", "completed"] = Field(
        ..., description="Trạng thái thực thi hiện tại của notebook"
    )
    progress: Optional[str] = Field(
        None, description="Trạng thái tiến độ tổng thể (ví dụ: done)"
    )
    next_notebook_ref: Optional[str] = Field(
        None, description="Tên đăng nhập và tên notebook tiếp theo cần chạy"
    )
    text_data: Optional[str] = Field(
        None, description="Dữ liệu văn bản đính kèm tùy chọn từ notebook"
    )


class UpdateJobIdPayload(BaseModel):
    job_id: Optional[str] = Field(
        None,
        description="Job ID mới cần kích hoạt. Truyền null hoặc chuỗi rỗng để xóa giới hạn.",
    )


# ==========================================
# 4. LỚP DỊCH VỤ (SERVICES)
# ==========================================
class TelegramService:
    @staticmethod
    async def send_message(message: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning(
                "Chưa cấu hình Telegram. Hệ thống sẽ bỏ qua bước gửi tin nhắn."
            )
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                logger.info("Đã gửi thông báo đến Telegram thành công.")
            except Exception as e:
                logger.error(f"Lỗi hệ thống khi gửi tin nhắn Telegram: {str(e)}")


class KaggleService:
    @staticmethod
    def trigger_next_notebook(notebook_ref: str):
        try:
            username = notebook_ref.split("/")[0]

            if username not in KAGGLE_ACCOUNTS:
                logger.error(
                    f"Hủy lệnh chạy {notebook_ref}: Không tìm thấy API Key cho tài khoản [{username}]."
                )
                return

            logger.info(
                f"Đang sử dụng tài khoản [{username}] để kích hoạt notebook: {notebook_ref}"
            )

            isolated_env = os.environ.copy()
            isolated_env["KAGGLE_USERNAME"] = username
            isolated_env["KAGGLE_KEY"] = KAGGLE_ACCOUNTS[username]
            # Tắt SyntaxWarning từ thư viện kaggle (Python 3.12) qua biến môi trường
            isolated_env["PYTHONWARNINGS"] = "ignore"

            folder_name = notebook_ref.replace("/", "_")
            folder_path = BASE_DIR / "tmp" / folder_name
            os.makedirs(folder_path, exist_ok=True)

            # --- Bước 1: Pull metadata (-m) để lấy kernel-metadata.json ---
            pull_meta_cmd = [
                "kaggle",
                "kernels",
                "pull",
                notebook_ref,
                "-p",
                str(folder_path),
                "-m",
            ]
            pull_meta_result = subprocess.run(
                pull_meta_cmd, env=isolated_env, capture_output=True, text=True
            )
            real_stderr_meta = "\n".join(
                line
                for line in pull_meta_result.stderr.splitlines()
                if "SyntaxWarning" not in line and "invalid escape sequence" not in line
            ).strip()
            if pull_meta_result.returncode != 0:
                logger.error(
                    f"Lỗi khi pull metadata {notebook_ref}:\n"
                    f"  stderr: {real_stderr_meta}\n"
                    f"  stdout: {pull_meta_result.stdout.strip()}"
                )
                return
            if real_stderr_meta:
                logger.warning(
                    f"Pull metadata [{notebook_ref}] stderr (non-fatal): {real_stderr_meta}"
                )
            logger.info(
                f"Pull metadata [{notebook_ref}] stdout: {pull_meta_result.stdout.strip()}"
            )

            # --- Bước 2: Pull notebook (không -m) để lấy file .ipynb ---
            pull_nb_cmd = [
                "kaggle",
                "kernels",
                "pull",
                notebook_ref,
                "-p",
                str(folder_path),
            ]
            pull_nb_result = subprocess.run(
                pull_nb_cmd, env=isolated_env, capture_output=True, text=True
            )
            real_stderr_nb = "\n".join(
                line
                for line in pull_nb_result.stderr.splitlines()
                if "SyntaxWarning" not in line and "invalid escape sequence" not in line
            ).strip()
            if pull_nb_result.returncode != 0:
                logger.error(
                    f"Lỗi khi pull notebook {notebook_ref}:\n"
                    f"  stderr: {real_stderr_nb}\n"
                    f"  stdout: {pull_nb_result.stdout.strip()}"
                )
                return
            if real_stderr_nb:
                logger.warning(
                    f"Pull notebook [{notebook_ref}] stderr (non-fatal): {real_stderr_nb}"
                )
            logger.info(
                f"Pull notebook [{notebook_ref}] stdout: {pull_nb_result.stdout.strip()}"
            )

            metadata_path = folder_path / "kernel-metadata.json"
            if metadata_path.exists():
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                if meta.get("machine_shape") == "None":
                    meta["machine_shape"] = None
                meta["enable_internet"] = True
                metadata_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                logger.info(f"Đã chuẩn hóa kernel-metadata.json cho {notebook_ref}")

            # --- Bước 3: Push để kích hoạt notebook chạy lại ---
            push_cmd = ["kaggle", "kernels", "push", "-p", str(folder_path)]
            push_result = subprocess.run(
                push_cmd, env=isolated_env, capture_output=True, text=True
            )
            real_stderr_push = "\n".join(
                line
                for line in push_result.stderr.splitlines()
                if "SyntaxWarning" not in line and "invalid escape sequence" not in line
            ).strip()
            if push_result.returncode != 0:
                logger.error(
                    f"Lỗi hệ thống khi gửi lệnh chạy {notebook_ref}:\n"
                    f"  stderr: {real_stderr_push}\n"
                    f"  stdout: {push_result.stdout.strip()}"
                )
                return
            if real_stderr_push:
                logger.warning(
                    f"Push [{notebook_ref}] stderr (non-fatal): {real_stderr_push}"
                )
            logger.info(f"Push [{notebook_ref}] stdout: {push_result.stdout.strip()}")

            logger.info(
                f"Đã kích hoạt thành công tiến trình thực thi cho notebook: {notebook_ref}"
            )

        except Exception as e:
            logger.error(
                f"Phát hiện lỗi ngoại lệ khi xử lý notebook [{notebook_ref}]: {str(e)}"
            )
        finally:
            if "folder_path" in locals() and folder_path.exists():
                shutil.rmtree(folder_path, ignore_errors=True)
                logger.info(f"Đã dọn dẹp thư mục tạm thời: {folder_path.name}")


# ==========================================
# 5. KHỞI TẠO ỨNG DỤNG & CƠ CHẾ XÁC THỰC
# ==========================================
app = FastAPI(title="Remote Notebook Coordinator", version="1.2.0")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

# Mount thư mục static để phục vụ CSS cho admin panel
_STATIC_DIR = BASE_DIR / "src" / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != SERVER_API_KEY:
        logger.warning(f"Cảnh báo bảo mật: Từ chối yêu cầu do API Key không hợp lệ.")
        raise HTTPException(
            status_code=403, detail="Khóa xác thực API không hợp lệ hoặc đã hết hạn"
        )
    return api_key


jobs_state: Dict[str, dict] = {}


# ==========================================
# 6. CÁC ĐIỂM CUỐI GIAO TIẾP (API ENDPOINTS)
# ==========================================
@app.post("/webhook/notebook", tags=["Integration Workflow"])
async def receive_notebook_webhook(
    payload: NotebookPayload,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key),
):
    logger.info(
        f"Tiếp nhận dữ liệu từ Job [{payload.job_id}] | Phân loại: {payload.notebook_index_type} | Trạng thái: {payload.status}"
    )

    # Kiểm tra job_id filter — từ chối nếu không khớp với active_job_id
    active_job_id = server_config.get("active_job_id")
    if active_job_id and payload.job_id != active_job_id:
        logger.warning(
            f"Từ chối request: Job ID [{payload.job_id}] không khớp với "
            f"active_job_id [{active_job_id}] đang được lưu trên server."
        )
        raise HTTPException(
            status_code=403,
            detail=f"Job ID không hợp lệ. Server hiện chỉ chấp nhận job_id: [{active_job_id}]",
        )

    # Gửi thông báo tức thì đến Telegram cho mọi payload nhận được
    notify_message = (
        f"📩 <b>[B6 Team - Tín hiệu Notebook đến server]</b>\n\n"
        f"Job ID    : <code>{payload.job_id}</code>\n"
        f"Loại      : <b>{payload.notebook_index_type.upper()}</b>\n"
        f"Trạng thái: <b>{payload.status.upper()}</b>"
    )
    background_tasks.add_task(TelegramService.send_message, notify_message)

    if payload.job_id not in jobs_state:
        jobs_state[payload.job_id] = {"status": "running", "history": []}
    jobs_state[payload.job_id]["history"].append(payload.dict())

    if payload.status == "completed" and payload.notebook_index_type in [
        "start",
        "mid",
    ]:
        if payload.next_notebook_ref:
            logger.info(
                f"Hệ thống sẽ thực hiện quá trình gọi ngầm notebook tiếp theo: {payload.next_notebook_ref}"
            )
            background_tasks.add_task(
                KaggleService.trigger_next_notebook, payload.next_notebook_ref
            )
        else:
            logger.warning(
                "Notebook báo cáo trạng thái 'completed' nhưng lại thiếu trường tham chiếu 'next_notebook_ref'."
            )

    elif payload.notebook_index_type == "end" and payload.progress == "done":
        logger.info(
            f"Ghi nhận hoàn tất toàn bộ chuỗi công việc của Job [{payload.job_id}]."
        )
        logger.info(
            f"Hệ thống sẽ thực hiện quá trình gửi thông báo tổng kết đến Telegram cho Job [{payload.job_id}]."
        )
        jobs_state[payload.job_id]["status"] = "finished"

        message = (
            f"🎉 <b>[B6 Team - Thông Báo Hệ Thống]</b>\n\n"
            f"Chuỗi Notebook mang mã định danh: <code>{payload.job_id}</code> đã được thực thi <b>HOÀN TẤT</b>.\n"
            f"Tiến độ tổng thể: <b>{payload.progress.upper()}</b>"
        )
        if payload.text_data:
            message += f"\nDữ liệu đính kèm từ notebook: {payload.text_data}"
        background_tasks.add_task(TelegramService.send_message, message)

    return {
        "message": "Dữ liệu tín hiệu đã được máy chủ tiếp nhận thành công",
        "job_id": payload.job_id,
    }


@app.get("/healthcheck", tags=["System Monitoring"])
async def healthcheck():
    """
    Điểm cuối (Endpoint) kiểm tra tình trạng hoạt động của máy chủ.
    - Trả về thời gian hiện tại theo chuẩn ISO 8601.
    - Dùng để các công cụ bên thứ 3 (như UptimeRobot) ping giữ máy chủ luôn thức.
    """
    current_time_iso = datetime.now(timezone.utc).isoformat()
    logger.info("Healthcheck pinged. Hệ thống hoạt động bình thường.")
    return {"name": "healthcheck response", "timestamp": current_time_iso}


# ==========================================
# 7. ADMIN PANEL
# ==========================================
@app.get("/admin/manage", response_class=HTMLResponse, include_in_schema=False)
async def admin_manage():
    """Trả về trang HTML cho Admin Panel."""
    html_path = BASE_DIR / "src" / "templates" / "admin.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/admin/api/logs", response_class=PlainTextResponse, include_in_schema=False)
async def admin_get_logs():
    """Trả về toàn bộ nội dung file runtime.log dưới dạng plain text."""
    if not _LOG_FILE_PATH.exists():
        return PlainTextResponse("")
    return PlainTextResponse(_LOG_FILE_PATH.read_text(encoding="utf-8"))


@app.get("/admin/api/logs/download", include_in_schema=False)
async def admin_download_logs():
    """Tải xuống file runtime.log."""
    if not _LOG_FILE_PATH.exists():
        raise HTTPException(status_code=404, detail="File log chưa tồn tại.")
    return FileResponse(
        path=str(_LOG_FILE_PATH),
        filename="runtime.log",
        media_type="text/plain",
    )


@app.get("/admin/api/config", include_in_schema=False)
async def admin_get_config():
    """Trả về cấu hình hiện tại của server (active_job_id)."""
    return server_config


@app.post("/admin/api/config/job-id", include_in_schema=False)
async def admin_update_job_id(payload: UpdateJobIdPayload):
    """Cập nhật active_job_id. Truyền null hoặc chuỗi rỗng để xóa giới hạn."""
    global server_config
    new_job_id = payload.job_id.strip() if payload.job_id else None
    server_config["active_job_id"] = new_job_id or None
    _save_config(server_config)
    logger.info(
        f"[Admin] Đã cập nhật active_job_id thành: {server_config['active_job_id']!r}"
    )
    return {
        "message": "Cập nhật cấu hình thành công.",
        "active_job_id": server_config["active_job_id"],
    }
