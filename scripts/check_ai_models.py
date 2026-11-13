#!/usr/bin/env python3
"""核对 .env 里的文案模型仍在平台模型目录中。

只读 /models，不发起生成、不消耗生成积分，也不打印任何密钥。
用法：.venv/bin/python scripts/check_ai_models.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATEWAY = 'https://devhub.supiedt.com/api/v1/model-gateway/v1'


def load_env(path: Path) -> None:
    """只补全当前进程缺失的键，不覆盖部署时注入的环境变量。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    load_env(ROOT / '.env')
    key = os.getenv('PIOS_MODEL_KEY', '')
    base = os.getenv('PIOS_GATEWAY_URL', DEFAULT_GATEWAY).rstrip('/')
    models = [m for m in (os.getenv('LLM_MODEL', ''), os.getenv('LLM_FALLBACK_MODEL', '')) if m]
    if not key:
        print('未配置 PIOS_MODEL_KEY，文案生成不会走平台模型网关。', file=sys.stderr)
        return 1
    if not models:
        print('未配置 LLM_MODEL / LLM_FALLBACK_MODEL。', file=sys.stderr)
        return 1
    request = urllib.request.Request(base + '/models', headers={'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, ValueError) as exc:
        print(f'读取平台模型目录失败：{exc}', file=sys.stderr)
        return 1
    rows = payload.get('data') if isinstance(payload, dict) else payload
    available = {row.get('id') for row in rows or [] if isinstance(row, dict)}
    missing = [model for model in models if model not in available]
    for model in models:
        print(('OK   ' if model in available else 'MISS ') + model)
    if missing:
        print('以下模型已不在目录中，请按 `pios model catalog` 重新选型。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
