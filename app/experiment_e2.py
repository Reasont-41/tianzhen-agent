"""执行执行前固定标签的功能基准，不将规则自检解释为真实合规率。"""
from __future__ import annotations
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from .core.constraint_engine import ConstraintEngine
from .core.models import PesticideRecord, Prescription, PrescriptionItem, SprayContext

ROOT = Path(__file__).resolve().parent.parent


def evaluate():
    fixture = ROOT / "benchmarks/constraint_cases.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    details = []
    states = ["passed", "blocked", "needs_review"]
    matrix = {expected: {actual: 0 for actual in states} for expected in states}
    for case in data["cases"]:
        record = PesticideRecord(**(data["record"] | case.get("record", {})))
        item = PrescriptionItem(**(data["item"] | case.get("item", {})))
        gap = case.get("harvest_gap", 5)
        ctx = SprayContext("番茄", "晚疫病", date(2026, 10, 17)+timedelta(days=gap) if gap is not None else None,
                           date(2026, 10, 17), 0)
        for key, value in case.get("context", {}).items():
            setattr(ctx, key, value)
        report = ConstraintEngine().validate(Prescription(ctx.crop, ctx.disease_name, [item]), ctx,
            lambda proposed, context: record if proposed.source_record_id == record.record_id else None)
        actual, expected = report.decision, case["expected"]
        matrix[expected][actual] += 1
        details.append({"case_id": case["id"], "expected": expected, "actual": actual,
                        "correct": actual == expected, "failed_rules": [r.rule_id for r in report.results if not r.passed]})
    n_blocked = sum(matrix["blocked"].values())
    n_valid = sum(matrix["passed"].values())
    return {"benchmark_type": "fixed_label_synthetic_functional_cases", "scope": data["scope"],
            "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "n_cases": len(details), "correct": sum(r["correct"] for r in details),
            "violation_recall": matrix["blocked"]["blocked"] / n_blocked,
            "false_accepts": matrix["blocked"]["passed"],
            "valid_false_block_rate": matrix["passed"]["blocked"] / n_valid,
            "review_correct": matrix["needs_review"]["needs_review"],
            "confusion_matrix": matrix, "details": details,
            "limitations": ["标签为开发者针对功能契约构造，未由外部专家独立标注。",
                            "不能外推为真实农业处方合规率或大模型错误率。"]}


def main():
    result = evaluate()
    path = ROOT / "app/artifacts/experiment_e2.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"details", "confusion_matrix"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
