# API Documentation – STT Project 

## 1. TỔNG QUAN KIẾN TRÚC HỆ THỐNG

Hệ thống Voice AI được thiết kế theo mô hình **Event‑Driven Asynchronous Pipeline**, tối ưu cho xử lý giọng nói thời gian thực, độ trễ thấp và khả năng mở rộng theo nhu cầu doanh nghiệp.

### 1.1. Luồng dữ liệu tổng quát

```
Client (Web / Mobile / POS)
        |
        | WebRTC / HTTP
        v
VAD → ASR → NLU → Dialog Manager / Business Logic → TTS
        |
        v
 WebRTC Audio Track / JSON Response
```

### 1.2. Các tầng chức năng

- **VAD Layer (Voice Activity Detection)**  \
  Sử dụng **Silero VAD** để phát hiện giọng nói, loại bỏ khoảng lặng và nhiễu nền, giúp giảm đáng kể khối lượng dữ liệu đầu vào cho ASR.

- **ASR Layer (Automatic Speech Recognition)**  \
  Ứng dụng **OpenAI Whisper** để chuyển đổi âm thanh WAV (Mono, 16kHz, PCM 16‑bit) thành văn bản với độ chính xác cao.

- **NLU Layer (Natural Language Understanding)**  \
  Phân tích văn bản bằng **Gemini LLM** hoặc **Rule‑based Engine** nhằm:

  - Nhận diện **Intent** (ý định người dùng)
  - Trích xuất **Entities** (thực thể nghiệp vụ)

- **Logic & Dialog Manager**  \
  Đóng vai trò điều phối trung tâm, kiểm tra Whitelist nghiệp vụ, quản lý trạng thái hội thoại, truy vấn CRM/POS và quyết định hành động tiếp theo.

- **TTS Layer (Text‑To‑Speech)**  \
  Chuyển phản hồi văn bản của hệ thống thành âm thanh (WAV) và trả lại cho Client thông qua WebRTC hoặc HTTP.

---

## 2. ĐẶC TẢ API ENDPOINTS

### 📡 2.1. WebRTC Gateway – Real‑time Voice Streaming

- **Endpoint**: `POST /offer`  \


- **Mục đích**: Khởi tạo kết nối WebRTC hai chiều (full‑duplex) cho giao tiếp giọng nói thời gian thực.

#### Request Body (JSON)

```json
{
  "sdp": "v=0\no=- 452...",
  "type": "offer",
  "api_key": "STRING (Optional)"
}
```

#### Quy trình xử lý nội bộ

1. Server tiếp nhận SDP Offer và khởi tạo một `RTCStreamProcessor` tương ứng với session.
2. Audio từ `MediaStreamTrack` được giải mã và đưa vào buffer.
3. VAD cắt đoạn giọng nói → ASR (Whisper) → NLU phân tích intent/entities.
4. Dialog Manager xác định hành động nghiệp vụ.
5. Kết quả được trả về qua:
   - WebRTC Audio Track (âm thanh)
   - WebRTC DataChannel (metadata/text nếu cần)

#### Response

- SDP Answer (`type: answer`, `sdp: ...`)

---

### 🎙️ 2.2. Upload & Xử Lý File Âm Thanh (REST API)

Phù hợp cho chế độ **Legacy**, xử lý offline hoặc debug.

- **Endpoint**: `POST /api/upload_wav`  \


- **Content‑Type**: `multipart/form-data`

#### Tham số

| Tên      | Kiểu        | Bắt buộc | Mô tả                               |
| -------- | ----------- | -------- | ----------------------------------- |
| audio    | File (.wav) | ✔        | Mono, 16kHz (khuyến nghị)           |
| api\_key | String      | ✔        | Khóa nội bộ cấu hình trong hệ thống |

#### Response (200 OK)

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_text": "Sản phẩm A giá bao nhiêu?",
  "bot_text": "Sản phẩm A có giá 250.000đ. Bạn có muốn đặt mua không?",
  "intent": "ask_price",
  "entities": {"product_name": "Sản phẩm A"},
  "action": "provide_info",
  "audio_path": "/audio_files/output_550e.wav"
}
```

---

### 🛒 2.3. Thanh Toán & CRM (Internal Endpoint)

- **Endpoint**: `GET /static/qr_payment_demo.html`  \


- **Mô tả**: Trang HTML hiển thị mã QR thanh toán động dựa trên thông tin đơn hàng.

**Luồng xử lý**: Khi intent `order_product` được nhận diện, Dialog Manager trả về `action_url`, Client tự động điều hướng người dùng.

---

## 3. INTENT MATRIX & HÀNH ĐỘNG

| Intent               | Ví dụ                     | Hành động hệ thống              |
| -------------------- | ------------------------- | ------------------------------- |
| chao\_hoi            | "Chào em", "Hello"        | Trả về lời chào                 |
| ask\_price           | "Cái này bao nhiêu tiền?" | Truy vấn bảng `products`        |
| order\_product       | "Tôi muốn mua cái này"    | Tạo bản ghi `payments`, sinh QR |
| ask\_promotion       | "Có khuyến mãi không?"    | Truy vấn router `promotions`    |
| fallback\_no\_speech | (Yên lặng)                | Nhắc người dùng nói lại         |

---

## 4. LƯU TRỮ DỮ LIỆU

### 4.1. SQLite (WAL Mode)

**Bảng \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*****payments**:

- `order_id` (Primary Key)
- `amount`
- `status` (PENDING / SUCCESS / FAILED)

### 4.2. Bộ nhớ hội thoại

- File `stt_memory.jsonl` lưu lịch sử tương tác
- Phục vụ huấn luyện lại NLU và cải thiện độ chính xác

---

## 5. BẢO MẬT & XÁC THỰC

- Xác thực bằng **API Key** (`INTERNAL_API_KEY`).
- Whitelist intent để ngăn phản hồi ngoài nghiệp vụ.
- WebRTC hỗ trợ ICE, STUN/TURN và tự động huỷ session khi không có audio.

---

## 6. TRIỂN KHAI & VẬN HÀNH

### Yêu cầu môi trường

- Python 3.10+
- FFmpeg (bắt buộc)

### Cài đặt

```bash
pip install -r requirements.txt
```

### Cấu hình `.env`

```env
INTERNAL_API_KEY=your_key_here
GEMINI_API_KEY=your_gemini_key
```

### Chạy hệ thống

```bash
python backend_webrtc_server.py
```

### Kiểm tra

- Swagger UI: `http://localhost:8000/docs`

---

## 7. LOGGING, HIỆU NĂNG & MỞ RỘNG

- Logging đầy đủ `INFO / ERROR / CRITICAL` kèm traceback.
- VAD giúp giảm 40–60% thời gian xử lý ASR.
- Có thể tách thành microservices và scale theo WebRTC session.
---

## 8. API Endpoints

### 8.1 Health Check

Kiểm tra trạng thái server.

* **URL**: `/status`
* **Method**: `GET`

**Response 200**

```json
{
  "status": "running"
}
```

---

### 8.2 Speech-to-Text (Audio File)

Gửi file âm thanh để nhận dạng giọng nói.

* **URL**: `/api/stt`
* **Method**: `POST`
* **Content-Type**: `multipart/form-data`

**Request Parameters**

| Tên   | Kiểu | Bắt buộc | Mô tả                      |
| ----- | ---- | -------- | -------------------------- |
| audio | file | ✔        | File âm thanh (.wav, .mp3) |

**Response 200**

```json
{
  "text": "Xin chào, đây là kết quả nhận dạng giọng nói",
  "confidence": 0.92
}
```

---

### 8.3 Speech-to-Text (WebRTC / Streaming)

Nhận dạng giọng nói thời gian thực thông qua WebRTC.

* **URL**: `/api/webrtc`
* **Method**: `POST / GET`
* **Protocol**: WebRTC

**Mô tả**:

* Client gửi audio stream
* Server xử lý liên tục và trả về transcript theo thời gian thực

**Response (ví dụ)**

```json
{
  "partial_text": "xin chào",
  "is_final": false
}
```

---

## 9. Mã lỗi

| HTTP Code | Ý nghĩa                 |
| --------- | ----------------------- |
| 200       | Thành công              |
| 400       | Dữ liệu không hợp lệ    |
| 404       | Không tìm thấy endpoint |
| 500       | Lỗi server              |

## 10. Ghi chú triển khai

* Sử dụng `--reload` chỉ cho môi trường phát triển
* Khi deploy production, nên dùng:

```bash
uvicorn backend_webrtc_server:app --host 0.0.0.0 --port 8000
```

* Có thể đóng gói bằng Docker để triển khai

**Phiên bản tài liệu**: v1.0

