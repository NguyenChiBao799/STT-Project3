# backend_webrtc_server.py
import asyncio
import os
import json
import uuid
import wave
import numpy as np
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import traceback 
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse # ✅ BỔ SUNG: Import JSONResponse cho xử lý lỗi
from fastapi.middleware.cors import CORSMiddleware
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.exceptions import InvalidStateError
from routers import products, orders, promotions, payment
from ai_modules.rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, INTERNAL_API_KEY
import base64
from gtts import gTTS  # ✅ Thêm để fallback phản hồi giọng nói

# --- Import RTCStreamProcessor ---
try:
    from ai_modules.rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, INTERNAL_API_KEY 
except ImportError:
    class RTCStreamProcessor:
        def __init__(self, *args, **kwargs): pass
        async def handle_rtc_session(self, *args, **kwargs): 
            yield (False, {"user_text": "LỖI: RTCStreamProcessor không import được.", "bot_text": "Lỗi hệ thống nội bộ."})
    SAMPLE_RATE = 16000
    INTERNAL_API_KEY = "MOCK_INTERNAL_KEY" 

# --- Cấu hình ---
CHANNELS = 1
SAMPLE_WIDTH = 2
os.makedirs("temp", exist_ok=True)
ICE_SERVERS = [{"urls": "stun:stun.l.google.com:19302"}]
processing_tasks: Dict[str, asyncio.Task] = {}

# ======================================================
# Tạo ứng dụng FastAPI chính
# ======================================================
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

# ======================================================
# Logging
# ======================================================
def log_info(message: str, color="white"):
    color_map = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", 
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m", "white": "\033[97m"
    }
    RESET = "\033[0m"
    print(f"{color_map.get(color, RESET)}INFO:backend_webrtc_server:[{message}]{RESET}", flush=True)

# ======================================================
# WAV Writer Helper
# ======================================================
def _write_wav_file_safe_helper(file_path_str: str, chunks: list[bytes], wav_params_tuple: tuple):
    with wave.open(file_path_str, 'wb') as wf:
        wf.setparams(wav_params_tuple)
        for chunk in chunks:
            wf.writeframes(chunk)
    log_info(f"[WAV Writer] ✅ Ghi file thành công: {file_path_str}")

WAV_PARAMS = (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE, 0, 'NONE', 'not compressed')

# ======================================================
# AudioFileRecorder Class
# ======================================================
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
        log_info(f"[Recorder] Bắt đầu ghi âm: {self._file_path.name}")

    def on(self, event: str, callback: Callable):
        if event == "stop":
            self._on_stop_callback = callback

    def _get_wav_params_tuple(self):
        return WAV_PARAMS

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
                    self._chunks.append(audio_data_np.tobytes())
                except InvalidStateError:
                    break
                except Exception as e:
                    if not self._stop_event.is_set():
                        log_info(f"[Recorder] Lỗi nhận packet audio: {e}", "red")
                    break
        except asyncio.CancelledError:
            log_info(f"[Recorder] Task đọc track bị hủy.")
        finally:
            if not self._chunks:
                if self._on_stop_callback and self._file_path:
                    self._on_stop_callback(None)
                return
            try:
                await asyncio.to_thread(_write_wav_file_safe_helper, str(self._file_path), self._chunks, self._get_wav_params_tuple())
                if self._on_stop_callback:
                    self._on_stop_callback(str(self._file_path))
            except Exception as e:
                log_info(f"[Recorder] Lỗi ghi file WAV: {e}", "red")
                if self._on_stop_callback:
                    self._on_stop_callback(None)

    def stop(self):
        log_info("[Recorder] 🛑 Dừng ghi âm.")
        self._stop_event.set()
        if self._record_task:
            self._record_task.cancel()

    

# ======================================================
# Hàm xử lý phản hồi
# ======================================================
async def _process_audio_and_respond(session_id, dm_processor, pc, data_channel, record_file, api_key):
    if data_channel is None:
        log_info(f"[{session_id}] ❌ Data Channel None", "red")
        return

    try:
        timeout = 5
        start_time = asyncio.get_event_loop().time()
        while data_channel.readyState != 'open':
            if asyncio.get_event_loop().time() - start_time > timeout:
                log_info(f"[{session_id}] ❌ Data Channel chưa mở sau {timeout}s.", "red")
                return
            await asyncio.sleep(0.1)
    except Exception as e:
        log_info(f"[{session_id}] Lỗi khi chờ DC: {e}", "red")
        return

    if not record_file or not os.path.exists(record_file):
        log_info(f"[{session_id}] ❌ Không có file ghi âm đầu vào", "red")
        try:
            data_channel.send(json.dumps({"type": "error", "error": "Không có dữ liệu audio"}))
        except Exception:
            pass
        return

    try:
        data_channel.send(json.dumps({"type": "start_processing"}))
        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id,
            api_key=api_key
        )

        audio_chunks_binary = []
        text_data = {}

        async for is_audio, data in stream_generator:
            if data_channel.readyState != 'open':
                log_info(f"[{session_id}] DC đóng, dừng stream.", "orange")
                break
            if is_audio:
                audio_chunks_binary.append(base64.b64decode(data))
            else:
                text_data = data
                data_channel.send(json.dumps({"type": "text_response_partial", **data}))

        output_file_name = f"{session_id}_output.wav"
        output_file_path = os.path.join("temp", output_file_name)

        if audio_chunks_binary:
            await asyncio.to_thread(_write_wav_file_safe_helper, output_file_path, audio_chunks_binary, WAV_PARAMS)
            log_info(f"[{session_id}] ✅ Đã ghi file phản hồi từ AI: {output_file_name}", "green")
        else:
            # ✅ Tạo phản hồi fallback bằng gTTS nếu không có audio từ AI
            fallback_text = text_data.get("bot_text", "Xin lỗi, tôi chưa có phản hồi giọng nói.")
            tts = gTTS(fallback_text, lang="vi")
            tts.save(output_file_path)
            log_info(f"[{session_id}] ⚠️ Dùng gTTS fallback tạo file: {output_file_name}", "yellow")

        if data_channel.readyState == 'open':
            final_response = {
                "type": "end_of_session",
                "bot_audio_path": f"/audio_files/{output_file_name}"
            }
            data_channel.send(json.dumps(final_response))

    except Exception as e:
        log_info(f"[{session_id}] ❌ Lỗi xử lý chung: {e}", "red")
        log_info(traceback.format_exc(), "red")
        try:
            if data_channel and data_channel.readyState == 'open':
                data_channel.send(json.dumps({"type": "error", "error": str(e)}))
        except Exception:
            pass
    finally:
        if os.path.exists(record_file):
            os.remove(record_file)
            log_info(f"[{session_id}] ✅ Xóa file ghi âm đầu vào.", "green")
        if session_id in processing_tasks:
            del processing_tasks[session_id]

# ======================================================
# ROUTES CHÍNH
# ======================================================
dm = RTCStreamProcessor(log_callback=log_info)

@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    session_id = params.get("session_id", str(uuid.uuid4()))
    client_api_key = params.get("api_key", INTERNAL_API_KEY)

    ice_servers_objects = [RTCIceServer(urls=s["urls"]) for s in ICE_SERVERS]
    config = RTCConfiguration(iceServers=ice_servers_objects)
    pc = RTCPeerConnection(configuration=config)

    recorder = AudioFileRecorder(pc)
    data_channel_holder = None

    @pc.on("datachannel")
    def on_datachannel(channel):
        nonlocal data_channel_holder
        data_channel_holder = channel

        @channel.on("open")
        def on_open():
            log_info(f"[{session_id}] ✅ Data Channel mở thành công.")

        @channel.on("close")
        def on_close():
            log_info(f"[{session_id}] ❌ Data Channel đã đóng.")
            if session_id in processing_tasks:
                processing_tasks[session_id].cancel()

        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    if data.get("type") == "stop_recording":
                        recorder.stop()
                    elif data.get("type") == "cancel_processing":
                        if session_id in processing_tasks:
                            processing_tasks[session_id].cancel()
                            log_info(f"[{session_id}] Hủy xử lý theo yêu cầu.", "orange")
                except Exception:
                    pass

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            path = os.path.join("temp", f"{session_id}_input.wav")
            recorder.start(track, path)

            def on_stop(saved_path):
                nonlocal data_channel_holder
                if not data_channel_holder:
                    log_info(f"[{session_id}] ❌ Không có data_channel.", "red")
                    return
                if not saved_path:
                    log_info(f"[{session_id}] ❌ Ghi âm thất bại.", "red")
                    return

                task = asyncio.create_task(
                    _process_audio_and_respond(session_id, dm, pc, data_channel_holder, saved_path, client_api_key)
                )
                processing_tasks[session_id] = task

            recorder.on("stop", on_stop)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = "default_session"):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

# ======================================================
# Static files
# ======================================================
app.mount("/audio_files", StaticFiles(directory="temp"), name="audio_files")
app.mount("/", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
