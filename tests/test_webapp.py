from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Environment
from app.webapp import _llm_configured, app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_ok_returns_200_and_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.webapp._graph_loaded", lambda: True)
    monkeypatch.setattr("app.webapp._llm_configured", lambda: True)
    monkeypatch.setattr("app.webapp.get_version", lambda: "0.1.0")
    monkeypatch.setattr("app.webapp.get_environment", lambda: Environment.PRODUCTION)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "version": "0.1.0",
        "graph_loaded": True,
        "llm_configured": True,
        "env": "production",
    }


def test_health_unhealthy_returns_503_and_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.webapp._graph_loaded", lambda: False)
    monkeypatch.setattr("app.webapp._llm_configured", lambda: True)
    monkeypatch.setattr("app.webapp.get_version", lambda: "0.1.0")
    monkeypatch.setattr("app.webapp.get_environment", lambda: Environment.DEVELOPMENT)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "version": "0.1.0",
        "graph_loaded": False,
        "llm_configured": True,
        "env": "development",
    }


def test_health_payload_has_stable_keys(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.webapp._graph_loaded", lambda: True)
    monkeypatch.setattr("app.webapp._llm_configured", lambda: False)
    monkeypatch.setattr("app.webapp.get_version", lambda: "0.1.0")
    monkeypatch.setattr("app.webapp.get_environment", lambda: Environment.PRODUCTION)

    response = client.get("/health")

    assert sorted(response.json().keys()) == [
        "env",
        "graph_loaded",
        "llm_configured",
        "ok",
        "version",
    ]


def test_llm_configured_returns_false_for_misconfiguration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValidationError from bad LLM config should return False, not raise."""
    monkeypatch.setattr(
        "app.webapp.LLMSettings.from_env",
        lambda: (_ for _ in ()).throw(
            ValidationError.from_exception_data(
                title="LLMSettings",
                input_type="python",
                line_errors=[
                    {
                        "type": "value_error",
                        "loc": ("provider",),
                        "msg": "Value error, Unsupported LLM provider",
                        "input": "bad-provider",
                        "ctx": {"error": ValueError("Unsupported LLM provider")},
                    }
                ],
            )
        ),
    )

    assert _llm_configured() is False


def test_llm_configured_reraises_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-configuration exceptions must not be silently converted to False."""

    def _boom() -> None:
        raise RuntimeError("unexpected internal failure")

    monkeypatch.setattr("app.webapp.LLMSettings.from_env", _boom)

    with pytest.raises(RuntimeError, match="unexpected internal failure"):
        _llm_configured()

