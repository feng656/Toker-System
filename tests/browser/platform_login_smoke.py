"""共享受管浏览器自查：真实测试后端持久化 + 显式模拟扫码状态；不登录外部平台。
需要 playwright==受管实例expected_version；不可在此脚本中launch独立浏览器。
仅对独立验收数据库运行，会新增一个平台和一个账号，不删除历史记录。
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    if os.environ.get('TOKER_SMOKE_ISOLATED') != 'yes':
        raise SystemExit('必须明确TOKER_SMOKE_ISOLATED=yes，只能在独立测试环境运行')
    url=os.environ['TOKER_SMOKE_URL'].rstrip('/')
    out=Path(os.environ.get('TOKER_SMOKE_OUT','var/login-smoke'));out.mkdir(parents=True,exist_ok=True)
    suffix=uuid.uuid4().hex[:6]
    custom_name='验收测试社区-'+suffix
    account_label='验收账号-'+suffix
    with sync_playwright() as p:
        browser=p.chromium.connect(os.environ['MANAGED_BROWSER_WS'])
        context=browser.contexts[0] if browser.contexts else browser.new_context()
        page=context.new_page()
        page.set_viewport_size({'width':1440,'height':1000})
        page.emulate_media(reduced_motion='reduce')
        def shot(filename):
            page.evaluate("async()=>{await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))}")
            page.screenshot(path=str(out/filename),animations='disabled')
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url,wait_until='networkidle')
        if page.locator('.login-card').is_visible():
            page.get_by_placeholder('请输入账号').fill(os.environ.get('TOKER_SMOKE_USER','admin'))
            page.get_by_placeholder('请输入密码').fill(os.environ['TOKER_SMOKE_PASSWORD'])
            page.get_by_role('button',name='登录',exact=True).click()
        accounts=page.locator('.platform-accounts')
        expect(accounts).to_be_visible(timeout=20000)
        accounts.get_by_role('button',name='+ 添加账号',exact=True).click()
        dlg=page.get_by_role('dialog',name='添加平台账号',exact=True)
        expect(dlg.locator('.pa-platform-option')).to_have_count(
            len(page.evaluate("async()=>{const r=await fetch('/api/workspace/platforms',{headers:{Authorization:'Bearer '+localStorage.getItem('tk_token')}});return r.json()}")))
        initial_count=dlg.locator('.pa-platform-option').count()
        assert initial_count>=15
        dlg.get_by_role('button',name='抖音 视频',exact=True).click()
        shot('platform-login-desktop.png')
        dlg.get_by_role('button',name='找不到平台？手动添加并保存').click()
        dlg.get_by_role('textbox',name='自定义平台名称',exact=True).fill(custom_name)
        dlg.get_by_role('textbox',name='平台登录入口',exact=True).fill('https://community.company.com/login')
        dlg.get_by_role('button',name='保存平台并选用').click()
        expect(dlg.locator('.pa-platform-option.selected')).to_contain_text(custom_name)
        dlg.get_by_role('textbox',name='搜索平台',exact=True).fill(custom_name)
        expect(dlg.locator('.pa-platform-option.selected')).to_be_visible()
        shot('platform-login-custom-saved.png')
        dlg.get_by_role('button',name='取消',exact=True).click()
        page.reload(wait_until='networkidle')
        accounts.get_by_role('button',name='+ 添加账号',exact=True).click()
        expect(dlg.locator('.pa-platform-option')).to_have_count(initial_count+1)
        expect(dlg.locator('.pa-platform-option').filter(has_text=custom_name)).to_be_visible()
        dlg.get_by_role('button',name='抖音 视频',exact=True).click()
        dlg.get_by_role('textbox',name='平台账号',exact=True).fill('smoke-brand-account')
        dlg.get_by_role('textbox',name='账号备注',exact=True).fill(account_label)
        dlg.get_by_role('button',name='保存账号并获取二维码').click()
        qr=page.get_by_role('dialog',name='平台扫码登录',exact=True)
        expect(qr.get_by_role('alert')).to_contain_text('账号已保存',timeout=20000)
        expect(qr.locator('.pa-qr-image')).to_have_count(0)
        shot('platform-login-unconfigured.png')
        qr.get_by_role('button',name='关闭',exact=True).click()
        page.reload(wait_until='networkidle')
        row=accounts.locator('.pa-account').filter(has_text=account_label)
        expect(row).to_have_count(1)
        expect(row).to_contain_text('未登录')
        # 仅以下登录接口模拟响应。图片是空白测试夹具，不含真实登录二维码。
        counters={'login':0,'refresh':0,'session':0}
        base={'id':999991,'platform_id':1,'label':account_label,'login_hint':'smoke-brand-account',
              'status':'awaiting_scan','qr_available':True,'expires_soon':False,'nickname':'模拟授权账号'}
        mode={'value':'waiting'}
        png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBYcAAAAASUVORK5CYII='
        def handle(route):
            action=route.request.url.rsplit('/',1)[-1]
            if action not in ('login','session','refresh'):
                route.continue_();return
            counters[action]+=1
            data=dict(base)
            # 获取真实选中账号ID/平台ID，只在浏览器中替换远端授权返回。
            data['id']=int(route.request.url.split('/')[-2])
            if mode['value']=='connect' and counters['refresh']:
                data.update(status='connected',qr_available=False)
            elif mode['value']=='expired':
                data.update(status='expired',qr_available=False)
            else:
                data.update(qr_expires_at=(datetime.now(timezone.utc)+timedelta(seconds=90)).isoformat(),
                    qr_url='data:image/png;base64,'+png)
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/api/workspace/accounts/*/*',handle)
        mode['value']='connect'
        row.get_by_role('button',name='扫码登录').click()
        expect(qr.locator('.pa-qr-image')).to_be_visible()
        expect(qr.get_by_text('登录成功',exact=True)).to_be_visible(timeout=12000)
        assert counters['refresh']>=1
        qr.get_by_role('button',name='关闭',exact=True).click()
        mode['value']='expired'
        row.get_by_role('button',name='扫码登录').click()
        expect(qr.get_by_role('button',name='重新获取二维码')).to_be_visible()
        expect(qr.locator('.pa-qr-image')).to_have_count(0)
        qr.get_by_role('button',name='关闭',exact=True).click()
        page.unroute('**/api/workspace/accounts/*/*',handle)
        page.evaluate('window.ElementPlus.ElMessage.closeAll()')
        expect(page.locator('.el-message')).to_have_count(0)
        # 手机尺寸只检查账号弹窗；未改动工作台其他区域的布局。
        page.set_viewport_size({'width':390,'height':844})
        accounts.get_by_role('button',name='+ 添加账号',exact=True).click()
        dlg.get_by_role('button',name='抖音 视频',exact=True).click()
        box=dlg.bounding_box()
        assert box and box['x']>=0 and box['x']+box['width']<=391
        assert dlg.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        footer=dlg.get_by_role('button',name='保存账号并获取二维码').bounding_box()
        assert footer and footer['y']>=0 and footer['y']+footer['height']<=844
        shot('platform-login-mobile.png')
        dlg.get_by_role('button',name='取消',exact=True).click()
        assert not errors,errors
        summary={'real_backend':['15 platform options','custom platform persists after reload','account saved once','unconfigured login has no fake QR'],
                 'mock_only':['active refresh progresses to connected','expired QR removed'],
                 'mobile_dialog_width':box['width'],'javascript_errors':errors,'adapter_requests':counters,
                 'real_external_platform_login_verified':False}
        (out/'browser-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False))
        page.close()
        browser.close()


if __name__=='__main__':main()
