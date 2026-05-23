import time
import requests
from datetime import datetime

# ==========================================
# CẤU HÌNH HỆ THỐNG
# ==========================================
# Đường dẫn trực tiếp đến API giám sát của máy chủ
HEALTHCHECK_URL = "https://b6-remote-server-kaggle-2026.onrender.com/healthcheck"

# Tần suất gửi yêu cầu (Tính bằng giây: 6 phút * 60 giây)
INTERVAL_SECONDS = 6 * 60


def ping_server():
    """Hàm thực hiện gửi yêu cầu HTTP GET đến máy chủ"""
    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"[{current_time}] Đang gửi yêu cầu đánh thức đến máy chủ...")

    try:
        # Thời gian chờ tối đa là 15 giây
        response = requests.get(HEALTHCHECK_URL, timeout=15)
        response.raise_for_status()

        # Đọc dữ liệu phản hồi (response) dạng JSON
        data = response.json()
        print(
            f"[{current_time}] THÀNH CÔNG: Máy chủ phản hồi ổn định - {data.get('timestamp')}"
        )

    except requests.exceptions.Timeout:
        print(
            f"[{current_time}] CẢNH BÁO: Máy chủ phản hồi quá chậm (Có thể đang khởi động lại từ trạng thái ngủ)."
        )
    except requests.exceptions.RequestException as e:
        print(
            f"[{current_time}] LỖI HỆ THỐNG: Không thể kết nối đến máy chủ. Chi tiết: {e}"
        )


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 KHỞI ĐỘNG TRÌNH GIỮ NHỊP (KEEP-ALIVE) CHO MÁY CHỦ RENDER")
    print(f"Mục tiêu giám sát : {HEALTHCHECK_URL}")
    print(f"Tần suất hoạt động: Mỗi {INTERVAL_SECONDS // 60} phút / lần")
    print("Nhấn tổ hợp phím [Ctrl + C] để dừng chương trình.")
    print("=" * 60 + "\n")

    try:
        # Vòng lặp vô hạn để chương trình chạy liên tục
        while True:
            ping_server()
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n[HỆ THỐNG] Đã nhận lệnh dừng từ người dùng. Đang tắt chương trình...")
