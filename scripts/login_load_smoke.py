"""应用内登录并发烟测，不是公网压测或DDoS抵抗证明；仅专用PostgreSQL测试schema。"""
import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
from app import config
from app.db import engine
from app.main import app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    if config.APP_ENV!='test' or engine.dialect.name!='postgresql':raise SystemExit('仅专用PG测试环境可执行')
    with engine.connect() as c:
        if c.scalar(text('select current_schema()'))!='jiangguo_phase2_validation':raise SystemExit('拒绝非专用schema')
    path=Path(args.out)
    if path.exists():raise SystemExit('输出已存在，请使用新文件名')
    timings=[]
    config.LOGIN_IP_LIMIT=30
    config.LOGIN_ACCOUNT_LIMIT=10
    with TestClient(app) as client:
        def attempt(i):
            start=time.monotonic()
            response=client.post('/api/v1/auth/login',json={'username':f'load-smoke-{i}','password':'not-a-valid-password'})
            return response.status_code,(time.monotonic()-start)*1000
        start=time.monotonic()
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures=[pool.submit(attempt,i) for i in range(64)]
            health_start=time.monotonic()
            health=client.get('/api/v1/health')
            health_ms=(time.monotonic()-health_start)*1000
            values=[f.result() for f in futures]
        elapsed=time.monotonic()-start
    codes=Counter(x[0] for x in values)
    assert set(codes)<= {401,428,429},codes
    assert codes[429]>0 and health.status_code==200
    timings=sorted(x[1] for x in values)
    report={'status':'passed','requests':64,'concurrency':16,'status_counts':dict(codes),
        'login_p95_ms':round(timings[int(len(timings)*0.95)-1],2),'health_status':health.status_code,
        'health_ms':round(health_ms,2),'elapsed_seconds':round(elapsed,2),
        'scope':'in-process TestClient with real PostgreSQL; no proxy or real network load test'}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
