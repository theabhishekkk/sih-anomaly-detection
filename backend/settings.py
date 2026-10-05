from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url


def normalize_database_url(database_url: str) -> str:
    """Use the installed Psycopg 3 driver for PostgreSQL URLs."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        return url.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        )
    return database_url


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    session_secret: str
    oidc_tenant_id: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_allowed_emails: frozenset[str]
    public_base_url: str
    ollama_model: str
    ollama_url: str
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    auth_allowed_emails: frozenset[str] = frozenset()

    @property
    def allowed_emails(self) -> frozenset[str]:
        return self.auth_allowed_emails or self.oidc_allowed_emails

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_enabled(self) -> bool:
        return self.production

    @property
    def supabase_auth_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    @classmethod
    def from_environment(cls) -> Settings:
        sqlite_path = Path(
            os.getenv(
                "SIH_DB_PATH",
                str(Path(__file__).resolve().parent / "data" / "sih.db"),
            )
        ).resolve()
        environment = os.getenv("APP_ENV", "development").strip().lower()
        if os.getenv("RENDER_EXTERNAL_URL", "").strip():
            environment = "production"
        return cls(
            environment=environment,
            database_url=normalize_database_url(
                os.getenv("DATABASE_URL", "").strip()
                or f"sqlite+pysqlite:///{sqlite_path.as_posix()}"
            ),
            session_secret=os.getenv("APP_SESSION_SECRET", ""),
            oidc_tenant_id=os.getenv("OIDC_TENANT_ID", "").strip(),
            oidc_client_id=os.getenv("OIDC_CLIENT_ID", "").strip(),
            oidc_client_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
            oidc_allowed_emails=frozenset(
                email.strip().lower()
                for email in os.getenv("OIDC_ALLOWED_EMAILS", "").split(",")
                if email.strip()
            ),
            public_base_url=(
                os.getenv("PUBLIC_BASE_URL", "").strip()
                or os.getenv("RENDER_EXTERNAL_URL", "").strip()
            ).rstrip("/"),
            ollama_model=os.getenv(
                "OLLAMA_MODEL",
                "qwen3:4b" if environment == "development" else "",
            ).strip(),
            ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            auth_allowed_emails=frozenset(
                email.strip().lower()
                for email in (
                    os.getenv("AUTH_ALLOWED_EMAILS", "")
                    or os.getenv("OIDC_ALLOWED_EMAILS", "")
                ).split(",")
                if email.strip()
            ),
        )

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production.")
        if not self.production:
            return
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Production requires a PostgreSQL DATABASE_URL using psycopg.")
        if len(self.session_secret) < 32:
            raise ValueError("Production APP_SESSION_SECRET must be at least 32 characters.")
        if not self.allowed_emails:
            raise ValueError("Production requires an explicit AUTH_ALLOWED_EMAILS allowlist.")
        if self.supabase_url or self.supabase_publishable_key:
            if not self.supabase_url.startswith("https://"):
                raise ValueError("Production SUPABASE_URL must use HTTPS.")
            if not self.supabase_publishable_key:
                raise ValueError("SUPABASE_PUBLISHABLE_KEY is required with SUPABASE_URL.")
        else:
            missing = [
                name
                for name, value in (
                    ("OIDC_TENANT_ID", self.oidc_tenant_id),
                    ("OIDC_CLIENT_ID", self.oidc_client_id),
                    ("OIDC_CLIENT_SECRET", self.oidc_client_secret),
                    ("PUBLIC_BASE_URL", self.public_base_url),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"Production authentication is missing: {', '.join(missing)}.")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("Production PUBLIC_BASE_URL must use HTTPS.")
        if not self.ollama_url.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_URL must be an HTTP(S) URL.")
