import json
from typing import Any, Dict, Optional, Callable

# Import đúng cấu trúc dự án
from core.nlu_connector import NLUModule
from core.db_connector import SystemIntegrationManager
from core.intent_whitelist import IntentWhitelist
from core.logic_manager import LogicManager
from ai_modules.response_generator import ResponseGenerator


class DialogManager:
    """
    Pipeline chính của hệ thống:
    - Nhận văn bản hoặc NLU JSON
    - Phân tích intent
    - Query DB
    - Gọi LogicManager
    - Sinh phản hồi bằng ResponseGenerator
    """

    def __init__(self, log_callback=print, api_key=None, mode="normal"):
        # Logging
        self._log = log_callback or (lambda *args, **kwargs: None)

        # Chế độ chạy
        self.mode = mode
        self._log(f"[DM] Khởi tạo chế độ: {self.mode}")

        # API key cho NLU/LLM/TTS
        self.api_key = api_key

        # State ban đầu
        self.state = "START"

        # Scenario
        self.scenarios = {}
        self.current_scenario = None
        self.current_step_index = 0

        self._log(f"[DM] State ban đầu: {self.state}")

        # Whitelist
        self.whitelist = IntentWhitelist(self._log)

        # DB connector
        self.db = SystemIntegrationManager("MOCK", self._log)

        # NLU module
        self.nlu = NLUModule(
            mode="LLM",
            api_key=self.api_key,
            log_callback=self._log,
        )

        # Response generator
        self.rg = ResponseGenerator(
            log_callback=self._log,
            config=self.scenarios,
            llm_mode="LLM",
            tts_mode="LLM",
            db_mode="LLM",
            api_key=self.api_key
        )

        # Sync API key nếu RG có shared variable
        if hasattr(self.rg, "api_key_var"):
            self.rg.api_key_var.value = self.api_key
            self._log(f"[DM] Sync API key vào RG: {self.api_key}")

    # ======================================================================
    #      HÀM TRUNG TÂM – BACKEND RTC GỌI Ở MỌI NƠI
    # ======================================================================
    def process_with_logic_manager(
        self,
        logic_manager,
        user_text: Optional[str] = "",
        nlu_json: Optional[Dict[str, Any]] = None,
        wav_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        self._log(f"[DM] Nhận user_text: {user_text}")

        # --------------------------
        # 1) ƯU TIÊN NLU JSON (từ ASR/RTC)
        # --------------------------
        if nlu_json:
            self._log(f"[DM] Nhận nlu_json từ backend: {nlu_json}")
            intent = nlu_json.get("intent", "no_match")
            entities = nlu_json.get("entities", {})

        else:
            if user_text is None:
                user_text = ""
            nlu_result = self.nlu.get_intent(user_text, context)
            intent = nlu_result.get("intent", "no_match")
            entities = nlu_result.get("entities", {})

        # --------------------------
        # 2) DB Query
        # --------------------------
        try:
            db_result = self.db.query_data(intent, entities)
        except Exception as e:
            self._log(f"[DM] DB lỗi: {e}")
            db_result = {}

        # --------------------------
        # 3) Logic Manager
        # --------------------------
        try:
            logic_result = logic_manager.decide_action(intent, entities)
        except Exception as e:
            self._log(f"[DM] LogicManager lỗi: {e}")
            logic_result = {"bot_text": "Xin lỗi, hệ thống gặp sự cố."}

        # --------------------------
        # 4) Response Generator
        # --------------------------
        response_text = self.rg.generate(
            intent=intent,
            entities=entities,
            db_data=db_result,
            logic_data=logic_result,
            state=self.state,
            scenario=self.current_scenario,
            step_index=self.current_step_index,
            api_key=self.api_key,
            history=[],
        )

        self._log(f"[DM] Phản hồi cuối: {response_text}")

        # --------------------------
        # 5) RETURN OBJECT (KHÔNG TRẢ STRING NỮA)
        # --------------------------
        return {
            "response_text": response_text,
            "intent": intent,
            "entities": entities,
            "db_result": db_result,
            "logic_result": logic_result,
            "state": self.state,
            "scenario": self.current_scenario,
            "step_index": self.current_step_index
        }


# ======================================================================
#  Helper backend dùng
# ======================================================================
def create_dialog_manager(log_callback, api_key=None, mode="normal"):
    return DialogManager(
        log_callback=log_callback,
        api_key=api_key,
        mode=mode,
    )
