# routers/products.py

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

# Khởi tạo APIRouter. Mọi route trong đây sẽ bắt đầu bằng prefix "/products"
router = APIRouter(
    prefix="/products",
    tags=["Sản Phẩm"], # Dùng cho tài liệu Swagger/OpenAPI
)

# Giả lập database
MOCK_PRODUCTS = [
    {"id": 1, "name": "Điện thoại ABC", "price": 10000000},
    {"id": 2, "name": "Laptop XYZ", "price": 25000000},
]

@router.get("/", response_model=List[Dict[str, Any]])
def get_all_products():
    """
    [GET /api/products]
    Lấy danh sách tất cả sản phẩm.
    """
    # Logic tra cứu DB thực tế sẽ được đặt ở đây
    return MOCK_PRODUCTS

@router.get("/{product_id}", response_model=Dict[str, Any])
def get_product_detail(product_id: int):
    """
    [GET /api/products/{id}]
    Lấy chi tiết sản phẩm theo ID.
    """
    product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product