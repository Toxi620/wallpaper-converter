# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: 动态壁纸视频转平台 (Wallpaper Converter)

Single Python script that converts an MP4 video to three phone-brands' dynamic wallpaper formats (OPPO, VIVO, 荣耀/Honor) using ffmpeg under the hood. Can be packaged as a standalone macOS executable via PyInstaller (bundles ffmpeg inside).

## Commands

```bash
# Run (requires ffmpeg on system PATH)
python convert_wallpaper.py /path/to/input.mp4

# No args = interactive path input
python convert_wallpaper.py

# GitHub Actions: push to main/tag triggers macOS build automatically
#   → Artifact: "壁纸转换工具" (single-file macOS executable, ~50MB)
```

### Manual packaging (macOS only)
```bash
pip3 install pyinstaller
./build_mac.sh        # downloads ffmpeg + builds with pyinstaller --onefile
```

## Architecture

### Single-file structure: `convert_wallpaper.py`

| Section | Lines | Role |
|---------|-------|------|
| ffmpeg path resolver | 33-62 | Finds ffmpeg/ffprobe: PyInstaller bundle → script dir → system PATH |
| Platform config | 68-97 | OPPO/VIVO/荣耀 presets (dir names, bitrate limits, scaling rules) |
| Core ffmpeg wrappers | 104-290 | `run_cmd`, `get_video_info`(via ffprobe), `encode_mp4`, `make_gif`, `make_gif_constrained` |
| Platform processors | 292-372 | `process_oppo`, `process_vivo`, `process_honor` |
| Orchestration | 375-413 | `process_all` iterates PROCESSORS map; `main` is CLI entry point |

### Processing pipeline

```
Input MP4 → get_video_info() → loop over PROCESSORS map
  ├── OPPO:   encode_mp4(1080x1920, maxrate=6M) + make_gif_constrained(400x710, ≤3MB, 色数≥128, fps[10,15], 帧数[20,30])
  ├── VIVO:   encode_mp4(1080x1920, crf=18) + make_gif_constrained(216x384, ≥10fps, <1MB)
  └── 荣耀:   scale:1316x2340 → center-crop:1080x2340 → encode_mp4(crf=18)
```

### Key technical details

- **Mac compatibility**: Always uses `libx264` + `pix_fmt=yuv420p` (mandatory), even-dimension scale filter (`trunc(w/2)*2`).
- **GIF quality**: Two-stage palette method (`split` → `palettegen` → `paletteuse`), NOT a direct conversion. The original "gray/washed-out" look had two causes, fixed separately: **(1) bayer dither noise** (switching OPPO to `sierra2_4a` raised SSIM 0.963 → 0.973), and **(2) faint-tint loss in near-white areas** when the palette drops to 128 colors — measured: light pixels (luma≥200) with slight tint (sat≥0.04) fall from source 35.6% → 30.0% in the GIF, which reads as "whiter/grayer than the source". Dithering and eq compensation are per-platform (`dither`, `sat_boost`, `contrast_boost` args; eq applies to the palette path `[s0]` only, output frames `[s1]` keep original pixels so nothing overshoots):
  - **OPPO**: `dither=sierra2_4a` + `sat_boost=OPPO_GIF_SAT_BOOST` (1.08) — the measured sweet spot: restores near-white tint to 34.8% (≈ source 35.6%) with only 101.3% saturation, MAE 2.76, SSIM 0.982. eq=1.0 keeps saturation closest (97.1%) but loses the tint; eq=1.3 overshoots (103.5%, MAE 5.66). `eq` filter is only inserted when sat_boost/contrast_boost ≠ 1.0.
  - **VIVO**: `dither=bayer:bayer_scale=2` (sierra error-diffusion is too hard to compress and breaks the <1MB cap) + `eq=1.3:1.04` on the palette path only — user-confirmed OK.
- **荣耀 scaling**: Proportional scale so height=2340 (factor 2340/src_h), then center-crop width to 1080. Formula: `new_w = trunc(src_w * 2340 / src_h / 2) * 2`.
- **OPPO bitrate**: `-maxrate 6M -bufsize 6M -b:v 6M` ensures ≤6Mbps.
- **VIVO GIF 约束**: `make_gif_constrained` 尺寸**固定 216x384**（不缩放），帧率下限 10fps、大小 <1MB；超限时先降帧率(15→10)再降调色板色数(256→128→64)，尺寸不变；仍超限则警告并保留当前结果。抖动用 `dither=bayer:bayer_scale=2`（sierra 误差扩散难压缩，会顶破 <1MB）+ 调色板路径 `eq=saturation=1.3:contrast=1.04`。
- **OPPO GIF 约束**: 同 `make_gif_constrained`，尺寸**固定 400x710**、大小 ≤3MB、色数下限 **128**、帧率 [10,15]、总帧数 [20,30]；帧数上限通过把源视频裁到 `max_frames/start_fps`（30/15=2s）实现，降到 10fps 时帧数同步减为 20，仍落在 [20,30]。抖动用 `dither=sierra2_4a`（3MB 余量足够，观感更贴源片）+ `sat_boost=1.08`（补回 128 色时近白区被抹掉的淡色调，避免"比源视频偏白偏灰"）。
- **Path resolution**: `FFMPEG_PATH, FFPROBE_PATH` globals set once at module load. PyInstaller `sys._MEIPASS` gets priority so bundled binary works offline.

### Output layout

All files are created relative to the script's parent directory:
```
script_dir/
├── OPPO/{stem}.mp4, {stem}.gif
├── vivo/{stem}.mp4, {stem}.gif
└── 荣耀/{stem}.mp4
```
