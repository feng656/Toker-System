"""导出FastAPI运行时同源的OpenAPI 3.1；不连接数据库或启动服务。"""
import argparse
import json
from pathlib import Path
from app.main import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='docs/openapi-3.1.json')
    args = parser.parse_args()
    data = app.openapi()
    assert data['openapi'].startswith('3.1.')
    assert all(p.startswith('/api/v1') for p in data['paths'])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise SystemExit('目标规范已存在；请显式选新路径，不覆盖已交付文件')
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'OpenAPI {data["openapi"]}：{len(data["paths"])}个路径，{out}')


if __name__ == '__main__':
    main()
