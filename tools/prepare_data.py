"""训练数据准备脚本 —— 一键拉取病害图像数据集。

为什么单独写脚本而不直接把数据打包
----------------------------------
数据集为 5452 张图像、约 102MB。压缩后体积几乎不变（图像本身已压缩），
通过聊天工具/网盘传输不便，且数据是可公开获取的，没必要重复搬运。
因此改为提供本脚本，一条命令即可复现完全相同的训练集。

数据来源
--------
PlantVillage 数据集：https://github.com/spMohanty/PlantVillage-Dataset
仅取 raw/color 下与知识库严格对齐的番茄四类：

    Tomato___Late_blight   -> 晚疫病
    Tomato___Early_blight  -> 早疫病
    Tomato___Leaf_Mold     -> 叶霉病
    Tomato___healthy       -> 健康

采用 `--filter=blob:none --sparse` 稀疏检出：只下载需要的四个目录，
避免拉取完整仓库（完整仓库含灰度图与分割图，体积大得多）。

用法
----
    python tools/prepare_data.py

可用 --dest 指定输出目录（默认 data_raw/pv），--full 拉取全部类别。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/spMohanty/PlantVillage-Dataset.git"

# 与知识库对齐的类别（目录名 -> 知识库病害名）
TOMATO_CLASSES = {
    "Tomato___Late_blight": "晚疫病",
    "Tomato___Early_blight": "早疫病",
    "Tomato___Leaf_Mold": "叶霉病",
    "Tomato___healthy": "健康",
}

# 项目根目录（脚本位于 scripts/ 下）
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = ROOT / "data_raw" / "pv"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def run(cmd: list[str], cwd: Path | None = None) -> bool:
    """执行命令并实时输出，返回是否成功。"""
    print(f"  $ {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=cwd, check=False)
        return proc.returncode == 0
    except FileNotFoundError:
        print(f"  ✗ 命令不存在：{cmd[0]}")
        return False


def check_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def clone(dest: Path, full: bool) -> bool:
    if (dest / ".git").exists():
        print(f"  仓库已存在于 {dest}，跳过克隆")
        return True

    if dest.exists() and any(dest.iterdir()):
        print(f"  ✗ 目标目录非空且不是 git 仓库：{dest}")
        print("    请先删除该目录，或用 --dest 指定其他位置")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    print("\n[1/3] 稀疏克隆 PlantVillage 仓库（只取目录结构，不下载文件内容）")
    if not run([
        "git", "clone", "--depth", "1",
        "--filter=blob:none", "--sparse", REPO, str(dest),
    ]):
        print("  ✗ 克隆失败。若网络无法访问 GitHub，可考虑：")
        print("    - 使用代理或镜像站点")
        print("    - 从 Kaggle 搜索 'PlantVillage' 手动下载后解压到 data_raw/pv/raw/color/")
        return False
    return True


def checkout(dest: Path, full: bool) -> bool:
    print("\n[2/3] 检出图像文件")
    if full:
        print("  --full：检出全部类别（数据量较大，请耐心等待）")
        if not run(["git", "sparse-checkout", "set", "--no-cone", "raw/color/*"], cwd=dest):
            return False
        return True

    patterns = []
    for d in TOMATO_CLASSES:
        patterns.append(f"raw/color/{d}/*")
    print(f"  仅检出番茄 {len(TOMATO_CLASSES)} 类（与知识库对齐）")
    if not run(["git", "sparse-checkout", "set", "--no-cone", *patterns], cwd=dest):
        return False
    return True


def verify(dest: Path) -> bool:
    print("\n[3/3] 校验数据")
    color_dir = dest / "raw" / "color"
    if not color_dir.exists():
        print(f"  ✗ 未找到 {color_dir}")
        return False

    total = 0
    ok = True
    missing = [name for name in TOMATO_CLASSES if not (color_dir / name).is_dir()]
    if missing:
        print(f"缺少类别目录：{missing}")
        return False
    dirs = sorted([d for d in color_dir.iterdir() if d.is_dir()]) if not TOMATO_CLASSES else \
           sorted([d for d in color_dir.iterdir() if d.is_dir() and d.name in TOMATO_CLASSES])

    for d in dirs:
        files = [p for p in d.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
        total += len(files)
        kb_name = TOMATO_CLASSES.get(d.name, "—")
        flag = "✓" if files else "✗"
        if not files:
            ok = False
        print(f"  {flag} {d.name:<28} -> {kb_name:<6} {len(files):>5} 张")

    print(f"\n  合计 {total} 张图像")
    if total == 0:
        print("  ✗ 没有找到任何图像，检出可能失败")
        return False
    manifest_file = ROOT / 'app/artifacts/dataset_manifest.json'
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        mismatches = []
        for entry in manifest['rows']:
            image = color_dir / entry['path']
            if not image.exists() or hashlib.sha256(image.read_bytes()).hexdigest() != entry['sha256']:
                mismatches.append(entry['path'])
        if mismatches:
            print(f'与随包样本清单不一致：{len(mismatches)} 项。请核对数据版本，不自动替换样本。')
            return False
        print('随包固定样本清单的路径与 SHA-256 均匹配。')
    print("  ✓ 数据就绪，可以运行： python -m app.train_diagnosis")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="准备训练数据（PlantVillage 番茄子集）")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="输出目录")
    ap.add_argument("--full", action="store_true", help="拉取全部类别而非仅番茄")
    args = ap.parse_args()

    print("=" * 68)
    print("训练数据准备（PlantVillage 数据集）")
    print("=" * 68)
    print(f"目标目录：{args.dest}")

    if not check_git():
        print("\n✗ 未检测到 git。请先安装 Git：https://git-scm.com/")
        sys.exit(1)

    if not clone(args.dest, args.full):
        sys.exit(1)
    if not checkout(args.dest, args.full):
        sys.exit(1)
    if not verify(args.dest):
        sys.exit(1)

    print("\n完成。")


if __name__ == "__main__":
    main()
