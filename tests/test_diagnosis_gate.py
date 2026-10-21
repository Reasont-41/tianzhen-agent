from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.diagnosis import DiagnosisModule


def test_module_rejects_unsupported_crop_before_image_inference():
    module = DiagnosisModule()
    result = module.predict(b"not-an-image", crop="黄瓜")

    assert result.available is False
    assert result.error_code == "unsupported_crop"
    assert result.predictions == []
    assert "仅支持番茄" in result.message


def test_supported_crop_is_exposed_in_metadata():
    response = TestClient(app).get("/api/meta")

    assert response.status_code == 200
    assert response.json()["vision_model"]["supported_crops"] == ["番茄"]


def test_api_returns_friendly_cross_crop_message():
    response = TestClient(app).post(
        "/api/diagnose",
        data={"crop": "小麦"},
        files={"file": ("leaf.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["error_code"] == "unsupported_crop"
    assert "小麦" in payload["message"]
