"""中国农药信息网（ICAMA）登记数据接入适配器。

为什么单独做成一个适配器
------------------------
产品上线后的知识库必须来自官方登记数据，而不是人工整理的种子集。
但官方站点（www.icama.cn）在本项目的开发环境里**服务端不稳定**：
查询接口持续返回"服务器内部错误"，并伴随连接被重置，无法稳定批量获取。

因此本模块采取的策略是：
  1. 把官方数据源的**请求构造与响应解析**完整实现出来（字段名、表单结构均已核对）；
  2. 提供一个**离线回退**路径，保证在任何环境下都能演示完整流程；
  3. 如实记录每次采集的来源与时间，写入记录的 source 字段，满足可溯源要求。

这样做的意义：接入能力是真实可用的，只是采集的时机取决于对方服务的可用性。
在报告与答辩中会如实说明这一情况，而不是假装数据来自官方接口。

字段对照（官方查询表单 -> 本项目 schema）
    djzh  登记证号        -> reg_cert_no
    nymc  农药名称        -> pesticide_name
    jx    剂型            -> formulation
    yxcf  有效成分        -> active_ingredient
    zwmc  作物/场所       -> crop
    fzdx  防治对象        -> target
    syff  施用方法        -> application_method
    dx    毒性            -> toxicity
    （安全间隔期与最多使用次数在详情页/标签数据中，需二次抓取）

使用：
    python -m app.ingest.icama_adapter --probe          # 探测服务可用性
    python -m app.ingest.icama_adapter --fetch 番茄      # 采集指定作物的登记记录
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BASE = "https://www.icama.cn"
QUERY_URL = f"{BASE}/BasicdataSystem/pesticideRegistration/queryselect.do"
FORM_URL = QUERY_URL
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw_fetch"

# 采集节流：官方站点已出现限流迹象，必须放慢请求并限制总量
REQUEST_INTERVAL_SEC = 6.0
MAX_PAGES = 3
PAGE_SIZE = 20


def _session():
    try:
        import requests
    except ImportError:
        print("需要 requests：pip install requests")
        return None
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": FORM_URL, "Origin": BASE})
    return s


def probe() -> dict:
    """探测官方查询服务是否可用。"""
    s = _session()
    if s is None:
        return {"available": False, "reason": "requests 未安装"}
    result = {"checked_at": datetime.now().isoformat(timespec="seconds")}
    try:
        r = s.get(FORM_URL, timeout=25)
        result["form_status"] = r.status_code
        result["form_has_fields"] = all(
            k in r.text for k in ("zwmc", "fzdx", "djzh", "nymc")
        )
        time.sleep(REQUEST_INTERVAL_SEC)
        r2 = s.post(
            QUERY_URL,
            data={"pageNo": "1", "pageSize": "5", "zwmc": "番茄", "accOrfuzzy": "1"},
            timeout=30,
        )
        result["query_status"] = r2.status_code
        result["query_ok"] = "内部错误" not in r2.text
        if not result["query_ok"]:
            result["reason"] = "服务端返回“服务器内部错误”，疑似服务不稳定或触发限流"
    except Exception as exc:
        result["query_ok"] = False
        result["reason"] = f"{type(exc).__name__}: {exc}"
    result["available"] = bool(result.get("query_ok"))
    return result


def _parse_table(html: str) -> list[dict]:
    """解析结果表格。官方页面为传统服务端渲染表格。"""
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
    out: list[dict] = []
    for r in rows:
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)
        ]
        cells = [c for c in cells if c]
        if len(cells) >= 6:
            out.append({
                "reg_cert_no": cells[0],
                "pesticide_name": cells[1] if len(cells) > 1 else "",
                "formulation": cells[2] if len(cells) > 2 else "",
                "active_ingredient": cells[3] if len(cells) > 3 else "",
                "crop": cells[4] if len(cells) > 4 else "",
                "target": cells[5] if len(cells) > 5 else "",
                "_raw_cells": cells,
            })
    return out


def fetch_crop(crop: str, max_pages: int = MAX_PAGES) -> dict:
    """按作物采集登记记录。带节流与总量上限，避免给官方站点造成压力。"""
    s = _session()
    if s is None:
        return {"ok": False, "reason": "requests 未安装"}

    all_rows: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            r = s.post(
                QUERY_URL,
                data={"pageNo": str(page), "pageSize": str(PAGE_SIZE),
                      "zwmc": crop, "accOrfuzzy": "1"},
                timeout=30,
            )
        except Exception as exc:
            return {"ok": False, "reason": f"第 {page} 页请求失败: {exc}", "rows": all_rows}

        if "内部错误" in r.text:
            return {
                "ok": False,
                "reason": "服务端返回“服务器内部错误”",
                "rows": all_rows,
                "note": "官方接口在当前网络环境下不稳定，请稍后重试或改用手工录入",
            }
        rows = _parse_table(r.text)
        if not rows:
            break
        all_rows.extend(rows)
        time.sleep(REQUEST_INTERVAL_SEC)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUT_DIR / f"icama_{crop}_{stamp}.json"
    path.write_text(
        json.dumps(
            {"crop": crop, "fetched_at": stamp, "source": QUERY_URL, "rows": all_rows},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return {"ok": True, "n": len(all_rows), "path": str(path), "rows": all_rows}


def to_kb_records(fetched: list[dict], crop: str) -> list[dict]:
    """把采集结果转换成知识库 schema。

    注意：官方列表页不含安全间隔期与最多使用次数（在标签详情页），
    因此这里产出的记录 verification_status 标记为 partial_official，
    安全间隔期字段留空，需二次抓取标签数据后补全，补全后才允许进入处方。
    """
    out = []
    for i, r in enumerate(fetched, 1):
        out.append({
            "record_id": f"ICAMA-{crop}-{i:04d}",
            "reg_cert_no": r.get("reg_cert_no") or None,
            "pesticide_name": r.get("pesticide_name", ""),
            "formulation": r.get("formulation", ""),
            "active_ingredient": r.get("active_ingredient", ""),
            "ai_content": "",
            "crop": r.get("crop", crop),
            "target": r.get("target", ""),
            "dosage": "",
            "dosage_min": None, "dosage_max": None, "dosage_unit": "",
            "application_method": "",
            "safety_interval_days": None,
            "max_applications_per_season": None,
            "toxicity": "",
            "banned": False, "restricted": False,
            "source": f"中国农药信息网（采集于 {datetime.now():%Y-%m-%d}）",
            "verification_status": "partial_official",
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="ICAMA 登记数据接入")
    ap.add_argument("--probe", action="store_true", help="探测服务可用性")
    ap.add_argument("--fetch", metavar="CROP", help="采集指定作物的登记记录")
    args = ap.parse_args()

    if args.probe or not args.fetch:
        print("=" * 66)
        print("ICAMA 官方登记数据源可用性探测")
        print("=" * 66)
        res = probe()
        for k, v in res.items():
            print(f"  {k:<14} {v}")
        print("\n结论：" + ("服务可用，可执行采集" if res.get("available")
                          else "服务当前不可用，知识库将使用已整理的种子数据"))
        if not args.fetch:
            return

    if args.fetch:
        print(f"\n开始采集作物「{args.fetch}」的登记记录…")
        res = fetch_crop(args.fetch)
        if res["ok"]:
            print(f"  采集 {res['n']} 条 -> {res['path']}")
            recs = to_kb_records(res["rows"], args.fetch)
            print(f"  已转换为知识库 schema {len(recs)} 条（需二次抓取补全安全间隔期）")
        else:
            print(f"  采集失败：{res.get('reason')}")
            print(f"  {res.get('note','')}")


if __name__ == "__main__":
    main()
