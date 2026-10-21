"""逐条校验；信息不足与违规分开记录，未核验数据只能进入演示预览。"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Protocol

from .models import Prescription, RuleResult, SprayContext, ValidationReport


class Rule(Protocol):
    rule_id: str
    rule_name: str
    severity: str

    def check(self, item, record, context) -> RuleResult: ...


def _result(rule, passed, message, evidence=None, *, review=False):
    return RuleResult(rule.rule_id, rule.rule_name,
                      "pass" if passed else "warn" if review else rule.severity,
                      passed, message, evidence or {})


def _missing(rule):
    return _result(rule, False, "缺少唯一匹配的依据记录，无法完成此项检查。", review=True)


class TraceabilityRule:
    rule_id, rule_name, severity = "traceability", "来源与产品身份", "block"

    def check(self, item, record, context):
        if record is None:
            return _result(self, False, "未找到唯一匹配记录，请核对记录编号、药剂名称、作物和病害。")
        mismatches = []
        for key in ("pesticide_name", "formulation", "active_ingredient", "ai_content", "reg_cert_no"):
            actual = getattr(item, key, None)
            expected = getattr(record, key, None)
            if actual and str(actual).strip() != str(expected or "").strip():
                mismatches.append(key)
        if mismatches:
            return _result(self, False, "条目身份与来源记录不一致，不能借用其他产品的依据。",
                           {"mismatched_fields": mismatches, "record_id": record.record_id})
        if not record.source:
            return _result(self, False, "依据记录缺少来源。")
        if not record.registration_verified:
            return _result(self, False,
                           "当前仅有种子资料或标准比对，尚未完成现行产品登记核验；只供演示预览。",
                           {"record_id": record.record_id, "verification_status": record.verification_status,
                            "source": record.source, "degraded": True}, review=True)
        return _result(self, True, "产品身份与已核验登记记录一致。",
                       {"record_id": record.record_id, "reg_cert_no": record.reg_cert_no})


class BannedPesticideRule:
    rule_id, rule_name, severity = "banned", "禁用清单检查", "block"

    def __init__(self, banned_names):
        self.banned_names = banned_names

    def check(self, item, record, context):
        hit = item.pesticide_name.strip() in self.banned_names or bool(record and record.banned)
        return _result(self, not hit, "命中禁用清单，拦截。" if hit else "未命中本版本禁用清单。")


class RestrictedPesticideRule:
    rule_id, rule_name, severity = "restricted", "限用范围检查", "block"
    _VEGETABLE_CROPS = {"番茄", "黄瓜", "白菜", "辣椒", "茄子", "豇豆", "芹菜", "韭菜"}

    def __init__(self, restricted_map):
        self.restricted_map = restricted_map

    def check(self, item, record, context):
        note = self.restricted_map.get(item.pesticide_name.strip(), "")
        if record:
            note = record.restrict_note or note
        if not note:
            if record and record.restricted:
                return _result(self, False, "标记为限用但缺少适用范围，需补充依据。", review=True)
            return _result(self, True, "未命中本版本限用条目。")
        if context.crop in self._VEGETABLE_CROPS and ("蔬菜" in note or "瓜类" in note):
            return _result(self, False, f"当前作物命中限制范围：{note}")
        return _result(self, False, f"限用范围需人工复核：{note}", review=True)


class CropRegisteredRule:
    rule_id, rule_name, severity = "crop_registered", "依据记录的作物匹配", "block"

    def check(self, item, record, context):
        if record is None:
            return _missing(self)
        ok = record.crop.strip() == context.crop.strip()
        return _result(self, ok, "作物与依据记录一致。" if ok else "作物与依据记录不一致。")


class TargetRegisteredRule:
    rule_id, rule_name, severity = "target_registered", "依据记录的防治对象匹配", "block"

    def check(self, item, record, context):
        if record is None:
            return _missing(self)
        ok = record.target.strip() == context.disease_name.strip()
        return _result(self, ok, "防治对象与依据记录一致。" if ok else "防治对象与依据记录不一致。")


# 仅换算相同量纲；倍液、有效成分剂量不与制剂亩用量混算。
_UNITS = {
    "克/亩": ("mass_per_mu", 1), "g/亩": ("mass_per_mu", 1),
    "千克/亩": ("mass_per_mu", 1000), "kg/亩": ("mass_per_mu", 1000),
    "毫升/亩": ("volume_per_mu", 1), "ml/亩": ("volume_per_mu", 1),
    "升/亩": ("volume_per_mu", 1000), "l/亩": ("volume_per_mu", 1000),
}


class DosageRangeRule:
    rule_id, rule_name, severity = "dosage_range", "剂量与单位检查", "block"

    def check(self, item, record, context):
        if record is None:
            return _missing(self)
        if record.dosage_min is None or record.dosage_max is None:
            return _result(self, False, "依据记录没有可计算剂量区间，转人工确认。", review=True)
        if item.dosage_value is None or not item.dosage_unit.strip():
            return _result(self, False, "剂量数值和单位均须填写。")
        val = float(item.dosage_value)
        src = _UNITS.get(item.dosage_unit.strip().lower())
        dst = _UNITS.get(record.dosage_unit.strip().lower())
        if not math.isfinite(val) or val <= 0:
            return _result(self, False, "剂量须为有限正数。")
        if not src or not dst or src[0] != dst[0]:
            return _result(self, False, "剂量单位不兼容或尚不支持，不能判定通过。")
        normalized = val * src[1] / dst[1]
        lo, hi = float(record.dosage_min), float(record.dosage_max)
        ok = math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= normalized <= hi
        return _result(self, ok, "换算后的剂量在依据区间内。" if ok else "换算后的剂量超出依据区间。",
                       {"input_value": val, "input_unit": item.dosage_unit,
                        "normalized_value": normalized, "registered_unit": record.dosage_unit,
                        "registered_min": lo, "registered_max": hi})


class SafetyIntervalRule:
    rule_id, rule_name, severity = "safety_interval", "间隔期与采收计划", "block"

    def check(self, item, record, context):
        interval = item.safety_interval_days
        if interval is None:
            return _result(self, False, "条目缺少安全间隔期，须补全后重新校验。",
                           {"recoverable_from_record": bool(record and record.safety_interval_days is not None)})
        if record is None or record.safety_interval_days is None:
            return _result(self, False, "缺少依据间隔期，不能采用条目自报值判定通过。", review=True)
        if interval < record.safety_interval_days or interval < 0:
            return _result(self, False, "条目间隔期短于依据记录，拦截。",
                           {"proposed_days": interval, "record_days": record.safety_interval_days})
        if context.application_date is None or context.planned_harvest_date is None:
            return _result(self, False, "采收计划或施药日期未确定，时间冲突检查待补全。", review=True)
        gap = (context.planned_harvest_date - context.application_date).days
        ok = gap >= interval
        return _result(self, ok, f"距采收 {gap} 天，{'满足' if ok else '不满足'}条目间隔期 {interval} 天。",
                       {"gap_days": gap, "safety_interval_days": interval,
                        "latest_application_date": (context.planned_harvest_date - timedelta(days=interval)).isoformat()})


class MaxApplicationsRule:
    rule_id, rule_name, severity = "max_applications", "每季使用次数上限", "block"

    def check(self, item, record, context):
        if record is None or record.max_applications_per_season is None:
            return _result(self, False, "缺少使用次数上限依据，需复核。", review=True)
        used = context.history_by_record.get(record.record_id, context.history_applications)
        if used is None:
            return _result(self, False, "尚未提供该药剂的本季使用次数，请补充。", review=True)
        limit = record.max_applications_per_season
        ok = isinstance(used, int) and 0 <= used < limit
        return _result(self, ok, f"该药剂本季已用 {used} 次，上限 {limit} 次；" + ("可继续检查。" if ok else "不再推荐使用。"),
                       {"used": used, "limit": limit})


class ConstraintEngine:
    def __init__(self, banned_names=None, restricted_map=None):
        self.rules = [TraceabilityRule(), BannedPesticideRule(banned_names or set()),
                      RestrictedPesticideRule(restricted_map or {}), CropRegisteredRule(),
                      TargetRegisteredRule(), DosageRangeRule(), SafetyIntervalRule(), MaxApplicationsRule()]

    def validate(self, prescription: Prescription, context: SprayContext, resolve_record) -> ValidationReport:
        if not prescription.items:
            return ValidationReport(False, [RuleResult("non_empty", "条目非空", "block", False, "没有可检查的条目。")])
        results = []
        for index, item in enumerate(prescription.items):
            record = resolve_record(item, context)
            for rule in self.rules:
                result = rule.check(item, record, context)
                result.evidence.update({"pesticide": item.pesticide_name, "item_index": index})
                results.append(result)
        return ValidationReport(all(r.passed for r in results), results)
