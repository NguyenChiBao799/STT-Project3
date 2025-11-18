# ai_modules/rtc_integration_layer.py
import asyncio
import os
import json
import torch
import numpy as np
import soundfile as sf
import librosa
from pathlib import Path
from datetime import datetime
from gtts import gTTS
import tempfile
import traceback

import shutil
from pathlib import Path

silero_base = Path.home() / ".cache" / "torch" / "hub" / "snakers4-silero-vad_master" / "src" / "silero_vad"
local_utils_vad = Path(__file__).parent / "utils_vad.py"
target_utils_vad = silero_base / "utils_vad.py"

try:
    if local_utils_vad.exists() and silero_base.exists() and not target_utils_vad.exists():
        shutil.copyfile(local_utils_vad, target_utils_vad)
        print(f"[AUTO-FIX] Copied utils_vad.py → {target_utils_vad}")
except Exception as e:
    print(f"[AUTO-FIX ERROR] {e}")


# =========================================================
# 🔐 BỔ SUNG ĐỂ GIỮ NGUYÊN IMPORT CHO BACKEND
# =========================================================
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "LOCAL-STT-KEY")

# =========================================================
# LOGGING
# =========================================================
def _log_colored(msg: str, color="white"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# =========================================================
# GLOBAL CONFIG
# =========================================================
SAMPLE_RATE = 16000
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "base")

# =========================================================
# WHISPER INITIALIZATION
# =========================================================
try:
    import whisper
    _log_colored(f"[ASR] Đang tải Whisper model '{WHISPER_MODEL_NAME}' trên thiết bị {DEVICE}...", "yellow")
    WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME if WHISPER_MODEL_NAME else "base")
    WHISPER_MODEL = WHISPER_MODEL.to(DEVICE)
    WHISPER_IS_READY = True
    _log_colored(f"✅ Whisper model '{WHISPER_MODEL_NAME if WHISPER_MODEL_NAME else 'base'}' loaded.", "green")
except Exception as e:
    WHISPER_MODEL = None
    WHISPER_IS_READY = False
    _log_colored(f"❌ Không thể tải Whisper model: {e}", "red")

# ============================================================
# 🧠 SILERO VAD FIX – hỗ trợ đa phiên bản
# ============================================================

try:
    vad_load = torch.hub.load(repo_or_dir="snakers4/silero-vad", model="silero_vad", trust_repo=True)
    if isinstance(vad_load, tuple) and len(vad_load) == 2:
        VAD_MODEL, utils = vad_load
    else:
        VAD_MODEL = vad_load
        try:
            from silero_vad import utils as _vad_utils
            utils = _vad_utils
        except Exception as inner_e:
            utils = None
            print(f"[⚠️ VAD] Không thể import utils trực tiếp: {inner_e}")

    if isinstance(utils, tuple):
        try:
            if len(utils) > 0 and hasattr(utils[0], "get_speech_timestamps"):
                utils = utils[0]
                print("[FIX] Silero VAD: utils tuple → utils[0] (module hợp lệ).")
            else:
                from silero_vad import utils as _vad_utils
                utils = _vad_utils
                print("[FIX] Silero VAD: fallback import utils từ silero_vad.")
        except Exception as fix_e:
            print(f"[FIX ERROR] Không thể khởi tạo utils chính xác: {fix_e}")

    VAD_IS_READY = True
    print("[✅] Silero VAD loaded successfully (multi-version safe).")
except Exception as e:
    VAD_MODEL, utils = None, None
    VAD_IS_READY = False
    print(f"[❌] Lỗi tải Silero VAD: {e}")

# =========================================================
# HELPER FUNCTIONS
# =========================================================
def _apply_silero_vad(audio_path: Path, log=_log_colored):
    """Cắt bỏ đoạn im lặng bằng Silero VAD"""
    if not VAD_IS_READY:
        return librosa.load(audio_path, sr=SAMPLE_RATE)[0]

    wav, sr = librosa.load(audio_path, sr=SAMPLE_RATE)
    try:
        speech_timestamps = utils.get_speech_timestamps(torch.tensor(wav), VAD_MODEL, sampling_rate=sr)
    except Exception as e:
        log(f"[⚠️ [VAD]] Lỗi utils Silero: {e}", "yellow")
        from silero_vad import utils as _vad_utils
        speech_timestamps = _vad_utils.get_speech_timestamps(torch.tensor(wav), VAD_MODEL, sampling_rate=sr)

    if not speech_timestamps:
        log(f"[VAD] Không phát hiện giọng nói trong {audio_path.name}.", "yellow")
        return wav

    start = speech_timestamps[0]["start"]
    end = speech_timestamps[-1]["end"]
    return wav[start:end]

# =========================================================
# ASR SERVICE (WHISPER)
# =========================================================
class ASRServiceWhisper:
    def __init__(self, log_callback=_log_colored, model=None):
        self._log = log_callback
        self._model = model or WHISPER_MODEL

    async def transcribe(self, audio_filepath: Path):
        try:
            if not os.path.exists(audio_filepath):
                self._log(f"[❌ [ASR]] Không tìm thấy file {audio_filepath}", "red")
                yield "[NO SPEECH DETECTED]"
                return

            audio_numpy, sr = sf.read(audio_filepath)
            rms = np.sqrt(np.mean(audio_numpy**2))
            if rms < 0.005:
                self._log(f"[⚠️ [ASR]] Âm lượng thấp ({rms:.4f}) hoặc không có giọng nói.", "yellow")
                yield "[NO SPEECH DETECTED]"
                return

            audio_input = await asyncio.to_thread(_apply_silero_vad, audio_filepath, self._log)
            if len(audio_input) == 0:
                self._log("[⚠️ [ASR]] File sau VAD trống.", "yellow")
                yield "[NO SPEECH DETECTED]"
                return

            result = await asyncio.to_thread(self._model.transcribe, audio_input)
            text = result.get("text", "").strip()
            if not text:
                text = "[NO SPEECH DETECTED]"
            self._log(f"[🧠 [ASR]] Văn bản nhận được: {text}")
            yield text

        except Exception as e:
            self._log(f"[❌ [ASR]] Lỗi khi nhận dạng: {e}", "red")
            traceback.print_exc()
            yield "[NO SPEECH DETECTED]"

# =========================================================
# NLU & DIALOG MANAGER
# =========================================================
class DialogManager:
    def __init__(self, log_callback=_log_colored):
        self._log = log_callback

    async def handle_text(self, text: str):
        self._log(f"[🧠 [DM/NLU]] Đang xử lý văn bản: {text}")
        if not text or text.strip() in ["[NO SPEECH DETECTED]", ""]:
            response = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
        elif "xin chào" in text.lower():
            response = "Chào bạn! Tôi có thể giúp gì hôm nay?"
        elif "tạm biệt" in text.lower():
            response = "Tạm biệt nhé, hẹn gặp lại!"
        else:
            response = f"Bạn vừa nói: {text}"
        self._log(f"[🧠 [DM]] Hoàn tất. Response: '{response[:50]}...'")
        return response

# =========================================================
# TTS SERVICE
# =========================================================
class TTSService:
    def __init__(self, log_callback=_log_colored):
        self._log = log_callback

    async def synthesize(self, text: str, output_path: Path):
        try:
            self._log(f"[🧠 [GTTS]] Bắt đầu tổng hợp văn bản: '{text[:50]}...'")
            tts = gTTS(text=text, lang="vi")
            tts.save(output_path)
            self._log(f"[🎵 [GTTS]] Đã tạo file âm thanh: {output_path}")
            return output_path
        except Exception as e:
            self._log(f"[❌ [TTS]] Lỗi tổng hợp âm thanh: {e}", "red")
            return None

# =========================================================
# RTC STREAM PROCESSOR
# =========================================================
class RTCStreamProcessor:
    def __init__(self, log_callback=_log_colored):
        self._log = log_callback
        if WHISPER_IS_READY and WHISPER_MODEL is not None:
            self._asr_client = ASRServiceWhisper(self._log, WHISPER_MODEL)
        else:
            self._log("⚠️ [ASR] Whisper chưa sẵn sàng. Sử dụng chế độ giả lập.", "orange")

            async def mock_transcribe(fp):
                yield "[NO SPEECH DETECTED]"

            self._asr_client = type("ASRMock", (), {"transcribe": mock_transcribe})()

        self._dm = DialogManager(self._log)
        self._tts = TTSService(self._log)

    async def handle_rtc_session(self, record_file: Path, session_id: str, api_key: str):
        try:
            self._log(f"[▶️ [RTC]] Bắt đầu phiên xử lý ASR/NLU. Session ID: {session_id}.")
            dm_input_asr = ""

            async for text in self._asr_client.transcribe(record_file):
                dm_input_asr = text

            if dm_input_asr == "[NO SPEECH DETECTED]" or len(dm_input_asr.strip()) == 0:
                self._log("⚠️ [RTC] Không phát hiện lời nói hợp lệ, bỏ qua xử lý NLU.", "yellow")
                response_text = "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại không?"
                yield (False, {"user_text": dm_input_asr, "bot_text": response_text})
                return

            response_text = await self._dm.handle_text(dm_input_asr)
            yield (False, {"user_text": dm_input_asr, "bot_text": response_text})

            output_audio_path = Path("temp") / f"{session_id}_output.wav"
            await self._tts.synthesize(response_text, output_audio_path)

            with open(output_audio_path, "rb") as f:
                audio_data = f.read()

            # 🔥 FIX: trả về bytes, không phải list
            yield (True, audio_data)

            self._log(f"[🎵 [TTS]] Kết thúc phiên {session_id}.")
        except Exception as e:
            self._log(f"[❌ [RTC]] Lỗi trong phiên {session_id}: {e}", "red")
            traceback.print_exc()
            yield (False, {"bot_text": "Đã xảy ra lỗi trong quá trình xử lý."})
