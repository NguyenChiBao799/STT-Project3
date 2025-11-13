# core/logic_manager.py

import json
from typing import Dict, Any

from core.json_loader import JSONLogLoader
from core.stt_log_parser import STTLogParser
from core.intent_whitelist import IntentWhitelist
from ai_modules.response_generator import ResponseGenerator


# -------------------------------------------------------
# File thanh toán đã upload sẵn trong static/
# -------------------------------------------------------
PAYMENT_PAGE_PATH = "/static/qr_payment_demo.html"


class LogicManager:

    def __init__(
        self,
        log_callback=print,
        response_config: Dict[str, Any] = None,
        llm_mode: str = "mock",
        tts_mode: str = "MOCK",
        db_mode: str = "MOCK",
        api_key: str = None
    ):
        self.log = log_callback
        self.state = "idle"
        self.response_config = response_config or {}

        # --------------------------------------------
        # Khởi tạo các module phụ
        # --------------------------------------------
        self.json_loader = JSONLogLoader(log_callback=self.log)
        self.parser = STTLogParser(log_callback=self.log)
        self.whitelist = IntentWhitelist(log_callback=self.log)

        # Response Generator
        self.response_gen = ResponseGenerator(
            log_callback=self.log,
            config=self.response_config,
            llm_mode=llm_mode,
            tts_mode=tts_mode,
            db_mode=db_mode,
            api_key=api_key
        )

        self.log("[LogicManager] Khởi tạo thành công.", "green")

    # ==========================================================
    # 🔥 Xử lý JSON từ NLU (đã convert xong)
    # ==========================================================
def handle_nlu_result(self, nlu_json: Dict[str, Any]) -> Dict[str, Any]:

    text = nlu_json.get("text", "")
    intent = nlu_json.get("intent", "no_match")
    entities = nlu_json.get("entities", {})
    db_result = nlu_json.get("db_result", {})

    # 1) Intent không thuộc whitelist
    if not self.whitelist.is_intent_supported(intent):
        return {
            "action": "fallback",
            "intent": "unsupported_topic",
            "bot_text": self.whitelist.get_unsupported_response(),
            "entities": entities,
            "db_result": db_result
        }

    # 2) Intent đặt hàng → mở QR payment
    if intent == "order_product":
        return {
            "action": "payment",
            "intent": "order_product",
            "bot_text": "Bạn có thể thanh toán ngay tại liên kết sau:",
            "payment_url": PAYMENT_PAGE_PATH,
            "entities": entities,
            "db_result": db_result
        }

    # 3) Intent hợp lệ → để DM tự tạo phản hồi
    return {
        "action": "normal",
        "intent": intent,
        "bot_text": None,   # DM sẽ tự dùng ResponseGenerator
        "entities": entities,
        "db_result": db_result
    }


    # ==========================================================
    # 🔥 Xử lý file JSON từ thư mục STT /temp
    # ==========================================================
    def handle_from_file(self) -> Dict[str, Any]:
        """Đọc JSON mới nhất trong D:\\STT Project\\temp rồi xử lý."""
        raw_json = self.json_loader.load_latest_json()
        if not raw_json:
            return {
                "type": "error",
                "response": "Không tìm thấy file JSON nào trong thư mục temp."
            }

        # Convert dạng STT → NLU chuẩn
        nlu_json = self.parser.convert(raw_json)

        # Chạy logic chính
        return self.handle_nlu_result(nlu_json)

    # ==========================================================
    # (Optional) Xử lý log dạng string JSON
    # ==========================================================
    def handle_stt_log(self, json_raw: str):
        """Nhận log STT dạng string, parse và trả về dict."""
        try:
            data = json.loads(json_raw)
            return self.parser.convert(data)
        except:
            self.log("[Logic] JSON log bị lỗi định dạng", "red")
            return None
