import json
from typing import Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
import google.generativeai as genai


# ========================================================
# Interface chung
# ========================================================

class INLUClient(ABC):
    @abstractmethod
    def get_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pass


# ========================================================
# Mock NLU
# ========================================================

class NLUClientMock(INLUClient):
    def __init__(self, log_callback: Callable, config=None):
        self._log = log_callback
        self._log("⚠️ [NLU] Dùng MOCK.")

    def get_intent(self, text: str, context=None):
        self._log(f"[NLU MOCK] Nhận: {text}")
        return {"intent": "no_match", "confidence": 0.0, "entities": {}}


# ========================================================
# Gemini LLM NLU
# ========================================================

class NLUClientLLM(INLUClient):
    def __init__(self, log_callback: Callable, api_key: str):
        self._log = log_callback

        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel("gemini-pro")
            self._log("🧠 [NLU] Dùng Gemini Pro.")
        except Exception as e:
            self._log(f"❌ [NLU Gemini ERROR] {e}")
            self.model = None

    def get_intent(self, text: str, context=None):
        if not self.model:
            return {"intent": "no_match", "confidence": 0.0, "entities": {}}

        prompt = f"""
        Phân tích câu sau và trả về JSON:
        {{
            "intent": "ten_intent",
            "confidence": 0.0,
            "entities": {{}}
        }}
        Câu: "{text}"
        """

        try:
            raw = self.model.generate_content(prompt).text.strip()
            return json.loads(raw)
        except Exception as e:
            self._log(f"❌ [NLU Gemini ERROR] {e}")
            return {"intent": "no_match", "confidence": 0.0, "entities": {}}


# ========================================================
# Factory
# ========================================================

def NLUClientFactory(mode: str, log_callback: Callable, api_key=None):
    mode = (mode or "").upper()

    if mode == "MOCK":
        return NLUClientMock(log_callback)

    if mode == "LLM":
        return NLUClientLLM(log_callback, api_key)

    log_callback(f"⚠️ [NLU] Mode không hỗ trợ: {mode}, dùng MOCK")
    return NLUClientMock(log_callback)


# ========================================================
# ⚡⚡ CLASS QUAN TRỌNG NHẤT — GIỮ NGUYÊN IMPORT GỐC ⚡⚡
# ========================================================

class NLUModule:
    """Wrapper chuẩn hóa theo kiến trúc ban đầu của dự án."""
    def __init__(self, mode="MOCK", api_key=None, log_callback=print):
        self._log = log_callback
        self.mode = mode
        self.api_key = api_key

        self._log(f"[NLUModule] Init mode = {self.mode}")

        self.client = NLUClientFactory(
            mode=self.mode,
            log_callback=self._log,
            api_key=self.api_key
        )

    def get_intent(self, text: str, context=None):
        return self.client.get_intent(text, context)
