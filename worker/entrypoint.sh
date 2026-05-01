#!/bin/sh
# 启动前自动修复挂载目录权限，兼容 root / 普通用户 / NAS 等任意环境
for dir in /sessions /downloads /cookies /config/rclone; do
    if [ -d "$dir" ]; then
        chmod 777 "$dir" 2>/dev/null || true
    fi
done

# 预下载 yt-dlp EJS 脚本（YouTube n challenge 解密需要），失败不阻断启动
echo "[entrypoint] 正在预下载 yt-dlp EJS 组件..."
yt-dlp --remote-components ejs:github -q --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>/dev/null || true
echo "[entrypoint] EJS 组件预下载完成（或已缓存）"

exec "$@"
