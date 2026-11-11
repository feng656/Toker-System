"""环境配置；相对路径始终相对于项目根，不依赖操作系统或当前目录。"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)

DATABASE_URL = os.getenv('DATABASE_URL', '')
JWT_SECRET = os.getenv('JWT_SECRET', '')
JWT_EXPIRE_HOURS = int(os.getenv('JWT_EXPIRE_HOURS', '24'))
APP_ENV = os.getenv('APP_ENV', 'production')
DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() == 'true'
SCHEDULER_ENABLED = os.getenv('SCHEDULER_ENABLED', 'false').lower() == 'true'
CORS_ORIGINS = [v.strip() for v in os.getenv('CORS_ORIGINS', '').split(',') if v.strip()]
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', '')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', '')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', '')
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'tuoke')
MINIO_SECURE = os.getenv('MINIO_SECURE', 'false').lower() == 'true'
WECOM_WEBHOOK = os.getenv('WECOM_WEBHOOK', '')
CRM_WEBHOOK = os.getenv('CRM_WEBHOOK', '')
CRM_TOKEN = os.getenv('CRM_TOKEN', '')
LLM_PROVIDERS = json.loads(os.getenv('LLM_PROVIDERS', '[]'))
# 平台网关一次四平台长文生成实测约 60s，30s 会稳定超时；默认给足 120s。
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '120'))
# 平台模型网关（OpenAI 兼容）。配置 PIOS_MODEL_KEY 后，未显式给 LLM_PROVIDERS 时自动接入。
PIOS_GATEWAY_URL = os.getenv('PIOS_GATEWAY_URL', 'https://devhub.supiedt.com/api/v1/model-gateway/v1')
PIOS_MODEL_KEY = os.getenv('PIOS_MODEL_KEY', '')
LLM_MODEL = os.getenv('LLM_MODEL', 'deepseek/deepseek-v3.2')
LLM_FALLBACK_MODEL = os.getenv('LLM_FALLBACK_MODEL', 'qwen/qwen3.7-flash')
# 平台视频生成（/agent-api/video/*）。PIOS_API_URL 形如 https://host/api/v1。
PIOS_API_URL = os.getenv('PIOS_API_URL', '').rstrip('/')
PIOS_TOKEN = os.getenv('PIOS_TOKEN', '')
VIDEO_PROVIDER = os.getenv('VIDEO_PROVIDER', 'pios')
VIDEO_MODEL = os.getenv('VIDEO_MODEL', 'MiniMax-H3')
VIDEO_RESOLUTION = os.getenv('VIDEO_RESOLUTION', '768P')
VIDEO_ASPECT_RATIO = os.getenv('VIDEO_ASPECT_RATIO', '9:16')
VIDEO_DURATION_SEC = int(os.getenv('VIDEO_DURATION_SEC', '5'))
VIDEO_POLL_INTERVAL = float(os.getenv('VIDEO_POLL_INTERVAL', '10'))
VIDEO_TIMEOUT = float(os.getenv('VIDEO_TIMEOUT', '900'))
VIDEO_WATERMARK = os.getenv('VIDEO_WATERMARK', 'true').lower() == 'true'
OCR_TIMEOUT = float(os.getenv('OCR_TIMEOUT', '30'))
OCR_BACKEND = os.getenv('OCR_BACKEND', 'tesseract')
OCR_ENDPOINT = os.getenv('OCR_ENDPOINT', '')
OCR_TOKEN = os.getenv('OCR_TOKEN', '')
OCR_LANG = os.getenv('OCR_LANG', 'chi_sim+eng')
OCR_THRESHOLD = float(os.getenv('OCR_THRESHOLD', '0.85'))
UPLOAD_MAX_BYTES = int(os.getenv('UPLOAD_MAX_BYTES', str(10 * 1024 * 1024)))
OUTBOX_MAX_ATTEMPTS = int(os.getenv('OUTBOX_MAX_ATTEMPTS', '5'))
BROWSER_ENABLED = os.getenv('BROWSER_ENABLED', 'false').lower() == 'true'
BROWSER_ADAPTER_URL = os.getenv('BROWSER_ADAPTER_URL', '')
BROWSER_ADAPTER_TOKEN = os.getenv('BROWSER_ADAPTER_TOKEN', '')
BROWSER_LOGIN_PLATFORMS = [x.strip() for x in os.getenv('BROWSER_LOGIN_PLATFORMS', '').split(',') if x.strip()]
OFFICIAL_PUBLISH_ENABLED = os.getenv('OFFICIAL_PUBLISH_ENABLED', 'false').lower() == 'true'
AUTO_REGISTER_MODE = os.getenv('AUTO_REGISTER_MODE', 'off')
REGISTER_INVITE_CODE = os.getenv('REGISTER_INVITE_CODE', '')
LOGIN_WINDOW_SECONDS = int(os.getenv('LOGIN_WINDOW_SECONDS', '60'))
LOGIN_IP_LIMIT = int(os.getenv('LOGIN_IP_LIMIT', '30'))
LOGIN_ACCOUNT_LIMIT = int(os.getenv('LOGIN_ACCOUNT_LIMIT', '10'))
LOGIN_CHALLENGE_AFTER = int(os.getenv('LOGIN_CHALLENGE_AFTER', '3'))
LOGIN_MAX_INFLIGHT = int(os.getenv('LOGIN_MAX_INFLIGHT', '4'))
SESSION_ENCRYPTION_KEY = os.getenv('SESSION_ENCRYPTION_KEY', '')
ADAPTER_ALLOWED_HOSTS = [x.strip().lower() for x in os.getenv('ADAPTER_ALLOWED_HOSTS', '').split(',') if x.strip()]
MEDIA_ALLOWED_HOSTS = [x.strip().lower() for x in os.getenv('MEDIA_ALLOWED_HOSTS', '').split(',') if x.strip()]
PHASE2_WORKER_ENABLED = os.getenv('PHASE2_WORKER_ENABLED', 'false').lower() == 'true'
AUTOMATION_ENABLED = os.getenv('AUTOMATION_ENABLED', 'false').lower() == 'true'
AUTOMATION_INTERVAL_SECONDS = int(os.getenv('AUTOMATION_INTERVAL_SECONDS', '60'))
AUTOMATION_DAILY_LIMIT = int(os.getenv('AUTOMATION_DAILY_LIMIT', '50'))


def _platform_llm_providers():
    """平台模型网关是 OpenAI 兼容接口，直接映射成 LLM_PROVIDERS 即可复用现有故障转移。"""
    if not PIOS_MODEL_KEY:
        return []
    providers = [{'name': 'pios-gateway', 'base_url': PIOS_GATEWAY_URL,
                  'model': LLM_MODEL, 'key': PIOS_MODEL_KEY}]
    if LLM_FALLBACK_MODEL and LLM_FALLBACK_MODEL != LLM_MODEL:
        providers.append({'name': 'pios-gateway-fallback', 'base_url': PIOS_GATEWAY_URL,
                          'model': LLM_FALLBACK_MODEL, 'key': PIOS_MODEL_KEY})
    return providers


# 显式 LLM_PROVIDERS 优先；否则用平台网关（PIOS_MODEL_KEY）自动接入。
if not LLM_PROVIDERS:
    LLM_PROVIDERS = _platform_llm_providers()


def path_setting(name, default):
    path = Path(os.getenv(name, default)).expanduser()
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


BROWSER_STATE_DIR = path_setting('BROWSER_STATE_DIR', 'var/browser_state')
VIDEO_OUTPUT_DIR = path_setting('VIDEO_OUTPUT_DIR', 'var/video_out')
UPLOAD_DIR = path_setting('UPLOAD_DIR', 'var/uploads')


def validate():
    if not DATABASE_URL:
        raise RuntimeError('必须配置 DATABASE_URL（PostgreSQL）')
    if not DATABASE_URL.startswith('postgresql') and APP_ENV != 'test':
        raise RuntimeError('业务环境必须使用 PostgreSQL；SQLite 仅用于隔离测试')
    if len(JWT_SECRET) < 32:
        raise RuntimeError('JWT_SECRET 至少 32 字符，请使用随机值')
    if DEMO_MODE and APP_ENV == 'production':
        raise RuntimeError('生产环境禁止 DEMO_MODE')
    if AUTO_REGISTER_MODE not in ('off', 'invite'):
        raise RuntimeError('自动注册仅允许off或invite；不能开放无邀请注册')
    if AUTO_REGISTER_MODE == 'invite' and len(REGISTER_INVITE_CODE) < 16:
        raise RuntimeError('邀请码模式必须配置至少16字符随机邀请码')
