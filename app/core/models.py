"""数据模型定义。

约束校验引擎的输入输出契约都定义在这里，规则实现只依赖这些结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Literal

# 可回查依据的状态集合；标准比对不等同于现行产品登记核验。
#
# 之所以把集合抽出来集中管理：核验状态是产品的可信度开关，
# 判断逻辑散落在多处时，新增一种状态极易漏改某处，导致
# "界面显示已核验、但处方仍被当作待核验数据"这类不一致。
#
#   official              —— 来自官方农药登记数据
#   verified_by_expert    —— 由植保专业人员核验
#   verified_by_standard  —— 团队比对国家标准（如 GB/T 8321）
TRACEABLE_STATUSES = frozenset({
    "official",
    "verified_by_expert",
    "verified_by_standard",
})

# ---------------------------------------------------------------- 知识库实体


@dataclass
class Disease:
    disease_id: str
    crop: str
    name: str
    aliases: list[str] = field(default_factory=list)
    pathogen: str = ""
    symptoms: str = ""
    favorable_conditions: str = ""
    severity_levels: list[str] = field(default_factory=list)
    source: str = ""
    verification_status: str = "seed_unverified"

    @property
    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass
class PesticideRecord:
    """一条农药登记记录。约束校验的判定依据。"""

    record_id: str
    pesticide_name: str
    crop: str
    target: str
    formulation: str = ""
    active_ingredient: str = ""
    ai_content: str = ""
    dosage: str = ""
    dosage_min: float | None = None
    dosage_max: float | None = None
    dosage_unit: str = ""
    application_method: str = ""
    safety_interval_days: int | None = None
    max_applications_per_season: int | None = None
    toxicity: str = ""
    banned: bool = False
    restricted: bool = False
    restrict_note: str = ""
    reg_cert_no: str | None = None
    source: str = ""
    verification_status: str = "seed_unverified"
    # 核验依据：指向具体的标准条款（如"GB/T 8321.10—2018 表 2 序号 51"）。
    # 只写"已核验"没有意义，必须能指回条款，用户才可能复核。
    verified_basis: str = ""

    @property
    def is_traceable(self) -> bool:
        """可溯源 = 有来源标注，且核验状态达到可发布要求。

        未核验的种子数据在演示中可以走通流程，但会被标记为"待核验"，
        产品界面必须把它当作降级信息展示。
        """
        return bool(self.source) and self.verification_status in TRACEABLE_STATUSES

    @property
    def registration_verified(self) -> bool:
        return bool(self.source and self.reg_cert_no) and self.verification_status in {
            "official", "verified_by_expert"
        }


# ---------------------------------------------------------------- 校验报告


Severity = Literal["block", "warn", "info", "pass"]


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    severity: Severity
    passed: bool
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = "passed" if self.passed else (
            "blocked" if self.severity == "block" else "needs_review"
        )
        return data


@dataclass
class ValidationReport:
    """一次处方校验的完整结果。"""

    passed: bool
    results: list[RuleResult] = field(default_factory=list)

    @property
    def blocking(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == "block"]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.results if not r.passed and r.severity == "warn"]

    @property
    def passed_rules(self) -> list[RuleResult]:
        return [r for r in self.results if r.passed]

    @property
    def decision(self) -> str:
        if self.blocking:
            return "blocked"
        return "passed" if self.passed else "needs_review"

    @property
    def compliance_rate(self) -> float:
        """通过率，用于对照实验统计。"""
        if not self.results:
            return 0.0
        return len(self.passed_rules) / len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "decision": self.decision,
            "review_required": bool(self.warnings),
            "compliance_rate": round(self.compliance_rate, 4),
            "results": [r.to_dict() for r in self.results],
            "blocking": [r.to_dict() for r in self.blocking],
            "warnings": [r.to_dict() for r in self.warnings],
        }


# ---------------------------------------------------------------- 处方与上下文


@dataclass
class SprayContext:
    """校验所需的田间上下文。没有这些信息，安全间隔期与用量规则无法判定。"""

    crop: str
    disease_name: str
    planned_harvest_date: date | None = None
    application_date: date | None = None
    history_applications: int | None = 0  # API 中未知次数传 None，不当作零次
    area_mu: float | None = None  # 地块面积（亩）
    history_by_record: dict[str, int] = field(default_factory=dict)


@dataclass
class PrescriptionItem:
    """处方中的一条建议。字段刻意与 PesticideRecord 对齐，便于逐项校验。"""

    pesticide_name: str
    formulation: str = ""
    dosage: str = ""
    dosage_value: float | None = None
    dosage_unit: str = ""
    application_method: str = ""
    safety_interval_days: int | None = None
    source_record_id: str | None = None
    reg_cert_no: str | None = None
    source: str = ""
    verification_status: str = ""
    verified_basis: str = ""
    active_ingredient: str = ""
    ai_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Prescription:
    crop: str
    disease_name: str
    items: list[PrescriptionItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    generated_by: str = "template"  # template | llm | unconstrained_baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "crop": self.crop,
            "disease_name": self.disease_name,
            "items": [i.to_dict() for i in self.items],
            "notes": self.notes,
            "generated_by": self.generated_by,
        }
