# D:\STT Project\core\tts_connector.py
import os
import asyncio
import traceback

# ================================================
#  TTS Client (MOCK / LOCAL / CLOUD)
# ================================================

class TTSClient:
    """
    TTSClient dùng cho ResponseGenerator:
      - synthesize_stream(text) → async generator (yield audio bytes)
      - mode = "MOCK" | "LOCAL" | "CLOUD"
    """

    def __init__(self, mode: str = "MOCK", api_key=None, log_callback=print):
        self.mode = (mode or "MOCK").upper()
        self.api_key = api_key
        self.log = log_callback or (lambda *args, **kwargs: None)

        self.log(f"[TTS] Khởi tạo TTSClient (mode={self.mode}).")

        # ----------------------------------------------------
        # Nếu chưa có API key → fallback hoàn toàn về MOCK
        # ----------------------------------------------------
        if self.mode != "MOCK" and not self.api_key:
            self.log("⚠️ [TTS] Không có API key. Tự động chuyển sang MOCK.", "orange")
            self.mode = "MOCK"

    # ===================================================================
    #  MOCK TTS — tạo audio giả để test pipeline WebRTC
    # ===================================================================
    async def _mock_tts_stream(self, text: str):
        """Stream audio giả (8 chunk)."""
        fake_audio = b"\x00\x11\x22\x33\x44\x55\x66\x77"
        for _ in range(8):
            yield fake_audio
            await asyncio.sleep(0.02)

    # ===================================================================
    #  LOCAL TTS (Silero) — offline
    # ===================================================================
    async def _local_tts_stream(self, text: str):
        try:
            import torch
            import numpy as np
            from TTS.api import TTS  # nếu bạn chưa cài TTS, để mode MOCK

            model = TTS("tts_models/en/ljspeech/tacotron2-DDC")
            wav = model.tts(text)
            audio_bytes = (np.array(wav) * 32767).astype(np.int16).tobytes()

            chunk_size = 16000  
            for i in range(0, len(audio_bytes), chunk_size):
                yield audio_bytes[i:i + chunk_size]
                await asyncio.sleep(0.01)
        except Exception as e:
            self.log(f"❌ [TTS Local] Lỗi: {e}. Fallback về MOCK.")
            async for chunk in self._mock_tts_stream(text):
                yield chunk

    # ===================================================================
    #  CLOUD TTS (OpenAI / Google / Gemini) — bạn sẽ bật sau
    # ===================================================================
    async def _cloud_tts_stream(self, text: str):
        self.log("⚠️ [TTS Cloud] Chưa cấu hình API cloud. Fallback MOCK.")
        async for chunk in self._mock_tts_stream(text):
            yield chunk

    # ===================================================================
    #  API CHÍNH — được gọi từ ResponseGenerator
    # ===================================================================
    async def synthesize_stream(self, text: str):
        """
        Trả về async generator stream audio theo mode.
        """
        try:
            if self.mode == "MOCK":
                return self._mock_tts_stream(text)

            if self.mode == "LOCAL":
                return self._local_tts_stream(text)

            if self.mode == "CLOUD":
                return self._cloud_tts_stream(text)

            # fallback
            self.log(f"⚠️ [TTS] Mode '{self.mode}' không hợp lệ. Fallback MOCK.")
            return self._mock_tts_stream(text)

        except Exception as e:
            self.log(f"❌ [TTS] Lỗi synthesize_stream: {e}\n{traceback.format_exc()}")
            return self._mock_tts_stream(text)
