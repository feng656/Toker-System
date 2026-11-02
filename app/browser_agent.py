"""常驻浏览器代理：各平台登录态 + 自动填稿发布。

- 一个 chromium 实例，每个平台一个 Page，cookie/localStorage 持久化到盘
- 截图接口给前端嵌入展示（用户扫码登录用）
- publish_gzh_web()：公众号草稿箱自动填稿 + 提交（群发扫码由用户在嵌入画面里完成）
"""
import asyncio
import base64
import json
import os
from pathlib import Path

STORAGE_DIR = Path("/workspace/personal-313-53/tuoke/browser_state")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

PLATFORMS = {
    "gzh": {
        "home": "https://mp.weixin.qq.com",
        "login_check": "扫码登录",   # 页面含此文案=未登录
    },
    "douyin": {
        "home": "https://creator.douyin.com/creator-micro/content/upload",
        "login_check": "登录",
    },
    "shipinhao": {
        "home": "https://channels.weixin.qq.com/platform/post/create",
        "login_check": "登录",
    },
    "xhs": {
        "home": "https://creator.xiaohongshu.com/publish/publish",
        "login_check": "登录",
    },
}

_lock = asyncio.Lock()
_pw = None
_browser = None
_contexts = {}  # platform -> (context, page)


async def _ensure_browser():
    global _pw, _browser
    if _browser and _browser.is_connected():
        return
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )


async def _get_page(platform: str):
    """每个平台一个持久化 context（cookie/session 存盘）。"""
    if platform in _contexts:
        ctx, page = _contexts[platform]
        try:
            await page.title()  # 探活
            return page
        except Exception:
            _contexts.pop(platform, None)
    await _ensure_browser()
    state_file = STORAGE_DIR / f"{platform}.json"
    kwargs = {"viewport": {"width": 1920, "height": 1200}}
    if state_file.exists():
        kwargs["storage_state"] = str(state_file)
    ctx = await _browser.new_context(**kwargs)
    page = await ctx.new_page()
    _contexts[platform] = (ctx, page)
    return page


async def _qr_element(platform: str):
    """优先截取登录二维码元素本身，而不是整页。

    顺序：①页内 data:image 的方形小图（各平台二维码几乎都是内联 png）；
    ②各平台已知的二维码容器选择器；③兜底返回 None 走整页截图。"""
    page = await _get_page(platform)
    # ① 先找方形 data:image 小图——抖音/视频号/小红书/公众号的二维码都是这种形式
    try:
        qr = await page.evaluate("""() => {
            const cands = [];
            document.querySelectorAll('img,canvas').forEach(e => {
                const r = e.getBoundingClientRect();
                const src = e.src || '';
                // 方形、80-400px、视口内可见
                const sq = Math.abs(r.width - r.height) < r.width * 0.1;
                const inView = r.x > -50 && r.y > -50 && r.x < innerWidth && r.y < innerHeight;
                if (sq && inView && r.width >= 80 && r.width <= 400) {
                    const isData = src.startsWith('data:image');
                    cands.push({isData, w: r.width, x: r.x, y: r.y, src: isData ? src.slice(0, 200000) : ''});
                }
            });
            // 优先 data:image（内联二维码），其次取最靠近页面右侧登录卡区域的
            cands.sort((a, b) => (b.isData - a.isData) || (b.x - a.x));
            if (cands.length === 0) return null;
            const best = cands[0];
            // 回传坐标 + 原图 dataURL（二维码源图往往比显示尺寸大）
            return {x: best.x, y: best.y, w: best.w, src: best.src};
        }""")
        if qr:
            out = {"clip": {"x": qr["x"], "y": qr["y"], "width": qr["w"], "height": qr["w"]}}
            if qr.get("src"):
                out["data_url"] = qr["src"]  # 原始二维码图，分辨率比 CSS 显示高
            return out
    except Exception:
        pass
    # ② 各平台二维码容器选择器
    selectors = {
        "gzh": [".login__type__container", ".login__type__container__scan", ".login_box"],
        "douyin": [".semi-modal", "[class*=qrcode]", "[class*=QrCode]", "[class*=login-card]"],
        "shipinhao": ["[class*=qrcode]", "[class*=QrCode]", "[class*=login]"],
        "xhs": [".login-container", "[class*=qrcode]", "[class*=QrCode]", "[class*=login]"],
    }.get(platform, ["[class*=qrcode]", "[class*=QrCode]", "[class*=login]"])
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                try:
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box and box["width"] > 100 and box["height"] > 100:
                            return el
                except Exception:
                    continue
        except Exception:
            continue
    return None


async def open_platform(platform: str):
    """打开平台登录/后台页，返回截图(base64)。已登录时不重复跳转，避免搅乱登录态。"""
    async with _lock:
        page = await _get_page(platform)
        # 已登录：保持当前页面，别再 goto 首页，否则可能退出登录态
        if _is_logged_in(platform, page.url):
            await asyncio.sleep(1)
            return await screenshot(platform)
        # 未登录或空白页：导航到平台入口
        try:
            await page.goto(PLATFORMS[platform]["home"], wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(3)
        return await screenshot(platform)


def _is_logged_in(platform: str, url: str) -> bool:
    """登录后平台 URL 会带后台路径/token。先排除明确的登录页 URL，
    否则抖音/视频号/小红书的登录页（文案里含'内容管理/创作者'等词）会骗过文案判据。"""
    # 命中这些 = 一定是登录页，直接返回 False
    notlogin_urls = [
        "/login", "login.html", "login?", "redirectReason=401",
        "passport", "signin",
    ]
    if any(s in url for s in notlogin_urls):
        return False
    rules = {
        "gzh": ["token=", "cgi-bin/home", "cgi-bin/frame", "cgi-bin/settingpage"],
        # 抖音：creator-micro/content/upload 是发布页，登录页 URL 也一样 → URL 判据不可靠，
        # 这里只留真正登录态 URL 特征（带具体子页/参数），其余靠 screenshot 的文案兜底
        "douyin": ["creator-micro/home", "creator-micro/content/manage", "creator-micro/content/post"],

        # 视频号：login.html 也是同域名，必须看 /platform/ 路径
        "shipinhao": ["channels.weixin.qq.com/platform/", "channels.weixin.qq.com/post"],
        # 小红书：/publish/publish 既是登录页目标也是发布页，不能作判据；
        # 登录后 URL 通常带 /creator/ 或 top_level_page=xxx，login 页 URL 含 /login
        "xhs": ["creator.xiaohongshu.com/creator/", "creator.xiaohongshu.com/home", "creator.xiaohongshu.com/statistics"],
    }.get(platform, [])
    return any(r in url for r in rules)


async def screenshot(platform: str) -> dict:
    """当前页面截图 + 登录状态判断。未登录时把二维码区域截下来再放大渲染到白底大画布。"""
    page = await _get_page(platform)
    logged = _is_logged_in(platform, page.url)
    # URL 判据说"已登录"时，再用页面文案反向确认（抖音/小红书登录页 URL 会骗过 URL 判据）
    if logged:
        try:
            txt = await page.inner_text("body", timeout=3000)
            if any(s in txt[:3000] for s in ["扫码登录", "验证码登录", "密码登录", "短信登录", "手机号登录", "登录即代表"]):
                logged = False
        except Exception:
            pass
    if not logged:
        try:
            txt = await page.inner_text("body", timeout=3000)
            notlogin = ["扫码登录", "登录后", "请登录", "使用账号登录", "微信扫一扫", "选择公众平台账号",
                        "登录视频号助手", "短信登录", "验证码登录", "密码登录", "手机号登录", "登录即代表",
                        "登录即同意", "如何扫码", "打开「抖音APP」"]
            logged_in_signs = {
                "gzh": ["草稿箱", "新的创作", "内容与互动", "发表文章"],
                # 抖音登录页介绍话术也有"创作者"，改用更唯一的已登录特征
                "douyin": ["发布视频", "作品管理", "我的主页", "发布内容"],
                # 视频号登录页有"内容管理"介绍话术，改用登录后才出现的功能名
                "shipinhao": ["发表动态", "视频号助手", "我的视频号", "数据中心"],
                "xhs": ["发布笔记", "笔记管理", "我的笔记", "数据概览"],
            }.get(platform, ["内容管理", "数据中心"])
            has_notlogin = any(s in txt[:4000] for s in notlogin)
            has_loggedin = any(s in txt[:4000] for s in logged_in_signs)
            logged = has_loggedin and not has_notlogin
        except Exception:
            pass
    b64 = ""
    try:
        target = None if logged else await _qr_element(platform)
        if isinstance(target, dict) and target.get("data_url"):
            # 直接用二维码原始 data:image，清晰度最高
            import base64 as _b64
            try:
                raw = _b64.b64decode(target["data_url"].split(",", 1)[1])
                buf = _upscale_qr(raw)
            except Exception:
                buf = await page.screenshot(timeout=10000)
        elif isinstance(target, dict) and "clip" in target:
            # 精确坐标裁剪二维码
            c = target["clip"]
            pad = 20  # 留一圈白边，扫码 App 更容易对焦
            clip = {"x": max(0, c["x"] - pad), "y": max(0, c["y"] - pad),
                    "width": c["width"] + pad * 2, "height": c["height"] + pad * 2}
            buf = await page.screenshot(clip=clip, timeout=8000)
            buf = _upscale_qr(buf)
        elif target is not None:
            buf = await target.screenshot(timeout=8000)
            buf = _upscale_qr(buf)
        else:
            buf = await page.screenshot(timeout=10000)
        b64 = base64.b64encode(buf).decode()
    except Exception as e:
        return {"platform": platform, "error": str(e)}
    if logged:
        await _save_state(platform)
    return {"platform": platform, "img": b64, "logged_in": logged, "url": page.url}


def _upscale_qr(png: bytes, target_w: int = 720) -> bytes:
    """把小尺寸二维码 NEAREST 放大（保锐度）后贴到纯白画布中央，
    周围留白边——扫码 App 对'白底+清晰边缘'识别率最高。"""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(png)).convert("RGB")
        # 放大到 target_w（保持比例）
        scale = target_w / im.width
        new_h = int(im.height * scale)
        im_big = im.resize((target_w, new_h), Image.Resampling.NEAREST)
        # 白底画布，四周留白
        margin = 60
        canvas = Image.new("RGB", (target_w + margin * 2, new_h + margin * 2), (255, 255, 255))
        canvas.paste(im_big, (margin, margin))
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return png


async def _save_state(platform: str):
    if platform in _contexts:
        ctx, _ = _contexts[platform]
        try:
            await ctx.storage_state(path=str(STORAGE_DIR / f"{platform}.json"))
        except Exception:
            pass


async def gzh_publish_draft(title: str, body_html: str) -> dict:
    """公众号：自动新建草稿填内容提交群发（最后扫码由用户确认）。"""
    async with _lock:
        page = await _get_page("gzh")
        try:
            await page.goto("https://mp.weixin.qq.com", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(3)
        if not _is_logged_in("gzh", page.url):
            return {"ok": False, "err": "公众号未登录，请先在右侧扫码并在手机上确认", "need_login": True}
        try:
            token = ""
            if "token=" in page.url:
                token = page.url.split("token=")[-1].split("&")[0]
            if not token:
                return {"ok": False, "err": "登录态异常（URL 无 token），请重新扫码", "need_login": True}
            edit_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&createType=0&token={token}&lang=zh_CN"
            await page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)

            # 关闭所有弹窗（"我知道了"、education-dialog 等遮挡层）
            for sel in ["text=我知道了", "text=知道了"]:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click(timeout=1500)
                except Exception:
                    pass
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            await page.evaluate("()=>{document.querySelectorAll('.weui-desktop-dialog__wrp,.education-dialog,[class*=education-dialog]').forEach(e=>e.remove())}")
            await asyncio.sleep(0.5)

            # 填标题：用 JS value + input/change 事件（比 page.fill 稳，避开不可见元素）
            await page.evaluate(
                "(t)=>{const els=document.querySelectorAll('textarea#title');"
                "for(const e of els){if(e.offsetParent){e.value=t;"
                "e.dispatchEvent(new Event('input',{bubbles:true}));"
                "e.dispatchEvent(new Event('change',{bubbles:true}));break;}}}",
                title[:64])
            await asyncio.sleep(0.5)

            # 填正文：点 ProseMirror 聚焦 → keyboard.type 模拟键盘输入
            # ProseMirror 只认真实键盘事件 / paste 事件，innerHTML 注入无效
            plain_text = _strip_html(body_html)
            clicked = False
            for el in await page.query_selector_all(".ProseMirror"):
                try:
                    if await el.is_visible():
                        await el.click(timeout=3000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                return {"ok": False, "err": "找不到正文编辑区", "img": None}
            await asyncio.sleep(0.5)
            # 键盘逐字输入（type 速度 8ms/字符，正文 500 字约 4 秒）
            await page.keyboard.type(plain_text, delay=8)
            await asyncio.sleep(1)
            # 兜底：若 keyboard.type 没进 ProseMirror（少数时序问题），
            # 用真实 paste 事件灌入纯文本（ProseMirror 认 paste 不认 innerHTML）
            _wc0 = await page.evaluate("()=>{const e=[...document.querySelectorAll('.ProseMirror')].find(x=>x.offsetParent);return e?e.innerText.trim().length:0}")
            if _wc0 == 0:
                await page.evaluate("(t)=>{const e=[...document.querySelectorAll('.ProseMirror')].find(x=>x.offsetParent);if(!e)return;e.focus();const dt=new DataTransfer();dt.setData('text/plain',t);e.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}))}", plain_text)
                await asyncio.sleep(1)

            # 校验正文是否填入：直接量 ProseMirror 的 innerText
            # （页面"正文字数"统计是延迟/节流更新的，不能作为校验依据）
            wc = await page.evaluate("()=>{const e=[...document.querySelectorAll('.ProseMirror')].find(x=>x.offsetParent);return e?e.innerText.trim().length:0}")
            if wc == 0:
                return {"ok": False, "err": "正文填入失败（字数仍0），请重试", "img": None}

            # 保存为草稿
            saved = False
            for sel in ["#js_submit", "button:has-text('保存为草稿')", "text=保存为草稿"]:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.click(timeout=5000)
                        saved = True
                        break
                except Exception:
                    continue
            if not saved:
                return {"ok": False, "err": "找不到保存按钮", "img": None}
            await asyncio.sleep(4)
            await _save_state("gzh")
            return {"ok": True, "stage": "draft_saved",
                    "note": f"已填入草稿（{wc}字），请到公众号后台草稿箱确认群发"}
        except Exception as e:
            return {"ok": False, "err": f"自动填稿失败：{e}", "img": None}


def _strip_html(html: str) -> str:
    """去掉 HTML 标签变成纯文本，换行保留。"""
    import re
    s = re.sub(r'<br\s*/?>', '\n', html)
    s = re.sub(r'</p>', '\n\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    return s.strip()


# ---------- 抖音 / 小红书 / 视频号：打开 + 填文字草稿 ----------
# 这三个平台的发布页都含文件上传（视频/图片），属于重交互，
# 目前实现到「自动打开发布页 + 把标题/正文填好」，文件由用户在右侧窗口手动拖入后点发布。

async def douyin_publish_draft(title: str, body_html: str,
                               video_path: str = "", biz_line: str = "channel") -> dict:
    """抖音：打开发布页，灌视频文件 + 填标题正文。"""
    return await _generic_fill("douyin", title, body_html,
                               home="https://creator.douyin.com/creator-micro/content/upload",
                               title_sels=["input[placeholder*='标题']", "input[placeholder*='作品标题']"],
                               body_sels=["div[contenteditable='true']", "textarea[placeholder*='正文']", "textarea[placeholder*='描述']"],
                               publish_sels=["button:has-text('发布')", "button.publish"],
                               video_path=video_path, biz_line=biz_line)


async def xhs_publish_draft(title: str, body_html: str,
                            video_path: str = "", biz_line: str = "channel") -> dict:
    """小红书：打开发布笔记页并填标题+正文。"""
    return await _generic_fill("xhs", title, body_html,
                               home="https://creator.xiaohongshu.com/publish/publish",
                               title_sels=["input[placeholder*='标题']", "input[placeholder*='填写标题']"],
                               body_sels=["div[contenteditable='true']", "textarea[placeholder*='正文']"],
                               publish_sels=["button:has-text('发布')", "button:has-text('发布笔记')"],
                               video_path=video_path, biz_line=biz_line)


async def shipinhao_publish_draft(title: str, body_html: str,
                                  video_path: str = "", biz_line: str = "channel") -> dict:
    """视频号：打开视频号助手发表页并填文案。"""
    return await _generic_fill("shipinhao", title, body_html,
                               home="https://channels.weixin.qq.com/platform/post/create",
                               title_sels=["input[placeholder*='标题']", "textarea[placeholder*='标题']"],
                               body_sels=["div[contenteditable='true']", "textarea[placeholder*='描述']", "textarea[placeholder*='正文']"],
                               publish_sels=["button:has-text('发表')", "button:has-text('发布')"],
                               video_path=video_path, biz_line=biz_line)


async def _generic_fill(platform: str, title: str, body_html: str,
                        home: str, title_sels: list, body_sels: list,
                        publish_sels: list,
                        video_path: str = "", biz_line: str = "channel") -> dict:
    """通用填稿：检查登录态 → 开发布页 → 关弹窗 → 填标题/正文 → 停在待用户点发布状态。

    返回 ok=True 表示已填好等用户确认（不自动点发布，避免误发）。
    """
    async with _lock:
        page = await _get_page(platform)
        try:
            await page.goto(home, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(4)
        # URL 判据 + 页面文案双重确认（URL 可能误判登录页）
        if not _is_logged_in(platform, page.url):
            return {"ok": False, "err": f"{platform} 未登录，请先在右侧扫码并在 App 里确认", "need_login": True}
        try:
            txt = await page.inner_text("body", timeout=3000)
            if any(s in txt[:3000] for s in ["扫码登录", "验证码登录", "密码登录", "登录即代表", "短信登录", "手机号登录"]):
                return {"ok": False, "err": f"{platform} 未登录，请先在右侧扫码", "need_login": True}
        except Exception:
            pass
        # 关常见弹窗
        for sel in ["text=我知道了", "text=知道了", ".semi-modal-close", "[class*=dialog] [class*=close]"]:
            try:
                b = await page.query_selector(sel)
                if b and await b.is_visible():
                    await b.click(timeout=1200)
            except Exception:
                pass
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        plain = _strip_html(body_html)

        # ---- 上传视频文件（平台必须传视频才能发） ----
        video_note = ""
        if platform in ("douyin", "shipinhao", "xhs"):
            if not video_path:
                # 没带视频就用图文生成一个
                try:
                    from .video_gen import gen_video_for_variant
                    video_path = str(gen_video_for_variant(title, body_html, biz_line, duration=6.0))
                    video_note = "（已自动合成图文视频）"
                except Exception as e:
                    video_note = f"（视频生成失败 {e}，请在右侧手动上传）"
            if video_path:
                try:
                    file_inputs = await page.query_selector_all("input[type=file]")
                    uploaded = False
                    for fi in file_inputs:
                        try:
                            accept = await fi.get_attribute("accept") or ""
                            if "video" in accept or "mp4" in accept or accept == "" or "*" in accept:
                                await fi.set_input_files(video_path)
                                uploaded = True
                                break
                        except Exception:
                            continue
                    if uploaded:
                        video_note += "·视频已填入上传框"
                        # 等平台处理上传
                        await asyncio.sleep(3)
                    else:
                        video_note += "·未找到视频上传框，请手动上传"
                except Exception as e:
                    video_note += f"·上传失败 {e}"


        filled = {"title": False, "body": False}
        # 标题
        for sel in title_sels:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    try:
                        await el.fill(title[:64])
                    except Exception:
                        await page.evaluate("(a)=>{const[s,t]=a;s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}))}", [sel, title[:64]])
                    filled["title"] = True
                    break
            except Exception:
                continue
        # 正文：优先 contenteditable（键盘输入），否则 textarea
        for sel in body_sels:
            try:
                el = await page.query_selector(sel)
                if not el or not await el.is_visible():
                    continue
                tag = await el.evaluate("e=>e.tagName.toLowerCase()+':'+(e.getAttribute('contenteditable')||'')")
                if "contenteditable" in tag or "div:" in tag:
                    await el.click(timeout=2000)
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(plain, delay=6)
                else:
                    try:
                        await el.fill(plain)
                    except Exception:
                        await page.evaluate("(a)=>{const[s,t]=a;s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}))}", [sel, plain])
                filled["body"] = True
                break
            except Exception:
                continue
        await _save_state(platform)
        if not (filled["title"] or filled["body"]):
            return {"ok": False, "err": f"{platform} 发布页没找到标题/正文输入框（DOM 变了？）", "need_login": False}
        return {"ok": True, "stage": "filled",
                "note": f"已在{platform}后台填好标题/正文{video_note}，请在右侧窗口确认后点发布",
                "filled": filled, "url": page.url, "video_note": video_note}
