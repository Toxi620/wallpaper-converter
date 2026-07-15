# 在 Mac 终端执行：

# 1. 设置 git 身份（首次需要）
git config --global user.email "你的邮箱"
git config --global user.name "Toxi620"

# 2. 克隆仓库
git clone https://github.com/Toxi620/wallpaper-converter.git
cd wallpaper-converter

# 3. 把写好的代码放进去
#    - 复制 convert_wallpaper.py 到 wallpaper-converter/
#    - 复制 build_mac.sh 到 wallpaper-converter/
#    - 复制 .github/workflows/build.yml 到对应目录

# 4. 推送
git add -A
git commit -m "feat: 动态壁纸三平台转换工具"
git push origin main

# 推送后 Actions 会自动开始打包
# 在 https://github.com/Toxi620/wallpaper-converter/actions 查看进度
# 打包完下载 Artifacts 即可
