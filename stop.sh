#!/bin/bash
# stop.sh · 停止 bid-master 服务（DEV-0058 起委托 start.sh 统一实现，避免双份停止逻辑）
# 保留此文件兼容既有习惯（README/DEV_LOG 历史引用 ./stop.sh）。
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/start.sh" stop
