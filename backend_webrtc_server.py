import asyncio
import os
import json
import uuid
import wave
import numpy as np
import librosa  # ✅ Dùng để resample
import warnings
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import traceback 
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.exceptions import InvalidStateError
from routers import products, orders, promotions, payment
from ai_modules.rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, INTERNAL_API_KEY
import base64
from gtts import gTTS

# ============================================================
# 🔧 FIX CHO LỖI "Transaction.__retry()" TRONG AIORTC/AIOICE
# ============================================================
import aioice
aioice.stun.TRANSACTION_RETRY_INTERVAL = 2.0
aioice.stun.TRANSACTION_MAX_RETRIES = 4

warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid state")
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine.*was never awaited")

# ============================================================
# CẤU HÌNH CHUNG
# ============================================================
CHANNELS = 1
SAMPLE_WIDTH = 2
os.makedirs("temp", exist_ok=True)

ICE_SERVERS = [
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
    {"urls": "stun:stun3.l.google.com:19302"},
]

processing_tasks: Dict[str, asyncio.Task] = {}

app = FastAPI(title="STT Voice AI Backend (WebRTC + REST API)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(promotions.router, prefix="/api")
app.include_router(payment.router, prefix="/api")

# ============================================================
# UTILITIES
# ============================================================
def log_info(message: str, color="white"):
    print(f"INFO:backend_webrtc_server:[{message}]")

def _write_wav_file_safe_helper(file_path_str: str, chunks: list[bytes], wav_params_tuple: tuple):
    with wave.open(file_path_str, 'wb') as wf:
        wf.setparams(wav_params_tuple)
        for chunk in chunks:
            wf.writeframes(chunk)
    log_info(f"[WAV Writer] ✅ Ghi file thành công: {file_path_str}")

WAV_PARAMS = (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE, 0, 'NONE', 'not compressed')

# ============================================================
# CLASS GHI ÂM AUDIO
# ============================================================
class AudioFileRecorder:
    def __init__(self, pc):
        self._pc = pc
        self._on_stop_callback: Optional[Callable] = None
        self._track: Optional[MediaStreamTrack] = None
        self._file_path: Optional[Path] = None
        self._stop_event = asyncio.Event()
        self._chunks: list[bytes] = []
        self._record_task: Optional[asyncio.Task] = None 

    def start(self, track: MediaStreamTrack, file_path: str):
        self._track = track
        self._file_path = Path(file_path)
        self._stop_event.clear()
        self._chunks = []
        self._record_task = asyncio.create_task(self._read_track_and_write()) 
        log_info(f"[Recorder] ▶️ Bắt đầu ghi âm: {self._file_path.name}")

    def on(self, event: str, callback: Callable):
        if event == "stop":
            self._on_stop_callback = callback

    async def _read_track_and_write(self):
        try:
            while not self._stop_event.is_set():
                try:
                    packet = await self._track.recv()
                    audio_data_np = packet.to_ndarray()

                    if audio_data_np.dtype == np.float32:
                        audio_data_np = (audio_data_np * 32767).astype(np.int16)
                    elif audio_data_np.dtype != np.int16:
                        audio_data_np = audio_data_np.astype(np.int16)

                    if len(audio_data_np.shape) > 1:
                        audio_data_np = np.mean(audio_data_np, axis=1)

                    audio_data_np = librosa.resample(audio_data_np.astype(np.float32), orig_sr=48000, target_sr=16000)
                    audio_data_np = (audio_data_np * 32767).astype(np.int16)

                    self._chunks.append(audio_data_np.tobytes())

                except InvalidStateError:
                    break
                except Exception as e:
                    if not self._stop_event.is_set():
                        log_info(f"[Recorder] Lỗi nhận packet audio: {e}")
                    break
        except asyncio.CancelledError:
            log_info(f"[Recorder] 🛑 Task đọc track bị hủy.")
        finally:
            if not self._chunks:
                if self._on_stop_callback and self._file_path:
                    self._on_stop_callback(None)
                return
            try:
                await asyncio.to_thread(_write_wav_file_safe_helper, str(self._file_path), self._chunks, WAV_PARAMS)
                if self._on_stop_callback:
                    self._on_stop_callback(str(self._file_path))
            except Exception as e:
                log_info(f"[Recorder] ❌ Lỗi ghi file WAV: {e}")
                if self._on_stop_callback:
                    self._on_stop_callback(None)

    def stop(self):
        log_info("[Recorder] 🛑 Dừng ghi âm.")
        self._stop_event.set()
        if self._record_task:
            self._record_task.cancel()

# ============================================================
# HÀM XỬ LÝ AUDIO SAU GHI
# ============================================================
async def _process_audio_and_respond(session_id, dm_processor, pc, data_channel, record_file, api_key):
    try:
        if not record_file or not os.path.exists(record_file):
            data_channel.send(json.dumps({
                "type": "error",
                "error": "Không có dữ liệu audio hoặc file không tồn tại."
            }))
            log_info(f"[{session_id}] ⚠️ Bỏ qua: file audio None hoặc không tồn tại.")
            return

        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id,
            api_key=api_key
        )

        audio_chunks_binary = []
        text_data = {}

        async for is_audio, data in stream_generator:
            if is_audio:
                audio_chunks_binary.append(base64.b64decode(data) if isinstance(data, str) else data)
            else:
                text_data = data
                if data_channel:
                    data_channel.send(json.dumps({"type": "text_response_partial", **data}))

        output_file_name = f"{session_id}_output.wav"
        output_file_path = os.path.join("temp", output_file_name)

        if audio_chunks_binary:
            await asyncio.to_thread(_write_wav_file_safe_helper, output_file_path, audio_chunks_binary, WAV_PARAMS)
        else:
            fallback_text = text_data.get("bot_text", "Xin lỗi, tôi không nghe rõ.")
            gTTS(fallback_text, lang="vi").save(output_file_path)

        response_json_path = os.path.join("temp", f"{session_id}_response.json")
        with open(response_json_path, "w", encoding="utf-8") as jf:
            json.dump({
                "session_id": session_id,
                "input_file": record_file,
                "output_audio": output_file_path,
                "text_response": text_data
            }, jf, ensure_ascii=False, indent=4)

        if data_channel:
            data_channel.send(json.dumps({
                "type": "end_of_session",
                "bot_audio_path": f"/audio_files/{output_file_name}"
            }))

    except Exception as e:
        log_info(f"[{session_id}] ❌ Lỗi xử lý: {e}")
        traceback.print_exc()
    finally:
        log_info(f"[{session_id}] ⚠️ Giữ lại file ghi âm đầu vào: {record_file}")

# ============================================================
# ENDPOINT /offer
# ============================================================
@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    session_id = params.get("session_id", str(uuid.uuid4()))
    api_key = params.get("api_key", INTERNAL_API_KEY)

    config = RTCConfiguration(iceServers=[RTCIceServer(urls=s["urls"]) for s in ICE_SERVERS])
    pc = RTCPeerConnection(configuration=config)
    recorder = AudioFileRecorder(pc)
    data_channel_holder = None

    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel_holder
        data_channel_holder = channel

        @channel.on("message")
        def on_message(message):
            data = json.loads(message)
            if data.get("type") == "stop_recording":
                recorder.stop()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            path = os.path.join("temp", f"{session_id}_input.wav")
            recorder.start(track, path)
            recorder.on("stop", lambda p: asyncio.create_task(
                _process_audio_and_respond(session_id, RTCStreamProcessor(log_callback=log_info),
                                           pc, data_channel_holder, p, api_key)
            ))

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

# ============================================================
# 📂 ENDPOINT: UPLOAD WAV FILE
# ============================================================
@app.post("/api/upload_wav")
async def upload_wav(file: UploadFile = File(...), api_key: str = Form(None)):
    """
    📂 Endpoint: Tải file WAV lên để backend phân tích.
    """
    try:
        os.makedirs("temp", exist_ok=True)
        session_id = str(uuid.uuid4())
        temp_path = os.path.join("temp", f"{session_id}_uploaded.wav")

        with open(temp_path, "wb") as f:
            f.write(await file.read())

        log_info(f"[UPLOAD] ✅ Đã nhận file: {file.filename} → {temp_path}")

        dm_processor = RTCStreamProcessor(log_callback=log_info)
        stream_gen = dm_processor.handle_rtc_session(
            record_file=Path(temp_path),
            session_id=session_id,
            api_key=api_key or INTERNAL_API_KEY,
        )

        text_data = {}
        audio_chunks = []

        async for is_audio, data in stream_gen:
            if is_audio:
                audio_chunks.extend(data)
            else:
                text_data = data

        output_file = os.path.join("temp", f"{session_id}_output.wav")
        if audio_chunks:
            await asyncio.to_thread(_write_wav_file_safe_helper, output_file, audio_chunks, WAV_PARAMS)

        response = {
            "session_id": session_id,
            "user_text": text_data.get("user_text", ""),
            "bot_text": text_data.get("bot_text", ""),
            "bot_audio_path": f"/audio_files/{Path(output_file).name}" if os.path.exists(output_file) else None,
        }

        log_info(f"[UPLOAD] ✅ Phân tích xong: {response['bot_text']}")
        return JSONResponse(response)

    except Exception as e:
        log_info(f"[UPLOAD] ❌ Lỗi xử lý file WAV: {e}")
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

# ============================================================
# STATIC ROUTES
# ============================================================
app.mount("/audio_files", StaticFiles(directory="temp"), name="audio_files")
app.mount("/", StaticFiles(directory="static"), name="static")

# ============================================================
# MAIN ENTRY
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
