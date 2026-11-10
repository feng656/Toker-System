"""安全镜像：仅把明确分支快进推到Gitee；无force/--mirror/删除远端。
用法：python scripts/sync_mirror.py --target https://gitee.com/ORG/REPO.git --branch main [--execute]
认证由本机Git credential helper或CI GIT_ASKPASS提供，禁止把令牌写URL/argv。
"""
import argparse
import re
import subprocess
from urllib.parse import urlsplit


def validate_target(url):
    u = urlsplit(url)
    if u.scheme != 'https' or u.hostname != 'gitee.com' or u.username or u.password or u.query or u.fragment or u.port:
        raise ValueError('目标必须是无凭据的https://gitee.com/组织/仓库.git')
    if not re.fullmatch(r'/[\w.-]+/[\w.-]+(?:\.git)?',u.path):
        raise ValueError('目标仓库路径无效')
    return url


def git(*args):
    # 不把stderr原文打到CI日志，避免credential helper异常输出秘密。
    result = subprocess.run(['git', *args], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Git操作失败；检查授权/网络或分支是否分叉，未强推。动作：'+args[0])
    return result.stdout.strip()


def sync(target, branch, execute=False):
    validate_target(target)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,150}', branch) or '..' in branch:
        raise ValueError('分支名无效')
    git('check-ref-format','refs/heads/'+branch)
    sha=git('rev-parse','refs/heads/'+branch)
    command=['push','--porcelain']
    if not execute:command.append('--dry-run')
    command.extend([target,f'{sha}:refs/heads/{branch}'])
    git(*command)  # Git默认拒绝non-fast-forward；不会覆盖镜像方新增提交。
    if execute:
        remote=git('ls-remote','--heads',target,'refs/heads/'+branch).split()
        if not remote or remote[0]!=sha:raise RuntimeError('推送后远端SHA不一致，请核对')
    return {'branch':branch,'sha':sha,'mode':'executed' if execute else 'dry-run'}


def main():
    import json
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',required=True)
    parser.add_argument('--branch',default='main')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    print(json.dumps(sync(args.target,args.branch,args.execute),ensure_ascii=False))


if __name__=='__main__':main()
