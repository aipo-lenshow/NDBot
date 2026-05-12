#!/bin/sh
# 启动前自动修复挂载目录权限，兼容 root / 普通用户 / NAS 等任意环境
for dir in /downloads; do
    if [ -d "$dir" ]; then
        chmod 777 "$dir" 2>/dev/null || true
    fi
done
exec "$@"
