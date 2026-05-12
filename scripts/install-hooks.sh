#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# 装本项目的 git hooks (本地防线)
#
# 用法: bash scripts/install-hooks.sh
#
# Git hooks 不能被 git 跟踪 (位于 .git/hooks/ 下), 所以模板放在
# scripts/hooks/ 里, 用本脚本拷过去. 每个新 clone 的机器都要跑一次.
# ─────────────────────────────────────────────────────────────────

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "✗ 不在 git 仓库里. 在项目根目录跑本脚本."
  exit 1
fi

HOOK_SRC="$REPO_ROOT/scripts/hooks"
HOOK_DST="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOK_SRC" ]; then
  echo "✗ 找不到 $HOOK_SRC, 项目结构是否正确?"
  exit 1
fi

mkdir -p "$HOOK_DST"

INSTALLED=0
for src in "$HOOK_SRC"/*; do
  [ -f "$src" ] || continue
  name=$(basename "$src")
  cp "$src" "$HOOK_DST/$name"
  chmod +x "$HOOK_DST/$name"
  echo "✓ $name → .git/hooks/$name"
  INSTALLED=$((INSTALLED+1))
done

if [ "$INSTALLED" -eq 0 ]; then
  echo "⚠ 没装任何 hook (scripts/hooks/ 是空的?)"
  exit 1
fi

echo ""
echo "─── 已装 $INSTALLED 个 hook ───"
echo "现在 git commit 前会自动扫描 staged 改动."
echo "测试: 故意往任意文件 stage 一行 RFC1918 私网 IP (192-dot-168-dot-X-dot-Y 段), 跑 git commit, 应被拒."
