"""生成 2 分钟内的“田诊卫士 · 智能体版”功能演示视频。

用法：python tools/build_competition_video.py
输出：materials/田诊卫士-智能体版-功能演示.mp4
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".build" / "competition-video"
SHOTS = ROOT / "reports" / "screenshots"
FIGURES = ROOT / "app" / "figures"
PPT_RENDER = ROOT / ".build" / "competition-ppt"
OUT = ROOT / "materials" / "田诊卫士-智能体版-功能演示.mp4"

W, H = 1920, 1080
GREEN_DARK = "#0E3B2E"
GREEN = "#146C50"
LIGHT = "#E6F1E8"
BG = "#F3F7F3"
INK = "#18372E"
MUTED = "#61766D"
AMBER = "#D9A441"
AMBER_BG = "#FFF6DF"
AMBER_INK = "#875A12"
WHITE = "#FFFFFF"
RED = "#9D3529"

FONT_REGULAR = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size, index=0)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + char
        if draw.textlength(candidate, font=f) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_text(draw, xy, text, f, fill, max_width=None, line_gap=8):
    x, y = xy
    if max_width is None:
        draw.text((x, y), text, font=f, fill=fill)
        return y + f.size
    lines = wrap(draw, text, f, max_width)
    for line in lines:
        draw.text((x, y), line, font=f, fill=fill)
        y += f.size + line_gap
    return y


def base_frame(title: str, caption: str, page: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page_img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(page_img)
    draw.rectangle((0, 0, W, 82), fill=GREEN_DARK)
    draw.text((60, 20), title, font=font(34, True), fill=WHITE)
    draw.rectangle((0, 950, W, H), fill="#17352B")
    draw_text(draw, (60, 970), caption, font(27), WHITE, max_width=1780, line_gap=4)
    draw.text((60, 1034), "田诊卫士 · 智能体版 · 竞赛演示", font=font(18), fill="#A8D4BF")
    draw.text((1740, 1034), f"{page:02d}", font=font(18), fill="#A8D4BF")
    return page_img, draw


def fit_image(page: Image.Image, image_path: Path, box: tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    image = Image.open(image_path).convert("RGB")
    scale = min(w / image.width, h / image.height)
    new_w = int(image.width * scale)
    new_h = int(image.height * scale)
    image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    # 白色卡片 + 细边框
    pad = 10
    draw = ImageDraw.Draw(page)
    draw.rounded_rectangle(
        (x - pad, y - pad, x + new_w + pad, y + new_h + pad),
        radius=16,
        fill=WHITE,
        outline="#DCE7DF",
        width=2,
    )
    page.paste(image, (x + (w - new_w) // 2, y + (h - new_h) // 2))


def side_panel(draw, x: int, y: int, width: int, heading: str, items: list[str], accent: str = GREEN) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 660), radius=18, fill=WHITE, outline="#DCE7DF", width=2)
    draw.text((x + 24, y + 26), heading, font=font(24, True), fill=accent)
    cursor = y + 82
    for item in items:
        draw.text((x + 24, cursor), "▪", font=font(22, True), fill=accent)
        cursor = draw_text(draw, (x + 52, cursor), item, font(21), INK, max_width=width - 76, line_gap=6) + 22


def image_segment(
    title: str,
    caption: str,
    page: int,
    image_path: Path,
    panel_heading: str,
    panel_items: list[str],
    layout: str = "right",
) -> Image.Image:
    page_img, draw = base_frame(title, caption, page)
    if layout == "right":
        fit_image(page_img, image_path, (60, 120, 1400, 790))
        side_panel(draw, 1510, 140, 350, panel_heading, panel_items)
    elif layout == "chart":
        fit_image(page_img, image_path, (70, 130, 980, 780))
        side_panel(draw, 1100, 140, 760, panel_heading, panel_items)
    else:
        fit_image(page_img, image_path, (160, 120, 1600, 790))
    return page_img


def title_frame() -> Image.Image:
    page = Image.new("RGB", (W, H), GREEN_DARK)
    draw = ImageDraw.Draw(page)
    draw.text((110, 180), "智慧农业 · 智能体创新应用比赛", font=font(28, True), fill="#A8D4BF")
    draw.text((110, 250), "田诊卫士", font=font(92, True), fill=WHITE)
    draw.text((110, 380), "面向小农户的番茄病害诊断\n与安全用药智能体", font=font(42), fill="#D7E8DD", spacing=16)
    draw.text((110, 600), "大模型规划  ·  工具调用  ·  规则否决", font=font(32, True), fill=AMBER)
    draw_text(
        draw,
        (110, 690),
        "从一句口语描述开始，调用视觉诊断、病害检索、候选记录、规则校验和施药窗口工具，给出可回查的依据与缺口。",
        font(25),
        "#B8D4C5",
        max_width=820,
        line_gap=10,
    )
    draw.text((110, 920), "“码上智农，电亮未来”智能体创新应用比赛", font=font(22), fill="#A8D4BF")
    draw.text((110, 962), "团队：【队名】 · 2026 年 10 月", font=font(22), fill="#A8D4BF")

    # 右侧真实界面缩略图
    shot = Image.open(SHOTS / "agent-02-回答结论.png").convert("RGB")
    shot = shot.resize((840, 472), Image.Resampling.LANCZOS)
    draw.rounded_rectangle((1000, 180, 1880, 700), radius=24, fill=WHITE)
    page.paste(shot, (1020, 194))
    draw.text((1020, 716), "真实运行界面：对话 + 工具轨迹 + 逐条校验", font=font(20), fill="#A8D4BF")
    return page


def window_frame() -> Image.Image:
    page, draw = base_frame(
        "施药窗口：从‘能用什么’到‘什么时候能打’",
        "窗口按每种药剂分别计算；过滤已开始的小时和超过最晚施药日的日期；不是当地预报。",
        7,
    )
    draw.rounded_rectangle((150, 140, 1770, 900), radius=24, fill=WHITE, outline="#DCE7DF", width=2)
    draw.text((210, 190), "模拟窗口（以烯酰吗啉为例）", font=font(32, True), fill=GREEN)
    draw.rounded_rectangle((1540, 190, 1710, 242), radius=20, fill=AMBER_BG)
    draw.text((1560, 200), "模拟天气", font=font(22, True), fill=AMBER_INK)
    draw.text((210, 290), "10/21  06:00–08:00", font=font(64, True), fill=GREEN)
    draw.text((210, 385), "首选窗口", font=font(26), fill=MUTED)
    draw.text((210, 470), "10/22  16:00–19:00", font=font(50, True), fill=GREEN)
    draw.text((210, 545), "备选窗口 · 风速 2–3 级，建议降低喷头或加防风罩", font=font(24), fill=MUTED)
    draw.text((210, 650), "最晚施药日 10/22", font=font(34, True), fill=AMBER_INK)
    draw_text(
        draw,
        (210, 720),
        "窗口不是‘全天可打’：清晨和傍晚优先，降雨、风速、温度、湿度逐小时评估；超过最晚施药日的日期直接排除。",
        font(23),
        MUTED,
        max_width=1450,
        line_gap=8,
    )
    draw.text((210, 820), "实际应用前需接入真实气象服务并核验当地适用条件。", font=font(22), fill=AMBER_INK)
    return page


def safety_frame() -> Image.Image:
    page, draw = base_frame(
        "安全边界：把‘不知道’显式暴露出来",
        "竞赛演示，不签发正式田间处方；待核验资料只能作为演示预览。",
        9,
    )
    draw.rounded_rectangle((430, 340, 1490, 505), radius=24, fill=GREEN_DARK)
    draw.text((480, 372), "ready_for_field_use = false", font=font(54, True), fill=WHITE)
    draw.text((480, 450), "不签发正式处方，不替代农技员", font=font(26), fill="#D7E8DD")
    cards = [
        (120, 140, "未提供次数 ≠ 0", "不把未知当零次"),
        (1390, 140, "图文冲突先澄清", "不猜病名"),
        (120, 560, "纯色 / 模糊图片拒识", "推理前拦截"),
        (1390, 560, "待核验只作演示", "不混入正式通过"),
    ]
    for x, y, heading, note in cards:
        draw.rounded_rectangle((x, y, x + 410, y + 150), radius=18, fill=WHITE, outline="#DCE7DF", width=2)
        draw.text((x + 24, y + 22), heading, font=font(25, True), fill=GREEN)
        draw.text((x + 24, y + 84), note, font=font(21), fill=MUTED)
    draw_text(
        draw,
        (120, 800),
        "知识库 40 条：6 条团队标准比对 · 34 条待核验 · 0 条现行登记核验。标准比对不等于具体产品登记核验。",
        font(23),
        MUTED,
        max_width=1680,
        line_gap=8,
    )
    return page


def closing_frame() -> Image.Image:
    page = Image.new("RGB", (W, H), GREEN_DARK)
    draw = ImageDraw.Draw(page)
    draw.text((110, 170), "当前边界", font=font(26, True), fill="#A8D4BF")
    draw.text((110, 220), "先把能做的做扎实，\n再把不能做的说清楚", font=font(58, True), fill=WHITE, spacing=20)
    items = [
        "34 / 40 条药剂记录仍待核验",
        "天气为模拟数据，未接真实气象",
        "未开展田间试用与专家独立核验",
        "不签发正式田间处方",
    ]
    cursor = 520
    for item in items:
        draw.text((110, cursor), "▪", font=font(28, True), fill=AMBER)
        draw.text((150, cursor), item, font=font(28), fill="#D7E8DD")
        cursor += 62
    draw.text((1050, 180), "下一步", font=font(26, True), fill="#A8D4BF")
    next_items = ["完成具体产品现行登记核验", "接入真实气象并核验当地规则", "小规模用户任务测试与田间试点"]
    cursor = 240
    for item in next_items:
        draw.text((1050, cursor), "▪", font=font(28, True), fill=AMBER)
        draw.text((1090, cursor), item, font=font(28), fill="#D7E8DD")
        cursor += 62
    draw.text((1050, 600), "让创意被体验、\n被演示、能继续迭代。", font=font(48, True), fill=AMBER, spacing=16)
    draw.text((110, 980), "田诊卫士 · 智能体版  ·  【队名】", font=font(22), fill="#A8D4BF")
    draw.text((1620, 980), "谢谢", font=font(22), fill="#A8D4BF")
    return page


def build() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, float]] = []

    def save(image: Image.Image, name: str, duration: float) -> None:
        path = BUILD / name
        image.save(path)
        frames.append((path, duration))

    save(title_frame(), "frame-01.png", 8)
    save(
        image_segment(
            "智能体架构：大模型规划，规则引擎否决",
            "模型负责理解、追问和选择工具；所有用药条目必须经过确定性规则引擎。",
            2,
            PPT_RENDER / "slide-04.png",
            "关键点",
            ["大模型只做理解与规划", "7 个可调用工具", "规则引擎逐条否决", "工具结果作为事实来源", "未核验只作演示预览", "每次回答可回查"],
            "right",
        ),
        "frame-02.png",
        10,
    )
    save(
        image_segment(
            "对话式入口：描述症状或上传叶片照片",
            "支持多轮对话、照片上传、工具调用轨迹；信息不足时先追问。",
            3,
            SHOTS / "agent-01-首页.png",
            "交互",
            ["口语描述 + 图片", "大模型规划模式", "本地规划可回退"],
            "right",
        ),
        "frame-03.png",
        10,
    )
    save(
        image_segment(
            "一次完整对话：从症状到逐条裁决",
            "检索到晚疫病候选；代森锰锌因 15 天间隔期被拦截；其余条目待核验。",
            4,
            SHOTS / "agent-02-回答结论.png",
            "结果",
            ["结论 + 依据 + 待补", "来源与核验状态", "不签发正式处方"],
            "right",
        ),
        "frame-04.png",
        14,
    )
    save(
        image_segment(
            "工具调用轨迹：每一次回答都能回查",
            "真实运行截图：5 次工具调用，依次完成诊断、检索、候选、校验和窗口。",
            5,
            SHOTS / "agent-03-工具调用.png",
            "工具链",
            ["get_leaf_diagnosis", "search_disease", "get_candidate_records", "validate_prescription", "get_spray_window", "ask_user", "get_kb_status"],
            "right",
        ),
        "frame-05.png",
        14,
    )
    save(
        image_segment(
            "逐条规则校验：把‘能说’变成‘能过’",
            "通过、待核验、拦截分开；blocked 不推荐，needs_review 必须标注。",
            6,
            SHOTS / "agent-04-逐条校验.png",
            "裁决",
            ["8 条确定性规则", "blocked 不推荐", "同名条目独立裁决"],
            "right",
        ),
        "frame-06.png",
        12,
    )
    save(window_frame(), "frame-07.png", 10)
    save(
        image_segment(
            "视觉诊断：先拒识，再分类",
            "冻结测试集 1088 张；总体准确率 96.88%，拒识率 6.53%，接受样本准确率 98.82%。",
            8,
            FIGURES / "fig1_confusion_matrix.png",
            "指标",
            ["96.88% 总体准确率", "6.53% 拒识率", "98.82% 接受样本准确率", "0.941 验证集阈值"],
            "chart",
        ),
        "frame-08.png",
        12,
    )
    save(safety_frame(), "frame-09.png", 12)
    save(closing_frame(), "frame-10.png", 9)

    total = sum(duration for _, duration in frames)
    print(f"segments: {len(frames)}, total {total}s")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    part_paths = []
    for index, (path, duration) in enumerate(frames, 1):
        part = BUILD / f"part-{index:02}.mp4"
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "10", "-i", str(path),
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                "-crf", "22", "-pix_fmt", "yuv420p",
                str(part),
            ],
            check=True,
        )
        part_paths.append(part)
        print(f"encoded {index}/{len(frames)}")

    concat = BUILD / "concat.txt"
    concat.write_text("".join(f"file '{part.as_posix()}'\n" for part in part_paths), encoding="utf-8")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", "-movflags", "+faststart", str(OUT),
        ],
        check=True,
    )
    meta = imageio_ffmpeg.read_frames(str(OUT)).__next__()
    report = {
        "file": OUT.name,
        "duration_seconds": total,
        "bytes": OUT.stat().st_size,
        "metadata": meta,
        "mode": "actual screenshots + architecture + experiment chart + captions, no voiceover",
    }
    (ROOT / "reports" / "video-validation-agent.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
