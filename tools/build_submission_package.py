"""构建比赛提交包：源代码 zip + 材料目录 + 外层 zip。

用法：python tools/build_submission_package.py
输出：
  delivery/【按报名群格式命名】-田诊卫士-智能体版-提交包/
  delivery/田诊卫士-智能体版-提交包（请按报名群格式改名）.zip
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATERIALS = ROOT / "materials" / "智能体版-提交材料"
DELIVERY = ROOT / "delivery" / "【按报名群格式命名】-田诊卫士-智能体版-提交包"
DELIVERY_ZIP = ROOT / "delivery" / "田诊卫士-智能体版-提交包（请按报名群格式改名）.zip"
SOURCE_ZIP = DELIVERY / "09-源代码与部署说明.zip"

INCLUDE_DIRS = ["app", "tests", "tools", "benchmarks"]
INCLUDE_FILES = [
    "README.md",
    "00-作品说明.md",
    "GITHUB-发布说明.md",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "启动本地演示.ps1",
    "reports/AGENT_TEST_REPORT.md",
]
EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".matplotlib",
    ".venv",
    ".build",
    "archive",
    "delivery",
    "data_raw",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

SUBMIT_NOTE = """田诊卫士 · 智能体版 —— 提交包说明

一、发送前必须完成
1. 按报名群公布的格式重命名外层压缩包；如果报名群要求文件夹同名，也把本文件夹改成相同格式。
2. 原创承诺书：下载模板、按要求签字并扫描为 PDF，命名为“05-原创承诺书.pdf”放入本目录；
   然后删除占位文件“05-原创承诺书-请放入签字扫描件.txt”。
3. 打开“06-作品访问方式.txt”，确认 GitHub 链接为 https://github.com/Reasont-41/tianzhen-agent，
   并确认仓库是 Public；如已部署公网，同时填写体验链接和测试账号。
4. 检查 PPT、视频、PDF 能正常打开；视频不超过 2 分钟。
5. 把 PPT、视频、团队分工说明、作品说明中的【队名】【成员姓名】等占位符替换为真实信息；
   团队分工说明修改后请重新导出 PDF。
6. 删除本说明文件（00-提交说明.txt）和“05-原创承诺书-请放入签字扫描件.txt”，
   再把本目录压缩为单个 zip 发送。
7. 只由队长发送到 ciee_qnfzb@163.com；邮件主题按报名群格式；不要卡 10 月 25 日 20:00。

二、本目录内容
01-PPT-田诊卫士-智能体版.pptx
02-演示视频-田诊卫士-智能体版.mp4
03-团队分工说明.pdf
04-AI工具与开发说明.pdf
05-原创承诺书-请放入签字扫描件.txt   ← 替换为签字 PDF
06-作品访问方式.txt
07-作品说明-智能体版.pdf
08-报名简介-300字以内.txt
09-源代码与部署说明.zip

三、不要放进提交包
- 无关的历史材料、构建缓存和内部截图。
- .build/、.venv/、__pycache__/ 等本地目录。
"""

COMMITMENT_PLACEHOLDER = """请把签字并扫描后的原创承诺书 PDF 放在本目录，文件名为：

    05-原创承诺书.pdf

然后删除本占位文件。

如果报名群对文件名有特殊要求，以群里格式为准。

原创承诺书模板下载：见报名群通知或推文二维码；
本目录的 03-原创承诺书-填写说明.pdf 不是签字件，不能作为最终材料。
"""


def clean_previews() -> None:
    for path in MATERIALS.glob("_preview-*.png"):
        path.unlink()


def build_source_zip() -> None:
    DELIVERY.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in INCLUDE_FILES:
            path = ROOT / name
            if path.exists():
                zf.write(path, name)
        for directory in INCLUDE_DIRS:
            base = ROOT / directory
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in EXCLUDE_DIRS for part in path.parts):
                    continue
                if path.suffix.lower() in EXCLUDE_SUFFIXES:
                    continue
                zf.write(path, path.relative_to(ROOT).as_posix())


def copy_materials() -> None:
    DELIVERY.mkdir(parents=True, exist_ok=True)
    copies = [
        (ROOT / "presentation" / "田诊卫士-智能体版-答辩.pptx", "01-PPT-田诊卫士-智能体版.pptx"),
        (ROOT / "materials" / "田诊卫士-智能体版-功能演示.mp4", "02-演示视频-田诊卫士-智能体版.mp4"),
        (MATERIALS / "01-团队分工说明.pdf", "03-团队分工说明.pdf"),
        (MATERIALS / "02-AI工具与开发说明.pdf", "04-AI工具与开发说明.pdf"),
        (MATERIALS / "06-作品访问方式.txt", "06-作品访问方式.txt"),
        (MATERIALS / "04-作品说明-智能体版.pdf", "07-作品说明-智能体版.pdf"),
        (MATERIALS / "05-报名简介-300字以内.txt", "08-报名简介-300字以内.txt"),
    ]
    for source, name in copies:
        if not source.exists():
            raise FileNotFoundError(f"缺少材料：{source}")
        shutil.copy2(source, DELIVERY / name)

    (DELIVERY / "00-提交说明.txt").write_text(SUBMIT_NOTE, encoding="utf-8")
    placeholder = DELIVERY / "05-原创承诺书-请放入签字扫描件.txt"
    if not placeholder.exists() and not (DELIVERY / "05-原创承诺书.pdf").exists():
        placeholder.write_text(COMMITMENT_PLACEHOLDER, encoding="utf-8")


def build_delivery_zip() -> None:
    with zipfile.ZipFile(DELIVERY_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(DELIVERY.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(DELIVERY).as_posix())


def main() -> None:
    clean_previews()
    build_source_zip()
    copy_materials()
    build_delivery_zip()
    print(f"source zip: {SOURCE_ZIP}  {SOURCE_ZIP.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"delivery  : {DELIVERY}")
    print(f"outer zip : {DELIVERY_ZIP}  {DELIVERY_ZIP.stat().st_size / 1024 / 1024:.2f} MB")
    print("\n提交前请按 00-提交说明.txt 替换承诺书、确认 GitHub 链接并重命名。")


if __name__ == "__main__":
    main()
