from datetime import date, datetime, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.main import app
from app.core import get_kb, PrescriptionPipeline, SprayContext
from app.core.models import Prescription, PrescriptionItem
from app.core.spray_window import HourlyWeather, compute_spray_window

client = TestClient(app)


def external(**changes):
    item = dict(pesticide_name="烯酰吗啉", source_record_id="P0001", dosage_value=30,
                dosage_unit="克/亩", safety_interval_days=3)
    item.update(changes)
    return client.post("/api/prescription/validate", json={
        "crop": "番茄", "disease": "晚疫病", "harvest_in_days": 30,
        "history_applications": 0, "items": [item]}).json()


@pytest.mark.parametrize("change", [
    {"dosage_unit": "千克/亩"}, {"dosage_unit": "毫升/亩"}, {"dosage_value": None},
    {"dosage_unit": ""}, {"pesticide_name": "未知药剂ABC"},
    {"source_record_id": "INVALID"}, {"formulation": "错误剂型"},
    {"ai_content": "99%"}, {"active_ingredient": "其他成分"},
])
def test_external_mutations_cannot_pass(change):
    result = external(**change)
    assert not result["passed"]
    assert result["decision"] == "blocked"


def test_equivalent_unit_conversion_does_not_false_block():
    result = external(dosage_value=.03, dosage_unit="千克/亩")
    assert result["decision"] == "needs_review"  # 来源仍待核验
    dose = next(r for r in result["report"]["results"] if r["rule_id"] == "dosage_range")
    assert dose["passed"] and dose["evidence"]["normalized_value"] == 30


def test_shortened_interval_is_blocked_against_record():
    result = external(pesticide_name="代森锰锌", source_record_id="P0005", dosage_value=150, safety_interval_days=1)
    assert any(r["rule_id"] == "safety_interval" for r in result["report"]["blocking"])


def test_no_record_id_resolves_in_crop_and_target_context():
    result = client.post("/api/prescription/validate", json={"crop": "番茄", "disease": "早疫病",
        "harvest_in_days": 30, "history_applications": 0,
        "items": [{"pesticide_name": "嘧菌酯", "dosage_value": 40,
                   "dosage_unit": "毫升/亩", "safety_interval_days": 3}]}).json()
    assert not any(r["rule_id"] == "target_registered" for r in result["report"]["blocking"])
    assert result["decision"] == "needs_review"


@pytest.mark.parametrize("query", ["没有白毛，不是晚疫病", "不长白毛", "无黑杆也没白毛", "叶子黄了", "我想知道价格"])
def test_insufficient_or_negated_text_never_releases_medication(query):
    result = client.post("/api/consult", json={"crop": "番茄", "query": query}).json()
    assert result["prescription"]["items"] == []
    assert result["diagnosis_status"] in {"needs_clarification", "insufficient_evidence"}


def test_text_scores_are_not_probabilities_and_baseline_is_opt_in():
    result = client.post("/api/consult", json={"crop": "番茄", "query": "白毛，茎上有黑斑"}).json()
    assert result["diagnosis"]
    assert all("confidence" not in d for d in result["diagnosis"])
    assert "baseline_without_validator" not in result


@pytest.mark.parametrize("color", ["white", "black", "gray"])
def test_blank_images_rejected_before_backbone(color):
    data = BytesIO()
    Image.new("RGB", (224, 224), color).save(data, format="PNG")
    result = client.post("/api/diagnose", data={"crop": "番茄"},
                         files={"file": ("blank.png", data.getvalue(), "image/png")}).json()
    assert result["error_code"] == "image_quality"
    assert result["top1"] is None and not result["predictions"]


def test_windows_remove_elapsed_hours_and_harvest_conflicts():
    start = datetime(2026, 10, 17)
    weather = [HourlyWeather(start+timedelta(hours=h), 22, 65, 1, 0, 0) for h in range(72)]
    record = get_kb()._by_record_id["P0001"]
    result = compute_spray_window(weather, [], [{"start_hour": 6, "end_hour": 9}, {"start_hour": 16, "end_hour": 19}],
                                  record=record, planned_harvest_date=date(2026, 10, 20),
                                  now=datetime(2026, 10, 17, 12))
    assert len(result.daily_plans) == 1
    assert result.daily_plans[0]["date"] == "2026-10-17"
    assert result.daily_plans[0]["windows"][0]["start"] == "2026-10-17T16:00"
    assert result.to_dict()["is_simulated"] is True


def test_duplicate_product_rows_have_independent_verdicts():
    kb = get_kb()
    items = [PrescriptionItem("烯酰吗啉", dosage_value=v, dosage_unit="克/亩",
                              safety_interval_days=3, source_record_id="P0001") for v in (30, 3000)]
    context = SprayContext("番茄", "晚疫病", date(2026, 11, 20), date(2026, 10, 17), 0)
    report = PrescriptionPipeline(kb).engine.validate(Prescription("番茄", "晚疫病", items), context, kb.resolve_record_for_item)
    verdict = PrescriptionPipeline._per_item_verdict(Prescription("番茄", "晚疫病", items), report)
    assert verdict["0"]["decision"] == "needs_review"
    assert verdict["1"]["decision"] == "blocked"


def test_healthy_image_observation_needs_no_prescription():
    result = client.post("/api/consult", json={"crop": "番茄", "healthy_observation": True}).json()
    assert result["diagnosis_status"] == "healthy"
    assert not result["prescription"]["items"]
