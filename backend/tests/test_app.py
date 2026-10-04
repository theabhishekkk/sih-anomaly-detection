import pytest
from fastapi.testclient import TestClient

import app as backend_app
from app import create_app
from settings import Settings
import storage


@pytest.fixture
def client(tmp_path):
    application = create_app(tmp_path / "screening.sqlite3")
    with TestClient(application) as test_client:
        yield test_client


def reference_lot():
    return [
        {
            "device_id": f"REF-{index}",
            "parameter": "iddq",
            "value_0h": 10 + index * 0.01,
            "value_24h": 10.2 + index * 0.01,
            "value_168h": 11.4 + index * 0.01,
        }
        for index in range(20)
    ]


def test_dashboard_and_static_assets_are_served(client):
    assert client.get("/").status_code == 200
    assert "SIH" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    assert client.get("/").headers["content-security-policy"].startswith("default-src 'self'")


def test_production_requires_secure_postgres_and_allowlisted_oidc():
    settings = Settings(
        environment="production",
        database_url="sqlite+pysqlite:///insecure.db",
        session_secret="short",
        oidc_tenant_id="",
        oidc_client_id="",
        oidc_client_secret="",
        oidc_allowed_emails=frozenset(),
        public_base_url="http://localhost",
        ollama_model="",
        ollama_url="http://127.0.0.1:11434",
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        settings.validate()


def test_render_external_url_is_used_as_the_production_origin(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://sih-burnin.onrender.com/")

    assert Settings.from_environment().public_base_url == "https://sih-burnin.onrender.com"


def test_production_auth_requires_login_csrf_and_allowlisted_identity(
    tmp_path, monkeypatch
):
    database = tmp_path / "production.sqlite3"
    storage.initialize(database)
    monkeypatch.setattr(storage, "check_database", lambda _: True)
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://burnin:secret@localhost/burnin",
        session_secret="a-production-session-secret-that-is-at-least-32-bytes",
        oidc_tenant_id="tenant-123",
        oidc_client_id="client-123",
        oidc_client_secret="oidc-secret",
        oidc_allowed_emails=frozenset({"qa@example.com"}),
        public_base_url="https://burnin.example.com",
        ollama_model="",
        ollama_url="http://127.0.0.1:11434",
    )
    application = create_app(database, settings)

    async def fake_authorize_access_token(request):
        return {
            "userinfo": {
                "tid": "tenant-123",
                "preferred_username": "qa@example.com",
                "name": "QA Engineer",
            }
        }

    monkeypatch.setattr(
        application.state.oauth.entra,
        "authorize_access_token",
        fake_authorize_access_token,
    )
    with TestClient(application, base_url="https://testserver") as client:
        assert client.get("/", follow_redirects=False).status_code == 303
        unauthorized = client.get("/api/state")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["x-content-type-options"] == "nosniff"
        login = client.get("/auth/callback", follow_redirects=False)
        assert login.status_code == 303
        assert client.get("/api/whoami").json()["user"]["email"] == "qa@example.com"
        assert client.post(
            "/api/calibration", json={"reference": reference_lot()}
        ).status_code == 403
        csrf = client.get("/api/csrf").json()["csrf_token"]
        assert client.post(
            "/api/calibration",
            json={"reference": reference_lot()},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 200
        screened = client.post(
            "/api/screen",
            json={
                "devices": [
                    {
                        "device_id": "PROD-1",
                        "parameter": "iddq",
                        "value_0h": 10,
                        "value_24h": 45,
                    }
                ]
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert screened.status_code == 200
        decision = client.post(
            "/api/decisions",
            json={
                "device_id": "PROD-1",
                "action": "approve_rejection",
                "inspector": "spoofed@example.com",
                "reason": "Confirmed abnormal drift.",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert decision.status_code == 201
        assert decision.json()["inspector"] == "qa@example.com"


def test_calibration_screening_explain_and_durable_qa_audit(client):
    calibrated = client.post(
        "/api/calibration",
        json={"reference": reference_lot(), "safety_slope": 100},
    )
    assert calibrated.status_code == 200

    screened = client.post(
        "/api/screen",
        json={
            "safety_slope": 100,
            "devices": [
                {
                    "device_id": "BAD-1",
                    "parameter": "iddq",
                    "value_0h": 10,
                    "value_24h": 45,
                }
            ],
        },
    )
    assert screened.status_code == 200
    assert screened.json()["summary"]["flagged_devices"] == 1

    explanation = client.get("/api/devices/BAD-1/explain")
    assert explanation.status_code == 200
    assert explanation.json()["llm_status"] == "not_configured"
    assert "robust z-score" in explanation.json()["explanation"]

    decision = client.post(
        "/api/decisions",
        json={
            "device_id": "BAD-1",
            "action": "approve_rejection",
            "inspector": "QA Engineer",
            "reason": "Confirmed abnormal leakage-current drift.",
        },
    )
    assert decision.status_code == 201
    audit = client.get("/api/audit").json()["decisions"]
    assert audit[0]["action"] == "approve_rejection"
    assert audit[0]["evidence"]["device_results"][0]["flagged"] is True

    persisted_state = client.get("/api/state").json()
    assert persisted_state["calibration"]["data"]["device_count"] == 20
    assert persisted_state["screening"]["data"]["summary"]["flagged_devices"] == 1


def test_csv_upload_and_validation(client):
    response = client.post(
        "/api/calibration/upload",
        files={
            "file": (
                "known-good.csv",
                b"device_id,parameter,value_0h,value_24h,value_168h\n"
                b"R1,iddq,10,10.2,11.4\nR2,iddq,10.1,10.3,11.5\n"
                b"R3,iddq,10.2,10.4,11.6\nR4,iddq,10.3,10.5,11.7\n"
                b"R5,iddq,10.4,10.6,11.8\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 200

    screen = client.post(
        "/api/screen/upload",
        files={
            "file": (
                "lot.csv",
                b"device_id,parameter,value_0h,value_24h\nD1,iddq,10,45\n",
                "text/csv",
            )
        },
    )
    assert screen.status_code == 200
    assert screen.json()["devices"][0]["flagged"] is True

    invalid = client.post(
        "/api/calibration/upload",
        files={"file": ("bad.csv", b"device_id,foo\nA,1\n", "text/csv")},
    )
    assert invalid.status_code == 400


def test_bad_decisions_and_uncalibrated_screening_are_rejected(client):
    assert client.post(
        "/api/screen",
        json={"devices": [{"device_id": "D1", "value_0h": 1, "value_24h": 2}]},
    ).status_code == 400
    assert client.post(
        "/api/decisions",
        json={
            "device_id": "missing",
            "action": "approve_rejection",
            "inspector": "QA",
            "reason": "review",
        },
    ).status_code == 404


def test_calibration_and_audit_survive_application_restart(tmp_path):
    database = tmp_path / "persisted.sqlite3"
    with TestClient(create_app(database)) as first_client:
        first_client.post("/api/calibration", json={"reference": reference_lot()})
        first_client.post(
            "/api/screen",
            json={
                "devices": [
                    {
                        "device_id": "BAD-2",
                        "parameter": "iddq",
                        "value_0h": 10,
                        "value_24h": 45,
                    }
                ]
            },
        )
        first_client.post(
            "/api/decisions",
            json={
                "device_id": "BAD-2",
                "action": "approve_rejection",
                "inspector": "QA",
                "reason": "Confirmed by review.",
            },
        )

    with TestClient(create_app(database)) as restarted_client:
        state = restarted_client.get("/api/state").json()
    assert state["calibration"]["data"]["device_count"] == 20
    assert state["screening"]["data"]["summary"]["flagged_devices"] == 1
    assert state["decisions"][0]["device_id"] == "BAD-2"


def test_local_ollama_path_receives_the_measurements_and_shap_evidence(
    tmp_path, monkeypatch
):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "The 24-hour reading is far above the baseline."}

    class FakeAsyncClient:
        def __init__(self, timeout):
            assert timeout == 12.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setenv("OLLAMA_MODEL", "local-test-model")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(backend_app.httpx, "AsyncClient", FakeAsyncClient)
    with TestClient(create_app(tmp_path / "ollama.sqlite3")) as client:
        client.post("/api/calibration", json={"reference": reference_lot()})
        client.post(
            "/api/screen",
            json={
                "devices": [
                    {
                        "device_id": "BAD-3",
                        "parameter": "iddq",
                        "value_0h": 10,
                        "value_24h": 45,
                    }
                ]
            },
        )

        response = client.get("/api/devices/BAD-3/explain")
        assert response.json()["llm_status"] == "available"
    assert "Shapley attributions" in captured["prompt"]
    assert "shap_value" in captured["prompt"]


def test_csv_helper_imports_are_not_needed_for_api_payloads(client):
    response = client.post(
        "/api/analyze",
        json={"values": [10, 10, 10, 45], "threshold": 3},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["anomaly_count"] == 1
