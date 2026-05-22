import os
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Literal, Optional, Dict

from fastapi import FastAPI, HTTPException, BackgroundTasks, Security, Depends
from fastapi.security import APIKeyHeader
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
# 2. CẤU HÌNH & GHI NHẬT KÝ (CONFIG & LOGGING)
# ==========================================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
logger = logging.getLogger("RemoteCoordinator")

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

            folder_name = notebook_ref.replace("/", "_")
            folder_path = BASE_DIR / "tmp" / folder_name
            os.makedirs(folder_path, exist_ok=True)

            pull_cmd = [
                "kaggle",
                "kernels",
                "pull",
                notebook_ref,
                "-p",
                str(folder_path),
                "-m",
            ]
            pull_result = subprocess.run(
                pull_cmd, env=isolated_env, capture_output=True, text=True
            )
            if pull_result.returncode != 0:
                logger.error(
                    f"Lỗi hệ thống khi kéo cấu hình {notebook_ref}: {pull_result.stderr}"
                )
                return

            push_cmd = ["kaggle", "kernels", "push", "-p", str(folder_path)]
            push_result = subprocess.run(
                push_cmd, env=isolated_env, capture_output=True, text=True
            )
            if push_result.returncode != 0:
                logger.error(
                    f"Lỗi hệ thống khi gửi lệnh chạy {notebook_ref}: {push_result.stderr}"
                )
                return

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
app = FastAPI(title="Remote Notebook Coordinator", version="1.1.0")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


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
        jobs_state[payload.job_id]["status"] = "finished"

        message = (
            f"🎉 <b>[B6 Team - Thông Báo Hệ Thống]</b>\n\n"
            f"Chuỗi Notebook mang mã định danh: <code>{payload.job_id}</code> đã được thực thi <b>HOÀN TẤT</b>.\n"
            f"Tiến độ tổng thể: <b>{payload.progress.upper()}</b>"
        )
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
    # Lấy thời gian UTC hiện tại và chuyển sang định dạng chuẩn ISO 8601
    current_time_iso = datetime.now(timezone.utc).isoformat()

    logger.info("Healthcheck pinged. Hệ thống hoạt động bình thường.")

    return {"name": "healthcheck response", "timestamp": current_time_iso}
