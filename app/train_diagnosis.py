"""固定训练/验证/测试划分；只在验证集选拒识阈值，保存逐样本证据。"""
from __future__ import annotations
import argparse
import hashlib
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
ARTIFACT_DIR = ROOT / "artifacts"
RAW_DIR = ROOT.parent / "data_raw/pv/raw/color"
CLASS_MAP = {"Tomato___Late_blight": ("晚疫病", "番茄叶片"),
             "Tomato___Early_blight": ("早疫病", "番茄叶片"),
             "Tomato___Leaf_Mold": ("叶霉病", "番茄叶片"),
             "Tomato___healthy": ("健康", "番茄叶片")}
SEED = 20261017


def build_backbone():
    import torch
    from torchvision import models
    torch.set_num_threads(4)
    weight_file = ARTIFACT_DIR / "mobilenet_v3_small-047dcff4.pth"
    if not weight_file.exists():
        raise FileNotFoundError("缺少骨干权重，请先运行 python tools/prepare_weights.py")
    weights = models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
    model = models.mobilenet_v3_small(weights=None)
    model.load_state_dict(torch.load(weight_file, map_location="cpu", weights_only=True))
    model.classifier = torch.nn.Identity()
    model.eval()
    return model, weights


def extract_features(paths, backbone, weights):
    import torch
    from PIL import Image, ImageOps
    batches = []
    transform = weights.transforms()
    for i in range(0, len(paths), 64):
        batch = []
        for path in paths[i:i+64]:
            # 读取失败直接报错，不能截断标签去“对齐”已经错位的特征。
            with Image.open(path) as source:
                batch.append(transform(ImageOps.exif_transpose(source).convert("RGB")))
        with torch.no_grad():
            batches.append(backbone(torch.stack(batch)).cpu().numpy())
    return np.concatenate(batches)


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--feature-cache", type=Path)
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(exist_ok=True)
    rows, paths, seen, duplicates = [], [], {}, 0
    for folder, (label, _) in CLASS_MAP.items():
        directory = args.data_dir / folder
        if not directory.exists():
            raise FileNotFoundError(f"缺少类别目录：{directory}")
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:
                if seen[digest] != label:
                    raise ValueError("同一图像具有冲突标签，需先清理数据")
                duplicates += 1
                continue
            seen[digest] = label
            rows.append({"path": f"{folder}/{path.name}", "label": label, "sha256": digest})
            paths.append(path)
    labels = np.array([r["label"] for r in rows])
    indexes = np.arange(len(rows))
    trainval, test = train_test_split(indexes, test_size=.2, stratify=labels, random_state=SEED)
    train, validation = train_test_split(trainval, test_size=.25, stratify=labels[trainval], random_state=SEED)
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    print(f"样本 {len(rows)}，去除精确重复 {duplicates}；训练 {len(train)} / 验证 {len(validation)} / 测试 {len(test)}", flush=True)
    backbone, weights = build_backbone()
    X = None
    if args.feature_cache and args.feature_cache.exists():
        cache = np.load(args.feature_cache)
        if str(cache["fingerprint"]) == fingerprint:
            X = cache["X"]
    if X is None:
        X = extract_features(paths, backbone, weights)
        if args.feature_cache:
            args.feature_cache.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(args.feature_cache, X=X, fingerprint=fingerprint)
    scaler = StandardScaler().fit(X[train])
    clf = LogisticRegression(max_iter=3000, C=1.0)
    clf.fit(scaler.transform(X[train]), labels[train])
    val_probability = clf.predict_proba(scaler.transform(X[validation]))
    val_predictions = clf.classes_[val_probability.argmax(axis=1)]
    val_correct = val_predictions == labels[validation]
    # 预先固定为验证集正确样本置信度的第 5 百分位；不观察测试结果调参。
    threshold = float(np.percentile(val_probability.max(axis=1)[val_correct], 5))
    probability = clf.predict_proba(scaler.transform(X[test]))
    predictions = clf.classes_[probability.argmax(axis=1)]
    confidence = probability.max(axis=1)
    accepted = confidence >= threshold
    correct = predictions == labels[test]
    report = classification_report(labels[test], predictions, output_dict=True, zero_division=0)
    classes = list(clf.classes_)
    for split, idx in (("train", train), ("validation", validation), ("test", test)):
        for i in idx:
            rows[i]["split"] = split
    model_file = ARTIFACT_DIR / "diagnosis_clf.pkl"
    model_file.write_bytes(pickle.dumps({"scaler": scaler, "clf": clf, "classes": classes}))
    selective = {"threshold": threshold, "rejection_rate": float((~accepted).mean()),
                 "accuracy_on_accepted": float(correct[accepted].mean()) if accepted.any() else None,
                 "n_accepted": int(accepted.sum()), "accepted_errors": int((~correct & accepted).sum()),
                 "baseline_accuracy": float(correct.mean())}
    metrics = {"trained_at": datetime.now().isoformat(timespec="seconds"),
               "evaluation_protocol": "stratified_train_validation_test_60_20_20",
               "threshold_selection": "validation_correct_confidence_5th_percentile",
               "random_seed": SEED, "dataset_fingerprint": fingerprint,
               "n_total": len(rows), "exact_duplicates_removed": duplicates,
               "n_train": len(train), "n_validation": len(validation), "n_test": len(test),
               "accuracy": float(correct.mean()), "low_confidence_threshold": threshold,
               "selective_prediction": selective, "feature_dim": int(X.shape[1]), "img_size": 224,
               "backbone": "MobileNetV3-Small (ImageNet, frozen)", "head": "LogisticRegression(C=1)",
               "dataset": "PlantVillage tomato four-class controlled leaf dataset",
               "scope": "公开叶片数据集评估；未验证真实田间泛化；输入质量门禁另作回归测试。",
               "per_class": {c: {"precision": report[c]["precision"], "recall": report[c]["recall"],
                                  "f1": report[c]["f1-score"], "support": report[c]["support"]} for c in classes},
               "confusion_matrix": {"labels": classes, "matrix": confusion_matrix(labels[test], predictions, labels=classes).tolist()},
               "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest()}
    manifest = {"source": "https://github.com/spMohanty/PlantVillage-Dataset", "seed": SEED,
                "fingerprint": fingerprint, "rows": rows}
    for name, data in (("diagnosis_metrics.json", metrics), ("dataset_manifest.json", manifest),
                       ("test_predictions.json", [{**rows[i], "predicted": str(predictions[k]),
                                                   "confidence": float(confidence[k]), "accepted": bool(accepted[k])}
                                                  for k, i in enumerate(test)])):
        (ARTIFACT_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"accuracy": metrics["accuracy"], "selective_prediction": selective}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
