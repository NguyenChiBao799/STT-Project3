import os
import sqlite3
from pathlib import Path

# ======================================================
# CLASS CẤU HÌNH TỔNG HỢP: ConfigDB
# ======================================================
class ConfigDB:
    # --- CẤU HÌNH CHUNG CỦA DỰ ÁN ---
    PROJECT_NAME = "STT Project - Payment System"
    DB_NAME = "payment.db"
    DB_FOLDER = "core"
    DB_PATH = os.path.join(DB_FOLDER, DB_NAME)

    # --- CẤU HÌNH KẾT NỐI SQLITE ---
    SQLITE_PRAGMA_SETTINGS = [
        ("journal_mode", "WAL"),       # Ghi nhật ký WAL để tăng tốc
        ("synchronous", "NORMAL"),     # Giảm độ trễ I/O
        ("temp_store", "MEMORY"),      # Tạm lưu trong RAM
    ]

    # --- CẤU HÌNH BẢNG CƠ BẢN ---
    PAYMENT_TABLE_NAME = "payments"
    TABLE_SCHEMA = f"""
        CREATE TABLE IF NOT EXISTS {PAYMENT_TABLE_NAME} (
            order_id TEXT PRIMARY KEY,
            amount INTEGER NOT NULL,
            description TEXT NOT NULL,
            customer_info TEXT,
            status TEXT DEFAULT 'PENDING',
            qr_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """

    # --- CẤU HÌNH MẶC ĐỊNH CHO QR PAYMENT ---
    QR_STORAGE_DIR = "static/payments"
    QR_FILE_EXTENSION = ".png"
    QR_TEXT_TEMPLATE = (
        "Thanh toán đơn hàng: {order_id}\n"
        "Số tiền: {amount:,} VND\n"
        "Nội dung: {description}\n"
        "Khách hàng: {customer_info}"
    )

    # --- CẤU HÌNH LOGGING ---
    LOG_FILE_PATH = os.path.join(DB_FOLDER, "payment.log")
    ENABLE_CONSOLE_LOG = True


# ======================================================
# HÀM KHỞI TẠO VÀ QUẢN LÝ DATABASE
# ======================================================

def init_db():
    """
    Khởi tạo cơ sở dữ liệu SQLite và bảng thanh toán.
    Nếu DB hoặc bảng chưa tồn tại, tự động tạo mới.
    """
    os.makedirs(ConfigDB.DB_FOLDER, exist_ok=True)
    conn = sqlite3.connect(ConfigDB.DB_PATH)
    c = conn.cursor()
    c.execute(ConfigDB.TABLE_SCHEMA)
    conn.commit()

    # Áp dụng các thiết lập PRAGMA để tối ưu
    for key, value in ConfigDB.SQLITE_PRAGMA_SETTINGS:
        try:
            c.execute(f"PRAGMA {key}={value}")
        except Exception as e:
            if ConfigDB.ENABLE_CONSOLE_LOG:
                print(f"[ConfigDB] ⚠️ PRAGMA {key} lỗi: {e}")

    conn.close()
    if ConfigDB.ENABLE_CONSOLE_LOG:
        print(f"[ConfigDB] ✅ Database sẵn sàng tại: {ConfigDB.DB_PATH}")


def get_connection():
    """
    Lấy kết nối SQLite đang hoạt động.
    Đảm bảo DB được khởi tạo trước khi mở kết nối.
    """
    init_db()
    return sqlite3.connect(ConfigDB.DB_PATH)


# ======================================================
# HÀM GHI LOG (CHO QR PAYMENT)
# ======================================================

def log_event(message: str):
    """
    Ghi log ra file và console (nếu bật).
    """
    from datetime import datetime
    os.makedirs(os.path.dirname(ConfigDB.LOG_FILE_PATH), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"
    with open(ConfigDB.LOG_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(log_line)
    if ConfigDB.ENABLE_CONSOLE_LOG:
        print(log_line.strip())


# ======================================================
# HẰNG SỐ XUẤT KHẨU (EXPORTING FOR DIRECT IMPORT)
# ======================================================
PROJECT_NAME = ConfigDB.PROJECT_NAME
DB_PATH = ConfigDB.DB_PATH
DB_NAME = ConfigDB.DB_NAME
DB_FOLDER = ConfigDB.DB_FOLDER
PAYMENT_TABLE_NAME = ConfigDB.PAYMENT_TABLE_NAME
QR_STORAGE_DIR = ConfigDB.QR_STORAGE_DIR
QR_FILE_EXTENSION = ConfigDB.QR_FILE_EXTENSION
QR_TEXT_TEMPLATE = ConfigDB.QR_TEXT_TEMPLATE
LOG_FILE_PATH = ConfigDB.LOG_FILE_PATH
ENABLE_CONSOLE_LOG = ConfigDB.ENABLE_CONSOLE_LOG
