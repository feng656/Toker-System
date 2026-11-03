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
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '30'))
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
OFFICIAL_PUBLISH_ENABLED = os.getenv('OFFICIAL_PUBLISH_ENABLED', 'false').lower() == 'true'


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
