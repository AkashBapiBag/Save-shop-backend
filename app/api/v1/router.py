from fastapi import APIRouter

from app.api.v1.endpoints import auth, billing, customers, dashboard, inventory, notifications, stores, transfers

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router)
api_v1_router.include_router(stores.router)
api_v1_router.include_router(customers.router)
api_v1_router.include_router(inventory.router)
api_v1_router.include_router(transfers.router)
api_v1_router.include_router(billing.router)
api_v1_router.include_router(dashboard.router)
api_v1_router.include_router(notifications.router)
