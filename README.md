# API Documentation – STT Project 3

## 1. Giới thiệu

**STT Project 3** là hệ thống backend xử lý **Speech-to-Text (STT)**, hỗ trợ nhận dữ liệu âm thanh (file hoặc stream WebRTC) và chuyển đổi thành văn bản bằng mô hình AI.

* Ngôn ngữ: **Python**
* Framework: **FastAPI / WebRTC Server**
* Mục đích: Phục vụ nhận dạng giọng nói thời gian thực và không thời gian thực

---

## 2. Kiến trúc hệ thống

```
Client (Web / App)
        |
        | HTTP / WebRTC
        v
Backend STT Server (FastAPI)
        |
        v
Speech-to-Text Model
```

---

## 3. Cài đặt môi trường

### 3.1 Yêu cầu

* Python >= 3.8
* pip

### 3.2 Cài đặt thư viện

```bash
pip install -r requirements.txt
```

---

## 4. Chạy backend

### 4.1 Chạy server

```bash
python backend_webrtc_server.py
```

Hoặc (nếu dùng FastAPI + Uvicorn):

```bash
uvicorn backend_webrtc_server:app --host 127.0.0.1 --port 8000 --reload
```

### 4.2 Truy cập

* API base URL: `http://127.0.0.1:8000`
* Swagger UI: `http://127.0.0.1:8000/docs`

---

## 5. API Endpoints

### 5.1 Health Check

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

### 5.2 Speech-to-Text (Audio File)

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

### 5.3 Speech-to-Text (WebRTC / Streaming)

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

## 6. Mã lỗi

| HTTP Code | Ý nghĩa                 |
| --------- | ----------------------- |
| 200       | Thành công              |
| 400       | Dữ liệu không hợp lệ    |
| 404       | Không tìm thấy endpoint |
| 500       | Lỗi server              |

## 7. Ghi chú triển khai

* Sử dụng `--reload` chỉ cho môi trường phát triển
* Khi deploy production, nên dùng:

```bash
uvicorn backend_webrtc_server:app --host 0.0.0.0 --port 8000
```

* Có thể đóng gói bằng Docker để triển khai

---

## 8. Hướng phát triển

* Thêm xác thực (JWT / API Key)
* Thêm timestamp cho từng từ
* Hỗ trợ đa ngôn ngữ
* Tối ưu latency cho real-time STT

---

**Tác giả**: Nguyen Chi Bao
**Repository**: STT-Project3
