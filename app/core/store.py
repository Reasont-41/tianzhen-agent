"""知识库装载与查询。

负责把 data/ 下的 JSON 读成内存对象，并提供约束校验所需的记录解析能力。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import Disease, PesticideRecord, PrescriptionItem, SprayContext

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


class KnowledgeBase:
    """内存知识库。数据量在万级以内时无需引入数据库。"""

    def __init__(self) -> None:
        self.diseases: list[Disease] = [
            Disease(**{k: v for k, v in d.items() if k in Disease.__dataclass_fields__})
            for d in _load("kb_diseases.json")["diseases"]
        ]
        self.pesticides: list[PesticideRecord] = [
            PesticideRecord(
                **{k: v for k, v in r.items() if k in PesticideRecord.__dataclass_fields__}
            )
            for r in _load("kb_pesticides.json")["records"]
        ]

        banned_raw = _load("kb_banned.json")
        self.banned_names: set[str] = {b["name"] for b in banned_raw["banned"]}
        self.restricted_map: dict[str, str] = {
            r["name"]: r["note"] for r in banned_raw["restricted"]
        }

        spray_raw = _load("kb_spray_rules.json")
        self.spray_rules: list[dict] = spray_raw["rules"]
        self.preferred_windows: list[dict] = spray_raw.get("preferred_time_windows", [])

        self._by_record_id = {r.record_id: r for r in self.pesticides}
        self._triples = {(r.crop, r.target): [] for r in self.pesticides}
        for r in self.pesticides:
            self._triples.setdefault((r.crop, r.target), []).append(r)

    # ------------------------------------------------------------ 查询接口

    @property
    def crops(self) -> list[str]:
        seen: list[str] = []
        for r in self.pesticides:
            if r.crop not in seen:
                seen.append(r.crop)
        return seen

    def diseases_of(self, crop: str) -> list[Disease]:
        return [d for d in self.diseases if d.crop == crop]

    def find_disease(self, crop: str, name: str) -> Disease | None:
        name = (name or "").strip()
        for d in self.diseases:
            if d.crop != crop:
                continue
            if name in d.all_names or d.name in name:
                return d
        return None

    def candidates_for(self, crop: str, disease_name: str) -> list[PesticideRecord]:
        """取出某作物某病害下所有登记记录，这是生成合规处方的候选池。"""
        return list(self._triples.get((crop.strip(), disease_name.strip()), []))

    def find_by_name(self, crop: str, disease: str, pesticide_name: str) -> PesticideRecord | None:
        for r in self.candidates_for(crop, disease):
            if r.pesticide_name == pesticide_name:
                return r
        return None

    def resolve_record_for_item(self, item: PrescriptionItem, context: SprayContext | None = None) -> PesticideRecord | None:
        """约束校验引擎注入的记录解析函数。

        优先按 record_id 精确命中；否则按名称在候选池中查。
        刻意**不**放宽到"任意作物任意病害"，因为一旦放宽，
        登记作物/防治对象校验就失去意义。
        """
        if item.source_record_id:
            rec = self._by_record_id.get(item.source_record_id)
            return rec
        pool = [r for r in self.pesticides if r.pesticide_name == item.pesticide_name.strip()]
        if context is not None:
            pool = [r for r in pool if r.crop == context.crop and r.target == context.disease_name]
        for key in ("formulation", "active_ingredient", "ai_content", "reg_cert_no"):
            value = getattr(item, key, None)
            if value:
                pool = [r for r in pool if getattr(r, key, None) == value]
        return pool[0] if len(pool) == 1 else None

    def is_banned(self, pesticide_name: str) -> bool:
        return pesticide_name in self.banned_names


@lru_cache(maxsize=1)
def get_kb() -> KnowledgeBase:
    return KnowledgeBase()
