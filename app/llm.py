"""大模型调用封装：多 provider 故障转移（DeepSeek → GLM → Kimi）。
全部走 OpenAI 兼容接口。配置见 .env 的 LLM_PROVIDERS JSON。
"""
import json
import os
from pathlib import Path

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# 默认三家池子，env 里可用 LLM_PROVIDERS JSON 覆盖
PROVIDERS = json.loads(os.environ.get("LLM_PROVIDERS", "null")) or [
    {"name": "deepseek", "base_url": "https://api.deepseek.com/v1",
     "model": "deepseek-chat", "key": os.environ.get("DEEPSEEK_KEY", "")},
    {"name": "glm", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4.5-flash", "key": os.environ.get("GLM_KEY", "")},
    {"name": "kimi", "base_url": "https://api.moonshot.cn/v1",
     "model": "kimi-k2.6", "key": os.environ.get("KIMI_KEY", "")},
]

_active = None  # 当前可用 provider 名


def _glm_token(key: str) -> str:
    """智谱 GLM 用 JWT(APIKey.APISecret 签名) 而非直接 Bearer。"""
    import base64, hashlib, hmac, json as _j, time
    kid, sec = key.split(".")
    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    h = b64(_j.dumps({"alg": "HS256", "sign_type": "SIGN"}).encode())
    p = b64(_j.dumps({"api_key": kid, "exp": int(time.time() * 1000) + 3600000,
                      "timestamp": int(time.time() * 1000)}).encode())
    s = b64(hmac.new(sec.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"


def _try(p: dict, system: str, user: str, json_mode: bool) -> str | None:
    if not p["key"]:
        return None
    try:
        from openai import OpenAI
        key = p["key"]
        if p["name"] == "glm":          # GLM 需要 JWT 签名
            key = _glm_token(key)
        client = OpenAI(api_key=key, base_url=p["base_url"], timeout=60)
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        r = client.chat.completions.create(
            model=p["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            **kw)
        return r.choices[0].message.content or ""
    except Exception as e:
        print(f"[llm] {p['name']} fail: {e}", flush=True)
        return None


import threading
_lock = threading.Lock()

def chat(system: str, user: str, json_mode: bool = False) -> str:
    global _active
    import time
    PRIORITY = {"glm": 0, "kimi": 1, "deepseek": 2}
    ordered = sorted(PROVIDERS,
                     key=lambda p: (-1 if p["name"] == _active else PRIORITY.get(p["name"], 9)))
    for p in ordered:
        for attempt in range(3):
            print(f"[llm] try {p['name']} #{attempt+1}", flush=True)
            with _lock:
                out = _try(p, system, user, json_mode)
            if out:
                print(f"[llm] ok {p['name']} len={len(out)}", flush=True)
                _active = p["name"]
                return out
            if attempt < 2:
                print(f"[llm] {p['name']} backoff 5s", flush=True)
                time.sleep(5)
    print("[llm] all fail, return stub", flush=True)
    return _stub(json_mode)


def chat_json(system: str, user: str) -> dict:
    raw = chat(system, user, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _stub(json_mode: bool) -> str:
    if json_mode:
        return json.dumps({
            "douyin": {"body": "[STUB] 口播脚本占位", "cover_text": "占位", "hashtags": "#弱电", "image_prompt": "仓库实拍", "best_time": "18:00"},
            "shipinhao": {"body": "[STUB] 视频号占位", "cover_text": "占位", "hashtags": "", "image_prompt": "", "best_time": "12:00"},
            "gzh": {"body": "[STUB] 公众号占位", "cover_text": "占位", "hashtags": "", "image_prompt": "", "best_time": "17:00"},
            "moments": {"body": "[STUB] 朋友圈占位", "cover_text": "", "hashtags": "", "image_prompt": "", "best_time": "08:30"},
        }, ensure_ascii=False)
    return "[STUB] 所有 LLM 均不可用"


def status() -> dict:
    """返回各 provider 可用性，供前端/健康检查展示。"""
    return {"active": _active,
            "providers": [{"name": p["name"], "model": p["model"],
                           "configured": bool(p["key"])} for p in PROVIDERS]}
