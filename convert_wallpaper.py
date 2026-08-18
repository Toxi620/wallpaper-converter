#!/usr/bin/env python3
"""
动态壁纸视频转平台 — 视频转 MP4+GIF 工具
===========================================
将输入的 MP4 视频自动转换为 OPPO / VIVO / 荣耀三个手机的动态壁纸格式。
最终运行环境为 macOS，视频编码保证 Mac/iOS 原生播放器兼容。

依赖：可单独运行（自带 ffmpeg 打包）或依赖系统已安装的 ffmpeg

用法：
    python convert_wallpaper.py /path/to/input.mp4       # 直接传参
    python convert_wallpaper.py                           # 交互式输入路径

打包（在 Mac 上运行）：
    curl -L -o /tmp/ffmpeg.zip https://evermeet.cx/ffmpeg/ffmpeg-7.1.zip
    unzip /tmp/ffmpeg.zip -d /tmp/ffmpeg-bin/
    pyinstaller --onefile --add-data "/tmp/ffmpeg-bin/ffmpeg:." \\
                           --add-data "/tmp/ffmpeg-bin/ffprobe:." \\
                           --name "壁纸转换工具" convert_wallpaper.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


# ── ffmpeg 路径查找（支持 PyInstaller 打包）─────────────────────────

def _get_ffmpeg_paths() -> tuple[str, str]:
    """
    返回 (ffmpeg_path, ffprobe_path) 元组。
    查找顺序：
      1. PyInstaller bundle 内 (sys._MEIPASS)
      2. 脚本同目录下的 ffmpeg/ffprobe
      3. 系统 PATH
    """
    is_win = sys.platform.startswith("win")
    ffmpeg_exe = "ffmpeg.exe" if is_win else "ffmpeg"
    ffprobe_exe = "ffprobe.exe" if is_win else "ffprobe"
    candidates = []

    # 1) PyInstaller bundle
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        candidates.append((base / ffmpeg_exe, base / ffprobe_exe))

    # 2) 脚本同目录
    script_dir = Path(__file__).resolve().parent
    candidates.append((script_dir / ffmpeg_exe, script_dir / ffprobe_exe))

    for ffmpeg, ffprobe in candidates:
        if ffmpeg.exists() and ffprobe.exists():
            return (str(ffmpeg), str(ffprobe))

    # 3) 系统 PATH
    return (ffmpeg_exe, ffprobe_exe)


FFMPEG_PATH, FFPROBE_PATH = _get_ffmpeg_paths()


# ── 平台配置 ──────────────────────────────────────────────────────────

PLATFORMS = {
    "OPPO": {
        "dir_name": "OPPO",
        "generate_gif": True,
        "max_bitrate": "6M",  # ≤ 6 Mbps
        # GIF 规格：固定 400x710、大小≤3MB、色数≥128、帧率[10,15]、总帧数[20,30]
    },
    "VIVO": {
        "dir_name": "vivo",
        "generate_gif": True,
        "gif_width": 216,
        "gif_height": 384,
        "gif_fps": 15,
        "gif_min_fps": 10,       # GIF 帧率下限
        "gif_max_size_mb": 1,    # GIF 大小上限 (<1MB)
        # MP4 无码率限制（高质量 crf=18）
    },
    "荣耀": {
        "dir_name": "荣耀",
        "generate_gif": False,
        # 等比例放大高度至 2340 → 居中裁剪宽度至 1080
        "target_height": 2340,
        "crop_width": 1080,
    },
}

# ── GIF 色彩保真（256 色量化 vs 原片色彩）──────────────────────────────
# 抖动：OPPO 用 sierra2_4a（平滑、SSIM 最接近源片）；VIVO 因 <1MB 硬约束
# 只能用 bayer（sierra 误差扩散难压缩、会超限）。
# eq 补偿作用于调色板路径 [s0]（输出帧 [s1] 保持原色），强度按平台传入：
#   OPPO+sierra 扫出最优强度 OPPO_GIF_SAT_BOOST=1.08：色数降到 128 时近白区
#   （luma≥200）细微色调像素会从源片 35.6% 掉到 30%（淡色调被抹成纯白，整体
#   显得"发白偏灰"）；eq=1.08 可恢复到 34.8%，全局饱和度仅 101.3%、MAE 2.76、
#   SSIM 仍 0.982。eq=1.0 虽饱和度最贴(97.1%)但保留不了淡色调；eq=1.3 过冲
#   (103.5%) 又明显偏离原片。VIVO 用 bayer+eq=1.3:1.04，用户确认观感 OK。
OPPO_GIF_SAT_BOOST = 1.08    # OPPO 近白区色调的温和补偿（详见上方注释）


# ── 工具函数 ──────────────────────────────────────────────────────────

def ensure_even(n: int) -> int:
    """向下取整到最近的偶数。"""
    return n if n % 2 == 0 else n - 1


def run_cmd(cmd: list[str], desc: str = "") -> None:
    """运行外部命令，失败时打印错误并退出。"""
    print(f"  [CMD] {desc or ' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        print("  [ERROR] 未找到 ffmpeg/ffprobe，请确认已安装并加入 PATH。")
        sys.exit(1)

    if result.returncode != 0:
        # ffmpeg 错误信息通常在 stderr
        err = result.stderr.strip() or result.stdout.strip()
        print(f"  [ERROR] 命令失败 (exit={result.returncode}): {err[:500]}")
        sys.exit(1)


def get_video_info(path: str) -> dict:
    """用 ffprobe 读取视频文件的宽、高、帧率、时长。"""
    cmd = [
        FFPROBE_PATH, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        path,
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print("[ERROR] 未找到 ffprobe，请确认已安装 ffmpeg 并加入 PATH。")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print(f"[ERROR] 无法读取视频文件: {path}")
        sys.exit(1)

    data = json.loads(result.stdout)
    video_stream = None
    for s in data.get("streams", []):
        if s["codec_type"] == "video":
            video_stream = s
            break

    if video_stream is None:
        print("[ERROR] 未找到视频流。")
        sys.exit(1)

    width = int(video_stream["width"])
    height = int(video_stream["height"])
    # ffprobe 用 "r_frame_rate" 作为分数如 "24/1"
    r_frame_rate = video_stream.get("r_frame_rate", "0/1")
    num, den = r_frame_rate.split("/")
    fps = float(num) / float(den) if float(den) != 0 else 0.0
    duration = float(video_stream.get("duration", 0))

    print(f"  [INFO] 源视频: {width}x{height}, {fps:.2f} fps, {duration:.2f}s")
    return {"width": width, "height": height, "fps": fps, "duration": duration}


def encode_mp4(
    input_path: str,
    output_path: str,
    width: int,
    height: int,
    maxrate: str | None = None,
    crf: int | None = None,
) -> None:
    """
    使用 libx264 + yuv420p 编码 MP4。
    - width / height 已确保为偶数
    - scale 滤镜即使传入偶数也会做一次防御性偶数修正
    - maxrate: OPPO 限码率用 (≤ 6 Mbps)
    - crf: VIVO/荣耀 高质量用 (18)
    """
    scale_filter = f"scale='trunc({width}/2)*2:trunc({height}/2)*2'"
    cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", scale_filter,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-c:a", "aac",
    ]
    if maxrate:
        cmd += ["-maxrate", maxrate, "-bufsize", f"{maxrate}"]
        cmd += ["-b:v", maxrate]
    if crf is not None:
        cmd += ["-crf", str(crf)]
    cmd.append(str(output_path))

    run_cmd(cmd, f"编码 MP4 → {os.path.basename(output_path)}")


def make_gif_constrained(
    input_path: str,
    output_path: str,
    width: int,
    height: int,
    max_size_bytes: int,
    min_fps: int = 10,
    start_fps: int = 15,
    min_colors: int = 64,
    max_frames: int | None = None,
    dither: str = "bayer:bayer_scale=2",
    sat_boost: float = 1.0,
    contrast_boost: float = 1.0,
) -> None:
    """
    生成满足约束的 GIF（尺寸固定，不缩放）：
    - 尺寸固定为 width x height（VIVO 要求 216x384 / OPPO 要求 400x710）
    - 帧率不低于 min_fps（VIVO/OPPO 要求 ≥10 fps）
    - 色数不低于 min_colors（VIVO 默认 64 / OPPO 要求 ≥128）
    - 总帧数不超过 max_frames（OPPO 要求 [20,30]）：把源视频裁到
      max_frames/start_fps 秒（如 30/15 = 2s），降到 min_fps 时帧数同步变少
      （10fps*2s = 20 帧），仍落在 [20,30]，且压缩依然有效
    - 文件大小不超过 max_size_bytes（VIVO 要求 <1MB / OPPO 要求 ≤3MB）
    压缩策略（按优先级）：先降帧率到 min_fps → 降调色板色数（不低于 min_colors），
    尺寸始终不变。每轮生成后检查大小，直到达标或达到最小压缩。
    色彩保真：eq 只加在调色板路径 [s0]（sat_boost/contrast_boost，默认 1.0 即不补偿），
    输出帧 [s1] 保持原色；抖动用 dither 参数
    （OPPO=sierra2_4a 平滑、无需 eq；VIVO=bayer + eq=1.3:1.04 因 <1MB 硬约束）。
    """
    w = ensure_even(width)
    h = ensure_even(height)
    fps = start_fps
    colors = 256
    max_attempts = 12
    trim_duration = f"{max_frames / start_fps:.3f}" if max_frames else None

    for attempt in range(1, max_attempts + 1):
        # 仅当需要 eq 补偿时才插入该滤镜，避免无谓的像素处理
        s0_eq = ""
        if sat_boost != 1.0 or contrast_boost != 1.0:
            s0_eq = f"eq=saturation={sat_boost}:contrast={contrast_boost},"
        filter_complex = (
            f"fps={fps},"
            f"scale={w}:{h}:flags=lanczos,"
            "split[s0][s1];"
            f"[s0]{s0_eq}palettegen=max_colors={colors}[p];"
            f"[s1][p]paletteuse=dither={dither}"
        )
        cmd = [
            FFMPEG_PATH, "-y", "-i", input_path,
            "-vf", filter_complex,
            "-loop", "0",
        ]
        if trim_duration:
            cmd += ["-t", trim_duration]
        cmd.append(str(output_path))
        run_cmd(cmd, f"生成 GIF (fps={fps}, {w}x{h}, {colors}色) — 第{attempt}次尝试")
        size = os.path.getsize(output_path)
        print(f"  [INFO] GIF 大小: {size/1024:.0f}KB (目标 ≤ {max_size_bytes/1024:.0f}KB)")
        if size <= max_size_bytes:
            print(f"  [INFO] GIF 达标 [OK] {w}x{h} @ {fps}fps, {colors}色")
            return

        # 未达标 → 尺寸不变，仅降帧率到 min_fps，再降调色板色数（不低于 min_colors）
        if fps > min_fps:
            fps = max(min_fps, fps - 5)
        elif colors > min_colors:
            colors = max(min_colors, colors // 2)
        else:
            break

    print(f"  [WARN] 已达最小压缩仍超限 ({size/1024:.0f}KB)，尺寸保持 {w}x{h}，保留当前结果")


# ── 平台处理 ──────────────────────────────────────────────────────────

def process_oppo(
    input_path: str,
    info: dict,
    output_dir: Path,
    stem: str,
) -> None:
    """OPPO：原尺寸重编码（≤ 6 Mbps）+ 400x710 GIF（≤3MB、色数≥128、fps[10,15]、帧数[20,30]）。"""
    w = ensure_even(info["width"])
    h = ensure_even(info["height"])

    # MP4
    mp4_out = output_dir / f"{stem}.mp4"
    encode_mp4(input_path, str(mp4_out), w, h, maxrate="6M")

    # GIF：固定 400x710，约束：大小≤3MB、色数≥128、帧率[10,15]、总帧数[20,30]（超限自动压缩）
    gif_out = output_dir / f"{stem}.gif"
    make_gif_constrained(
        input_path, str(gif_out),
        width=400, height=710,
        max_size_bytes=3 * 1024 * 1024,
        min_fps=10, start_fps=15,
        min_colors=128,
        max_frames=30,
        dither="sierra2_4a",  # OPPO 有 3MB 余量，用更平滑、更贴源片的抖动
        sat_boost=OPPO_GIF_SAT_BOOST,  # 温和补偿，补回近白区被抹掉的淡色调
    )


def process_vivo(input_path: str, info: dict, output_dir: Path, stem: str) -> None:
    """VIVO：原尺寸重编码（高质量，无码率限制）+ 216x384 GIF（帧率≥10fps、大小<1MB）。"""
    w = ensure_even(info["width"])
    h = ensure_even(info["height"])

    mp4_out = output_dir / f"{stem}.mp4"
    encode_mp4(input_path, str(mp4_out), w, h, crf=18)

    # 216x384 GIF，约束：帧率≥10fps、文件<1MB（超限自动压缩）
    gif_out = output_dir / f"{stem}.gif"
    make_gif_constrained(
        input_path, str(gif_out),
        width=216, height=384,
        max_size_bytes=1 * 1024 * 1024,
        min_fps=10, start_fps=15,
        dither="bayer:bayer_scale=2",
        sat_boost=1.3, contrast_boost=1.04,  # bayer 小尺寸需 eq 补偿（用户确认 OK）
    )


def process_honor(input_path: str, info: dict, output_dir: Path, stem: str) -> None:
    """
    荣耀：等比例放大（高度 → 2340）→ 居中裁剪宽度至 1080。
    公式：
      scale_factor = 2340 / src_height
      new_w        = trunc(src_width * scale_factor / 2) * 2   （偶数）
      crop_x       = (new_w - 1080) // 2
      滤镜： scale={new_w}:2340, crop=1080:2340:{crop_x}:0
    """
    src_w = info["width"]
    src_h = info["height"]
    target_h = 2340
    crop_w = 1080

    scale_factor = target_h / src_h
    new_w = ensure_even(int(src_w * scale_factor))
    crop_x = (new_w - crop_w) // 2

    print(f"  [INFO] 荣耀缩放: {src_w}x{src_h} → {new_w}x{target_h} → 裁宽 {crop_w} (crop_x={crop_x})")

    scale_filter = f"scale={new_w}:{target_h}"
    crop_filter = f"crop={crop_w}:{target_h}:{crop_x}:0"

    cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", f"{scale_filter},{crop_filter}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
    ]
    mp4_out = output_dir / f"{stem}.mp4"
    cmd.append(str(mp4_out))

    run_cmd(cmd, f"编码荣耀 MP4 → {stem}.mp4")


# ── 编排 ──────────────────────────────────────────────────────────────

PROCESSORS = {
    "OPPO": process_oppo,
    "VIVO": process_vivo,
    "荣耀": process_honor,
}


def process_all(input_path: str, output_base: Path) -> None:
    """读取视频信息，为三个平台分别调用处理函数。"""
    info = get_video_info(input_path)
    stem = Path(input_path).stem

    for platform_key, processor in PROCESSORS.items():
        cfg = PLATFORMS[platform_key]
        out_dir = output_base / cfg["dir_name"]
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*50}")
        print(f"  [PLAT] 平台: {platform_key}  目录: {out_dir}")
        print(f"{'='*50}")
        processor(input_path, info, out_dir, stem)

    print(f"\n[DONE] 全部完成！输出目录: {output_base}")


def main() -> None:
    """CLI 入口。"""
    print("=" * 50)
    print("  动态壁纸视频转平台 — 转换工具")
    print("  OPPO / VIVO / 荣耀 三平台一键生成")
    print("=" * 50)

    if len(sys.argv) >= 2:
        input_path = sys.argv[1]
    else:
        input_path = input("请将 MP4 视频拖入或输入路径: ").strip().strip('"').strip("'")

    if not input_path:
        print("[ERROR] 未提供输入路径。")
        sys.exit(1)

    if not os.path.isfile(input_path):
        print(f"[ERROR] 文件不存在: {input_path}")
        sys.exit(1)

    ext = os.path.splitext(input_path)[1].lower()
    if ext not in (".mp4", ".mov", ".m4v"):
        print(f"[WARN]  文件扩展名为 {ext}，非 MP4 格式，尝试继续处理…")

    # 输出目录 = 输入视频所在目录
    input_dir = Path(input_path).resolve().parent
    process_all(input_path, input_dir)


if __name__ == "__main__":
    main()
