from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.constraint_engine import ConstraintEngine
from app.core.models import PesticideRecord, Prescription, PrescriptionItem, SprayContext


@pytest.fixture
def record() -> PesticideRecord:
    return PesticideRecord(
        record_id="TEST-001",
        pesticide_name="测试药剂",
        crop="番茄",
        target="晚疫病",
        dosage="10-20克/亩",
        dosage_min=10,
        dosage_max=20,
        dosage_unit="克/亩",
        safety_interval_days=3,
        max_applications_per_season=2,
        source="测试登记记录",
        verification_status="official",
        reg_cert_no="PD-TEST",
    )


@pytest.fixture
def context() -> SprayContext:
    today = date.today()
    return SprayContext(
        crop="番茄",
        disease_name="晚疫病",
        application_date=today,
        planned_harvest_date=today + timedelta(days=5),
        history_applications=0,
    )


def make_item(**changes) -> PrescriptionItem:
    values = {
        "pesticide_name": "测试药剂",
        "dosage_value": 15,
        "dosage_unit": "克/亩",
        "safety_interval_days": 3,
        "source_record_id": "TEST-001",
    }
    values.update(changes)
    return PrescriptionItem(**values)


def validate(engine, item, context, record):
    prescription = Prescription(crop=context.crop, disease_name=context.disease_name, items=[item])
    return engine.validate(prescription, context, lambda _, ctx=None: record)


def failed(report, rule_id: str):
    return [r for r in report.results if r.rule_id == rule_id and not r.passed]


def test_all_eight_rules_accept_a_valid_item(record, context):
    report = validate(ConstraintEngine(), make_item(), context, record)

    assert report.passed
    assert not report.blocking
    assert {r.rule_id for r in report.results} == {
        "traceability",
        "banned",
        "restricted",
        "crop_registered",
        "target_registered",
        "dosage_range",
        "safety_interval",
        "max_applications",
    }


def test_traceability_blocks_unknown_record(context):
    report = validate(ConstraintEngine(), make_item(pesticide_name="未知药剂"), context, None)
    assert failed(report, "traceability")
    assert not report.passed


def test_banned_pesticide_is_one_vote_veto(record, context):
    report = validate(ConstraintEngine(banned_names={"测试药剂"}), make_item(), context, record)
    assert failed(report, "banned")
    assert not report.passed


def test_restricted_pesticide_blocks_vegetable_use(record, context):
    engine = ConstraintEngine(restricted_map={"测试药剂": "蔬菜上禁止使用"})
    report = validate(engine, make_item(), context, record)
    assert failed(report, "restricted")


def test_registered_crop_must_match(record, context):
    record.crop = "黄瓜"
    report = validate(ConstraintEngine(), make_item(), context, record)
    assert failed(report, "crop_registered")


def test_registered_target_must_match(record, context):
    record.target = "早疫病"
    report = validate(ConstraintEngine(), make_item(), context, record)
    assert failed(report, "target_registered")


@pytest.mark.parametrize("value", [10, 20])
def test_dosage_boundaries_are_inclusive(record, context, value):
    report = validate(ConstraintEngine(), make_item(dosage_value=value), context, record)
    assert not failed(report, "dosage_range")


@pytest.mark.parametrize("value", [9.99, 20.01])
def test_dosage_outside_range_is_blocked(record, context, value):
    report = validate(ConstraintEngine(), make_item(dosage_value=value), context, record)
    assert failed(report, "dosage_range")


def test_missing_safety_interval_is_blocked(record, context):
    report = validate(
        ConstraintEngine(), make_item(safety_interval_days=None), context, record
    )
    hit = failed(report, "safety_interval")
    assert hit
    assert hit[0].evidence["recoverable_from_record"] is True


def test_harvest_conflict_is_blocked(record, context):
    context.planned_harvest_date = context.application_date + timedelta(days=2)
    report = validate(ConstraintEngine(), make_item(), context, record)
    assert failed(report, "safety_interval")


def test_max_applications_blocks_another_use(record, context):
    context.history_applications = 2
    report = validate(ConstraintEngine(), make_item(), context, record)
    assert not report.passed
    assert any(r.rule_id == "max_applications" for r in report.blocking)


def test_empty_prescription_is_blocked(context):
    report = ConstraintEngine().validate(
        Prescription(crop="番茄", disease_name="晚疫病", items=[]),
        context,
        lambda _, ctx=None: None,
    )
    assert not report.passed
    assert report.results[0].rule_id == "non_empty"
