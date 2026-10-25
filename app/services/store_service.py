import base64
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateEntityException,
    EntityNotFoundException,
    ForbiddenException,
    StoreCreationIntegrityException,
)
from app.models.store import Store
from app.models.user import User
from app.schemas.store import StoreCreate, StoreResponse, StoreUpdate


class StoreService:
    @staticmethod
    def create_store(db: Session, store_in: StoreCreate, current_user: User) -> Store:
        """
        Creates a new store entity.
        - Enforces Admin role requirement.
        - Enforces Critical Pre-save constraint:
          SELECT COUNT(*) FROM transactions WHERE store_id = :new_store_id
          must confirm zero existing linked data records.
        """
        if not current_user.is_admin():
            raise ForbiddenException("Only Admin users can initiate the creation of a new store entity.")

        # Check for duplicate store name
        existing_name = db.query(Store).filter(Store.name == store_in.name).first()
        if existing_name:
            raise DuplicateEntityException("Store", "name", store_in.name)

        new_store_id = store_in.store_id or uuid.uuid4()

        # CRITICAL CONSTRAINT: Pre-save check against transactions
        query = text("SELECT COUNT(*) FROM transactions WHERE store_id = :new_store_id")
        result = db.execute(query, {"new_store_id": str(new_store_id)}).scalar()
        if result and result > 0:
            raise StoreCreationIntegrityException(
                f"Critical constraint violation: {result} existing transaction record(s) linked to store_id '{new_store_id}'. Store creation aborted.",
                details={"linked_transactions_count": result, "attempted_store_id": str(new_store_id)},
            )

        # Parse authorized signature if provided as base64
        signature_bytes = None
        if store_in.authorized_signature_base64:
            try:
                raw_b64 = store_in.authorized_signature_base64
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                signature_bytes = base64.b64decode(raw_b64)
            except Exception as e:
                raise StoreCreationIntegrityException(f"Invalid base64 signature format: {str(e)}") from e

        # Parse store logo if provided as base64
        logo_bytes = None
        if store_in.logo_base64:
            try:
                raw_logo_b64 = store_in.logo_base64
                if "," in raw_logo_b64:
                    raw_logo_b64 = raw_logo_b64.split(",", 1)[1]
                logo_bytes = base64.b64decode(raw_logo_b64)
            except Exception as e:
                raise StoreCreationIntegrityException(f"Invalid base64 logo format: {str(e)}") from e

        new_store = Store(
            store_id=new_store_id,
            name=store_in.name,
            owner_name=store_in.owner_name,
            phone_number=store_in.phone_number,
            address=store_in.address,
            state=store_in.state or "19-West Bengal",
            email=store_in.email,
            logo_url=store_in.logo_url,
            logo_data=logo_bytes,
            authorized_signature_data=signature_bytes,
            is_active=True,
        )

        db.add(new_store)
        db.commit()
        db.refresh(new_store)

        # Automatically associate admin to the store
        if new_store not in current_user.accessible_stores:
            current_user.accessible_stores.append(new_store)
            if not current_user.current_store_id:
                current_user.current_store_id = new_store.store_id
            db.commit()

        return new_store

    @staticmethod
    def get_store_by_id(db: Session, store_id: uuid.UUID) -> Store:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            raise EntityNotFoundException("Store", store_id)
        return store

    @staticmethod
    def list_stores(db: Session, user: User) -> list[Store]:
        """
        Admins can view all stores.
        Standard users only view stores they have access to.
        """
        if user.is_admin():
            return db.query(Store).order_by(Store.created_at.desc()).all()
        return user.accessible_stores

    @staticmethod
    def update_store(
        db: Session,
        store_id: uuid.UUID,
        store_update: StoreUpdate,
        current_user: User,
    ) -> Store:
        if not current_user.is_admin():
            raise ForbiddenException("Only Admins can update store configuration.")

        store = StoreService.get_store_by_id(db, store_id)

        if store_update.name is not None and store_update.name != store.name:
            existing = db.query(Store).filter(Store.name == store_update.name, Store.store_id != store_id).first()
            if existing:
                raise DuplicateEntityException("Store", "name", store_update.name)
            store.name = store_update.name

        if store_update.owner_name is not None:
            store.owner_name = store_update.owner_name
        if store_update.phone_number is not None:
            store.phone_number = store_update.phone_number
        if store_update.address is not None:
            store.address = store_update.address
        if store_update.state is not None:
            store.state = store_update.state
        if store_update.email is not None:
            store.email = store_update.email
        if store_update.logo_url is not None:
            store.logo_url = store_update.logo_url
        if store_update.is_active is not None:
            store.is_active = store_update.is_active

        if store_update.logo_base64 is not None:
            raw_logo_b64 = store_update.logo_base64
            if "," in raw_logo_b64:
                raw_logo_b64 = raw_logo_b64.split(",", 1)[1]
            store.logo_data = base64.b64decode(raw_logo_b64)

        if store_update.authorized_signature_base64 is not None:
            raw_b64 = store_update.authorized_signature_base64
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            store.authorized_signature_data = base64.b64decode(raw_b64)

        db.commit()
        db.refresh(store)
        return store

    @staticmethod
    def set_store_signature(db: Session, store_id: uuid.UUID, signature_base64: str, current_user: User) -> Store:
        if not current_user.is_admin():
            raise ForbiddenException("Only Admins can upload store signature.")
        store = StoreService.get_store_by_id(db, store_id)
        raw_b64 = signature_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        store.authorized_signature_data = base64.b64decode(raw_b64)
        db.commit()
        db.refresh(store)
        return store

    @staticmethod
    def get_signature_base64(store: Store) -> str | None:
        if store.authorized_signature_data:
            return base64.b64encode(store.authorized_signature_data).decode("utf-8")
        return None

    @staticmethod
    def get_logo_base64(store: Store) -> str | None:
        if store.logo_data:
            return base64.b64encode(store.logo_data).decode("utf-8")
        return None

    @staticmethod
    def get_indian_states(db: Session) -> list[dict]:
        from app.models.state import IndianState

        states = db.query(IndianState).order_by(IndianState.code.asc()).all()
        return [
            {
                "code": s.code,
                "name": s.name,
                "state_type": s.state_type,
                "display_name": s.display_name,
            }
            for s in states
        ]

    @staticmethod
    def to_response(store: Store) -> StoreResponse:
        return StoreResponse(
            store_id=store.store_id,
            name=store.name,
            owner_name=store.owner_name,
            phone_number=store.phone_number,
            address=store.address,
            state=getattr(store, "state", None) or "19-West Bengal",
            email=store.email,
            logo_url=store.logo_url,
            has_logo=store.logo_data is not None or store.logo_url is not None,
            logo_base64=base64.b64encode(store.logo_data).decode("utf-8") if store.logo_data else None,
            has_signature=store.authorized_signature_data is not None,
            authorized_signature_base64=base64.b64encode(store.authorized_signature_data).decode("utf-8")
            if store.authorized_signature_data
            else None,
            is_active=store.is_active,
            created_at=store.created_at,
            updated_at=store.updated_at,
        )
