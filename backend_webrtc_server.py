print("⚡ RUNNING BACKEND FILE:", __file__)
import asyncio
import os
import json
import uuid
import wave
import numpy as np
from scipy.signal import resample_poly 
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

# Routers
from routers import products, orders, promotions, payment

# WebRTC Pipeline
from ai_modules.rtc_integration_layer import RTCStreamProcessor, SAMPLE_RATE, INTERNAL_API_KEY

# === MODULES MỚI (NLU → LOGIC → DIALOG) ===
from core.logic_manager import LogicManager
from ai_modules.dialog_manager import DialogManager
from core.stt_log_parser import STTLogParser
from core.json_loader import JSONLogLoader

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

# ============================================================
# APP KHỞI TẠO
# ============================================================
app = FastAPI(title="STT Voice AI Backend (WebRTC + REST API)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(promotions.router, prefix="/api")
app.include_router(payment.router, prefix="/api")


# ============================================================
# LOGGING CHUẨN HOÁ (DÙNG CHO CẢ LOGICMANAGER & DM)
# ============================================================
def log_info(message: str, color="white"):
    print(f"INFO:backend_webrtc_server:[{message}]")
from core.memory_trainer import MemoryTrainer
memory_engine = MemoryTrainer(log_callback=log_info)


# 🔥 TÍCH HỢP LOGIC MANAGER + DIALOG MANAGER (ĐÚNG API KEY)
logic_manager = LogicManager(
    log_callback=log_info,
    response_config={},        # hoặc load file config nếu bạn có
    llm_mode="real",
    tts_mode="real",
    db_mode="real",
    api_key=INTERNAL_API_KEY   # <-- FIX API KEY
)

dialog_manager = DialogManager(
    log_callback=log_info,
    mode="rtc"                 # nếu DM của bạn cần mode
)


# ============================================================
# UTILITIES
# ============================================================
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

                    # Chuẩn hoá dtype
                    if audio_data_np.dtype == np.float32:
                        audio_data_np = (audio_data_np * 32767).astype(np.int16)
                    elif audio_data_np.dtype != np.int16:
                        audio_data_np = audio_data_np.astype(np.int16)

                    # Convert stereo → mono
                    if len(audio_data_np.shape) > 1:
                        audio_data_np = np.mean(audio_data_np, axis=1).astype(np.int16)

                    # 🚀 RESAMPLE REAL-TIME KHÔNG BLOCKING
                    # 48k → 16k dùng polyphase filter (siêu nhanh)
                    audio_data_np = resample_poly(audio_data_np, 1, 3).astype(np.int16)

                    # Lưu chunk
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
                # Ghi WAV chuẩn
                await asyncio.to_thread(
                    _write_wav_file_safe_helper,
                    str(self._file_path),
                    self._chunks,
                    WAV_PARAMS
                )

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
            if data_channel:
                data_channel.send(json.dumps({
                    "type": "error",
                    "error": "Không có dữ liệu audio hoặc file không tồn tại."
                }))
            log_info(f"[{session_id}] ⚠️ Bỏ qua: file audio None hoặc không tồn tại.")
            return

        # === BẮT ĐẦU PIPELINE ===
        stream_generator = dm_processor.handle_rtc_session(
            record_file=Path(record_file),
            session_id=session_id,
            api_key=api_key
        )

        # === DATA GIỮ LẠI ĐỂ TỔNG HỢP CUỐI ===
        audio_chunks_binary = []
        last_user_text = ""
        last_bot_text = ""
        last_intent = ""
        last_action = ""
        last_payment_url = None

        parser = STTLogParser(log_callback=log_info)

        # ===========================
        #   VÒNG LẶP NHẬN STREAM
        # ===========================
        async for is_audio, data in stream_generator:

            # --- AUDIO STREAM ---
            if is_audio:
                audio_chunks_binary.append(
                    base64.b64decode(data) if isinstance(data, str) else data
                )
                continue

            # --- TEXT STREAM ASR ---
            if "user_text" in data and data["user_text"].strip():
                last_user_text = data["user_text"].strip()

            # --- PARSER ---
            nlu_json = parser.convert({"text_response": {"user_text": last_user_text}})

            # --- LOGIC MANAGER ---
            decision = logic_manager.handle_nlu_result(nlu_json)
            last_intent = decision.get("intent")
            last_action = decision.get("action")
            last_payment_url = decision.get("payment_url")

            # --- DIALOG MANAGER ---
            final_response = dialog_manager.process_with_logic_manager(
                nlu_json=nlu_json,
                logic_manager=logic_manager
            )

            # Lấy bot_text nếu có
            bot_raw = final_response.get("response_text") or final_response.get("text")
            if bot_raw and bot_raw.strip():
                last_bot_text = bot_raw.strip()

            # Gửi TEXT PARTIAL cho UI
            if data_channel:
                data_channel.send(json.dumps({
                    "type": "text_response_partial",
                    "user_text": last_user_text,
                    "bot_text": last_bot_text,
                    "intent": last_intent,
                    "action": last_action,
                    "payment_url": last_payment_url
                }))

        # ===========================
        #   TTS SAU KHI KẾT THÚC
        # ===========================
        output_file_name = f"{session_id}_output.wav"
        output_file_path = os.path.join("temp", output_file_name)

        user_spoken = last_user_text if last_user_text else "tôi không nghe rõ câu bạn nói"
        bot_spoken = last_bot_text if last_bot_text else "Tôi xin lỗi, hiện tại tôi chưa tạo được câu trả lời."

        tts_text = f"Bạn vừa nói: {user_spoken}. Câu trả lời của tôi là: {bot_spoken}."

        from pydub import AudioSegment

        log_info(f"[🧠 [GTTS]] Tổng hợp văn bản FULL: '{tts_text[:80]}...'")

        mp3_path = os.path.join("temp", f"{session_id}_tts.mp3")
        wav_path = os.path.join("temp", f"{session_id}_output.wav")

        # Tạo MP3 trước
        gTTS(tts_text, lang='vi').save(mp3_path)

        # Convert MP3 → WAV chuẩn PCM16 16kHz mono
        audio = AudioSegment.from_mp3(mp3_path)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(wav_path, format="wav")

        output_file_path = wav_path

        log_info(f"[🎵 [GTTS]] Đã tạo file WAV PCM16 đầy đủ: {wav_path}")

        # ===========================
        #  GHI LOG JSON
        # ===========================
        response_json_path = os.path.join("temp", f"{session_id}_response.json")
        with open(response_json_path, "w", encoding="utf-8") as jf:
            json.dump({
                "session_id": session_id,
                "input_file": record_file,
                "output_audio": output_file_path,
                "user_text": user_spoken,
                "bot_text": bot_spoken,
                "intent": last_intent,
                "action": last_action,
                "payment_url": last_payment_url
            }, jf, ensure_ascii=False, indent=4)
            memory_engine.remember(response_json_path)
            memory_engine.build_intent_dataset()
            memory_engine.train_intent_classifier()


        # ===========================
        #  GỬI EVENT END SESSION
        # ===========================
        if data_channel:
            data_channel.send(json.dumps({
                "type": "end_of_session",
                "bot_audio_path": f"/audio_files/{output_file_name}"
            }))

        log_info(f"[{session_id}] ✅ Hoàn tất. Audio đầy đủ gửi về client.")

    except Exception as e:
        log_info(f"[{session_id}] ❌ Lỗi xử lý audio: {e}")
        traceback.print_exc()

# ============================================================
# ENDPOINT /offer — FULL CODE ĐÃ TÍCH HỢP MỚI
# ============================================================
@app.post("/offer")
async def offer(request: Request):
    params = await request.json()

    # WebRTC Offer từ client
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    # Session ID từ client hoặc tự sinh
    session_id = params.get("session_id", str(uuid.uuid4()))

    # API Key (bằng key nội bộ trên backend)
    api_key = params.get("api_key", INTERNAL_API_KEY)

    logic_manager.api_key = api_key
    dialog_manager.api_key = api_key


    # =======================
    # Tạo cấu hình WebRTC ICE
    # =======================
    config = RTCConfiguration(
        iceServers=[RTCIceServer(urls=s["urls"]) for s in ICE_SERVERS]
    )
    pc = RTCPeerConnection(configuration=config)

    # Recorder — nhận track audio từ client
    recorder = AudioFileRecorder(pc)

    # DataChannel holder
    data_channel_holder = None

    # ==============================================================
    # Khi client mở DataChannel → giữ reference để gửi text_response
    # ==============================================================
    @pc.on("datachannel")
    def on_datachannel(ch):
        nonlocal data_channel_holder
        data_channel_holder = ch
        log_info(f"[{session_id}] 📡 DataChannel nhận: {ch.label}")

        @ch.on("message")
        async def handle_message(message):
            try:
                # Nếu là binary (PCM từ AudioWorklet) → bỏ qua không parse
                if isinstance(message, (bytes, bytearray, memoryview)):
                    return

                # Nếu không phải string → bỏ qua
                if not isinstance(message, str):
                    return

                # Nếu là JSON thật → xử lý bình thường
                data = json.loads(message)

                if data.get("type") == "stop_recording":
                    log_info(f"[{session_id}] 🛑 Nhận yêu cầu STOP RECORDING từ client")
                    recorder.stop()
                    await asyncio.sleep(0)

            except Exception as e:
                # Chỉ log lỗi nếu message là string JSON
                if isinstance(message, str):
                    log_info(f"[{session_id}] ❌ Lỗi message handler: {e}")
        return



    # ==============================================================
    # Khi client gửi audio track
    # ==============================================================
    @pc.on("track")
    def on_track(track):
        log_info(f"[{session_id}] 🎤 Nhận track audio: {track.kind}")

        if track.kind == "audio":
            path = os.path.join("temp", f"{session_id}_input.wav")

            # Bắt đầu ghi file WAV từ audio track
            recorder.start(track, path)

            # Xử lý khi recorder dừng (gửi vào pipeline)
            recorder.on(
                "stop",
                lambda file_path: asyncio.create_task(
                    _process_audio_and_respond(
                        session_id=session_id,
                        dm_processor=RTCStreamProcessor(log_callback=log_info),
                        pc=pc,
                        data_channel=data_channel_holder,
                        record_file=file_path,
                        api_key=api_key
                    )
                )
            )

    # ==============================================================
    # SETUP OFFER — TRẢ ANSWER CHO CLIENT
    # ==============================================================
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
        "session_id": session_id
    }
# ============================================================
# 📂 ENDPOINT: UPLOAD WAV FILE (DÙNG CHO TEST & DEBUG)
# ============================================================
@app.post("/api/upload_wav")
async def upload_wav(file: UploadFile = File(...), api_key: str = Form(None)):
    """
    📂 Endpoint: Tải file WAV lên backend để phân tích:
    → STT → Parser → LogicManager → DialogManager → Bot_text → Bot_audio
    """
    try:
        os.makedirs("temp", exist_ok=True)
        session_id = str(uuid.uuid4())

        # --------------------------------------------------------
        # 1) Lưu file WAV được upload vào thư mục temp
        # --------------------------------------------------------
        temp_path = os.path.join("temp", f"{session_id}_uploaded.wav")
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        log_info(f"[UPLOAD {session_id}] 📁 File WAV nhận: {file.filename} → {temp_path}")

        # --------------------------------------------------------
        # 2) Gửi file WAV vào pipeline WebRTC STT Processor
        # --------------------------------------------------------
        dm_processor = RTCStreamProcessor(log_callback=log_info)
        stream_gen = dm_processor.handle_rtc_session(
            record_file=Path(temp_path),
            session_id=session_id,
            api_key=api_key or INTERNAL_API_KEY,
        )
        logic_manager.api_key = api_key or INTERNAL_API_KEY
        dialog_manager.api_key = api_key or INTERNAL_API_KEY

        last_user_text = ""
        audio_chunks_binary = []
        final_text_data = {}

        # --------------------------------------------------------
        # 3) Đọc kết quả STT & audio từ pipeline
        # --------------------------------------------------------
        async for is_audio, data in stream_gen:

            # AUDIO STREAM
            if is_audio:
                audio_chunks_binary.append(
                    base64.b64decode(data) if isinstance(data, str) else data
                )
                continue

            # TEXT STREAM
            user_text = data.get("user_text", "").strip()
            last_user_text = user_text

            # ----------------------------------------------------
            # 4) PARSER → convert JSON STT → JSON NLU chuẩn
            # ----------------------------------------------------
            parser = STTLogParser(log_callback=log_info)
            nlu_json = parser.convert({
                "text_response": {"user_text": user_text}
            })

            # ----------------------------------------------------
            # 5) LogicManager → xác định action & intent
            # ----------------------------------------------------
            decision = logic_manager.handle_nlu_result(nlu_json)

            # ----------------------------------------------------
            # 6) DialogManager → tạo bot_text
            # ----------------------------------------------------
            final_response = dialog_manager.process_with_logic_manager(
                nlu_json=nlu_json,
                logic_manager=logic_manager
            )
            logic_manager.api_key = api_key
            dialog_manager.api_key = api_key

            bot_text = final_response.get("response_text") or final_response.get("text") or ""

            final_text_data = {
                "user_text": user_text,
                "bot_text": bot_text,
                "intent": decision.get("intent"),
                "action": decision.get("action"),
                "payment_url": decision.get("payment_url")
            }

        # --------------------------------------------------------
        # 7) GHI BOT AUDIO — nếu pipeline STT không trả âm thanh
        # --------------------------------------------------------
        from pydub import AudioSegment

        tts_text = (
            f"Bạn vừa nói: {final_text_data.get('user_text', '')}. "
            f"Câu trả lời của tôi là: {final_text_data.get('bot_text', '')}."
        )

        mp3_path = os.path.join("temp", f"{session_id}_tts.mp3")
        wav_path = os.path.join("temp", f"{session_id}_output.wav")

        # TTS → MP3
        gTTS(tts_text, lang="vi").save(mp3_path)

        # MP3 → WAV chuẩn PCM16
        sound = AudioSegment.from_mp3(mp3_path)
        sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        sound.export(wav_path, format="wav")

        output_file = wav_path


        # --------------------------------------------------------
        # 8) Chuẩn bị JSON trả về
        # --------------------------------------------------------
        response = {
            "session_id": session_id,
            "user_text": final_text_data.get("user_text", ""),
            "bot_text": final_text_data.get("bot_text", ""),
            "intent": final_text_data.get("intent", ""),
            "action": final_text_data.get("action", ""),
            "payment_url": final_text_data.get("payment_url", None),
            "bot_audio_path": f"/audio_files/{Path(output_file).name}" if os.path.exists(output_file) else None,
        }

        log_info(f"[UPLOAD {session_id}] 🎯 Kết quả: {response['bot_text']}")

        return JSONResponse(response)

    except Exception as e:
        log_info(f"[UPLOAD] ❌ Lỗi xử lý file WAV: {e}")
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
# ============================================================
# STATIC ROUTES — SERVE AUDIO FILES & STATIC HTML
# ============================================================
from fastapi.responses import FileResponse

@app.get("/audio_files/{filename}")
async def serve_audio_file(filename: str):
    file_path = os.path.join("temp", filename)
    return FileResponse(
        file_path,
        media_type="audio/wav",
        headers={"Accept-Ranges": "none"}   # 🚫 Ngăn trình duyệt gửi Range requests
    )

# Thư mục static → chứa QR payment, HTML demo UI
app.mount("/static", StaticFiles(directory="static"), name="static")



# ============================================================
# MAIN ENTRY (CHẠY BẰNG PYTHON TRỰC TIẾP)
# ============================================================
if __name__ == "__main__":
    import uvicorn
    log_info("🚀 Backend WebRTC STT đang khởi động...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
print("\n==== ROUTES ====")
for r in app.routes:
    print(r.path, type(r))
print("==== END ROUTES ====\n")
