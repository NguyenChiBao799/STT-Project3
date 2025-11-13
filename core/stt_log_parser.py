# core/stt_log_parser.py
from typing import Dict, Any


class STTLogParser:
    """
    Chuyển đổi JSON output từ backend STT sang JSON chuẩn cho LogicManager.
    Dữ liệu đầu vào dạng:
    {
        "session_id": "...",
        "text_response": {
            "user_text": "[NO SPEECH DETECTED]",
            "bot_text": "..."
        }
    }
    """

    def __init__(self, log_callback=print):
        self.log = log_callback

    def convert(self, raw_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trả về JSON chuẩn:
        {
            "text": "...",
            "intent": "...",
            "entities": {},
            "db_result": {}
        }
        """

        text_resp = raw_json.get("text_response", {})
        user_text = text_resp.get("user_text", "").strip()

        # =================================================
        # 1) Không phát hiện giọng nói
        # =================================================
        if "[NO SPEECH DETECTED]" in user_text or user_text == "":
            self.log("[Parser] Không phát hiện tiếng nói → fallback_no_speech", "yellow")
            return {
                "text": "",
                "intent": "fallback_no_speech",
                "entities": {},
                "db_result": {}
            }

        # =================================================
        # 2) Có text từ giọng nói
        #    Tạm thời gán intent = no_match
        #    Khi có NLU thật thì thay block này
        # =================================================
        self.log(f"[Parser] User text nhận được: {user_text}", "cyan")

        detected_intent = "no_match"   # default, chờ module NLU thật

        return {
            "text": user_text,
            "intent": detected_intent,
            "entities": {},
            "db_result": {}
        }
