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
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

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
        'cookies': ('sessionid', 'sessionid_ss', 'sid_guard', 'sid_tt', 'uid_tt', 'uid_tt_ss'),
        # 官方页面把二维码放在 <img> 里（当前是 data:image PNG，也可能换成
        # blob/URL）；等待元素出现比反复执行页面脚本更稳，避免首屏主线程
        # 繁忙时把等待窗口耗尽。
        'qr_selector': '#douyin_login_comp_scan_code_qrcode img',
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
    """排除空白占位图、纯色 logo、宣传轮播和装饰图；二维码应近似正方形且以黑白为主。"""
    try:
        with Image.open(io.BytesIO(png)) as image:
            width, height = image.size
            # 登录页左侧的推广轮播是 4:3 横幅，二维码容器/图片接近正方形。
            if height <= 0 or not 0.9 <= width / height <= 1.1:
                return False
            gray = image.convert('L')
            histogram = gray.histogram()
            total = sum(histogram) or 1
            dark = sum(histogram[:96]) / total
            nonwhite = sum(histogram[:245]) / total
            deviation = ImageStat.Stat(gray).stddev[0]
            if not (0.035 <= dark <= 0.93 and nonwhite >= 0.08 and deviation >= 10):
                return False
            # 二维码主体是黑白模块，彩色像素占比很低；宣传图/插画颜色丰富。
            sample = image.convert('RGB').resize((64, 64))
            pixels = list(sample.getdata())
            saturated = sum(1 for r, g, b in pixels if max(r, g, b) - min(r, g, b) > 48)
            return saturated / len(pixels) <= 0.18
    except (ValueError, OSError, UnidentifiedImageError):
        return False


async def _qr_from_selector(page: Page, selector: str) -> bytes | None:
    """只截取平台登录卡片里被明确标记为二维码的 <img>，避免误收旁边的宣传图。"""
    try:
        frames = page.frames
    except Exception:
        return None
    for frame in frames:
        try:
            locator = frame.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                src = await locator.get_attribute('src', timeout=2000) or ''
            except Exception:
                src = ''
            if src.startswith('data:image/png;base64,'):
                try:
                    raw = base64.b64decode(src.split(',', 1)[1], validate=True)
                except (ValueError, IndexError):
                    raw = b''
                cleaned = _png(raw)
                if cleaned and _qr_like(cleaned):
                    return cleaned
            try:
                raw = await locator.screenshot(type='png', timeout=5000)
            except Exception:
                continue
            cleaned = _png(raw)
            if cleaned and _qr_like(cleaned):
                return cleaned
        except Exception:
            continue
    return None


async def _qr_from_page(page: Page, selector: str = '') -> bytes | None:
    """取二维码：优先精确选择器；没有时才在评分足够高的页面图片里兜底。"""
    if selector:
        precise = await _qr_from_selector(page, selector)
        if precise:
            return precise
    try:
        frames = page.frames
    except Exception:
        return None
    for frame in frames:
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
            # 只接受带 qr/scan 提示或平台 data PNG 的高分候选，避免把
            # 登录页轮播、插画或头像当成二维码返回给前端。
            if int(item.get('score') or 0) < 140:
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
    try:
        frames = page.frames
    except Exception:
        return None
    for frame in frames:
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
                 context: BrowserContext, page: Page, qr: bytes | None, expires_at: datetime):
        self.account_id = account_id
        self.platform = platform
        self.attempt_id = attempt_id
        self.context = context
        self.page = page
        self.qr = qr
        self.expires_at = expires_at
        self.handle = ''
        self.nickname = ''
        self.cookie_names: list[str] = []
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
        self._poll_state: dict[int, dict[str, Any]] = {}
        self._reaper: asyncio.Task | None = None
        self._user_agent = ''

    def _lock(self, account_id: int) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            executable_path=config.CHROMIUM_PATH,
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
            ],
        )
        version = (self._browser.version or '').split('.', 1)[0]
        if version.isdigit():
            # 去掉 HeadlessChrome 标记：平台会把无头 UA 当作高风险环境，
            # 扫码能通过、手机确认阶段却拒绝建立登录态。
            self._user_agent = (
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                f'(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36')
        self._reaper = asyncio.create_task(self._reap())
        LOG.info('登录适配器浏览器已启动：%s version=%s ua_headless=%s',
                 config.CHROMIUM_PATH, self._browser.version,
                 'HeadlessChrome' in self._user_agent)

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
                            self._poll_state.pop(account_id, None)
                            await session.close()

    def _watch_login_page(self, page: Page, account_id: int):
        """记录扫码链路的关键节点，不记录 Cookie 值、二维码 token 或跳转票据。"""
        page.on('framenavigated', lambda frame: LOG.info(
            '页面跳转 account=%s main=%s url=%s', account_id, frame == page.main_frame,
            frame.url.split('?', 1)[0][:160]))
        page.on('console', lambda msg: LOG.info(
            '页面控制台 account=%s type=%s text=%s', account_id, msg.type, msg.text[:300])
            if msg.type in ('error', 'warning') else None)
        page.on('pageerror', lambda exc: LOG.info(
            '页面异常 account=%s error=%s', account_id, str(exc)[:300]))
        page.on('response', lambda response: asyncio.create_task(
            self._log_login_response(account_id, response)))

    @staticmethod
    def _safe_payload(payload) -> dict:
        """脱敏后输出响应字段，定位平台返回的失败原因，同时避免落票据。"""
        if not isinstance(payload, dict):
            return {'_type': type(payload).__name__}
        data = payload.get('data')
        safe = {}
        if isinstance(data, dict):
            for key, value in data.items():
                low = str(key).lower()
                if any(part in low for part in ('token', 'ticket', 'qrcode', 'url', 'cookie', 'secret', 'sign')):
                    safe[str(key)] = f'<{type(value).__name__}:{len(str(value))}>'
                else:
                    safe[str(key)] = str(value)[:120]
        elif data is not None:
            safe['data'] = str(data)[:120]
        return {'status_code': payload.get('status_code'),
                'message': str(payload.get('message') or payload.get('msg') or '')[:160],
                'data': safe}

    async def _capture_login_error(self, account_id: int):
        """错误响应出现的瞬间抓取弹窗文案，页面随后可能被看门狗重载。"""
        session = self._sessions.get(account_id)
        if not session:
            return
        try:
            text = await session.page.evaluate(
                """() => {
                    const rows = [...document.querySelectorAll('div,span,p')]
                      .map(n => (n.innerText || '').trim())
                      .filter(t => t && t.length < 300 && /登录|二维码|失败|异常|重试|扫码/.test(t));
                    return [...new Set(rows)].slice(-8).join(' | ');
                }""")
            LOG.info('登录弹窗文案 account=%s text=%s', account_id, str(text)[:500])
        except Exception:
            LOG.info('登录弹窗文案读取失败 account=%s', account_id)

    async def _log_login_response(self, account_id: int, response):
        url = response.url.lower()
        api = 'check_qrconnect' if 'check_qrconnect' in url else ('get_qrcode' if 'get_qrcode' in url else '')
        if not api:
            # 手机确认后 passport 会跳转并下发 Cookie；只记路径与跳转主机，
            # 不落查询串（里面可能带一次性票据）。
            if '/passport/' in url:
                parts = urlsplit(response.url)
                location = response.headers.get('location') or ''
                target = urlsplit(location) if location else None
                LOG.info('passport 请求 account=%s http=%s path=%s location_host=%s location_path=%s',
                         account_id, response.status, parts.path[:120],
                         (target.hostname or '') if target else '',
                         (target.path[:120] or '') if target else '')
            return
        if api == 'check_qrconnect':
            self._poll_state[account_id] = {'at': _now(), 'http': response.status, 'status': None}
        try:
            payload = json.loads(await response.text())
        except Exception:
            LOG.info('扫码请求响应 account=%s api=%s http=%s body=unreadable',
                     account_id, api, response.status)
            return
        data = payload.get('data') if isinstance(payload, dict) else None
        status = data.get('status') if isinstance(data, dict) else None
        redirect = str(data.get('redirect_url') or '') if isinstance(data, dict) else ''
        host = urlsplit(redirect).hostname or ''
        msg = str(payload.get('message') or payload.get('msg') or '')[:80] if isinstance(payload, dict) else ''
        if api == 'check_qrconnect':
            self._poll_state[account_id] = {'at': _now(), 'http': response.status, 'status': status}
        LOG.info('扫码请求响应 account=%s api=%s http=%s code=%s status=%s redirect_host=%s msg=%s',
                 account_id, api, response.status,
                 payload.get('status_code') if isinstance(payload, dict) else None,
                 status, host, msg)
        if api == 'get_qrcode' or msg != 'success' or status not in ('new', 'scanned'):
            LOG.info('扫码响应字段 account=%s api=%s fields=%s',
                     account_id, api, self._safe_payload(payload))
        if api == 'check_qrconnect' and msg == 'error':
            asyncio.create_task(self._capture_login_error(account_id))

    async def _new_context(self) -> BrowserContext:
        context = await self._browser.new_context(
            viewport={'width': 1440, 'height': 900},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            user_agent=self._user_agent or None,
            extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'},
        )
        # 去除自动化标记，避免平台在手机确认后按风险环境拒绝下发登录态。
        await context.add_init_script(
            """Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
               Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
               window.chrome = window.chrome || {runtime: {}, app: {isInstalled: false}};""")
        return context

    @staticmethod
    def _playwright_cookies(cookies) -> list[dict]:
        result = []
        for item in cookies or []:
            if not isinstance(item, dict):
                continue
            name, domain = str(item.get('name') or ''), str(item.get('domain') or '')
            if not name or not domain:
                continue
            entry = {'name': name, 'value': str(item.get('value') or ''), 'domain': domain,
                     'path': str(item.get('path') or '/'),
                     'httpOnly': bool(item.get('httpOnly')), 'secure': bool(item.get('secure', True))}
            expires = item.get('expires', item.get('expirationDate'))
            if item.get('session') or expires is None or float(expires) <= 0:
                pass
            else:
                entry['expires'] = float(expires)
            same_site = {'no_restriction': 'None', 'none': 'None', 'lax': 'Lax',
                         'strict': 'Strict'}.get(str(item.get('sameSite') or '').lower())
            if same_site:
                entry['sameSite'] = same_site
            result.append(entry)
        return result

    @staticmethod
    def _cookie_expiry(cookies: list[dict], platform: str) -> datetime:
        now = _now()
        names = set(PLATFORM_CONFIG[platform].get('cookies', ()))
        values = [datetime.fromtimestamp(float(c['expires']), tz=timezone.utc)
                  for c in cookies
                  if c.get('name') in names and isinstance(c.get('expires'), (int, float))
                  and c['expires'] > now.timestamp()]
        cap = now + timedelta(hours=max(1, config.LOGIN_SESSION_TTL_HOURS))
        return min(min(values), cap) if values else cap

    async def _import_locked(self, account_id: int, platform: str, cookies) -> dict:
        settings = PLATFORM_CONFIG.get(platform)
        if not settings:
            raise AdapterError('该平台尚未接入扫码登录')
        normalized = self._playwright_cookies(cookies)
        if not normalized:
            return {'ok': True, 'status': 'invalid', 'error': 'Cookie 为空或格式无效'}
        previous = self._sessions.pop(account_id, None)
        self._poll_state.pop(account_id, None)
        if previous:
            await previous.close()
        await self._evict_if_needed()
        context = await self._new_context()
        try:
            await context.add_cookies(normalized)
            page = await context.new_page()
            page.set_default_timeout(5000)
            self._watch_login_page(page, account_id)
            LOG.info('写入导入 Cookie 并打开平台 account=%s platform=%s count=%s',
                     account_id, platform, len(normalized))
            await page.goto(settings['url'], wait_until='domcontentloaded', timeout=25000)
            try:
                await page.wait_for_timeout(2000)
            except Exception:
                pass
            expires_at = self._cookie_expiry(normalized, platform)
            session = _Session(account_id, platform, '', context, page, None, expires_at)
            if not await self._logged_in(session):
                LOG.info('导入 Cookie 未通过平台登录检测 account=%s url=%s',
                         account_id, page.url.split('?', 1)[0][:160])
                await context.close()
                return {'ok': True, 'status': 'invalid', 'error': 'Cookie 已失效或不属于该平台账号'}
            session.handle = uuid.uuid4().hex
            session.nickname = await self._nickname(session)
            self._sessions[account_id] = session
            LOG.info('导入 Cookie 登录成功 account=%s nickname=%s expires=%s',
                     account_id, session.nickname, _iso(expires_at))
            return {'ok': True, 'status': 'connected', 'session': {'handle': session.handle},
                    'nickname': session.nickname, 'expires_at': _iso(expires_at)}
        except Exception:
            try:
                await context.close()
            except Exception:
                pass
            raise

    async def import_session(self, account_id: int, platform: str, cookies) -> dict:
        async with self._lock(account_id):
            return await self._import_locked(account_id, platform, cookies)

    async def _evict_if_needed(self):
        if len(self._sessions) < max(1, config.LOGIN_MAX_BROWSER_SESSIONS):
            return
        # 优先清理已过期的未登录会话；仍有空位时拒绝新开，避免容器内存被打满。
        for account_id, session in list(self._sessions.items()):
            if session.expires_at <= _now() and not session.handle:
                async with self._lock(account_id):
                    if self._sessions.get(account_id) is session:
                        self._sessions.pop(account_id, None)
                        self._poll_state.pop(account_id, None)
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
            self._poll_state.pop(account_id, None)
            if previous:
                await previous.close()
            await self._evict_if_needed()
            context = await self._new_context()
            page = await context.new_page()
            page.set_default_timeout(5000)
            self._watch_login_page(page, account_id)
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
                    raw = await _qr_from_page(page, qr_selector)
                if not raw:
                    raw = await _qr_from_containers(page, settings.get('qr_containers', ()))
                if not raw:
                    # 元素已挂载但图片尚未解码完成时，再给一小段兜底时间。
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        raw = await _qr_from_page(page, qr_selector or '')
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
                self._poll_state[account_id] = {'at': _now(), 'http': None, 'status': None}
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
        current = sorted(names)
        if current != getattr(session, 'cookie_names', None):
            # 只记录名称与数量，便于判断确认后 passport 是否真的下发了会话 Cookie。
            session.cookie_names = current
            LOG.info('账号 %s Cookie 名称变化 count=%s names=%s',
                     getattr(session, 'account_id', '-'), len(current), current[:30])
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

    async def refresh(self, account_id: int, attempt_id: str,
                      session_payload: Any = None, platform: str = '') -> dict:
        async with self._lock(account_id):
            session = self._sessions.get(account_id)
            if not session:
                # 适配器重启后，导入的 Cookie 会话靠数据库里的密文恢复上下文。
                cookies = session_payload.get('cookies') if isinstance(session_payload, dict) else None
                if cookies and platform:
                    restored = await self._import_locked(account_id, platform, cookies)
                    if restored.get('status') == 'connected':
                        return restored
                return {'ok': True, 'status': 'expired'}
            if attempt_id and session.attempt_id and session.attempt_id != attempt_id:
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
                    'expires_at': _iso(min(session.expires_at, _now() + timedelta(
                        hours=max(1, config.LOGIN_SESSION_TTL_HOURS)))),
                }
            # 先查平台登录态，再处理本地二维码有效期。手机确认可能发生在旧码
            # 过期之后；如果先按时间清掉会话，就会把刚建立的平台登录一起丢掉。
            if await self._logged_in(session):
                session.handle = uuid.uuid4().hex
                session.nickname = await self._nickname(session)
                LOG.info('账号 %s 已完成平台登录 url=%s nickname=%s',
                         account_id, session.page.url.split('?', 1)[0][:160], session.nickname)
                return {
                    'ok': True,
                    'status': 'connected',
                    'session': {'handle': session.handle},
                    'nickname': session.nickname,
                    'expires_at': _iso(_now() + timedelta(hours=max(1, config.LOGIN_SESSION_TTL_HOURS))),
                }
            settings = PLATFORM_CONFIG[session.platform]
            selector = settings.get('qr_selector') or ''
            now = _now()
            # 平台页面自己约每 60 秒刷新一次二维码并持续轮询 check_qrconnect。
            # 这里只跟随页面换码，不主动点“刷新”遮盖按钮：提前换码会让
            # 刚扫完、正在手机上确认的旧 token 失效，反而丢掉登录。
            fresh = await _qr_from_page(session.page, selector)
            changed = bool(fresh and fresh != session.qr)
            if changed:
                session.qr = fresh
                session.expires_at = now + timedelta(seconds=max(15, config.LOGIN_QR_TTL_SECONDS))
                LOG.info('平台二维码已更新并延长有效期 account=%s', account_id)
            # 页面轮询一旦因 5xx/网络错误停掉，手机确认后也没有人完成
            # passport 交接。超过 15 秒没有任何 check_qrconnect 请求就重载
            # 页面，在原上下文里恢复轮询（Cookie 不会被清掉）。
            poll = self._poll_state.get(account_id) or {}
            last_poll = poll.get('at')
            if (last_poll
                    and (now - session.created_at).total_seconds() > 20
                    and (now - last_poll).total_seconds() > 15):
                LOG.info('扫码轮询已停止 account=%s last_http=%s，重载登录页恢复',
                         account_id, poll.get('http'))
                try:
                    await session.page.reload(wait_until='domcontentloaded', timeout=20000)
                    await session.page.wait_for_selector(selector, state='attached', timeout=15000)
                    self._poll_state[account_id] = {'at': _now(), 'http': None, 'status': None}
                    if await self._logged_in(session):
                        session.handle = uuid.uuid4().hex
                        session.nickname = await self._nickname(session)
                        LOG.info('账号 %s 重载后检测到登录成功', account_id)
                        return {
                            'ok': True,
                            'status': 'connected',
                            'session': {'handle': session.handle},
                            'nickname': session.nickname,
                            'expires_at': _iso(now + timedelta(hours=max(1, config.LOGIN_SESSION_TTL_HOURS))),
                        }
                    fresh = await _qr_from_page(session.page, selector)
                    if fresh:
                        session.qr = fresh
                        session.expires_at = now + timedelta(seconds=max(15, config.LOGIN_QR_TTL_SECONDS))
                        changed = True
                        LOG.info('重载后取得新二维码 account=%s', account_id)
                except Exception:
                    LOG.warning('重载登录页失败 account=%s', account_id, exc_info=True)
            if session.expires_at <= now:
                self._sessions.pop(account_id, None)
                await session.close()
                return {'ok': True, 'status': 'expired'}
            data = {
                'ok': True,
                'status': 'awaiting_scan',
                'attempt_id': session.attempt_id,
                'expires_at': _iso(session.expires_at),
            }
            if changed:
                data['qr_png_base64'] = base64.b64encode(fresh).decode()
            return data

    async def logout(self, account_id: int, session_payload: Any) -> dict:
        async with self._lock(account_id):
            session = self._sessions.pop(account_id, None)
            self._poll_state.pop(account_id, None)
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
        return await manager.refresh(account_id, attempt_id, payload.get('session'),
                                      str(payload.get('platform') or ''))
    except (TypeError, ValueError):
        return {'ok': False, 'error': '登录请求参数无效'}
    except Exception:
        LOG.exception('accounts/refresh failed')
        return {'ok': False, 'error': '扫码服务暂时不可用，请稍后重试'}


@app.post('/v2/accounts/import')
async def import_session(payload: dict = Body(...), authorization: str | None = Header(default=None)):
    _check(authorization)
    try:
        account_id = int(payload.get('account_id'))
        platform = str(payload.get('platform') or '')
        return await manager.import_session(account_id, platform, payload.get('cookies') or [])
    except AdapterError as exc:
        return {'ok': False, 'error': str(exc)}
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'Cookie 导入参数无效'}
    except Exception:
        LOG.exception('accounts/import failed')
        return {'ok': False, 'error': 'Cookie 导入校验失败，请稍后重试'}


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
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    uvicorn.run(app, host='127.0.0.1', port=config.LOGIN_ADAPTER_PORT, workers=1)
