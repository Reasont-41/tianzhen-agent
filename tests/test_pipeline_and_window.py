from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core import ConstrainedGenerator, PrescriptionPipeline, SprayContext, get_kb
from app.core.spray_window import HourlyWeather, compute_spray_window


def test_text_consultation_completes_generation_validation_traceability_loop():
    kb = get_kb()
    context = SprayContext(
        crop="番茄",
        disease_name="晚疫病",
        application_date=date.today(),
        planned_harvest_date=date.today() + timedelta(days=20),
    )
    result = PrescriptionPipeline(kb, ConstrainedGenerator(kb)).run(
        query="叶子背面长白毛，茎上有黑斑",
        crop="番茄",
        context=context,
    )

    assert result.disease_name == "晚疫病"
    assert result.review_items
    assert not result.released_items
    assert len(result.traceability) == len(result.review_items)
    assert all(item.source_record_id for item in result.review_items)


def test_spray_window_is_narrowed_to_preferred_farming_hours():
    day = date.today()
    weather = [
        HourlyWeather(
            ts=datetime.combine(day, datetime.min.time()) + timedelta(hours=hour),
            temp_c=22,
            humidity_pct=65,
            wind_speed_ms=1,
            precip_mm=0,
            precip_prob_next_6h=0,
        )
        for hour in range(24)
    ]
    result = compute_spray_window(
        weather,
        rules=[],
        preferred_windows=[
            {"start_hour": 6, "end_hour": 9},
            {"start_hour": 16, "end_hour": 19},
        ],
        now=datetime.combine(day, datetime.min.time()),
    )

    starts = [window["start"][11:] for window in result.daily_plans[0]["windows"]]
    assert starts == ["06:00", "16:00"]
    assert all(window["preferred"] for window in result.daily_plans[0]["windows"])
