# routers/promotions.py

from fastapi import APIRouter
from typing import List, Dict, Any

router = APIRouter(
    prefix="/promotions",
    tags=["Khuyến Mãi"],
)

MOCK_PROMOTIONS = [
    {"code": "SUMMER30", "discount": 30, "product_sku": "ALL"},
    {"code": "LAPTOP10", "discount": 10, "product_sku": "Laptop XYZ"},
]

@router.get("/", response_model=List[Dict[str, Any]])
def get_current_promotions():
    """
    [GET /api/promotions]
    Lấy danh sách các chương trình khuyến mãi đang diễn ra.
    """
    return MOCK_PROMOTIONS