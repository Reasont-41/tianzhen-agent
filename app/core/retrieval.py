"""混合检索模块。

用途有两个：
  1. 把农户的口语化描述（"叶子发黄长白毛了"）匹配到知识库中的标准病害名；
  2. 在病害知识文本上做 BM25 + 字符 n-gram 的混合召回，为生成模块提供上下文。

之所以不用向量模型：本机没有 GPU，且知识库规模小、领域术语高度集中在几百个词上，
BM25 加别名表在这个规模下召回质量足够，且推理是毫秒级、完全可复现。
这是一个刻意的工程取舍，报告中会如实说明并给出与向量方案的对比测试计划。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import jieba
from rank_bm25 import BM25Okapi

from .models import Disease, PesticideRecord

# 口语症状词 -> (权重, 对应病害)。用于把农户说法桥接到知识库。
#
# 权重是刻意分层的：像"黑杆""轮纹""烂头"这类**高特异**症状几乎只指向一种病，
# 给高权重；而"白毛""烂""枯"这类泛化描述多种病都有，给低权重。
# 不分层的话，"长白毛"会把霜霉/晚疫/灰霉拉到同一档，导致置信度失去区分度。
COLLOQUIAL_HINTS: dict[str, tuple[float, list[str]]] = {
    # 高特异症状：单一指向
    "黑杆": (6.0, ["晚疫病"]),
    "黑茎": (6.0, ["晚疫病"]),
    # 技术方案中的标准演示话术。限定“茎上/茎秆”以避免把一般叶部黑斑误判为晚疫病。
    "茎上有黑斑": (6.0, ["晚疫病"]),
    "茎上黑斑": (6.0, ["晚疫病"]),
    "茎秆黑斑": (6.0, ["晚疫病"]),
    "条斑": (5.0, ["晚疫病"]),
    "黑褐": (4.0, ["晚疫病"]),
    "轮纹": (6.0, ["早疫病"]),
    "同心": (5.0, ["早疫病"]),
    "穿孔": (6.0, ["炭疽病"]),
    "烂头": (6.0, ["赤霉病"]),
    "麦穗枯": (6.0, ["赤霉病"]),
    "跑马干": (6.0, ["霜霉病"]),
    "角斑": (6.0, ["霜霉病"]),
    "粉红": (5.0, ["赤霉病", "炭疽病"]),
    "虚线": (5.0, ["条锈病"]),
    "沿叶脉": (5.0, ["条锈病"]),
    "维管束": (5.0, ["枯萎病"]),
    # 中等特异性
    "白粉": (4.0, ["白粉病"]),
    "白点": (4.0, ["白粉病"]),
    "黄点": (4.0, ["条锈病"]),
    "黄斑": (4.0, ["条锈病"]),
    "锈": (4.0, ["条锈病"]),
    "萎蔫": (4.0, ["枯萎病"]),
    "蔫": (4.0, ["枯萎病"]),
    "霉层": (3.5, ["灰霉病", "叶霉病", "霜霉病"]),
    "水浸": (3.5, ["晚疫病", "赤霉病"]),
    "灰毛": (3.5, ["灰霉病"]),
    "绒毛": (3.0, ["叶霉病", "灰霉病"]),
    # 泛化症状：多病共有，低权重
    "白毛": (2.5, ["霜霉病", "晚疫病", "灰霉病"]),
    "枯": (2.0, ["枯萎病"]),
    "烂": (1.5, ["灰霉病", "枯萎病"]),
}


def _tokenize(text: str) -> list[str]:
    """中英混合分词：中文走 jieba，英文与数字单独切出。"""
    text = text.lower()
    tokens: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fa5]+|[a-z0-9]+", text):
        if re.match(r"[\u4e00-\u9fa5]", chunk):
            tokens.extend(jieba.lcut(chunk))
        else:
            tokens.append(chunk)
    return [t for t in tokens if t.strip()]


def positive_symptoms(query: str) -> str:
    """保守排除否定片段；不足以确诊时交由上层澄清，不补猜病名。"""
    clauses = re.split(r"[，,。；;！？!?\n]|但是|不过|但|而", query or "")
    return "，".join(c for c in clauses if not re.search(r"没有|并非|排除|(?:不|没|未)(?:是|见|长|有|发现|出现|观察到)|无(?:明显|病|白|黑|轮|霉)", c))


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    text = re.sub(r"\s+", "", text)
    return {text[i : i + n] for i in range(max(len(text) - n + 1, 0))}


class DiseaseRetriever:
    """病害检索：别名精确匹配 -> BM25 -> 字符相似度，三级回退。"""

    def __init__(self, diseases: list[Disease]):
        self.diseases = diseases
        self._corpus = [
            _tokenize(f"{d.name} {' '.join(d.aliases)} {d.symptoms} {d.favorable_conditions}")
            for d in diseases
        ]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, crop: str | None = None, top_k: int = 3) -> list[tuple[Disease, float]]:
        pool = [d for d in self.diseases if crop is None or d.crop == crop]
        if not pool:
            return []

        scores: dict[str, float] = {d.disease_id: 0.0 for d in pool}

        # 一级：别名/标准名直接命中
        q = positive_symptoms(query).strip()
        if not q:
            return []
        for d in pool:
            for alias in d.all_names:
                if alias and alias in q:
                    scores[d.disease_id] += 10.0
                elif q and q in alias:
                    scores[d.disease_id] += 5.0

        # 二级：口语症状词桥接（按特异程度加权）
        for hint, (weight, diseases_hit) in COLLOQUIAL_HINTS.items():
            if hint in q:
                for d in pool:
                    if d.name in diseases_hit:
                        scores[d.disease_id] += weight

        # 三级：BM25 全文（权重刻意压低，只作辅助信号）
        # 在这个领域，"杆上黑褐色条斑"这类**明确症状词**的证据强度，
        # 应当高于词袋相似度——否则一篇较长的症状描述会因为泛化词汇多
        # （叶、斑、背面）而盖过真正特异的症状匹配。
        if self._bm25 is not None:
            idx_map = {d.disease_id: i for i, d in enumerate(self.diseases)}
            raw = self._bm25.get_scores(_tokenize(q))
            local = [raw[idx_map[d.disease_id]] for d in pool]
            mx = max(local) if local else 0.0
            if mx > 0:
                for d, s in zip(pool, local):
                    scores[d.disease_id] += 2.5 * (s / mx)

        # 四级：字符 n-gram 相似度兜底，处理错别字与语序差异
        q_grams = _char_ngrams(q)
        if q_grams:
            for d in pool:
                for alias in d.all_names:
                    sim = len(q_grams & _char_ngrams(alias)) / max(len(q_grams | _char_ngrams(alias)), 1)
                    scores[d.disease_id] += 2.0 * sim

        ranked = sorted(
            ((d, scores[d.disease_id]) for d in pool), key=lambda x: x[1], reverse=True
        )
        ranked = [(d, round(s, 4)) for d, s in ranked if s > 0]
        return ranked[:top_k]


class PesticideRetriever:
    """药剂检索，用于按药剂名反查登记信息（例如校验一条外部给出的处方）。"""

    def __init__(self, records: list[PesticideRecord]):
        self.records = records
        self._corpus = [
            _tokenize(f"{r.pesticide_name} {r.active_ingredient} {r.formulation} {r.crop} {r.target}")
            for r in records
        ]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, top_k: int = 5) -> list[tuple[PesticideRecord, float]]:
        if self._bm25 is None:
            return []
        q = _tokenize(query)
        if not q:
            return []
        raw = self._bm25.get_scores(q)
        mx = max(raw) if len(raw) else 0.0
        if mx <= 0:
            return []
        ranked = sorted(zip(self.records, raw), key=lambda x: x[1], reverse=True)
        return [(r, round(float(s / mx), 4)) for r, s in ranked[:top_k] if s > 0]

    def best_name_match(self, name: str) -> PesticideRecord | None:
        """把外部处方里的药剂名匹配回知识库记录。

        用 SequenceMatcher 处理剂型后缀与简写差异（如"烯酰吗啉50%WDG"）。
        """
        if not name:
            return None
        exact = [r for r in self.records if r.pesticide_name == name]
        if exact:
            return exact[0]

        best, best_score = None, 0.0
        for r in self.records:
            if r.pesticide_name and r.pesticide_name in name:
                return r
            score = SequenceMatcher(None, name, r.pesticide_name).ratio()
            if score > best_score:
                best, best_score = r, score
        return best if best_score >= 0.6 else None
