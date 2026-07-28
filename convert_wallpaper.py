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
        "gif_max_width": 400,
        "gif_fps": 15,
        # 保持原尺寸（仅偶数修正）
    },
    "VIVO": {
        "dir_name": "vivo",
        "generate_gif": True,
        "gif_width": 216,
        "gif_height": 384,
        "gif_fps": 15,
        # 保持原尺寸（仅偶数修正），无码率限制
    },
    "荣耀": {
        "dir_name": "荣耀",
        "generate_gif": False,
        # 等比例放大高度至 2340 → 居中裁剪宽度至 1080
        "target_height": 2340,
        "crop_width": 1080,
    },
}


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


def make_gif(
    input_path: str,
    output_path: str,
    max_width: int = 400,
    fps: int = 15,
    height: int | None = None,
) -> None:
    """
    两阶段 palette 法生成高质量 GIF。
    - 帧率降至 ~15 fps
    - 默认宽度限制 max_width，高度等比缩放
    - 若指定 height，则强制输出 exact 尺寸 (max_width x height)
    - lanczos 下采样 + 256 色调色板
    """
    if height is not None:
        scale_expr = f"{max_width}:{height}"
    else:
        scale_expr = f"'min({max_width},iw)':-1"

    filter_complex = (
        f"fps={fps},"
        f"scale={scale_expr}:flags=lanczos,"
        "split[s0][s1];"
        "[s0]palettegen=max_colors=256[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", filter_complex,
        "-loop", "0",
        str(output_path),
    ]
    run_cmd(cmd, f"生成 GIF → {os.path.basename(output_path)}")


# ── 平台处理 ──────────────────────────────────────────────────────────

def process_oppo(
    input_path: str,
    info: dict,
    output_dir: Path,
    stem: str,
) -> None:
    """OPPO：原尺寸重编码（≤ 6 Mbps）+ GIF。"""
    w = ensure_even(info["width"])
    h = ensure_even(info["height"])

    # MP4
    mp4_out = output_dir / f"{stem}.mp4"
    encode_mp4(input_path, str(mp4_out), w, h, maxrate="6M")

    # GIF
    gif_out = output_dir / f"{stem}.gif"
    make_gif(input_path, str(gif_out), max_width=400, fps=15)


def process_vivo(input_path: str, info: dict, output_dir: Path, stem: str) -> None:
    """VIVO：原尺寸重编码（高质量，无码率限制）+ 216x384 GIF。"""
    w = ensure_even(info["width"])
    h = ensure_even(info["height"])

    mp4_out = output_dir / f"{stem}.mp4"
    encode_mp4(input_path, str(mp4_out), w, h, crf=18)

    # 216x384 GIF
    gif_out = output_dir / f"{stem}.gif"
    make_gif(input_path, str(gif_out), max_width=216, fps=15, height=384)


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
