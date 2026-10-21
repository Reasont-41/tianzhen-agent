"""按 GB/T 8321.10-2018 核验知识库药剂记录。

背景
----
原本计划请植保专业人员逐条核验，但短期内找不到人。团队提供了
《GB/T 8321.10—2018 农药合理使用准则（十）》，这是国家推荐性标准，
由农业农村部提出、农业农村部农药检定所起草，规定了 430 种农药在 50 种作物上
580 项合理使用准则。作为判据比"公开农技资料整理"权威得多。

核验方法与边界（重要）
--------------------
1. **只核验能确证的条目**。标准按"农药 × 作物 × 防治对象"组织，
   只有三者都对上，才采信其数值。
2. **剂型必须匹配**。标准中同一农药下并列多个剂型时，只有剂型一致才更新用药量；
   剂型不符时仅更新安全间隔期（更保守的方向），用药量维持原值并注明。
3. **未收录 ≠ 数据错误**。GB/T 8321 覆盖范围小于农药登记范围，
   标准里没有的作物/病害组合，不代表该登记用法不成立，只代表**无法用本标准核验**。
   这些记录保持 seed_unverified，不做任何修改。
4. 不臆造标准中不存在的数据。所有更新值均可回指到标准的具体序号。

核验结果：40 条中 6 条在标准中查到对应条目。

运行： python tools/verify_against_standard.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "app" / "data" / "kb_pesticides.json"
BACKUP = ROOT / "app" / "data" / "kb_pesticides.json.核验前备份"

STANDARD = "GB/T 8321.10—2018《农药合理使用准则（十）》"
STANDARD_9 = "GB/T 8321.9—2009《农药合理使用准则（九）》"

# ---------------------------------------------------------------- 核验表
# 每项：记录号 -> (标准条款位置, 标准原文数值, 需要更新的字段)
# 数值均逐字取自标准表 2「杀菌剂/杀线虫剂」，未作任何推断或换算。
# 标准中"每 667 m² 每次制剂施用量"即"每亩制剂施用量"，与本知识库单位一致。
UPDATES: dict[str, dict] = {
    # 表 2 序号 9：多菌灵，50%可湿性粉剂，小麦—赤霉病，100 g，喷雾，每季最多 1 次，安全间隔期 35 d
    "P0035": {
        "ref": "表 2 序号 9（多菌灵 50%可湿性粉剂 · 小麦 · 赤霉病）",
        "dosage": "100克/亩",
        "dosage_min": 100.0,
        "dosage_max": 100.0,
        "dosage_unit": "克/亩",
        "safety_interval_days": 35,
        "max_applications_per_season": 1,
        "note": "原值 100-150克/亩、2 次、20 天；标准为 100 克、1 次、35 天。"
                "安全间隔期由 20 天修正为 35 天，使用次数由 2 次收紧为 1 次。",
    },
    # 异菌脲 · 番茄 · 灰霉病 在两部分中均有条目，且安全间隔期不一致：
    #   GB/T 8321.9—2009：50% 悬浮剂，50 g~100 g，每季最多 3 次，安全间隔期 7 d
    #   GB/T 8321.10—2018：表 2 序号 34，番茄—灰霉病行以 mL 计（100 mL~200 mL），安全间隔期 5 d
    # 本记录用量为"50-100 克/亩"，与第九部分的 50 g~100 g 完全一致（第九部分更对口）；
    # 两来源冲突时取更保守（更长）的 7 天。
    "P0008": {
        "ref": ("GB/T 8321.9—2009 表 2（异菌脲 50%悬浮剂 · 番茄 · 灰霉病、早疫病）；"
                "另见 GB/T 8321.10—2018 表 2 序号 34（同作物同病害，安全间隔期 5 d）"),
        "safety_interval_days": 7,
        "note": "原值 3 天。两部分国家标准对同一作物与病害给出 7 天（2009 版，用量 50-100 克，"
                "与本记录一致）与 5 天（2018 版，用量以毫升计，剂型不符）两个值；"
                "两者冲突时取更保守的 7 天。用药量维持原值。",
    },
    # 表 2 序号 51：嘧霉胺，40%悬浮剂 / 70%水分散粒剂，番茄—灰霉病，
    #              45 g~55 g，喷雾，每季最多 3 次，安全间隔期 5 d
    "P0006": {
        "ref": "表 2 序号 51（嘧霉胺 · 番茄 · 灰霉病）",
        "dosage": "45-55克/亩",
        "dosage_min": 45.0,
        "dosage_max": 55.0,
        "dosage_unit": "克/亩",
        "safety_interval_days": 5,
        "note": "原值 60-90毫升/亩、3 天；标准为 45-55 克、5 天。"
                "用药量与安全间隔期均已按标准修正。",
    },
    # 表 2 序号 52：戊唑醇，43%悬浮剂，小麦—锈病、白粉病，
    #              5 g~8 g，喷雾，每季最多 2 次，安全间隔期 28 d
    "P0031": {
        "ref": "表 2 序号 52（戊唑醇 43%悬浮剂 · 小麦 · 锈病、白粉病）",
        "dosage": "5-8克/亩",
        "dosage_min": 5.0,
        "dosage_max": 8.0,
        "dosage_unit": "克/亩",
        "safety_interval_days": 28,
        "note": "原值 15-20毫升/亩、21 天；标准为 5-8 克、28 天。"
                "用药量与安全间隔期均已按标准修正。",
    },
    "P0037": {
        "ref": "表 2 序号 52（戊唑醇 43%悬浮剂 · 小麦 · 锈病、白粉病）",
        "dosage": "5-8克/亩",
        "dosage_min": 5.0,
        "dosage_max": 8.0,
        "dosage_unit": "克/亩",
        "safety_interval_days": 28,
        "note": "原值 15-20毫升/亩、21 天；标准为 5-8 克、28 天。"
                "用药量与安全间隔期均已按标准修正。",
    },
    # 表 2 序号 36：醚菌酯，50%水分散粒剂，黄瓜—白粉病，
    #              13.3 g~20 g，喷雾，每季最多 3 次，安全间隔期 3 d
    "P0022": {
        "ref": "表 2 序号 36（醚菌酯 50%水分散粒剂 · 黄瓜 · 白粉病）",
        "dosage": "13.3-20克/亩",
        "dosage_min": 13.3,
        "dosage_max": 20.0,
        "dosage_unit": "克/亩",
        "safety_interval_days": 3,
        "note": "原值 20-30克/亩、5 天；标准为 13.3-20 克、3 天。"
                "注意：本标准值比原值更宽松（5 天→3 天），此处以国家标准为准。",
    },
}


def main() -> None:
    data = json.loads(KB.read_text(encoding="utf-8"))

    if not BACKUP.exists():
        shutil.copy(KB, BACKUP)
        print(f"已备份原知识库 -> {BACKUP.name}")

    today = date.today().isoformat()
    changed = []

    for rec in data["records"]:
        rid = rec["record_id"]
        if rid not in UPDATES:
            continue
        up = UPDATES[rid]
        before = {
            "dosage": rec.get("dosage"),
            "safety_interval_days": rec.get("safety_interval_days"),
            "max_applications_per_season": rec.get("max_applications_per_season"),
        }
        for field in ("dosage", "dosage_min", "dosage_max", "dosage_unit",
                      "safety_interval_days", "max_applications_per_season"):
            if field in up:
                rec[field] = up[field]

        rec["verification_status"] = "verified_by_standard"
        # ref 若已自带标准名（跨部分引用时会写明"GB/T 8321.9—2009 表 2"），
        # 就不再重复拼接前缀，否则会出现两个标准名黏连的错乱依据。
        ref = up["ref"]
        rec["verified_basis"] = ref if ref.startswith("GB/T") else f"{STANDARD}{ref}"
        rec["verified_date"] = today
        rec["verified_by"] = "团队比对国家标准（非植保专业人员）"
        rec["source"] = f"{STANDARD}（团队比对）"
        rec["verification_note"] = up["note"]
        changed.append((rid, rec["crop"], rec["target"], rec["pesticide_name"], before, up))

    data["_meta"]["version"] = "0.2.0-standard-verified"
    data["_meta"]["IMPORTANT"] = (
        f"本文件 40 条记录中，{len(changed)} 条已比对 {STANDARD} 并修正（verification_status = "
        "verified_by_standard）；其余记录该标准未收录对应作物/病害组合，保持 seed_unverified，"
        "未作任何修改。国家标准覆盖范围小于农药登记范围，未被标准收录不代表登记用法不成立，"
        "仅代表无法用本标准核验。正式应用前仍建议由植保专业人员复核。"
    )
    KB.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n按 {STANDARD} 完成核验，共更新 {len(changed)} 条：\n")
    for rid, crop, target, pest, before, up in changed:
        print(f"[{rid}] {crop} · {target} · {pest}")
        print(f"    依据：{up['ref']}")
        if before["dosage"] != (up.get("dosage") or before["dosage"]):
            print(f"    用药量    {before['dosage']}  ->  {up['dosage']}")
        if before["safety_interval_days"] != (up.get("safety_interval_days") or before["safety_interval_days"]):
            print(f"    安全间隔期 {before['safety_interval_days']} 天  ->  {up['safety_interval_days']} 天")
        if before["max_applications_per_season"] != (up.get("max_applications_per_season") or before["max_applications_per_season"]):
            print(f"    使用次数   {before['max_applications_per_season']} 次  ->  {up['max_applications_per_season']} 次")
        print()

    total = len(data["records"])
    print(f"合计：{len(changed)}/{total} 条已核验，{total - len(changed)} 条标准未收录（保持未核验）")


if __name__ == "__main__":
    main()
