import base64
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import (
    DuplicateEntityException,
    EntityNotFoundException,
    ForbiddenException,
    StoreCreationIntegrityException,
    ValidationException,
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
            owner_id=current_user.user_id,
            name=store_in.name,
            owner_name=store_in.owner_name or current_user.name,
            phone_number=store_in.phone_number,
            address=store_in.address,
            state=store_in.state or "19-West Bengal",
            email=store_in.email or current_user.email,
            logo_url=store_in.logo_url,
            logo_data=logo_bytes,
            authorized_signature_data=signature_bytes,
            is_active=True,
        )

        db.add(new_store)
        db.commit()
        db.refresh(new_store)

        # Automatically associate creator/admin to the store
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
            owner_id=getattr(store, "owner_id", None),
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

    @staticmethod
    def get_store_members_and_invitations(
        db: Session, store_id: uuid.UUID, current_user: User
    ) -> dict:
        store = StoreService.get_store_by_id(db, store_id)
        from sqlalchemy import func

        # Enforce strict 1-owner rule: Ensure store has owner_id
        if not getattr(store, "owner_id", None):
            potential_owner = None
            if store.email:
                potential_owner = db.query(User).filter(func.lower(User.email) == store.email.strip().lower()).first()
            if not potential_owner and store.owner_name:
                potential_owner = db.query(User).filter(func.lower(User.name) == store.owner_name.strip().lower()).first()
            if potential_owner:
                store.owner_id = potential_owner.user_id
                db.commit()
                db.refresh(store)

        # Ensure the single owner user is in store.users_with_access
        target_owner_id = getattr(store, "owner_id", None)
        if target_owner_id:
            owner_user = db.query(User).filter(User.user_id == target_owner_id).first()
            if owner_user and owner_user not in store.users_with_access:
                store.users_with_access.append(owner_user)
                db.commit()
                db.refresh(store)

        # STRICT 1-OWNER RULE: Exactly at most ONE operator in the store has is_owner=True
        operators = [
            {
                "user_id": u.user_id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "picture_url": getattr(u, "picture_url", None),
                "is_owner": bool(target_owner_id is not None and u.user_id == target_owner_id),
                "created_at": u.created_at,
            }
            for u in store.users_with_access
        ]
        # Sort so that the single owner is ALWAYS the 1st item in the list
        operators.sort(key=lambda op: 0 if op["is_owner"] else 1)
        from app.models.invitation import StoreInvitation

        pending_invitations = (
            db.query(StoreInvitation)
            .filter(
                StoreInvitation.store_id == store_id,
                StoreInvitation.status == "pending",
            )
            .order_by(StoreInvitation.created_at.desc())
            .all()
        )
        invitations = [
            {
                "invitation_id": inv.invitation_id,
                "store_id": inv.store_id,
                "email": inv.email,
                "role": inv.role,
                "status": inv.status,
                "created_at": inv.created_at,
            }
            for inv in pending_invitations
        ]
        return {
            "store_id": store.store_id,
            "owner_id": getattr(store, "owner_id", None),
            "store_name": store.name,
            "operators": operators,
            "members": operators,
            "invitations": invitations,
        }

    @staticmethod
    def add_store_operator_by_email(
        db: Session,
        store_id: uuid.UUID,
        email: str,
        role: str | None,
        current_user: User,
    ) -> dict:
        store = StoreService.get_store_by_id(db, store_id)
        clean_email = email.strip().lower()
        from sqlalchemy import func
        from app.models.invitation import StoreInvitation
        from app.core.config import settings

        # Check target role - Enforce that a store can only have 1 owner
        target_role = (role or "").strip().lower() if role else None
        if target_role == "owner":
            raise ValidationException("A store can only have 1 owner. Additional staff or admin roles are determined by user database records.")

        target_owner_id = getattr(store, "owner_id", None)

        # Check if user already exists in DB
        user = db.query(User).filter(func.lower(User.email) == clean_email).first()
        if user:
            # ROLE IS DECIDED BY DATABASE: If user is admin in DB, they are admin in every store.
            # If user is staff in DB, they are staff. We do not alter user.role here.
            is_this_user_owner = bool(target_owner_id is not None and user.user_id == target_owner_id)

            # Check if user already has access to this store
            if store in user.accessible_stores:
                role_desc = "owner" if is_this_user_owner else ("admin" if user.is_admin() else "staff")
                return {
                    "status": "assigned",
                    "message": f"User '{user.email}' is already an operator ({role_desc}) of {store.name}.",
                    "operator": {
                        "user_id": user.user_id,
                        "email": user.email,
                        "name": user.name,
                        "role": user.role,
                        "picture_url": getattr(user, "picture_url", None),
                        "is_owner": is_this_user_owner,
                        "created_at": user.created_at,
                    },
                    "invitation": None,
                }

            user.accessible_stores.append(store)
            if not user.current_store_id:
                user.current_store_id = store.store_id

            # Update any pending invitations to accepted
            pending_invs = (
                db.query(StoreInvitation)
                .filter(
                    StoreInvitation.store_id == store_id,
                    func.lower(StoreInvitation.email) == clean_email,
                    StoreInvitation.status == "pending",
                )
                .all()
            )
            for pi in pending_invs:
                pi.status = "accepted"

            db.commit()
            db.refresh(user)

            role_desc = "owner" if is_this_user_owner else ("admin" if user.is_admin() else "staff")
            return {
                "status": "assigned",
                "message": f"User '{user.email}' successfully added to {store.name} as {role_desc}.",
                "operator": {
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "picture_url": getattr(user, "picture_url", None),
                    "is_owner": is_this_user_owner,
                    "created_at": user.created_at,
                },
                "invitation": None,
            }

        # User does not exist yet -> Create or reuse pending invitation
        # Role is based on system admin status (ADMIN_EMAILS) or default "user"
        invitation_role = "admin" if (clean_email in [e.lower() for e in settings.ADMIN_EMAILS] or target_role == "admin") else "user"

        existing_inv = (
            db.query(StoreInvitation)
            .filter(
                StoreInvitation.store_id == store_id,
                func.lower(StoreInvitation.email) == clean_email,
                StoreInvitation.status == "pending",
            )
            .first()
        )
        if existing_inv:
            return {
                "status": "invited",
                "message": f"An active invitation for '{clean_email}' already exists. They will be added to {store.name} upon signing in.",
                "operator": None,
                "invitation": {
                    "invitation_id": existing_inv.invitation_id,
                    "store_id": existing_inv.store_id,
                    "email": existing_inv.email,
                    "role": existing_inv.role,
                    "status": existing_inv.status,
                    "created_at": existing_inv.created_at,
                },
            }

        new_inv = StoreInvitation(
            store_id=store_id,
            email=clean_email,
            role=invitation_role,
            status="pending",
            invited_by_id=current_user.user_id,
        )
        db.add(new_inv)
        db.commit()
        db.refresh(new_inv)

        return {
            "status": "invited",
            "message": f"Invitation created for '{clean_email}'. When this user logs into Save Shop, they will automatically be assigned to {store.name}.",
            "operator": None,
            "invitation": {
                "invitation_id": new_inv.invitation_id,
                "store_id": new_inv.store_id,
                "email": new_inv.email,
                "role": new_inv.role,
                "status": new_inv.status,
                "created_at": new_inv.created_at,
            },
        }

    @staticmethod
    def remove_store_operator(
        db: Session, store_id: uuid.UUID, user_id: uuid.UUID, current_user: User
    ) -> bool:
        store = StoreService.get_store_by_id(db, store_id)
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise EntityNotFoundException("User", user_id)

        # 1. The single store owner cannot be removed from their own store by anyone
        target_owner_id = getattr(store, "owner_id", None)
        is_target_store_owner = bool(target_owner_id is not None and user_id == target_owner_id)
        if not target_owner_id:
            is_target_store_owner = bool(
                (bool(store.email) and user.email.lower() == store.email.lower()) or
                (bool(store.owner_name) and user.name.lower() == store.owner_name.lower())
            )
        if is_target_store_owner or user_id == current_user.user_id:
            raise ValidationException("Store owners cannot remove themselves from their own store.")

        # 2. Only the single store owner can remove administrators
        is_current_store_owner = bool(target_owner_id is not None and current_user.user_id == target_owner_id)
        if not target_owner_id:
            is_current_store_owner = bool(
                (bool(store.email) and current_user.email.lower() == store.email.lower()) or
                (bool(store.owner_name) and current_user.name.lower() == store.owner_name.lower())
            )
        if user.role == "admin" and not is_current_store_owner:
            raise ForbiddenException("Only the store owner can remove administrators from this store.")

        matched_stores = [s for s in user.accessible_stores if s.store_id == store.store_id]
        if matched_stores:
            for s in matched_stores:
                user.accessible_stores.remove(s)
            if user.current_store_id == store_id:
                other_stores = [s for s in user.accessible_stores if s.store_id != store_id and s.is_active]
                user.current_store_id = other_stores[0].store_id if other_stores else None
            # If user was promoted to admin by this store invitation, revert role to user if not in ADMIN_EMAILS
            from app.core.config import settings
            is_admin_email = user.email.lower() in [e.lower() for e in settings.ADMIN_EMAILS]
            if not is_admin_email and not user.accessible_stores:
                user.role = "user"
            db.commit()
        return True

    @staticmethod
    def revoke_store_invitation(
        db: Session, store_id: uuid.UUID, invitation_id: uuid.UUID, current_user: User
    ) -> bool:
        from app.models.invitation import StoreInvitation

        inv = (
            db.query(StoreInvitation)
            .filter(
                StoreInvitation.invitation_id == invitation_id,
                StoreInvitation.store_id == store_id,
            )
            .first()
        )
        if not inv:
            raise EntityNotFoundException("StoreInvitation", invitation_id)

        db.delete(inv)
        db.commit()
        return True

