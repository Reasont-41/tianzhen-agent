from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import MAX_UPLOAD_BYTES, app


client = TestClient(app)


def test_empty_consultation_is_rejected_instead_of_saved_as_a_result():
    response = client.post(
        "/api/consult",
        json={"crop": "番茄", "query": "   ", "show_baseline": False},
    )

    assert response.status_code == 400
    assert "症状描述" in response.json()["detail"]


def test_crop_and_disease_pair_must_be_supported():
    response = client.post(
        "/api/consult",
        json={"crop": "小麦", "disease": "晚疫病", "query": "叶片有病斑"},
    )

    assert response.status_code == 400
    assert "覆盖范围" in response.json()["detail"]


def test_numeric_boundaries_are_enforced_by_request_schema():
    response = client.post(
        "/api/consult",
        json={"crop": "番茄", "query": "叶片有病斑", "harvest_in_days": -1},
    )

    assert response.status_code == 422


def test_unverified_seed_data_is_never_reported_as_field_ready():
    response = client.post(
        "/api/consult",
        json={"crop": "番茄", "query": "叶子背面长白毛，茎上有黑斑"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_items"]
    assert payload["released_items"] == []
    assert payload["review_required"] is True
    assert payload["ready_for_field_use"] is False


def test_diagnosis_rejects_unsupported_media_type():
    response = client.post(
        "/api/diagnose",
        data={"crop": "番茄"},
        files={"file": ("leaf.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415
    assert "JPEG" in response.json()["detail"]


def test_diagnosis_rejects_oversized_upload_before_inference():
    response = client.post(
        "/api/diagnose",
        data={"crop": "番茄"},
        files={"file": ("leaf.jpg", b"0" * (MAX_UPLOAD_BYTES + 1), "image/jpeg")},
    )

    assert response.status_code == 413


def test_root_exposes_current_brand_and_security_headers():
    response = client.get("/")

    assert response.status_code == 200
    assert "田诊卫士" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"

