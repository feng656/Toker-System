#!/bin/sh
# 平台部署入口：先迁移和幂等初始化，再启动 API。
# 迁移/种子失败时容器直接退出，健康检查会失败，不带着半初始化数据库对外服务。
set -eu

echo "[start] alembic upgrade head"
alembic upgrade head

echo "[start] seed (idempotent)"
python -m scripts.seed

# 可选的内置扫码适配器：只在 BROWSER_ENABLED=true 时启动，监听本机回环，
# 由 API 通过 BROWSER_ADAPTER_URL 调用。Chromium 起不来就让容器失败，
# 避免部署显示健康但扫码功能实际不可用。
if python -c "from app import config; raise SystemExit(0 if config.BROWSER_ENABLED else 1)"; then
  ADAPTER_PORT=$(python -c "from app import config; print(config.LOGIN_ADAPTER_PORT)")
  echo "[start] login adapter on 127.0.0.1:${ADAPTER_PORT}"
  python -m app.login_adapter > var/login_adapter.log 2>&1 &
  adapter_pid=$!
  i=0
  while [ "$i" -lt 30 ]; do
    if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${ADAPTER_PORT}/health', timeout=2)" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "$adapter_pid" 2>/dev/null; then
      echo "[start] login adapter exited unexpectedly"
      cat var/login_adapter.log || true
      exit 1
    fi
    i=$((i + 1))
    sleep 1
  done
  if [ "$i" -ge 30 ]; then
    echo "[start] login adapter health check timed out"
    cat var/login_adapter.log || true
    kill "$adapter_pid" 2>/dev/null || true
    exit 1
  fi
fi

echo "[start] uvicorn on :8300"
exec uvicorn app.main:app --host 0.0.0.0 --port 8300 --workers "${WEB_CONCURRENCY:-2}"
