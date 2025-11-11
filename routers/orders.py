# routers/orders.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

router = APIRouter(
    prefix="/orders",
    tags=["Đặt Hàng"],
)

# Định nghĩa Schema cho dữ liệu đầu vào (Input Body)
class OrderCreate(BaseModel):
    product_id: int
    quantity: int
    customer_name: str
    shipping_address: str

@router.post("/")
def create_order(order: OrderCreate):
    """
    [POST /api/orders]
    Tạo một đơn hàng mới.
    """
    # Logic xử lý đơn hàng: Lưu vào DB, gửi email xác nhận, v.v.
    order_id = "ORD-" + str(hash(order.customer_name + str(order.product_id)))[:8]
    
    print(f"✅ [ORDER] Đã tạo đơn hàng mới: {order_id} cho {order.customer_name}")
    
    return {
        "message": "Đặt hàng thành công",
        "order_id": order_id,
        "detail": order.model_dump()
    }