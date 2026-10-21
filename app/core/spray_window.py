"""施药窗口期模块。

输入未来若干小时的逐时气象数据，输出"哪些时段适宜施药、哪些不宜、原因是什么"。

价值在于把诊断结果继续推进到"能直接执行的农事动作"——这是现有农业识别类软件
普遍缺失的一环：它们止步于"识别出是什么病"，农户真正的问题是"那我什么时候去打药"。

气象数据通过 WeatherProvider 抽象注入，便于：
  * 离线演示时使用确定性模拟数据（保证演示结果可复现）；
  * 生产环境接入真实气象 API（如和风天气）而不改动规则层。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from .models import PesticideRecord


def china_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


# ---------------------------------------------------------------- 气象数据


@dataclass
class HourlyWeather:
    ts: datetime
    temp_c: float
    humidity_pct: float
    wind_speed_ms: float
    precip_mm: float
    precip_prob_next_6h: float  # 未来6小时降雨概率（%）


class WeatherProvider(Protocol):
    def forecast(self, lat: float, lon: float, hours: int = 72) -> list[HourlyWeather]: ...


class MockWeatherProvider:
    """确定性模拟气象源。

    用固定种子生成，保证每次演示与实验的输入完全一致 —— 这对可复现的实验很重要。
    """

    def __init__(self, seed: int = 20261004):
        self.seed = seed

    def forecast(self, lat: float = 39.9, lon: float = 116.4, hours: int = 72) -> list[HourlyWeather]:
        rng = random.Random(self.seed)
        current = china_now()
        start = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        out: list[HourlyWeather] = []
        rain_front = rng.random() * 30 + 20  # 降雨过程出现在未来第 20-50 小时
        for h in range(hours):
            ts = start + timedelta(hours=h)
            hour = ts.hour
            # 日温曲线
            temp = 18 + 9 * math.sin((hour - 8) / 24 * 2 * math.pi) + rng.gauss(0, 0.8)
            # 午后风速抬升
            wind = 1.6 + 2.6 * max(0.0, math.sin((hour - 10) / 24 * 2 * math.pi)) + abs(rng.gauss(0, 0.5))
            humidity = 62 + 22 * math.sin((hour - 2) / 24 * 2 * math.pi) + rng.gauss(0, 4)

            near_rain = 8 <= h <= rain_front + 8
            precip_prob = 78.0 if near_rain else max(0.0, 18 + rng.gauss(0, 6))
            precip = 0.0
            if rain_front <= h <= rain_front + 6:
                precip = round(abs(rng.gauss(4.5, 2.0)), 2)

            out.append(
                HourlyWeather(
                    ts=ts,
                    temp_c=round(temp, 1),
                    humidity_pct=round(min(max(humidity, 20), 99), 1),
                    wind_speed_ms=round(max(wind, 0.2), 2),
                    precip_mm=precip,
                    precip_prob_next_6h=round(min(precip_prob, 100), 1),
                )
            )
        return out


# ---------------------------------------------------------------- 规则评估


@dataclass
class HourVerdict:
    ts: datetime
    suitable: bool
    blocks: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)
    in_preferred_window: bool = False


@dataclass
class SprayWindowResult:
    hours: list[HourVerdict]
    daily_plans: list[dict]
    latest_application_date: date | None
    summary: str

    @property
    def best_windows(self) -> list[dict]:
        """兼容字段：返回首个可施药日的时段明细。"""
        return self.daily_plans[0]["windows"] if self.daily_plans else []

    def to_dict(self) -> dict:
        return {
            "data_source": "simulated",
            "is_simulated": True,
            "timezone": "Asia/Shanghai",
            "summary": self.summary,
            "latest_application_date": (
                self.latest_application_date.isoformat() if self.latest_application_date else None
            ),
            "daily_plans": self.daily_plans,
            "best_windows": self.best_windows,
            "hours": [
                {
                    "ts": h.ts.isoformat(timespec="minutes"),
                    "suitable": h.suitable,
                    "blocks": h.blocks,
                    "warns": h.warns,
                    "preferred": h.in_preferred_window,
                }
                for h in self.hours
            ],
        }


def _apply_rules(hour: HourlyWeather, rules: list[dict]) -> HourVerdict:
    verdict = HourVerdict(ts=hour.ts, suitable=True)
    values = {
        "temp_c": hour.temp_c,
        "humidity_pct": hour.humidity_pct,
        "wind_speed_ms": hour.wind_speed_ms,
        "precip_mm": hour.precip_mm,
        "precip_prob_next_6h": hour.precip_prob_next_6h,
    }
    ops = {
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }
    for rule in rules:
        val = values.get(rule["field"])
        if val is None:
            continue
        if ops[rule["operator"]](val, rule["threshold"]):
            if rule["severity"] == "block":
                verdict.suitable = False
                verdict.blocks.append(rule["reason"])
            else:
                verdict.warns.append(rule["reason"])
    return verdict


def compute_spray_window(
    weather: list[HourlyWeather],
    rules: list[dict],
    preferred_windows: list[dict] | None = None,
    record: PesticideRecord | None = None,
    planned_harvest_date: date | None = None,
    now: datetime | None = None,
) -> SprayWindowResult:
    preferred_windows = preferred_windows or []
    verdicts = [_apply_rules(h, rules) for h in weather]

    now = now or china_now()
    latest = (planned_harvest_date - timedelta(days=record.safety_interval_days)
              if record and record.safety_interval_days is not None and planned_harvest_date else None)
    for verdict in verdicts:
        if verdict.ts < now:
            verdict.suitable = False
            verdict.blocks.append("该小时已开始或已经过去，不作为未来推荐窗口")
        if latest and verdict.ts.date() > latest:
            verdict.suitable = False
            verdict.blocks.append("超过按该药剂间隔期倒推的最晚施药日")

    for v in verdicts:
        for w in preferred_windows:
            if w["start_hour"] <= v.ts.hour < w["end_hour"]:
                v.in_preferred_window = True
                break

    # 按天汇总适宜时段。
    # 刻意不做"连续 N 小时"的原始输出——农事上不会连续施药几十小时，
    # 有意义的表述是"哪一天、当天哪个时段适合打药"。
    by_day: dict[date, list[HourVerdict]] = {}
    for v in verdicts:
        by_day.setdefault(v.ts.date(), []).append(v)

    daily_plans: list[dict] = []
    for day, hours in sorted(by_day.items()):
        ok = [h for h in hours if h.suitable]
        if not ok:
            continue
        segs = _split_segments(ok)

        # 推荐窗口只保留落在植保推荐时段（清晨 / 傍晚）内的部分。
        # 全天都适宜并不等于"全天都该打药"——把 24 小时报成一个窗口在农事上没有意义。
        recommended = [p for s in segs for p in _narrow_to_preferred(s)]
        chosen = recommended if preferred_windows else [s for s in segs if len(s) >= 2]

        windows = [
            {
                "start": s[0].ts.strftime("%Y-%m-%dT%H:%M"),
                "end": _fmt_end(s[-1].ts + timedelta(hours=1)),
                "hours": len(s),
                "preferred": any(h.in_preferred_window for h in s),
            }
            for s in chosen
            if len(s) >= 2
        ]
        if not windows:
            continue
        daily_plans.append(
            {
                "date": day.isoformat(),
                "weekday": "周" + "一二三四五六日"[day.weekday()],
                "suitable_hours": len(ok),
                "blocked_hours": len(hours) - len(ok),
                "windows": windows,
                "warns": sorted({w for h in ok for w in h.warns}),
            }
        )

    # 排序：优先推荐靠近"最晚施药日"、且当日有植保推荐时段的日期

    def _rank(p: dict) -> tuple:
        d = date.fromisoformat(p["date"])
        overdue = 1 if (latest is not None and d > latest) else 0
        has_preferred = 0 if any(w["preferred"] for w in p["windows"]) else 1
        return (overdue, d, has_preferred, -p["suitable_hours"])

    daily_plans.sort(key=_rank)
    daily_plans = daily_plans[:5]

    if not daily_plans:
        summary = "模拟天气中未找到同时满足未来时间、推荐时段和采收间隔的窗口；请复核计划，勿直接据此施药。"
    else:
        p = daily_plans[0]
        w = p["windows"][0]
        start = datetime.fromisoformat(w["start"])
        tail = ""
        if latest is not None:
            tail = (
                f" 最晚施药日为 {latest:%m月%d日}。"
                if date.fromisoformat(p["date"]) <= latest
                else f" ⚠ 该日已晚于按安全间隔期倒推的最晚施药日 {latest:%m月%d日}，需调整采收计划或更换药剂。"
            )
        summary = (
            f"模拟天气中有 {len(daily_plans)} 天满足当前规则。"
            f"首选 {start:%m月%d日} {start:%H:00} 起（{w['hours']} 小时"
            + ("，处于清晨/傍晚推荐时段" if w["preferred"] else "")
            + "）。"
            + tail
        )

    return SprayWindowResult(
        hours=verdicts,
        daily_plans=daily_plans,
        latest_application_date=latest,
        summary=summary,
    )


def _fmt_end(ts: datetime) -> str:
    """区间终点是次日零点时显示为 24:00，避免出现 '00:00-00:00' 这种读不懂的区间。"""
    if ts.hour == 0 and ts.minute == 0:
        return (ts - timedelta(days=1)).strftime("%Y-%m-%dT") + "24:00"
    return ts.strftime("%Y-%m-%dT%H:%M")


def _narrow_to_preferred(seg: list[HourVerdict]) -> list[list[HourVerdict]]:
    """把一段适宜区间收窄到其中的植保推荐时段，并重新切分。

    清晨与傍晚是两个独立窗口，中间即使同样适宜也不应连成一段——
    把 06:00-19:00 报成一个施药窗口在农事上是没有意义的。
    """
    out = [h for h in seg if h.in_preferred_window]
    if len(out) < 2:
        return []
    return [s for s in _split_segments(out) if len(s) >= 2]


def _split_segments(hours: list[HourVerdict]) -> list[list[HourVerdict]]:
    """把逐小时判定切成连续区间。"""
    segs: list[list[HourVerdict]] = []
    cur: list[HourVerdict] = []
    for h in hours:
        if cur and (h.ts - cur[-1].ts).total_seconds() > 3600:
            segs.append(cur)
            cur = []
        cur.append(h)
    if cur:
        segs.append(cur)
    return segs
