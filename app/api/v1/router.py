from fastapi import APIRouter

from app.api.v1.endpoints import auth, billing, dashboard, inventory, notifications, stores

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router)
api_v1_router.include_router(stores.router)
api_v1_router.include_router(inventory.router)
api_v1_router.include_router(billing.router)
api_v1_router.include_router(dashboard.router)
api_v1_router.include_router(notifications.router)
