"""评估分析与图表生成。

产出比赛报告需要的三组图与指标：
  1. 诊断模型：混淆矩阵、各类别 P/R/F1、拒识率-准确率权衡曲线（选择性预测分析）
  2. 约束校验层：无校验 vs 有校验的合规率对比、各类违规的检出率
  3. 实验数据汇总 JSON，供报告与答辩PPT直接引用

运行： python -m app.analyze
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts"
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

# Windows 受限环境下用户级 Matplotlib 缓存可能不可写；项目内缓存可复现且不需管理员权限。
MPL_CACHE = ART / ".matplotlib"
MPL_CACHE.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 中文字体
for f in ["Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS"]:
    try:
        matplotlib.rcParams["font.sans-serif"] = [f]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break
    except Exception:
        continue

GREEN, RED, AMBER, GRAY = "#2e9e6b", "#c0392b", "#c2761a", "#8a978f"


def load_metrics() -> dict:
    return json.loads((ART / "diagnosis_metrics.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 图 1


def fig_confusion(m: dict) -> None:
    cm = np.array(m["confusion_matrix"]["matrix"], dtype=float)
    labels = m["confusion_matrix"]["labels"]
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)

    fig, ax = plt.subplots(figsize=(5.6, 4.8), dpi=160)
    im = ax.imshow(norm, cmap="Greens", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("预测类别")
    ax.set_ylabel("真实类别")
    ax.set_title(f"病害识别混淆矩阵（行归一化）\n测试集准确率 {m['accuracy']:.2%}", fontsize=11)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{int(cm[i, j])}", ha="center", va="center",
                    color="white" if norm[i, j] > 0.5 else "#16211c", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, label="占该真实类别比例")
    fig.tight_layout()
    fig.savefig(FIG / "fig1_confusion_matrix.png")
    plt.close(fig)


# ---------------------------------------------------------------- 图 2


def fig_per_class(m: dict) -> None:
    pc = m["per_class"]
    labels = list(pc.keys())
    x = np.arange(len(labels))
    w = 0.26
    fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=160)
    for k, (metric, color) in enumerate(
        zip(["precision", "recall", "f1"], [GREEN, "#3b7dd8", AMBER])
    ):
        vals = [pc[l][metric] for l in labels]
        bars = ax.bar(x + (k - 1) * w, vals, w, label=metric.capitalize(), color=color)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + .012, f"{v:.3f}",
                    ha="center", fontsize=7.4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0.85, 1.03)
    ax.set_ylabel("分数")
    ax.set_title("各类别精确率 / 召回率 / F1", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=.25)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_per_class_metrics.png")
    plt.close(fig)


# 图 3 只读取冻结测试集预测，阈值在训练脚本中由验证集确定。
def main():
    m=load_metrics()
    fig_confusion(m);fig_per_class(m)
    records=json.loads((ART/'test_predictions.json').read_text(encoding='utf-8'))
    confidence=np.array([r['confidence'] for r in records])
    correct=np.array([r['predicted']==r['label'] for r in records])
    rejection=[];accuracy=[]
    for threshold in np.linspace(0, .9999, 100):
        keep=confidence>=threshold
        if keep.any():
            rejection.append(float((~keep).mean())*100);accuracy.append(float(correct[keep].mean())*100)
    rc=m['selective_prediction']
    fig,ax=plt.subplots(figsize=(6.4,4.2),dpi=160)
    ax.plot(rejection,accuracy,color=GREEN)
    ax.scatter([rc['rejection_rate']*100],[rc['accuracy_on_accepted']*100],color=RED,
               label=f"验证集冻结阈值 {rc['threshold']:.4f}")
    ax.set(xlabel='测试集拒识率（%）',ylabel='接受样本准确率（%）',title='固定测试集上的选择性预测分析')
    ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(FIG/'fig3_risk_coverage.png');plt.close(fig)
    e=json.loads((ART/'experiment_e2.json').read_text(encoding='utf-8'))
    states=['passed','blocked','needs_review'];names=['通过','拦截','待核验']
    matrix=np.array([[e['confusion_matrix'][x][y] for y in states] for x in states])
    fig,ax=plt.subplots(figsize=(6.2,4.4),dpi=160)
    ax.imshow(matrix,cmap='Greens');ax.set_xticks(range(3),names);ax.set_yticks(range(3),names)
    for i in range(3):
        for j in range(3):ax.text(j,i,str(matrix[i,j]),ha='center',va='center',color='white' if matrix[i,j]>10 else '#18372e')
    ax.set(xlabel='程序裁决',ylabel='执行前固定标签',title=f"构造功能基准 {e['correct']}/{e['n_cases']} 一致\n虚构记录，非真实农业合规率")
    fig.tight_layout();fig.savefig(FIG/'fig4_experiment_e2.png');plt.close(fig)
    summary={'diagnosis':m,'constraint_benchmark':{k:v for k,v in e.items() if k!='details'},
             'figures':[f'fig{i}_{name}.png' for i,name in [(1,'confusion_matrix'),(2,'per_class_metrics'),(3,'risk_coverage'),(4,'experiment_e2')]]}
    (ART/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('四张图与指标已从本版实际实验结果重新生成')

if __name__=='__main__':main()
