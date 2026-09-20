#!/bin/bash
# AIOps平台版本检查脚本
# 用法: bash check_version.sh

DST="/opt/aiops-deploy"
VERSION_FILE="version.txt"

echo "AIOps平台版本信息"
echo "=================="

if [ ! -d "$DST" ]; then
  echo "[错误] $DST 不存在"
  exit 1
fi

# 获取当前版本
if [ -f "$DST/$VERSION_FILE" ]; then
  current_version=$(cat "$DST/$VERSION_FILE" | head -1 | tr -d '\n\r')
  echo "当前版本: $current_version"
else
  echo "当前版本: unknown"
fi

# 检查最新版本
if command -v curl >/dev/null 2>&1; then
  latest_version=$(curl -s "https://raw.githubusercontent.com/lxm2016/aiops-deploy/main/version.txt" 2>/dev/null | head -1 | tr -d '\n\r')
  if [ "$latest_version" != "" ] && [ "$latest_version" != "unknown" ]; then
    echo "最新版本: $latest_version"
    
    # 比较版本
    if [ "$current_version" != "unknown" ] && [ "$current_version" != "$latest_version" ]; then
      echo "[提示] 发现新版本 $latest_version，建议执行更新"
    elif [ "$current_version" = "$latest_version" ]; then
      echo "[提示] 已是最新版本"
    fi
  else
    echo "最新版本: 无法获取"
  fi
else
  echo "最新版本: curl命令不可用，无法检查"
fi

# 显示更新命令
echo ""
echo "更新命令:"
echo "- 包覆盖更新: bash update.sh <解压后的新包路径>"
echo "- Git拉取更新: bash update.sh --git-pull"
echo "- 版本检查: bash update.sh --git-pull --check-version"