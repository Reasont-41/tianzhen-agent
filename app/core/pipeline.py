"""处方生成与「生成—校验—溯源」闭环编排。

本模块刻意把"生成"和"校验"解耦成两个独立部件：

    Generator  ──产出候选处方──▶  ConstraintEngine  ──否决/放行──▶  最终处方

这样做的价值在于：
  * 生成器可以自由替换（模板 / 大模型 / 外部系统给出的处方），校验强度不变；
  * 可以构造"无约束生成"对照组，量化校验层到底拦下了多少问题 —— 这正是本作品
    创新点的实验证据。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .constraint_engine import ConstraintEngine
from .models import (
    TRACEABLE_STATUSES,
    Disease,
    PesticideRecord,
    Prescription,
    PrescriptionItem,
    SprayContext,
    ValidationReport,
)
from .retrieval import DiseaseRetriever, PesticideRetriever, positive_symptoms
from .store import KnowledgeBase


# ---------------------------------------------------------------- 生成器


class ConstrainedGenerator:
    """合规生成器：只从知识库中「该作物 + 该病害」的登记记录里挑选候选。

    这是"AI 负责组织语言、确定性代码负责事实"的实现方式——
    生成阶段就被限定在合法候选池内，校验阶段再做二次把关。
    """

    def __init__(self, kb: KnowledgeBase, max_items: int = 3, seed: int = 20261004):
        self.kb = kb
        self.max_items = max_items
        self.rng = random.Random(seed)

    def generate(self, crop: str, disease_name: str, context: SprayContext) -> Prescription:
        candidates = self.kb.candidates_for(crop, disease_name)
        if not candidates:
            return Prescription(
                crop=crop,
                disease_name=disease_name,
                items=[],
                notes=["知识库中暂无该作物与病害的登记记录，无法生成处方，建议转当地植保部门。"],
                generated_by="constrained",
            )

        # 固定顺序，优先证据较完整、间隔期可满足的条目，避免同一输入随机换药。
        def rank(rec):
            gap = ((context.planned_harvest_date - context.application_date).days
                   if context.planned_harvest_date and context.application_date else None)
            conflict = gap is not None and rec.safety_interval_days is not None and rec.safety_interval_days > gap
            return (conflict, not rec.is_traceable, rec.record_id)
        picked = sorted(candidates, key=rank)[:self.max_items]

        items: list[PrescriptionItem] = []
        for rec in picked:
            items.append(
                PrescriptionItem(
                    pesticide_name=rec.pesticide_name,
                    formulation=rec.formulation,
                    dosage=rec.dosage,
                    dosage_value=rec.dosage_min,
                    dosage_unit=rec.dosage_unit,
                    application_method=rec.application_method,
                    safety_interval_days=rec.safety_interval_days,
                    source_record_id=rec.record_id,
                    reg_cert_no=rec.reg_cert_no,
                    source=rec.source,
                    verification_status=rec.verification_status,
                    verified_basis=getattr(rec, "verified_basis", ""),
                )
            )

        return Prescription(
            crop=crop,
            disease_name=disease_name,
            items=items,
            notes=["候选药剂来自知识库中该作物与病害的记录，规则校验通过后供参考；待核验数据不能作为正式处方依据。"],
            generated_by="constrained",
        )


class UnconstrainedBaselineGenerator:
    """按固定概率注入错误的合成演示生成器，不代表真实大模型输出分布。"""

    def __init__(self, kb: KnowledgeBase, failure_profile: dict[str, float] | None = None,
                 seed: int = 20261004):
        self.kb = kb
        self.seed = seed
        self.rng = random.Random(seed)
        self.failure_profile = failure_profile or {
            "cross_crop": 0.25,
            "cross_target": 0.20,
            "dosage_out_of_range": 0.25,
            "missing_safety_interval": 0.30,
        }
        self.pesticide_retriever = PesticideRetriever(kb.pesticides)

    def _pick_foreign_record(self, crop: str, disease_name: str, mode: str) -> PesticideRecord | None:
        """找一个"看着像"但实际不合规的记录。"""
        if mode == "cross_crop":
            # 治同一个病，但登记在别的作物上
            pool = [r for r in self.kb.pesticides if r.target == disease_name and r.crop != crop]
        else:
            # 登记在同一个作物上，但治的是别的病
            pool = [r for r in self.kb.pesticides if r.crop == crop and r.target != disease_name]
        return self.rng.choice(pool) if pool else None

    def generate(self, crop: str, disease_name: str, context: SprayContext) -> Prescription:
        candidates = self.kb.candidates_for(crop, disease_name)
        items: list[PrescriptionItem] = []

        # 基线以合规候选为底，再按 profile 注入失败模式，贴近真实模型的"部分正确"表现
        base_pool = candidates or [
            r for r in self.kb.pesticides if r.target == disease_name
        ]
        if not base_pool:
            return Prescription(crop=crop, disease_name=disease_name, items=[],
                                notes=["无候选"], generated_by="unconstrained_baseline")

        n = min(3, len(base_pool))
        picked: list[PesticideRecord | None] = self.rng.sample(base_pool, n)

        for rec in picked:
            roll = self.rng.random()
            item: PrescriptionItem

            if roll < self.failure_profile["cross_crop"]:
                foreign = self._pick_foreign_record(crop, disease_name, "cross_crop")
                if foreign is not None:
                    rec = foreign
            elif roll < self.failure_profile["cross_crop"] + self.failure_profile["cross_target"]:
                foreign = self._pick_foreign_record(crop, disease_name, "cross_target")
                if foreign is not None:
                    rec = foreign

            dosage_value = rec.dosage_min
            dosage_text = rec.dosage

            # 剂量越界
            if dosage_value is not None and self.rng.random() < self.failure_profile["dosage_out_of_range"]:
                dosage_value = round(dosage_value * self.rng.choice([2.0, 2.5, 3.0]), 2)
                dosage_text = f"{dosage_value:g}{rec.dosage_unit}"

            # 遗漏安全间隔期
            safety = rec.safety_interval_days
            if self.rng.random() < self.failure_profile["missing_safety_interval"]:
                safety = None

            item = PrescriptionItem(
                pesticide_name=rec.pesticide_name,
                formulation=rec.formulation,
                dosage=dosage_text,
                dosage_value=dosage_value,
                dosage_unit=rec.dosage_unit,
                application_method=rec.application_method,
                safety_interval_days=safety,
                source_record_id=None,       # 无溯源：这是无约束生成的典型特征
                reg_cert_no=None,
                source="",
                verification_status="",
            )
            items.append(item)

        return Prescription(
            crop=crop,
            disease_name=disease_name,
            items=items,
            notes=["无约束基线：直接给出的候选处方，未经任何登记信息校验。"],
            generated_by="unconstrained_baseline",
        )


# ---------------------------------------------------------------- 闭环编排


@dataclass
class PipelineResult:
    crop: str
    disease_name: str
    diagnosis: list[dict]
    prescription: Prescription
    report: ValidationReport
    released: bool                       # 是否放行发布
    released_items: list[PrescriptionItem]
    rejected_items: list[PrescriptionItem]
    traceability: list[dict]
    review_items: list[PrescriptionItem] = None
    item_verdicts: list[dict] = None
    diagnosis_status: str = "matched"
    clarification: list[str] = None

    def to_dict(self) -> dict:
        return {
            "crop": self.crop,
            "disease_name": self.disease_name,
            "diagnosis": self.diagnosis,
            "prescription": self.prescription.to_dict(),
            "validation": self.report.to_dict(),
            "released": self.released,
            "released_items": [i.to_dict() for i in self.released_items],
            "rejected_items": [i.to_dict() for i in self.rejected_items],
            "traceability": self.traceability,
            "review_items": [i.to_dict() for i in (self.review_items or [])],
            "item_verdicts": self.item_verdicts or [],
            "diagnosis_status": self.diagnosis_status,
            "clarification": self.clarification or [],
        }


class PrescriptionPipeline:
    """把检索、生成、校验、溯源串成一次完整请求。"""

    def __init__(self, kb: KnowledgeBase, generator=None):
        self.kb = kb
        self.disease_retriever = DiseaseRetriever(kb.diseases)
        self.engine = ConstraintEngine(kb.banned_names, kb.restricted_map)
        self.generator = generator or ConstrainedGenerator(kb)

    def run(
        self,
        query: str,
        crop: str,
        disease_name: str | None = None,
        context: SprayContext | None = None,
        top_k: int = 3,
    ) -> PipelineResult:
        # 1) 检索：口语描述 -> 标准病害
        matches = self.disease_retriever.search(query or disease_name or "", crop=crop, top_k=top_k)
        original_matches = list(matches)
        conflict = False
        if disease_name:
            target = self.kb.find_disease(crop, disease_name)
            if target is not None:
                conflict = bool(query and (
                    (disease_name in query and disease_name not in positive_symptoms(query)) or
                    (matches and matches[0][1] >= 4 and matches[0][0].name != target.name)
                ))
                matches = [(target, max(matches[0][1] if matches else 10, 10))] + [m for m in matches if m[0].disease_id != target.disease_id]
        ambiguous = (not disease_name and bool(matches) and (matches[0][1] < 4 or (
            len(matches) > 1 and (matches[0][1] - matches[1][1]) / matches[0][1] < 0.25
        )))
        if conflict or ambiguous:
            empty = Prescription(crop=crop, disease_name="", items=[])
            report = self.engine.validate(empty, context or SprayContext(crop, ""), self.kb.resolve_record_for_item)
            return PipelineResult(crop, "", [
                {"name": d.name, "match_score": s, "score_type": "retrieval_score",
                 "pathogen": d.pathogen, "symptoms": d.symptoms} for d, s in original_matches
            ], empty, report, False, [], [], [], diagnosis_status="needs_clarification",
                clarification=["叶片、茎秆还是果实出现症状？", "病斑是否有轮纹、白色或灰色霉层？请拍清晰叶片并描述实际观察到的特征。"])
        if not matches:
            empty = Prescription(crop=crop, disease_name=disease_name or "", items=[])
            report = self.engine.validate(empty, context or SprayContext(crop, disease_name or ""),
                                          self.kb.resolve_record_for_item)
            return PipelineResult(
                crop=crop, disease_name=disease_name or "", diagnosis=[],
                prescription=empty, report=report, released=False,
                released_items=[], rejected_items=[], traceability=[],
                diagnosis_status="insufficient_evidence",
                clarification=["暂不能确定病害。请描述实际存在的病斑、发生部位和变化过程；健康植株不需要据此用药。"],
            )

        top_disease: Disease = matches[0][0]
        diagnosis = [
            {
                "disease_id": d.disease_id,
                "name": d.name,
                "match_score": s,
                "score_type": "retrieval_score",
                "pathogen": d.pathogen,
                "symptoms": d.symptoms,
            }
            for d, s in matches
        ]

        ctx = context or SprayContext(crop=crop, disease_name=top_disease.name)
        ctx.crop = crop
        ctx.disease_name = top_disease.name

        # 2) 生成
        prescription = self.generator.generate(crop, top_disease.name, ctx)

        # 3) 校验
        report = self.engine.validate(prescription, ctx, self.kb.resolve_record_for_item)

        # 4) 逐条放行：只有该条目自身没有 block 级失败才发布
        item_status = self._per_item_verdict(prescription, report)

        released, rejected, review, trace = [], [], [], []
        for index, item in enumerate(prescription.items):
            status = item_status[str(index)]
            if status.get("released"):
                released.append(item)
            elif status["decision"] == "needs_review":
                review.append(item)
            else:
                rejected.append(item)
            if status["decision"] != "blocked":
                trace.append({
                    "pesticide": item.pesticide_name,
                    "record_id": item.source_record_id,
                    "reg_cert_no": item.reg_cert_no,
                    "source": item.source or "（无来源标注）",
                    "verification_status": item.verification_status or "unverified",
                    "verified_basis": item.verified_basis or "",
                    "traceable": bool(item.source)
                    and item.verification_status in TRACEABLE_STATUSES,
                })

        return PipelineResult(
            crop=crop,
            disease_name=top_disease.name,
            diagnosis=diagnosis,
            prescription=prescription,
            report=report,
            released=bool(released),
            released_items=released,
            rejected_items=rejected,
            traceability=trace,
            review_items=review,
            item_verdicts=list(item_status.values()),
        )

    @staticmethod
    def _per_item_verdict(prescription: Prescription, report: ValidationReport) -> dict[str, dict]:
        """把整份报告按药剂拆开，得到每条建议的独立裁决。

        这样"三条建议里两条合规、一条被拦"的表达才准确，而不是整份处方一刀切。
        """
        verdict: dict[str, dict] = {
            str(index): {"item_index": index, "pesticide": i.pesticide_name,
                         "record_id": i.source_record_id, "released": True,
                         "decision": "passed", "blocking": [], "review": []}
            for index, i in enumerate(prescription.items)
        }
        for res in report.results:
            key = str(res.evidence.get("item_index"))
            if key not in verdict:
                continue
            if not res.passed:
                verdict[key]["released"] = False
                bucket = "blocking" if res.severity == "block" else "review"
                verdict[key][bucket].append(
                    {"rule": res.rule_name, "message": res.message}
                )
        for value in verdict.values():
            value["decision"] = "blocked" if value["blocking"] else "needs_review" if value["review"] else "passed"
        return verdict
