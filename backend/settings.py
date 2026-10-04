from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_enabled(self) -> bool:
        return self.production

    @classmethod
    def from_environment(cls) -> Settings:
        sqlite_path = Path(
            os.getenv(
                "SIH_DB_PATH",
                str(Path(__file__).resolve().parent / "data" / "sih.db"),
            )
        ).resolve()
        return cls(
            environment=os.getenv("APP_ENV", "development").strip().lower(),
            database_url=os.getenv("DATABASE_URL", "").strip()
            or f"sqlite+pysqlite:///{sqlite_path.as_posix()}",
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
            ollama_model=os.getenv("OLLAMA_MODEL", "").strip(),
            ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
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
        if not self.oidc_allowed_emails:
            raise ValueError("Production requires an explicit OIDC_ALLOWED_EMAILS allowlist.")
        if not self.public_base_url.startswith("https://"):
            raise ValueError("Production PUBLIC_BASE_URL must use HTTPS.")
        if not self.ollama_url.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_URL must be an HTTP(S) URL.")
