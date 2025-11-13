# core/json_loader.py
import os
import json
from typing import Optional, Dict, Any

# Thư mục chứa file JSON đầu vào của STT pipeline
TEMP_DIR = r"D:\STT Project\temp"


class JSONLogLoader:

    def __init__(self, log_callback=print):
        self.log = log_callback

    def load_latest_json(self) -> Optional[Dict[str, Any]]:
        """
        Đọc file JSON mới nhất trong thư mục temp.
        Trả về Dict hoặc None nếu không có file.
        """
        try:
            if not os.path.exists(TEMP_DIR):
                self.log(f"[JSON Loader] Thư mục không tồn tại: {TEMP_DIR}", "red")
                return None

            files = [
                f for f in os.listdir(TEMP_DIR)
                if f.lower().endswith(".json")
            ]

            if not files:
                self.log("[JSON Loader] Không tìm thấy file JSON nào trong thư mục temp.", "yellow")
                return None

            # Tìm file được cập nhật gần nhất
            latest_file = max(
                files,
                key=lambda f: os.path.getmtime(os.path.join(TEMP_DIR, f))
            )

            full_path = os.path.join(TEMP_DIR, latest_file)
            self.log(f"[JSON Loader] Đang load file mới nhất: {latest_file}", "cyan")

            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            self.log(f"[JSON Loader] Lỗi đọc JSON: {e}", "red")
            return None
