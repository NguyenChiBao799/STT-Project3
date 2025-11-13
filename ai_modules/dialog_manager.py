import time
import uuid
import random
import os
import threading
import traceback
from typing import Dict, Any, Tuple, List, Optional, Callable, Literal
import wave 

_FALLBACK_API_KEY = "MOCK_API_KEY"
_FALLBACK_CONFIG = {"rules": []}

# =====================================================
# MOCK NLU (fallback)
# =====================================================
class NLUModule:
    def __init__(self, mode: str, api_key: str, log_callback: Callable):
        self.mode = mode
        self.log = log_callback
        self.log(f"⚠️ [NLU] Sử dụng NLU Module MOCK (fallback).", "orange")
        
    def run_nlu(self, text: str) -> Dict[str, Any]:
         if "chào" in text.lower():
             return {"intent": "chao_hoi", "entities": {"chao": "xin chào"}, "confidence": 0.95}
         return {"intent": "no_match", "entities": {}, "confidence": 0.1}

# =====================================================
# MOCK INTENT WHITELIST
# =====================================================
class IntentWhitelist:
    def __init__(self, log_callback: Callable):
        self.log = log_callback
        self.log(f"⚠️ [Whitelist] Sử dụng IntentWhitelist MOCK.", "orange")
    def is_intent_supported(self, intent: str) -> bool: return True
    def get_unsupported_response(self) -> str: return "Lỗi: Intent Whitelist không hoạt động (Mock)."


try:
    # ❗ FIX: GỠ API_KEY khỏi import → vì API key đến từ Web, không phải config
    from core.config_db import (
        NLU_CONFIDENCE_THRESHOLD, NLU_MODE_DEFAULT,
        DB_MODE_DEFAULT, TTS_MODE_DEFAULT, LLM_MODE_DEFAULT,
        SCENARIOS_CONFIG, INITIAL_STATE, GEMINI_MODEL
    )

    from ai_modules.response_generator import ResponseGenerator
    from core.db_connector import SystemIntegrationManager
    from core.nlu_connector import NLU_CONFIG
    from core.intent_whitelist import IntentWhitelist

except ImportError as e:
    class DefaultConfig:
        NLU_CONFIDENCE_THRESHOLD = 0.6
        NLU_MODE_DEFAULT = "MOCK"
        DB_MODE_DEFAULT = "MOCK"
        TTS_MODE_DEFAULT = "MOCK"
        LLM_MODE_DEFAULT = "MOCK"
        API_KEY = _FALLBACK_API_KEY   # fallback only
        SCENARIOS_CONFIG = _FALLBACK_CONFIG
        INITIAL_STATE = "START"
        GEMINI_MODEL = "gemini-2.5-flash"

    globals().update(DefaultConfig.__dict__)

    class ResponseGenerator:
        def __init__(self, log_callback: Callable, config: Dict[str, Any],
                     llm_mode: str, tts_mode: str, db_mode: str, api_key: str):
            self.log = log_callback
            self.log(f"⚠️ [RG Fallback] Sử dụng Response Generator Mock (vì lỗi import).", "orange")
            class MockTTSClient:
                def synthesize_stream(self, text: str):
                    async def mock_stream(): 
                        yield b'MOCK_AUDIO_CHUNK'
                    return mock_stream()
            self.tts_client = MockTTSClient()
            self.api_key_var = threading.local()
            self.api_key_var.value = api_key

    class SystemIntegrationManager:
        def __init__(self, db_mode: str, log_callback: Callable):
            self._log = log_callback
            self._log(f"⚠️ [DB] Sử dụng SystemIntegrationManager MOCK (vì lỗi import).")
        def query_data(self, intent: str, entities: Dict[str, Any]):
            return {"customer_data": None, "product_data": None}

    print(f"❌ [DM] LỖI IMPORT CONFIG/MODULE: {e}. Đang dùng chế độ Fallback/Mock.")
# ====================================================================
#  DIALOG MANAGER — FIXED VERSION (API_KEY runtime, không import config)
# ====================================================================

class DialogManager:
    """
    Điều phối toàn bộ quá trình hội thoại:
    - Nhận text từ LogicManager
    - Chạy NLU
    - Trả phản hồi qua ResponseGenerator
    - Điều khiển state hội thoại
    """

    def __init__(self, log_callback=print, api_key=None):
        self.log = log_callback or (lambda *args, **kwargs: None)

        # ❗ FIX: API_KEY lấy từ WEB/UI → truyền từ backend
        self.api_key = api_key or _FALLBACK_API_KEY

        # State hội thoại ban đầu
        try:
            self.state = globals().get("INITIAL_STATE", "START")
        except Exception:
            self.state = "START"

        # Load scenarios
        self.scenarios = globals().get("SCENARIOS_CONFIG", {})
        self.current_scenario = None
        self.current_step_index = 0

        self.log(f"[DM] Đã tải xong cấu hình. State ban đầu: {self.state}")

        # Khởi tạo Whitelist (real or mock)
        try:
            self.whitelist = IntentWhitelist(self.log)
        except Exception:
            self.whitelist = IntentWhitelist(self.log)

        # Khởi tạo SystemIntegrationManager (real or mock)
        try:
            self.db = SystemIntegrationManager(
                db_mode=globals().get("DB_MODE_DEFAULT", "MOCK"),
                log_callback=self.log
            )
        except Exception:
            self.db = SystemIntegrationManager("MOCK", self.log)

        # Khởi tạo NLU
        self.nlu = NLUModule(
            mode=globals().get("NLU_MODE_DEFAULT", "MOCK"),
            api_key=self.api_key,
            log_callback=self.log
        )

        # Khởi tạo ResponseGenerator
        try:
            self.rg = ResponseGenerator(
                log_callback=self.log,
                config=self.scenarios,
                llm_mode=globals().get("LLM_MODE_DEFAULT", "MOCK"),
                tts_mode=globals().get("TTS_MODE_DEFAULT", "MOCK"),
                db_mode=globals().get("DB_MODE_DEFAULT", "MOCK"),
                api_key=self.api_key,     # ❗ FIX: dùng key runtime
            )
        except Exception as e:
            self.log(f"⚠️ [DM] RG lỗi, fallback: {e}")
            self.rg = ResponseGenerator(
                log_callback=self.log,
                config=self.scenarios,
                llm_mode="MOCK",
                tts_mode="MOCK",
                db_mode="MOCK",
                api_key=self.api_key,
            )

    # -----------------------------------------------------------------
    # Cho backend gọi để set API_KEY của user
    # -----------------------------------------------------------------
    def set_api_key(self, key: str):
        self.api_key = key
        self.log(f"[DM] API Key đã cập nhật từ Web UI: {key}")

        # Update vào NLU + RG + DB nếu cần
        try:
            self.nlu.api_key = key
        except:
            pass

        try:
            self.rg.api_key_var.value = key
        except:
            pass

    # -----------------------------------------------------------------
    # Hàm xử lý hội thoại chính
    # -----------------------------------------------------------------
    def process_with_logic_manager(self, nlu_json: Dict[str, Any], logic_manager):
        """
        Nhận NLU JSON từ LogicManager → kết hợp DB → trả response_text
        Đây là hàm backend_webrtc_server gọi trong pipeline.
        """

        try:
            utterance = nlu_json.get("text", "")
            intent = nlu_json.get("intent", "")
            entities = nlu_json.get("entities", {})
            confidence = nlu_json.get("confidence", 1.0)

            # Check confidence
            threshold = globals().get("NLU_CONFIDENCE_THRESHOLD", 0.5)
            if confidence < threshold:
                self.log(f"[DM] NLU confidence thấp ({confidence}) → fallback", "yellow")
                return {
                    "response_text": "Mình nghe chưa rõ, bạn nói lại được không?",
                    "scenario": None,
                    "state": self.state
                }

            # Check whitelist
            if not self.whitelist.is_intent_supported(intent):
                self.log(f"[DM] Intent '{intent}' không trong whitelist", "orange")
                return {
                    "response_text": self.whitelist.get_unsupported_response(),
                    "scenario": None,
                    "state": self.state
                }

            # Query DB nếu intent cần
            db_result = self.db.query_data(intent, entities)

            # Gọi LogicManager xác định action
            logic_result = logic_manager.decide_action(intent, entities)

            # Tạo phản hồi
            response_text = self.rg.generate(
                intent=intent,
                entities=entities,
                db_data=db_result,
                logic_data=logic_result,
                state=self.state,
                scenario=self.current_scenario,
                step_index=self.current_step_index,
                api_key=self.api_key,
            )

            # Update scenario/state nếu cần
            if logic_result.get("next_state"):
                self.state = logic_result["next_state"]

            return {
                "response_text": response_text,
                "scenario": self.current_scenario,
                "state": self.state
            }

        except Exception as e:
            self.log(f"❌ [DM] Lỗi xử lý hội thoại: {e}", "red")
            traceback.print_exc()
            return {
                "response_text": "Lỗi hệ thống trong DialogManager.",
                "scenario": None,
                "state": self.state
            }
