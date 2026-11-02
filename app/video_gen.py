"""图文 → 竖版短视频生成器。

策略：用 PIL 画一张 1080×1920 的品牌海报（标题+卖点+公司信息+业务线色块），
再用 ffmpeg 把它做成 6 秒的静态短视频（轻微 zoom-in 效果）。

使用场景：抖音/视频号发图文内容时，没有现成视频就用这个先撑住。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

# 品牌主色（自由光 LED 风格：深蓝+亮蓝）
_BG_TOP = (15, 38, 80)      # 顶部深蓝
_BG_BOT = (8, 22, 48)       # 底部更深
_ACCENT = (255, 210, 80)    # 强调黄（LED 亮色）
_TEXT_MAIN = (255, 255, 255)
_TEXT_SUB = (200, 220, 245)
_LINE_CH = {"project": (255, 210, 80), "channel": (110, 220, 140), "both": (110, 200, 255)}

POSTER_DIR = Path("/workspace/personal-313-53/tuoke/video_out")
POSTER_DIR.mkdir(parents=True, exist_ok=True)


def _find_font(size: int, bold: bool = True):
    """找系统中文字体。优先思源/Noto，fallback 到 DejaVu。"""
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_w: int) -> list[str]:
    """按像素宽换行。"""
    from PIL import ImageDraw, Image
    img = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(img)
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _strip_html(t: str) -> str:
    t = re.sub(r'<br\s*/?>', '\n', t)
    t = re.sub(r'</p>', '\n\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    return t.strip()


def make_poster(title: str, body_text: str, biz_line: str = "channel",
                out_path: Optional[Path] = None) -> Path:
    """生成 1080×1920 竖版海报图。"""
    from PIL import Image, ImageDraw

    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), _BG_BOT)
    d = ImageDraw.Draw(img)

    # 顶部渐变（垂直方向两段）
    for y in range(H):
        t = y / H
        if t < 0.6:
            f = t / 0.6
            c = tuple(int(_BG_TOP[i] + (_BG_BOT[i] - _BG_TOP[i]) * f) for i in range(3))
        else:
            c = _BG_BOT
        d.line([(0, y), (W, y)], fill=c)

    accent = _LINE_CH.get(biz_line, _ACCENT)

    # 顶部品牌条
    f_brand = _find_font(40, bold=True)
    d.text((80, 90), "云南自由光科技", font=f_brand, fill=_TEXT_MAIN)
    # 品牌色小方块
    d.rectangle([50, 90, 70, 132], fill=accent)

    # 分隔线
    d.line([(80, 190), (W - 80, 190)], fill=accent, width=3)

    # 业务线标签
    f_tag = _find_font(32, bold=False)
    tag_txt = {"project": "甲方线 · 项目交付", "channel": "渠道线 · 合作赋能",
               "both": "自由光 · 综合服务"}.get(biz_line, "自由光科技")
    d.text((80, 220), tag_txt, font=f_tag, fill=accent)

    # 主标题（大字，自动换行）
    f_title = _find_font(96, bold=True)
    title_lines = _wrap_text(title, f_title, W - 160)
    y = 320
    for ln in title_lines[:4]:
        d.text((80, y), ln, font=f_title, fill=_TEXT_MAIN)
        y += 130

    # 取正文卖点（前几条✅/bullet，作为核心卖点）
    body = _strip_html(body_text)
    bullet_candidates = re.findall(r'[✅✓•·\-★●]\s*([^\n]{6,60})', body)
    if not bullet_candidates:
        # 没有 bullet，取前 3 个句子
        sents = re.split(r'[。！？；\n]', body)
        bullet_candidates = [s.strip() for s in sents if 8 <= len(s.strip()) <= 60][:3]
    else:
        bullet_candidates = bullet_candidates[:4]

    f_sub = _find_font(48, bold=False)
    y += 40
    for s in bullet_candidates:
        d.text((80, y), "▸", font=f_sub, fill=accent)
        # 卖点换行（限两行）
        sub_lines = _wrap_text(s, f_sub, W - 240)
        for sl in sub_lines[:2]:
            d.text((140, y), sl, font=f_sub, fill=_TEXT_SUB)
            y += 80
        y += 10

    # 底部公司信息条
    f_foot = _find_font(36, bold=False)
    f_foot_s = _find_font(28, bold=False)
    foot_y = H - 240
    d.line([(80, foot_y), (W - 80, foot_y)], fill=(80, 110, 160), width=2)
    d.text((80, foot_y + 40), "LED 显示 · 大屏方案 · 工程交付", font=f_foot, fill=_TEXT_MAIN)
    d.text((80, foot_y + 110), "京东方 LED 云南省总代  |  大华金牌代理  |  TCL 一级代理",
           font=f_foot_s, fill=_TEXT_SUB)

    out_path = out_path or POSTER_DIR / f"poster_{abs(hash(title)) % 10**10}.png"
    img.save(out_path, "PNG", optimize=True)
    return out_path


def make_video(poster_path: Path, out_path: Optional[Path] = None,
               duration: float = 6.0, zoom_in: bool = True) -> Path:
    """把海报图做成 6 秒短视频（带轻微 zoom-in，比静止图好看）。

    1080×1920 静态图 + zoompan 平滑推近，输出 H.264 mp4。
    """
    out_path = out_path or POSTER_DIR / (poster_path.stem + ".mp4")
    vf = (
        # zoompan：从 1.0x 慢推到 1.05x，让画面有轻微动感
        f"zoompan=z='min(zoom+0.0008,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={int(duration * 25)}:s=1080x1920:fps=25"
        if zoom_in else "scale=1080:1920"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(poster_path),
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",  # 加空音轨（抖音喜欢有音轨）
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-t", str(duration),
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {r.stderr[-400:]}")
    return out_path


def gen_video_for_variant(title: str, body_html: str, biz_line: str = "channel",
                          duration: float = 6.0) -> Path:
    """端到端：标题+正文 → 海报 → mp4。返回视频文件路径。"""
    poster = make_poster(title, body_html, biz_line)
    return make_video(poster, duration=duration)
