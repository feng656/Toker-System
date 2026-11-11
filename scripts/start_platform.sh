#!/bin/sh
# 平台部署入口：先迁移和幂等初始化，再启动 API。
# 迁移/种子失败时容器直接退出，健康检查会失败，不带着半初始化数据库对外服务。
set -eu

echo "[start] alembic upgrade head"
alembic upgrade head

echo "[start] seed (idempotent)"
python -m scripts.seed

echo "[start] uvicorn on :8300"
exec uvicorn app.main:app --host 0.0.0.0 --port 8300 --workers "${WEB_CONCURRENCY:-2}"
