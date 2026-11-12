"""可选内置受信浏览器适配器：打开平台官方登录页，取官方二维码并保持受管会话。

设计边界：
- 只加载平台官方登录页，二维码由平台页面签发；不绘制、不伪造二维码。
- 不导出 Cookie，不提供密码代填、验证码绕过、反检测或隐身能力。
- 会话只以浏览器上下文句柄形式留在本进程内；API 只持有不透明 handle。
- 仅监听 127.0.0.1，所有 /v2 接口要求 BROWSER_ADAPTER_TOKEN。
"""
import asyncio
import base64
import hmac
import io
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException
from PIL import Image, ImageStat, UnidentifiedImageError
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from . import config

LOG = logging.getLogger('login_adapter')

# 只接入已核验过“打开官方页面即出现扫码登录”的平台。不要把目录里的全平台
# 自动当成已接通；新增平台必须同时补登录判定规则并做真实扫码验收。
PLATFORM_CONFIG: dict[str, dict[str, Any]] = {
    'douyin': {
        # 使用创作者中心入口而不是营销首页：该入口稳定渲染扫码登录卡片。
        # 未登录时页面地址也停在 /creator-micro/，不能用 URL 判定登录成功；
        # 只认平台登录后签发的会话 Cookie，避免二维码刚出就被误判为已登录。
        'url': 'https://creator.douyin.com/creator-micro/home',
        'cookies': ('sessionid', 'sessionid_ss', 'sid_guard'),
        # 官方页面把二维码放在 data:image PNG 里；等待元素出现比反复执行
        # 页面脚本更稳，避免首屏长时间主线程繁忙时把等待窗口耗尽。
        'qr_selector': '#douyin_login_comp_scan_code_qrcode img[src^="data:image"]',
        # 二维码若改用 canvas / 背景图渲染，直接截取官方容器兜底。
        'qr_containers': ('#douyin_login_comp_scan_code_qrcode', '#animate_qrcode_container'),
    },
}

QR_SCAN_JS = r"""
() => {
  const square = (w, h) => w >= 90 && h >= 90 && Math.abs(w - h) <= Math.max(18, w * 0.16);
  const out = [];
  const images = Array.from(document.images);
  for (let i = 0; i < images.length; i += 1) {
    const img = images[i];
    const rect = img.getBoundingClientRect();
    if (!square(rect.width, rect.height) || !square(img.naturalWidth, img.naturalHeight)) continue;
    const src = img.currentSrc || img.src || '';
    const lower = src.toLowerCase();
    const hint = /qr|qrcode|scan/.test(lower) ||
      /qr|qrcode|scan/.test(String(img.className || '').toLowerCase()) ||
      /qr|qrcode|scan/.test(String(img.alt || '').toLowerCase());
    let score = 0;
    if (src.startsWith('data:image/')) score += 100;
    if (hint) score += 40;
    if (rect.width >= 140) score += 10;
    out.push({index: i, src: src.startsWith('data:image/') ? src : src.slice(0, 200), score,
              w: Math.round(rect.width), h: Math.round(rect.height)});
  }
  return out.sort((a, b) => b.score - a.score);
}
"""


class AdapterError(Exception):
    """可安全返回给调用方的业务错误，不含页面内容、Cookie 或堆栈。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _png(raw: bytes) -> bytes | None:
    """校验平台页面给出的图片，并统一转成白底 PNG。"""
    if not raw or len(raw) > config.UPLOAD_MAX_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width < 90 or image.height < 90 or image.width * image.height > 4_000_000:
                return None
            image.load()
            if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                rgba = image.convert('RGBA')
                canvas = Image.new('RGB', rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.getchannel('A'))
                image = canvas
            else:
                image = image.convert('RGB')
            output = io.BytesIO()
            image.save(output, 'PNG')
            return output.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def _qr_like(png: bytes) -> bool:
    """排除空白占位图、纯色 logo 和装饰图；二维码必须有明显的黑白分布。"""
    try:
        with Image.open(io.BytesIO(png)) as image:
            gray = image.convert('L')
            histogram = gray.histogram()
            total = sum(histogram) or 1
            dark = sum(histogram[:96]) / total
            nonwhite = sum(histogram[:245]) / total
            deviation = ImageStat.Stat(gray).stddev[0]
            return 0.035 <= dark <= 0.93 and nonwhite >= 0.08 and deviation >= 10
    except (ValueError, OSError, UnidentifiedImageError):
        return False


async def _qr_from_page(page: Page) -> bytes | None:
    """从任意 frame 的真实页面图片里取二维码；优先平台直接给出的 data PNG。"""
    for frame in page.frames:
        try:
            candidates = await asyncio.wait_for(frame.evaluate(QR_SCAN_JS), timeout=2.0)
        except Exception:
            continue
        if candidates:
            LOG.info('QR candidates frame=%s %s', frame.url[:80],
                     [{k: v for k, v in item.items() if k != 'src'} for item in candidates[:5] if isinstance(item, dict)])
        for item in candidates:
            if not isinstance(item, dict):
                continue
            src = str(item.get('src') or '')
            index = item.get('index')
            if src.startswith('data:image/png;base64,'):
                try:
                    raw = base64.b64decode(src.split(',', 1)[1], validate=True)
                except (ValueError, IndexError):
                    continue
                cleaned = _png(raw)
                if cleaned and _qr_like(cleaned):
                    return cleaned
            if isinstance(index, int):
                try:
                    raw = await frame.locator('img').nth(index).screenshot(type='png', timeout=5000)
                except Exception:
                    continue
                cleaned = _png(raw)
                if cleaned and _qr_like(cleaned):
                    return cleaned
    return None


async def _qr_from_containers(page: Page, selectors: tuple[str, ...]) -> bytes | None:
    """二维码不是 <img> 时，直接截取平台官方二维码容器。"""
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                if await locator.count() == 0:
                    continue
                raw = await locator.screenshot(type='png', timeout=5000)
            except Exception:
                continue
            cleaned = _png(raw)
            if cleaned and _qr_like(cleaned):
                LOG.info('从二维码容器取得图片 selector=%s bytes=%s', selector, len(cleaned))
                return cleaned
    return None


class _Session:
    def __init__(self, account_id: int, platform: str, attempt_id: str,
                 context: BrowserContext, page: Page, qr: bytes, expires_at: datetime):
        self.account_id = account_id
        self.platform = platform
        self.attempt_id = attempt_id
        self.context = context
        self.page = page
        self.qr = qr
        self.expires_at = expires_at
        self.handle = ''
        self.nickname = ''
        self.created_at = _now()

    async def close(self):
        try:
            await self.context.close()
        except Exception:
            LOG.warning('关闭账号 %s 的浏览器上下文失败', self.account_id, exc_info=True)


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._sessions: dict[int, _Session] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._reaper: asyncio.Task | None = None

    def _lock(self, account_id: int) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            executable_path=config.CHROMIUM_PATH,
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        self._reaper = asyncio.create_task(self._reap())
        LOG.info('登录适配器浏览器已启动：%s', config.CHROMIUM_PATH)

    async def stop(self):
        if self._reaper:
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                LOG.warning('关闭浏览器失败', exc_info=True)
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                LOG.warning('停止 Playwright 失败', exc_info=True)

    async def _reap(self):
        while True:
            await asyncio.sleep(30)
            now = _now()
            for account_id, session in list(self._sessions.items()):
                if session.expires_at <= now and not session.handle:
                    async with self._lock(account_id):
                        current = self._sessions.get(account_id)
                        if current is session and not session.handle:
                            self._sessions.pop(account_id, None)
                            await session.close()

    async def _evict_if_needed(self):
        if len(self._sessions) < max(1, config.LOGIN_MAX_BROWSER_SESSIONS):
            return
        # 优先清理已过期的未登录会话；仍有空位时拒绝新开，避免容器内存被打满。
        for account_id, session in list(self._sessions.items()):
            if session.expires_at <= _now() and not session.handle:
                async with self._lock(account_id):
                    if self._sessions.get(account_id) is session:
                        self._sessions.pop(account_id, None)
                        await session.close()
        if len(self._sessions) >= max(1, config.LOGIN_MAX_BROWSER_SESSIONS):
            raise AdapterError('同时登录的账号过多，请先关闭其他扫码窗口或退出旧账号')

    async def login(self, account_id: int, platform: str, mode: str) -> dict:
        if mode != 'qr':
            raise AdapterError('本扫码服务只支持二维码登录，不接收账号密码')
        settings = PLATFORM_CONFIG.get(platform)
        if not settings:
            raise AdapterError('该平台尚未接入扫码登录')
        async with self._lock(account_id):
            previous = self._sessions.pop(account_id, None)
            if previous:
                await previous.close()
            await self._evict_if_needed()
            context = await self._browser.new_context(
                viewport={'width': 1280, 'height': 900},
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
            )
            page = await context.new_page()
            page.set_default_timeout(5000)
            try:
                LOG.info('打开平台登录页 account=%s platform=%s', account_id, platform)
                await page.goto(settings['url'], wait_until='domcontentloaded', timeout=25000)
                try:
                    await page.evaluate('window.scrollTo(0, 0)')
                except Exception:
                    pass
                LOG.info('登录页已打开 account=%s url=%s', account_id, page.url)
                raw = None
                qr_selector = settings.get('qr_selector')
                if qr_selector:
                    # 登录卡片和二维码由页面异步渲染，首屏主线程可能繁忙十几秒；
                    # 用 Playwright 自身的等待器，避免业务轮询把等待时间耗在
                    # 一次卡住的 evaluate 上。
                    try:
                        await page.wait_for_selector(qr_selector, state='attached', timeout=30000)
                        LOG.info('二维码元素已出现 account=%s', account_id)
                    except Exception:
                        LOG.info('等待二维码元素超时 account=%s', account_id)
                    raw = await _qr_from_page(page)
                if not raw:
                    raw = await _qr_from_containers(page, settings.get('qr_containers', ()))
                if not raw:
                    # 元素已挂载但图片尚未解码完成时，再给一小段兜底时间。
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        raw = await _qr_from_page(page)
                        if raw:
                            break
                        raw = await _qr_from_containers(page, settings.get('qr_containers', ()))
                        if raw:
                            break
                        await page.wait_for_timeout(500)
                if not raw:
                    raise AdapterError('平台登录页暂时未生成二维码，请稍后重试；若页面要求验证码或短信验证，请先在官方页面人工处理')
                LOG.info('已取得平台二维码 account=%s bytes=%s', account_id, len(raw))
                attempt_id = uuid.uuid4().hex
                expires_at = _now() + timedelta(seconds=max(60, config.LOGIN_QR_TTL_SECONDS))
                session = _Session(account_id, platform, attempt_id, context, page, raw, expires_at)
                self._sessions[account_id] = session
                return {
                    'ok': True,
                    'status': 'awaiting_scan',
                    'attempt_id': attempt_id,
                    'qr_png_base64': base64.b64encode(raw).decode(),
                    'expires_at': _iso(expires_at),
                }
            except Exception as exc:
                LOG.warning('获取二维码失败 account=%s: %s', account_id, type(exc).__name__)
                try:
                    await page.screenshot(path='var/login-adapter-last.png', full_page=False, timeout=5000)
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass
                raise

    async def _logged_in(self, session: _Session) -> bool:
        if session.page.is_closed():
            return False
        settings = PLATFORM_CONFIG[session.platform]
        # URL 仅作为可选辅助条件。抖音未登录时也停在 /creator-micro/，
        # 单看 URL 会在 3 秒轮询后把登录卡片误判成已登录；会话 Cookie 才是凭据。
        url = session.page.url.lower()
        if any(part.lower() in url for part in settings.get('url_contains', ())):
            return True
        try:
            cookies = await session.context.cookies()
        except Exception:
            return False
        names = {str(c.get('name', '')).lower() for c in cookies if len(str(c.get('value', ''))) >= 8}
        return any(name.lower() in names for name in settings.get('cookies', ()))

    async def _nickname(self, session: _Session) -> str:
        try:
            value = await session.page.evaluate(
                """() => {
                    const nodes = document.querySelectorAll('[class*="nickname"], [class*="user-name"], [class*="userName"]');
                    for (const node of nodes) {
                        const text = (node.textContent || '').trim();
                        if (text && text.length <= 60) return text;
                    }
                    return '';
                }"""
            )
            return str(value or '')[:100]
        except Exception:
            return ''

    async def refresh(self, account_id: int, attempt_id: str) -> dict:
        async with self._lock(account_id):
            session = self._sessions.get(account_id)
            if not session or (attempt_id and session.attempt_id != attempt_id):
                return {'ok': True, 'status': 'expired'}
            if session.handle:
                if session.page.is_closed():
                    self._sessions.pop(account_id, None)
                    await session.close()
                    return {'ok': True, 'status': 'expired'}
                return {
                    'ok': True,
                    'status': 'connected',
                    'session': {'handle': session.handle},
                    'nickname': session.nickname,
                    'expires_at': _iso(_now() + timedelta(hours=max(1, config.LOGIN_SESSION_TTL_HOURS))),
                }
            if session.expires_at <= _now():
                self._sessions.pop(account_id, None)
                await session.close()
                return {'ok': True, 'status': 'expired'}
            if await self._logged_in(session):
                session.handle = uuid.uuid4().hex
                session.nickname = await self._nickname(session)
                return {
                    'ok': True,
                    'status': 'connected',
                    'session': {'handle': session.handle},
                    'nickname': session.nickname,
                    'expires_at': _iso(_now() + timedelta(hours=max(1, config.LOGIN_SESSION_TTL_HOURS))),
                }
            data = {
                'ok': True,
                'status': 'awaiting_scan',
                'attempt_id': session.attempt_id,
                'expires_at': _iso(session.expires_at),
            }
            fresh = await _qr_from_page(session.page)
            if fresh and fresh != session.qr:
                session.qr = fresh
                data['qr_png_base64'] = base64.b64encode(fresh).decode()
            return data

    async def logout(self, account_id: int, session_payload: Any) -> dict:
        async with self._lock(account_id):
            session = self._sessions.pop(account_id, None)
            if session:
                await session.close()
            return {'ok': True}


manager = BrowserManager()


def _authorized(authorization: str | None) -> bool:
    expected = config.BROWSER_ADAPTER_TOKEN
    if not expected or not authorization:
        return False
    return hmac.compare_digest(authorization, 'Bearer ' + expected)


def _check(authorization: str | None):
    if not _authorized(authorization):
        raise HTTPException(401, 'unauthorized')


@asynccontextmanager
async def lifespan(_: FastAPI):
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title='Toker Login Adapter', lifespan=lifespan)


@app.get('/health')
async def health():
    return {'ok': True, 'platforms': sorted(PLATFORM_CONFIG)}


@app.post('/v2/accounts/login')
async def login(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    _check(authorization)
    try:
        account_id = int(payload.get('account_id'))
        platform = str(payload.get('platform') or '')
        mode = str(payload.get('mode') or 'qr')
        return await manager.login(account_id, platform, mode)
    except AdapterError as exc:
        return {'ok': False, 'error': str(exc)}
    except (TypeError, ValueError):
        return {'ok': False, 'error': '登录请求参数无效'}
    except Exception:
        LOG.exception('accounts/login failed')
        return {'ok': False, 'error': '扫码服务暂时不可用，请稍后重试'}


@app.post('/v2/accounts/refresh')
async def refresh(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    _check(authorization)
    try:
        account_id = int(payload.get('account_id'))
        attempt_id = str(payload.get('attempt_id') or '')
        return await manager.refresh(account_id, attempt_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': '登录请求参数无效'}
    except Exception:
        LOG.exception('accounts/refresh failed')
        return {'ok': False, 'error': '扫码服务暂时不可用，请稍后重试'}


@app.post('/v2/accounts/logout')
async def logout(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    _check(authorization)
    try:
        account_id = int(payload.get('account_id'))
        return await manager.logout(account_id, payload.get('session'))
    except (TypeError, ValueError):
        return {'ok': False, 'error': '退出请求参数无效'}
    except Exception:
        LOG.exception('accounts/logout failed')
        return {'ok': False, 'error': '退出扫码会话失败，请稍后重试'}


if __name__ == '__main__':
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host='127.0.0.1', port=config.LOGIN_ADAPTER_PORT, workers=1)
