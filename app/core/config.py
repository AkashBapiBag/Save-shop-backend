from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "My Save Shop Management System API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Definitive backend REST API for My Save Shop Multi-Store Inventory & POS Billing"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database: Supports SQLite for rapid local testing/development and PostgreSQL for production
    DATABASE_URL: str = "sqlite:///./save_shop.db"

    # Google SSO Configuration
    GOOGLE_SSO_ENABLED: bool = True
    GOOGLE_CLIENT_ID: str = ""  # Google OAuth Client ID (Web/Server)
    GOOGLE_ALLOWED_CLIENT_IDS: list[str] = []  # Additional Client IDs (Android, iOS)
    ADMIN_EMAILS: list[str] = ["admin@saveshop.com"]  # Emails granted Admin privileges upon Google SSO
    ENABLE_DEV_DIRECT_LOGIN: bool = False  # Set to True only when running automated test suites

    # Auth0 Configuration
    AUTH0_ENABLED: bool = False  # Set to True when connected to real Auth0 tenant
    AUTH0_DOMAIN: str = "saveshop.us.auth0.com"
    AUTH0_API_AUDIENCE: str = "https://api.saveshop.com"
    AUTH0_ISSUER: str = ""
    AUTH0_ALGORITHMS: list[str] = ["RS256"]

    # Secret Key for Internal Session / JWT Signing in Dev Mode
    SECRET_KEY: str = "super-secret-save-shop-development-key-32-chars-long!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS configuration
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8081",
        "http://localhost:19006",
        "http://127.0.0.1:8081",
        "http://10.0.2.2:8081",
        "*",
    ]

    # Google Trigger & External Notifications
    GOOGLE_TRIGGER_WEBHOOK_SECRET: str = "saveshop-trigger-secret-key"
    WHATSAPP_API_ENABLED: bool = False
    WHATSAPP_API_KEY: str = "mock-whatsapp-api-key"
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "noreply@saveshop.com"

    @field_validator("AUTH0_ISSUER", mode="before")
    @classmethod
    def assemble_auth0_issuer(cls, v: str, info) -> str:
        if isinstance(v, str) and v:
            return v
        domain = info.data.get("AUTH0_DOMAIN", "saveshop.us.auth0.com")
        return f"https://{domain}/"


settings = Settings()
