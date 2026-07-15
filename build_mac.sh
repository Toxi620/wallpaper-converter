#!/bin/bash
# ============================================================
#  Mac 打包脚本 — 将 convert_wallpaper.py + ffmpeg 打包为单文件
# ============================================================
# 用法: 在 Mac 上运行:
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# 前提: 已安装 PyInstaller
#   pip3 install pyinstaller
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  Step 1: 下载 macOS ffmpeg 静态二进制"
echo "========================================="

FFMPEG_URL="https://evermeet.cx/ffmpeg/ffmpeg-7.1.zip"
FFPROBE_URL="https://evermeet.cx/ffmpeg/ffprobe-7.1.zip"

mkdir -p /tmp/ffmpeg-bundle

if [ ! -f /tmp/ffmpeg-bundle/ffmpeg ]; then
    curl -L -o /tmp/ffmpeg.zip "$FFMPEG_URL"
    unzip -o /tmp/ffmpeg.zip -d /tmp/ffmpeg-bundle/
fi

if [ ! -f /tmp/ffmpeg-bundle/ffprobe ]; then
    curl -L -o /tmp/ffprobe.zip "$FFPROBE_URL"
    unzip -o /tmp/ffprobe.zip -d /tmp/ffmpeg-bundle/
fi

chmod +x /tmp/ffmpeg-bundle/ffmpeg /tmp/ffmpeg-bundle/ffprobe
echo "  ffmpeg 版本: $(/tmp/ffmpeg-bundle/ffmpeg -version 2>&1 | head -1)"
echo ""

echo "========================================="
echo "  Step 2: PyInstaller 打包"
echo "========================================="

pyinstaller --onefile --console \
    --add-data "/tmp/ffmpeg-bundle/ffmpeg:." \
    --add-data "/tmp/ffmpeg-bundle/ffprobe:." \
    --name "壁纸转换工具" \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR" \
    "$SCRIPT_DIR/convert_wallpaper.py"

echo ""
echo "========================================="
echo "  ✅ 打包完成！"
echo "  输出文件: $SCRIPT_DIR/dist/壁纸转换工具"
echo "  大小: $(du -h "$SCRIPT_DIR/dist/壁纸转换工具" | cut -f1)"
echo ""
echo "  使用方式:"
echo "    ./dist/壁纸转换工具 ~/Downloads/input.mp4"
echo "    或直接拖拽视频到 壁纸转换工具 图标上"
echo "========================================="
