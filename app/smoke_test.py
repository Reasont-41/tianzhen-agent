"""冒烟测试：验证「生成—校验—溯源」闭环端到端可跑。

运行： python -m app.smoke_test
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import (  # noqa: E402
    ConstrainedGenerator,
    MockWeatherProvider,
    PrescriptionPipeline,
    SprayContext,
    UnconstrainedBaselineGenerator,
    compute_spray_window,
    get_kb,
)


def hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    kb = get_kb()
    hr("知识库装载")
    print(f"作物: {kb.crops}")
    print(f"病害: {len(kb.diseases)} 条 | 药剂登记记录: {len(kb.pesticides)} 条")
    print(f"禁用清单: {len(kb.banned_names)} 个 | 限用清单: {len(kb.restricted_map)} 个")

    ctx = SprayContext(
        crop="番茄",
        disease_name="晚疫病",
        application_date=date.today(),
        planned_harvest_date=date.today() + timedelta(days=5),
        history_applications=0,
        area_mu=1.5,
    )

    # ---------------- 闭环：口语输入 -> 检索 -> 生成 -> 校验 -> 放行
    hr("场景一：演示预览与逐项核验")
    pipe = PrescriptionPipeline(kb, ConstrainedGenerator(kb))
    result = pipe.run(query="番茄叶子背面长白毛，还有黑杆，是不是要烂了", crop="番茄", context=ctx)

    print("【诊断】")
    for d in result.diagnosis:
        print(f"  {d['name']}  检索分={d['match_score']}  病原={d['pathogen'][:34]}")
    print(f"\n【处方校验】放行={result.released}  规则通过占比={result.report.compliance_rate:.1%}")
    print(f"  放行 {len(result.released_items)} 条 / 拦截 {len(result.rejected_items)} 条")
    for r in result.report.results:
        flag = "OK  " if r.passed else f"{r.severity.upper():<5}"
        print(f"  [{flag}] {r.rule_name}: {r.message[:62]}")
    print("\n【溯源】")
    for t in result.traceability:
        print(f"  {t['pesticide']} <- record={t['record_id']} 来源={t['source'][:16]} 状态={t['verification_status']}")

    # ---------------- 对照：无约束生成
    hr("场景二：同一条问诊，合成错误注入（非真实模型对照）")
    pipe_u = PrescriptionPipeline(kb, UnconstrainedBaselineGenerator(kb))
    res_u = pipe_u.run(query="番茄叶子背面长白毛，还有黑杆", crop="番茄", context=ctx)
    print(f"【处方校验】放行={res_u.released}  规则通过占比={res_u.report.compliance_rate:.1%}")
    print(f"  放行 {len(res_u.released_items)} 条 / 拦截 {len(res_u.rejected_items)} 条")
    for r in res_u.report.blocking:
        print(f"  [BLOCK] {r.rule_name}: {r.message[:66]}")

    # ---------------- 施药窗口期
    hr("场景三：施药窗口期")
    weather = MockWeatherProvider().forecast()
    rec = kb.candidates_for("番茄", "晚疫病")[0]
    window = compute_spray_window(
        weather,
        kb.spray_rules,
        kb.preferred_windows,
        record=rec,
        planned_harvest_date=ctx.planned_harvest_date,
    )
    print(f"  {window.summary}")
    print(f"  最晚施药日（按安全间隔期 {rec.safety_interval_days} 天倒推）: {window.latest_application_date}")
    for p in window.daily_plans[:3]:
        seg = "、".join(
            f"{w['start'][11:16]}-{w['end'][11:16]}({'推荐' if w['preferred'] else '一般'})"
            for w in p["windows"]
        )
        print(f"  {p['date']} {p['weekday']}  适宜{p['suitable_hours']}h/不宜{p['blocked_hours']}h  -> {seg}")
        if p["warns"]:
            print(f"      注意: {p['warns'][0][:60]}")

    # ---------------- 禁用拦截
    hr("场景四：禁用农药一票否决")
    from app.core.models import Prescription, PrescriptionItem  # noqa: E402

    bad = Prescription(
        crop="番茄",
        disease_name="晚疫病",
        items=[PrescriptionItem(pesticide_name="甲胺磷", dosage_value=50, dosage_unit="毫升/亩")],
        generated_by="manual",
    )
    rep = pipe.engine.validate(bad, ctx, kb.resolve_record_for_item)
    print(f"  放行={rep.passed}")
    for r in rep.blocking:
        print(f"  [BLOCK] {r.rule_name}: {r.message}")


if __name__ == "__main__":
    main()
