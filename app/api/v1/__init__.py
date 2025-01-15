from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.products import router as products_router
from app.api.v1.orders import router as orders_router
from app.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(products_router)
api_router.include_router(orders_router)
api_router.include_router(webhooks_router)
