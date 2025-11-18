# Patched LogicManager with JSON log analysis + auto open order link
# (Replace your existing logic_manager.py with this version)

import json
from typing import Dict, Any

from core.json_loader import JSONLogLoader
from core.stt_log_parser import STTLogParser
from core.intent_whitelist import IntentWhitelist
from ai_modules.response_generator import ResponseGenerator

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
        self.api_key = api_key
        self.log = log_callback
        self.state = "idle"
        self.response_config = response_config or {}

        self.json_loader = JSONLogLoader(log_callback=self.log)
        self.parser = STTLogParser(log_callback=self.log)
        self.whitelist = IntentWhitelist(log_callback=self.log)

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
    # Xử lý JSON từ NLU
    # ==========================================================
    def handle_nlu_result(self, nlu_json: Dict[str, Any]) -> Dict[str, Any]:

        text = nlu_json.get("text", "")
        intent = nlu_json.get("intent", "no_match")
        entities = nlu_json.get("entities", {})
        db_result = nlu_json.get("db_result", {})

        # Intent không hợp lệ
        if not self.whitelist.is_intent_supported(intent):
            return {
                "action": "fallback",
                "intent": "unsupported_topic",
                "bot_text": self.whitelist.get_unsupported_response(),
                "entities": entities,
                "db_result": db_result
            }

        # Intent đặt hàng → mở link payment
        if intent == "order_product":
            return {
                "action": "payment",
                "intent": "order_product",
                "bot_text": "Hệ thống đã mở trang thanh toán.",
                "payment_url": PAYMENT_PAGE_PATH,
                "entities": entities,
                "db_result": db_result
            }

        # Intent hợp lệ → để DM xử lý
        return {
            "action": "normal",
            "intent": intent,
            "bot_text": None,
            "entities": entities,
            "db_result": db_result
        }

    # ==========================================================
    # Xử lý file JSON (STT)
    # ==========================================================
    def handle_from_file(self) -> Dict[str, Any]:
        raw_json = self.json_loader.load_latest_json()
        if not raw_json:
            return {
                "type": "error",
                "response": "Không tìm thấy file JSON nào trong thư mục temp."
            }

        nlu_json = self.parser.convert(raw_json)
        return self.handle_nlu_result(nlu_json)

    # ==========================================================
    # Xử lý log string JSON trực tiếp
    # ==========================================================
    def handle_stt_log(self, json_raw: str):
        try:
            data = json.loads(json_raw)
            nlu_json = self.parser.convert(data)
            return self.handle_nlu_result(nlu_json)
        except Exception as e:
            self.log(f"[Logic] JSON log lỗi định dạng: {e}", "red")
            return {
                "type": "error",
                "response": "JSON log không hợp lệ."
            }
        
    # ==========================================================
    # API tương thích cho DialogManager (DM gọi decide_action)
    # ==========================================================
    def decide_action(self, intent: str, entities: Dict[str, Any]):
        """
        Hàm adapter để LogicManager tương thích với DialogManager.
        Dựa vào intent + entities để quyết định action,
        mapping về handle_nlu_result() để tái sử dụng logic gốc.
        """
        try:
            # Tạo cấu trúc NLU JSON tối thiểu
            nlu_json = {
                "text": "",
                "intent": intent,
                "entities": entities,
                "db_result": {}
            }
            return self.handle_nlu_result(nlu_json)

        except Exception as e:
            self.log(f"[LogicManager] decide_action error: {e}", "red")
            return {
                "action": "error",
                "error": str(e),
                "intent": intent,
                "entities": entities
            }
