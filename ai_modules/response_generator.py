import time
import os
import random
import threading
from typing import Optional, Dict, Any, List, Callable, Literal, AsyncGenerator
import wave

_FALLBACK_API_KEY = "MOCK_API_KEY"

try:
    from config_db import GEMINI_MODEL, TTS_MODE_DEFAULT, TTS_VOICE_NAME_DEFAULT, API_KEY
except ImportError:
    GEMINI_MODEL = "gemini-2.5-flash"
    TTS_MODE_DEFAULT = "MOCK"
    TTS_VOICE_NAME_DEFAULT = "vi"
    API_KEY = _FALLBACK_API_KEY

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

# ========================================================
# TTS BASE + MOCK
# ========================================================

class BaseTTS:
    def __init__(self, log_callback: Callable):
        self.log = log_callback
        self.is_ready = True

    def generate(self, text: str, output_path: str) -> Optional[str]:
        try:
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b'\x00\x00' * 16000)
            self.log(f"🎵 [TTS Mock] Đã tạo file audio giả lập: {os.path.basename(output_path)}")
            return output_path
        except Exception as e:
            self.log(f"❌ [TTS Mock] Lỗi: {e}")
            return None

    def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        async def mock_stream():
            yield b"M1"
            yield b"M2"
            yield b"M3"
        return mock_stream()


class MockTTS(BaseTTS):
    pass


# ========================================================
# RESPONSE GENERATOR
# ========================================================

class ResponseGenerator:
    def __init__(self, log_callback: Callable, config: Dict[str, Any],
                 llm_mode: str, tts_mode: str, db_mode: str, api_key: str):

        self.log = log_callback
        self.config = config
        self.llm_mode = llm_mode
        self.tts_mode = tts_mode
        self.db_mode = db_mode

        self.api_key_var = threading.local()

        # ƯU TIÊN API KEY TỪ BACKEND
        if api_key and api_key != _FALLBACK_API_KEY:
            self.api_key_var.value = api_key
        else:
            self.api_key_var.value = API_KEY

        self.log(f"[RG] API KEY INIT = {self.api_key_var.value}")

        self._initialize_tts_client()

    # ========================================================
    # INIT TTS
    # ========================================================
    def _initialize_tts_client(self):
        mode = (self.tts_mode or "").upper()

        if mode == "MOCK":
            self.tts_client = MockTTS(self.log)
            self.log("🎵 [TTS] Dùng MOCK.")
            return

        # fallback
        self.log(f"⚠️ [TTS] Mode '{self.tts_mode}' không hỗ trợ → chuyển MOCK.")
        self.tts_client = MockTTS(self.log)

    # ========================================================
    # RULE-BASED RESPONSE
    # ========================================================
    def _generate_with_rules(self, intent: str) -> Optional[str]:
        rules = self.config.get("rules", [])
        for rule in rules:
            if rule["intent"] == intent:
                responses = rule.get("responses", [rule.get("response")])
                return random.choice(responses)

        # fallback rule no_match
        if intent != "no_match":
            return self._generate_with_rules("no_match")

        return None

    # ========================================================
    # DB-BASED RESPONSE
    # ========================================================
    def _generate_with_db_info(self, intent: str, db_result: Dict[str, Any]) -> Optional[str]:
        customer = db_result.get("customer_data")
        product = db_result.get("product_data")

        if intent == "query_customer_info" and customer:
            return f"Khách hàng: {customer['customer_name']} — Lần đặt gần nhất: {customer['last_order']}."

        if intent == "query_product_info" and product:
            discount = product.get("discount")
            if discount and int(discount) > 0:
                return f"Sản phẩm {product['product_name']} giá {product['price']} — Giảm {discount}%."
            return f"Sản phẩm {product['product_name']} giá {product['price']} — Không giảm giá."

        return None

    # ========================================================
    # MOCK LLM
    # ========================================================
    def _generate_with_llm_mock(self, ctx: Dict[str, Any]) -> str:
        key = getattr(self.api_key_var, "value", None)

    # Nếu không có API key → phản hồi rõ ràng, KHÔNG rỗng
        if not key or key == _FALLBACK_API_KEY:
            return (
                f"Tôi chưa có API key để sinh câu trả lời thông minh. "
                f"Nhưng tôi vẫn có thể giúp bạn. Bạn đang muốn hỏi điều gì?"
            )

        # Nếu user_text rỗng → tự sinh câu trả lời fallback
        if not ctx.get("user_text"):
            return (
                "Tôi chưa nghe rõ bạn nói gì. "
                "Bạn có thể nói lại một lần nữa không?"
            )

        # Mock LLM tử tế
        return (
            f"Tôi hiểu bạn đang nói: '{ctx['user_text']}'. "
            f"Nhưng hiện tôi đang ở chế độ mô phỏng LLM."
        )


    # ========================================================
    # RESPONSE ENGINE
    # ========================================================
    def generate_response(
        self,
        user_text: str,
        intent: str,
        entities: Dict[str, Any],
        db_result: Dict[str, Any],
        current_state: str,
        history: List[Dict[str, str]] = []
    ) -> str:

        # RULE ENGINE
        rule = self._generate_with_rules(intent)
        if rule:
            return rule

        # DB ENGINE
        db_resp = self._generate_with_db_info(intent, db_result)
        if db_resp:
            return db_resp

        # Nếu intent = no_match → có câu trả lời riêng
        if intent == "no_match":
            return (
                "Xin lỗi, tôi chưa hiểu ý bạn. "
                "Bạn có thể nói rõ hơn không?"
            )

        # LLM fallback
        ctx = {
            "user_text": user_text,
            "intent": intent,
            "entities": entities,
            "db_result": db_result,
            "current_state": current_state,
            "history": history,
        }

        return self._generate_with_llm_mock(ctx)


    # ========================================================
    # ADAPTER CHO DIALOG MANAGER
    # ========================================================
    def generate(
        self,
        intent: str,
        entities: Dict[str, Any],
        db_data: Dict[str, Any],
        logic_data: Dict[str, Any],
        state: str,
        scenario: str,
        step_index: int,
        api_key: str,
        history: List[Dict[str, str]] = []
    ) -> str:

        # Update API KEY mỗi lần sinh response
        if api_key and api_key != _FALLBACK_API_KEY:
            self.api_key_var.value = api_key

        self.log(f"[RG] API KEY ACTIVE = {self.api_key_var.value}")

        # Nếu logic_manager đã trả bot_text → dùng luôn
        if logic_data and logic_data.get("bot_text"):
            return logic_data["bot_text"]

        user_text = logic_data.get("user_text", "") if logic_data else ""

        return self.generate_response(
            user_text=user_text,
            intent=intent,
            entities=entities,
            db_result=db_data,
            current_state=state,
            history=history,
        )
