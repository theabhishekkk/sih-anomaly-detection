from __future__ import annotations

import csv
import hmac
import io
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncGenerator
from urllib.parse import urlsplit

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

if __package__:
    from . import storage
    from .anomaly_service import detect_anomalies, screen_devices, train_calibration
    from .settings import Settings
else:
    import storage
    from anomaly_service import detect_anomalies, screen_devices, train_calibration
    from settings import Settings

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 5000
logger = logging.getLogger("burnin.api")


def _csv_records(contents: bytes) -> list[dict[str, str]]:
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("CSV files must be 5 MB or smaller.")
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV files must use UTF-8 encoding.") from error
    reader = csv.DictReader(io.StringIO(text))
    required = {"device_id", "value_0h", "value_24h"}
    headers = {header.strip() for header in (reader.fieldnames or []) if header}
    if not required.issubset(headers):
        missing = ", ".join(sorted(required - headers))
        raise ValueError(f"CSV is missing required columns: {missing}.")
    records: list[dict[str, str]] = []
    for row_number, row in enumerate(reader, start=2):
        if row_number > MAX_CSV_ROWS + 1:
            raise ValueError(f"CSV files may contain at most {MAX_CSV_ROWS} records.")
        records.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
    return records


def _service_error(error: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _demo_reference() -> list[dict[str, Any]]:
    records = []
    for index in range(30):
        value_0h = 9.8 + index * 0.014
        delta_24h = 0.19 + (index % 5) * 0.009
        forecast_error = (index % 7 - 3) * 0.025
        records.append(
            {
                "device_id": f"REF-{index + 1:03}",
                "lot_id": "REFERENCE-LOT-01",
                "parameter": "leakage_current_uA",
                "value_0h": round(value_0h, 3),
                "value_24h": round(value_0h + delta_24h, 3),
                "value_96h": round(value_0h + delta_24h * 4 + forecast_error, 3),
                "value_168h": round(value_0h + delta_24h * 7 + forecast_error, 3),
            }
        )
    return records


def _demo_production_lot() -> list[dict[str, Any]]:
    records = []
    for index in range(11):
        value_0h = 9.9 + (index % 5) * 0.035
        delta_24h = 0.18 + (index % 3) * 0.008
        records.append(
            {
                "device_id": f"SIH-{index + 1:03}",
                "lot_id": "DEMO-LOT-07",
                "parameter": "leakage_current_uA",
                "value_0h": round(value_0h, 3),
                "value_24h": round(value_0h + delta_24h, 3),
            }
        )
    records[7]["value_0h"] = 10.02
    records[7]["value_24h"] = 45
    return records


def create_app(
    db_path: str | Path | None = None, settings: Settings | None = None
) -> FastAPI:
    config = settings or Settings.from_environment()
    insights_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if config.production and insights_connection_string:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(connection_string=insights_connection_string)

    database_path: str | Path | None = db_path or (
        config.database_url if config.database_url else None
    )

    oauth = OAuth()
    if config.oidc_tenant_id and config.oidc_client_id and config.oidc_client_secret:
        metadata_url = (
            "https://login.microsoftonline.com/"
            f"{config.oidc_tenant_id}/v2.0/.well-known/openid-configuration"
        )
        oauth.register(
            name="entra",
            client_id=config.oidc_client_id,
            client_secret=config.oidc_client_secret,
            server_metadata_url=metadata_url,
            client_kwargs={"scope": "openid profile email"},
        )

    async def supabase_auth_request(
        path: str, *, payload: dict[str, Any] | None = None, access_token: str = ""
    ) -> Any:
        if not config.supabase_auth_enabled:
            raise HTTPException(status_code=503, detail="Supabase sign-in is not configured.")
        supabase_url = urlsplit(config.supabase_url)
        if (
            supabase_url.scheme != "https"
            or not supabase_url.netloc
            or supabase_url.path
            or supabase_url.query
            or supabase_url.fragment
            or any(character.isspace() for character in config.supabase_url)
        ):
            raise HTTPException(
                status_code=503,
                detail="SUPABASE_URL must be one HTTPS project URL without extra lines or paths.",
            )
        if config.supabase_publishable_key.startswith("sb_secret_"):
            raise HTTPException(
                status_code=503,
                detail=(
                    "SUPABASE_PUBLISHABLE_KEY must contain the Supabase publishable "
                    "key (or legacy anon key), not a secret key."
                ),
            )
        headers = {"apikey": config.supabase_publishable_key}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if payload is None:
                    response = await client.get(
                        f"{config.supabase_url}/auth/v1/{path}",
                        headers=headers,
                    )
                else:
                    response = await client.post(
                        f"{config.supabase_url}/auth/v1/{path}",
                        headers=headers,
                        json=payload,
                    )
        except httpx.HTTPError as error:
            logger.warning(
                "supabase_auth_unavailable",
                extra={"auth_path": path, "exception_type": type(error).__name__},
            )
            raise HTTPException(
                status_code=503, detail="Supabase authentication is unavailable."
            ) from error
        if response.status_code >= 500:
            raise HTTPException(
                status_code=503, detail="Supabase authentication is unavailable."
            )
        if response.is_error:
            raise HTTPException(status_code=401, detail="Supabase sign-in was rejected.")
        try:
            return response.json() if response.content else {}
        except ValueError as error:
            raise HTTPException(
                status_code=502, detail="Supabase returned an invalid authentication response."
            ) from error

    async def validate_supabase_access_token(access_token: str) -> dict[str, str]:
        result = await supabase_auth_request("user", access_token=access_token)
        user = result if isinstance(result, dict) else {}
        email = str(user.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="Sign in with your QA account.")
        if email not in config.allowed_emails:
            raise HTTPException(
                status_code=403, detail="This account is not authorized for screening."
            )
        metadata = user.get("user_metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return {
            "id": str(user.get("id") or ""),
            "email": email,
            "name": str(metadata.get("full_name") or metadata.get("name") or email),
        }

    def supabase_token_response(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Supabase returned an invalid session.")
        user = payload.get("user")
        if not isinstance(user, dict):
            raise HTTPException(status_code=502, detail="Supabase returned no signed-in user.")
        email = str(user.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="The account has no verified email.")
        if email not in config.allowed_emails:
            raise HTTPException(
                status_code=403, detail="This account is not authorized for screening."
            )
        return {
            "access_token": str(payload.get("access_token") or ""),
            "refresh_token": str(payload.get("refresh_token") or ""),
            "expires_in": payload.get("expires_in"),
            "token_type": payload.get("token_type", "bearer"),
            "user": {
                "id": str(user.get("id") or ""),
                "email": email,
                "name": str(
                    (
                        user.get("user_metadata")
                        if isinstance(user.get("user_metadata"), dict)
                        else {}
                    ).get("full_name")
                    or (
                        user.get("user_metadata")
                        if isinstance(user.get("user_metadata"), dict)
                        else {}
                    ).get("name")
                    or email
                ),
            },
        }

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncGenerator[None, None]:
        config.validate()
        if not config.production:
            storage.initialize(database_path)
        else:
            storage.check_database(database_path)
        yield

    application = FastAPI(
        title="SIH Burn-In Screening",
        description="Lot-calibrated anomaly detection, drift screening, and QA audit logging.",
        version="1.0.0",
        docs_url=None if config.production else "/docs",
        redoc_url=None if config.production else "/redoc",
        openapi_url=None if config.production else "/openapi.json",
        lifespan=lifespan,
    )
    application.state.db_path = database_path
    application.state.settings = config
    application.state.oauth = oauth

    @application.middleware("http")
    async def enforce_production_access(request: Request, call_next):
        started_at = perf_counter()
        public_paths = {
            "/health",
            "/health/ready",
            "/auth/login",
            "/auth/callback",
            "/api/auth/config",
            "/api/auth/login",
            "/api/auth/refresh",
            "/api/auth/logout",
            "/api/demo",
        }
        response = None
        if config.production:
            path = request.url.path
            is_static_asset = path.startswith("/assets/")
            is_auth_api = path.startswith("/api/auth/")
            is_api = path.startswith("/api/")
            if (
                config.supabase_auth_enabled
                and is_api
                and path not in public_paths
                and not is_auth_api
            ):
                authorization = request.headers.get("authorization", "")
                scheme, separator, access_token = authorization.partition(" ")
                if not separator or scheme.lower() != "bearer" or not access_token:
                    response = JSONResponse(
                        {"detail": "Sign in with your QA account."},
                        status_code=401,
                    )
                else:
                    try:
                        request.state.supabase_user = await validate_supabase_access_token(
                            access_token
                        )
                    except HTTPException as error:
                        response = JSONResponse(
                            {"detail": error.detail}, status_code=error.status_code
                        )
            elif not config.supabase_auth_enabled and path not in public_paths and not is_static_asset:
                if not request.session.get("user"):
                    if is_api:
                        response = JSONResponse(
                            {"detail": "Sign in with your organization account."},
                            status_code=401,
                        )
                    else:
                        response = RedirectResponse("/auth/login", status_code=303)
                elif (
                    request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    and is_api
                ):
                    expected = request.session.get("csrf_token", "")
                    supplied = request.headers.get("x-csrf-token", "")
                    if not expected or not hmac.compare_digest(expected, supplied):
                        response = JSONResponse(
                            {"detail": "CSRF token is missing or invalid."},
                            status_code=403,
                        )

        if response is None:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if config.production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        route = request.scope.get("route")
        logger.info(
            "http_request",
            extra={
                "http_method": request.method,
                "http_route": getattr(route, "path", "unmatched"),
                "http_status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return response

    application.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret or "development-only-session-secret-change-me",
        same_site="lax",
        https_only=config.production,
        max_age=8 * 60 * 60,
    )

    @application.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    application.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    def readiness() -> dict[str, str]:
        try:
            storage.check_database(database_path)
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="Database is unavailable.") from error
        return {"status": "ready"}

    @application.get("/api/csrf")
    def csrf_token(request: Request) -> dict[str, str]:
        token = request.session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            request.session["csrf_token"] = token
        return {"csrf_token": token}

    @application.get("/api/auth/config")
    def auth_config() -> dict[str, Any]:
        return {
            "supabase_enabled": config.supabase_auth_enabled,
            "entra_enabled": config.auth_enabled and not config.supabase_auth_enabled,
        }

    @application.get("/api/demo")
    def demo() -> dict[str, Any]:
        try:
            calibration = train_calibration(_demo_reference(), direction="higher")
            report = screen_devices(_demo_production_lot(), calibration)
        except ValueError as error:
            raise _service_error(error) from error
        return {"calibration": calibration, "report": report}

    @application.post("/api/auth/login")
    async def supabase_login(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        email = str(payload.get("email") or "").strip().lower()
        password = payload.get("password")
        if not email or not isinstance(password, str) or not password:
            raise HTTPException(status_code=400, detail="Email and password are required.")
        result = await supabase_auth_request(
            "token?grant_type=password",
            payload={"email": email, "password": password},
        )
        return supabase_token_response(result)

    @application.post("/api/auth/refresh")
    async def supabase_refresh(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise HTTPException(status_code=400, detail="A Supabase refresh token is required.")
        result = await supabase_auth_request(
            "token?grant_type=refresh_token",
            payload={"refresh_token": refresh_token},
        )
        return supabase_token_response(result)

    @application.post("/api/auth/logout")
    async def supabase_logout(request: Request) -> dict[str, str]:
        authorization = request.headers.get("authorization", "")
        scheme, separator, access_token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and access_token:
            await supabase_auth_request("logout", access_token=access_token)
        return {"status": "signed_out"}

    @application.get("/api/whoami")
    def whoami(request: Request) -> dict[str, Any]:
        supabase_user = getattr(request.state, "supabase_user", None)
        if supabase_user:
            return {"authenticated": True, "user": supabase_user}
        user = request.session.get("user") if config.production else None
        return {"authenticated": bool(user), "user": user}

    @application.get("/auth/login", include_in_schema=False)
    async def auth_login(request: Request):
        if not config.auth_enabled or config.supabase_auth_enabled:
            return RedirectResponse("/", status_code=303)
        if oauth.create_client("entra") is None:
            raise HTTPException(status_code=503, detail="Organization sign-in is not configured.")
        redirect_uri = f"{config.public_base_url}/auth/callback"
        return await oauth.entra.authorize_redirect(request, redirect_uri)

    @application.get("/auth/callback", name="auth_callback", include_in_schema=False)
    async def auth_callback(request: Request):
        if not config.auth_enabled or config.supabase_auth_enabled:
            return RedirectResponse("/", status_code=303)
        try:
            token = await oauth.entra.authorize_access_token(request)
        except OAuthError as error:
            raise HTTPException(status_code=401, detail="Organization sign-in failed.") from error
        claims = token.get("userinfo")
        if not isinstance(claims, dict):
            raise HTTPException(status_code=401, detail="Sign-in returned no verified identity.")
        tenant_id = str(claims.get("tid") or "")
        if tenant_id.lower() != config.oidc_tenant_id.lower():
            request.session.clear()
            raise HTTPException(status_code=403, detail="This account belongs to a different tenant.")
        email = str(
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
            or ""
        ).strip().lower()
        if not email or email not in config.oidc_allowed_emails:
            request.session.clear()
            raise HTTPException(status_code=403, detail="This account is not authorized.")
        request.session.clear()
        request.session["user"] = {
            "email": email,
            "name": str(claims.get("name") or email),
        }
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)

    @application.post("/auth/logout", include_in_schema=False)
    async def auth_logout(request: Request):
        if config.production:
            expected = request.session.get("csrf_token", "")
            supplied = request.headers.get("x-csrf-token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                raise HTTPException(status_code=403, detail="CSRF token is missing or invalid.")
        request.session.clear()
        return {"status": "signed_out"}

    @application.get("/api/state")
    def get_state() -> dict[str, Any]:
        calibration = storage.load_snapshot(database_path, "calibration")
        screening = storage.load_snapshot(database_path, "screening")
        return {
            "calibration": calibration,
            "screening": screening,
            "decisions": storage.list_decisions(database_path, limit=20),
        }

    @application.post("/api/calibration")
    def calibrate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            result = train_calibration(
                payload.get("reference"),
                safety_slope=payload.get("safety_slope"),
                direction=payload.get("direction", "higher"),
            )
        except ValueError as error:
            raise _service_error(error) from error
        timestamp = storage.save_snapshot(database_path, "calibration", result)
        return {"calibration": result, "created_at": timestamp}

    @application.post("/api/calibration/upload")
    async def upload_calibration(
        file: UploadFile = File(...),
        direction: str = Form("higher"),
        safety_slope: float | None = Form(None),
    ) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Upload a .csv reference file.")
        try:
            records = _csv_records(await file.read(MAX_UPLOAD_BYTES + 1))
            result = train_calibration(
                records,
                direction=direction,
                safety_slope=safety_slope,
            )
        except ValueError as error:
            raise _service_error(error) from error
        finally:
            await file.close()
        timestamp = storage.save_snapshot(database_path, "calibration", result)
        return {"calibration": result, "created_at": timestamp}

    @application.post("/api/screen")
    def screen(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            report = screen_devices(
                payload.get("devices"),
                (
                    storage.load_snapshot(database_path, "calibration") or {}
                ).get("data"),
                safety_slope=payload.get("safety_slope"),
            )
        except ValueError as error:
            raise _service_error(error) from error
        timestamp = storage.save_snapshot(database_path, "screening", report)
        return {**report, "created_at": timestamp}

    @application.post("/api/screen/upload")
    async def upload_screening(
        file: UploadFile = File(...),
        safety_slope: float | None = Form(None),
    ) -> dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Upload a .csv screening file.")
        try:
            records = _csv_records(await file.read(MAX_UPLOAD_BYTES + 1))
            report = screen_devices(
                records,
                (
                    storage.load_snapshot(database_path, "calibration") or {}
                ).get("data"),
                safety_slope=safety_slope,
            )
        except ValueError as error:
            raise _service_error(error) from error
        finally:
            await file.close()
        timestamp = storage.save_snapshot(database_path, "screening", report)
        return {**report, "created_at": timestamp}

    @application.get("/api/devices/{device_id}/explain")
    async def explain_device(device_id: str) -> dict[str, Any]:
        snapshot = storage.load_snapshot(database_path, "screening")
        if not snapshot:
            raise HTTPException(status_code=404, detail="No screening report is available.")
        report = snapshot["data"]
        evidence = [
            item for item in report["devices"] if item["device_id"] == device_id
        ]
        if not evidence:
            raise HTTPException(status_code=404, detail="Device was not found in the latest lot.")
        deterministic_explanation = " ".join(
            f"{item['parameter']}: {item['reason']}" for item in evidence
        )
        model = config.ollama_model
        if not model:
            return {
                "explanation": deterministic_explanation,
                "source": "screening evidence",
                "llm_status": "not_configured",
            }

        base_url = config.ollama_url
        prompt = (
            "Explain this component screening evidence for a QA engineer. "
            "Use only the supplied evidence, do not invent causes, and state that this is "
            f"decision support, not a substitute for QA approval.\n{deterministic_explanation}"
        )
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(
                    f"{base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": (
                            f"{prompt}\nStructured device measurements and Shapley "
                            f"attributions:\n{json.dumps(evidence)}"
                        ),
                        "stream": False,
                    },
                )
                response.raise_for_status()
                body = response.json()
                generated = body.get("response") if isinstance(body, dict) else None
                if not isinstance(generated, str) or not generated.strip():
                    raise ValueError("Ollama returned an empty explanation.")
        except (httpx.HTTPError, ValueError) as error:
            return {
                "explanation": deterministic_explanation,
                "source": "screening evidence",
                "llm_status": "unavailable",
                "llm_error": str(error),
            }
        return {
            "explanation": generated.strip(),
            "source": f"local Ollama model: {model}",
            "llm_status": "available",
        }

    @application.post("/api/decisions", status_code=201)
    def log_decision(
        request: Request, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        device_id = str(payload.get("device_id", "")).strip()
        action = str(payload.get("action", "")).strip()
        if config.production:
            authenticated_user = request.session.get("user")
            inspector = (
                str(authenticated_user.get("email") or "").strip()
                if isinstance(authenticated_user, dict)
                else ""
            )
            if not inspector:
                raise HTTPException(status_code=401, detail="Sign in before recording a decision.")
        else:
            inspector = str(payload.get("inspector", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        if not device_id or not inspector or not reason:
            raise HTTPException(
                status_code=400,
                detail="device_id, inspector, and a decision reason are required.",
            )
        if action not in {"approve_rejection", "override_flag"}:
            raise HTTPException(status_code=400, detail="Unsupported QA decision.")
        screening_snapshot = storage.load_snapshot(database_path, "screening")
        report = screening_snapshot["data"] if screening_snapshot else None
        matching = [
            item for item in (report or {}).get("devices", [])
            if item["device_id"] == device_id
        ]
        if not matching:
            raise HTTPException(
                status_code=404, detail="Device is not in the latest screening report."
            )
        if action == "approve_rejection" and not any(item["flagged"] for item in matching):
            raise HTTPException(
                status_code=409, detail="Only a flagged device can be approved for rejection."
            )
        if action == "override_flag" and not any(item["flagged"] for item in matching):
            raise HTTPException(
                status_code=409, detail="Only a flagged device can have its flag overridden."
            )
        try:
            decision = storage.save_decision(
                database_path,
                device_id=device_id,
                action=action,
                inspector=inspector,
                reason=reason,
                evidence={"device_results": matching},
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=500, detail="Could not persist QA decision.") from error
        return decision

    @application.get("/api/audit")
    def audit(limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 500.")
        return {"decisions": storage.list_decisions(database_path, limit)}

    @application.post("/api/analyze")
    def analyze(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        values = payload.get("values")
        if not isinstance(values, list):
            raise HTTPException(
                status_code=400, detail="The 'values' field must be a list of numbers."
            )
        try:
            result = detect_anomalies(values, threshold=payload.get("threshold", 3.0))
        except (TypeError, ValueError) as error:
            raise _service_error(ValueError(str(error))) from error
        return result

    return application


app = create_app()
