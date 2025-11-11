from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
import uuid
import urllib.parse
import qrcode
import os
import sqlite3
from core.config_db import get_connection

router = APIRouter()

# =============================
# Mô hình dữ liệu
# =============================
class PaymentRequest(BaseModel):
    amount: int = Field(..., ge=1000, le=10000000000, description="Số tiền thanh toán (VND)")
    description: str = Field(..., max_length=100, description="Nội dung thanh toán")
    customer_info: Optional[str] = None

class PaymentResponse(BaseModel):
    order_id: str
    qr_url: str
    amount: int
    description: str
    customer_info: Optional[str]
    status: str

# =============================
# Tạo QR nội bộ và lưu DB
# =============================
def generate_qr_image(order_id: str, amount: int, description: str, customer_info: Optional[str]):
    os.makedirs("static/payments", exist_ok=True)
    qr_content = f"Thanh toán đơn hàng: {order_id}\nSố tiền: {amount:,} VND\nNội dung: {description}\nKhách hàng: {customer_info or 'Không có'}"
    qr = qrcode.make(qr_content)
    file_path = f"static/payments/{order_id}.png"
    qr.save(file_path)
    return f"/static/payments/{order_id}.png"

# =============================
# POST /api/payment/create
# =============================
@router.get("/payment/create", response_model=PaymentResponse)
async def create_payment_get(
    amount: int = Query(..., ge=1000, le=10000000000),
    description: str = Query(..., max_length=100),
    customer_info: Optional[str] = Query(None),
    gateway: str = Query("QRCODE")
):
    try:
        order_id = str(uuid.uuid4())[:8]
        qr_url = generate_qr_image(order_id, amount, description, customer_info)

        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO payments (order_id, amount, description, customer_info, qr_path, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (order_id, amount, description, customer_info, qr_url, "PENDING"))
        conn.commit()
        conn.close()

        return PaymentResponse(
            order_id=order_id,
            qr_url=qr_url,
            amount=amount,
            description=description,
            customer_info=customer_info,
            status="PENDING"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi tạo đơn hàng: {str(e)}")

# =============================
# GET /api/payment/status/{order_id}
# =============================
@router.get("/payment/status/{order_id}", response_model=PaymentResponse)
async def get_payment_status(order_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT order_id, amount, description, customer_info, qr_path, status FROM payments WHERE order_id=?", (order_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")

    return PaymentResponse(
        order_id=row[0],
        amount=row[1],
        description=row[2],
        customer_info=row[3],
        qr_url=row[4],
        status=row[5]
    )

# =============================
# PUT /api/payment/update/{order_id}
# =============================
@router.put("/payment/update/{order_id}")
async def update_payment_status(order_id: str, status: str = Query(..., regex="^(PENDING|SUCCESS|FAILED)$")):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE payments SET status=? WHERE order_id=?", (status, order_id))
    conn.commit()
    conn.close()
    return {"message": f"Đã cập nhật trạng thái {order_id} thành {status}"}

# =============================
# GET /api/payment/list
# =============================
@router.get("/payment/list")
async def list_all_payments():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT order_id, amount, description, customer_info, qr_path, status, created_at FROM payments ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "order_id": r[0],
            "amount": r[1],
            "description": r[2],
            "customer_info": r[3],
            "qr_url": r[4],
            "status": r[5],
            "created_at": r[6]
        })
    return {"total": len(result), "payments": result}
