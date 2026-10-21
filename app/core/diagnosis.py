"""病害视觉诊断推理模块。

与训练脚本的约定
----------------
产物由 app/train_diagnosis.py 生成，落在 app/artifacts/：
    diagnosis_clf.pkl       —— StandardScaler + LogisticRegression + 类别列表
    diagnosis_metrics.json  —— 训练指标、混淆矩阵、低置信度阈值

模型不可用时的行为
------------------
如果产物不存在（例如还没训练），本模块**明确报告不可用**，
由上层回退到"文本检索 + 人工确认"路径。
绝不返回编造的诊断结果 —— 这是整个产品"不胡说"原则的一部分。
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"

# 与知识库对齐：模型能识别的类别，知识库里都有对应处方
KB_ALIGNED_CLASSES = ["晚疫病", "早疫病", "叶霉病", "健康"]
# 当前训练集只包含番茄叶片。这个边界必须由后端强制执行，不能只靠前端提示。
SUPPORTED_CROPS = ("番茄",)


@dataclass
class DiseasePrediction:
    name: str
    confidence: float
    is_healthy: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "confidence": round(self.confidence, 4),
                "is_healthy": self.is_healthy}


@dataclass
class DiagnosisResult:
    available: bool
    predictions: list[DiseasePrediction]
    low_confidence: bool
    message: str
    top1: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "top1": str(self.top1) if self.top1 is not None else None,
            "low_confidence": self.low_confidence,
            "message": self.message,
            "error_code": self.error_code,
            "predictions": [p.to_dict() for p in self.predictions],
        }


class DiagnosisModule:
    """CPU 病害分类器推理封装。"""

    def __init__(self) -> None:
        self._ready = False
        self._scalers = None
        self._clf = None
        self._threshold = 0.5
        self._backbone = None
        self._weights = None
        self._backbone_error: str | None = None
        self._metrics: dict = {}
        self._load()

    # ------------------------------------------------------------ 装载

    def _load(self) -> None:
        model_path = ARTIFACT_DIR / "diagnosis_clf.pkl"
        metrics_path = ARTIFACT_DIR / "diagnosis_metrics.json"
        if not model_path.exists():
            return
        try:
            with open(model_path, "rb") as fh:
                bundle = pickle.load(fh)
            self._scalers = bundle["scaler"]
            self._clf = bundle["clf"]
            if metrics_path.exists():
                self._metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                self._threshold = float(self._metrics.get("low_confidence_threshold", 0.5))
            self._ready = True
        except Exception:
            self._ready = False

    @property
    def available(self) -> bool:
        return self._ready and (ARTIFACT_DIR / "mobilenet_v3_small-047dcff4.pth").exists()

    @property
    def metrics(self) -> dict:
        return self._metrics

    @property
    def supported_crops(self) -> tuple[str, ...]:
        """视觉模型实际覆盖的作物，而不是知识库覆盖的全部作物。"""
        return SUPPORTED_CROPS

    def supports_crop(self, crop: str) -> bool:
        return crop.strip() in self.supported_crops

    def _ensure_backbone(self) -> bool:
        """懒加载特征提取骨干。

        刻意**不**用裸 except 吞掉异常：初版这里写成 `except Exception: return False`，
        结果把 "torch 的 _C 扩展 DLL 加载失败" 这个真实错误伪装成了
        "torchvision 缺失"，排查时被误导了很久。错误信息必须保留。
        """
        if self._backbone is not None:
            return True
        if self._backbone_error is not None:
            return False
        try:
            import torch
            from torchvision import models

            torch.set_num_threads(4)
            weights = models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
            path = ARTIFACT_DIR / "mobilenet_v3_small-047dcff4.pth"
            if not path.exists():
                raise FileNotFoundError("缺少随包骨干权重，请运行 tools/prepare_weights.py")
            model = models.mobilenet_v3_small(weights=None)
            model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
            model.classifier = torch.nn.Identity()
            model.eval()
            self._backbone, self._weights = model, weights
            return True
        except Exception as exc:  # noqa: BLE001 - 需要保留原始错误以便排查
            self._backbone_error = f"{type(exc).__name__}: {exc}"
            return False

    # ------------------------------------------------------------ 推理

    def predict(
        self,
        image_bytes: bytes,
        top_k: int = 3,
        crop: str | None = None,
    ) -> DiagnosisResult:
        if crop is not None and not self.supports_crop(crop):
            return DiagnosisResult(
                available=False,
                predictions=[],
                low_confidence=True,
                message=(
                    f"当前视觉模型仅支持{'、'.join(self.supported_crops)}叶片，"
                    f"暂不支持「{crop}」图像识别。请改用文字描述症状或转人工确认。"
                ),
                error_code="unsupported_crop",
            )
        import io
        from PIL import Image, ImageOps
        try:
            with Image.open(io.BytesIO(image_bytes)) as source:
                if source.width * source.height > 20_000_000:
                    raise ValueError("图片像素过多，请压缩后上传")
                img = ImageOps.exif_transpose(source).convert("RGB")
                img.load()
        except Exception:
            return DiagnosisResult(False, [], True, "图片无法解析或像素过多，请重新拍摄清晰叶片。", error_code="invalid_image")
        if min(img.size) < 96:
            return DiagnosisResult(False, [], True, "图片过小，请上传至少 96×96 像素的清晰叶片。", error_code="image_quality")
        sample = np.asarray(img.resize((128, 128)), dtype=float)
        gray = sample.mean(axis=2)
        contrast = float(gray.std())
        laplace = gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4 * gray[1:-1, 1:-1]
        if contrast < 8 or float(laplace.var()) < 1.0:
            return DiagnosisResult(False, [], True,
                                   "图片缺少可辨认的叶片纹理，可能为纯色、曝光异常或严重模糊；请重新拍摄。",
                                   error_code="image_quality")
        if not self._ready:
            return DiagnosisResult(
                available=False, predictions=[], low_confidence=True,
                message="视觉诊断模型尚未训练或产物缺失，请改用文字描述症状，或联系人工确认。",
                error_code="model_unavailable",
            )
        if not self._ensure_backbone():
            detail = f"（{self._backbone_error}）" if self._backbone_error else ""
            return DiagnosisResult(
                available=False, predictions=[], low_confidence=True,
                message=f"特征提取骨干不可用{detail}，请改用文字描述症状。",
                error_code="backbone_unavailable",
            )

        import torch

        x = self._weights.transforms()(img).unsqueeze(0)
        with torch.no_grad():
            feat = self._backbone(x).cpu().numpy()
        feat = self._scalers.transform(feat)

        proba = self._clf.predict_proba(feat)[0]
        classes = list(self._clf.classes_)
        order = np.argsort(proba)[::-1][:top_k]

        preds = [
            DiseasePrediction(
                name=classes[i],
                confidence=float(proba[i]),
                is_healthy=(classes[i] == "健康"),
            )
            for i in order
        ]

        top1 = preds[0]
        low_conf = top1.confidence < self._threshold

        if low_conf:
            message = (
                f"图片特征与已知病害的匹配度偏低（最高 {top1.confidence:.0%}，"
                f"低于可信阈值 {self._threshold:.0%}），无法给出可靠诊断，建议补充症状描述或转人工确认。"
            )
        elif top1.is_healthy:
            message = f"未发现明显病斑特征，判断为健康叶片（置信度 {top1.confidence:.0%}）。"
        else:
            message = (
                f"诊断倾向为「{top1.name}」，置信度 {top1.confidence:.0%}。"
                f"仅适用于番茄叶片四分类，请结合田间症状确认；该概率不能证明输入一定是支持的叶片。"
            )

        return DiagnosisResult(
            available=True, predictions=preds, low_confidence=low_conf,
            message=message, top1=None if low_conf else top1.name,
        )


_module: DiagnosisModule | None = None


def get_diagnosis_module() -> DiagnosisModule:
    global _module
    if _module is None:
        _module = DiagnosisModule()
    return _module
