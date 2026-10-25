from typing import Any

from fastapi import HTTPException, status


class AppException(HTTPException):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Any | None = None,
    ):
        super().__init__(
            status_code=status_code,
            detail={
                "error_code": error_code,
                "message": message,
                "details": details,
            },
        )
        self.error_code = error_code
        self.message = message
        self.details = details


class EntityNotFoundException(AppException):
    def __init__(self, entity_name: str, identifier: Any):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            message=f"{entity_name} with identifier '{identifier}' was not found.",
        )


class DuplicateEntityException(AppException):
    def __init__(self, entity_name: str, field_name: str, value: Any):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            error_code="DUPLICATE_ENTITY",
            message=f"{entity_name} with {field_name}='{value}' already exists.",
        )


class InsufficientStockException(AppException):
    def __init__(
        self,
        product_name: str,
        product_id: Any,
        requested: float,
        available: float,
    ):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INSUFFICIENT_STOCK",
            message=(
                f"Insufficient stock for product '{product_name}' (ID: {product_id}). Requested: {requested}, Available: {available}."
            ),
            details={
                "product_id": str(product_id),
                "product_name": product_name,
                "requested": float(requested),
                "available": float(available),
            },
        )


class StoreCreationIntegrityException(AppException):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            error_code="STORE_CREATION_INTEGRITY_VIOLATION",
            message=message,
            details=details,
        )


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Invalid or expired authentication credentials."):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="UNAUTHORIZED",
            message=message,
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="FORBIDDEN",
            message=message,
        )


class ValidationException(AppException):
    def __init__(self, message: str, details: Any | None = None):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="VALIDATION_ERROR",
            message=message,
            details=details,
        )
