"""跨进程持久化限流、失败退避、绑定IP的一次性工作量挑战；不信任转发头。"""
import hashlib
import hmac
import secrets
import threading
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from . import config
from .auth import hash_password, verify_password
from .db import utcnow
from .models import AuthChallenge, LoginBucket, User
from .tasks import lock

_gate = threading.BoundedSemaphore(config.LOGIN_MAX_INFLIGHT)
DUMMY_HASH = hash_password('dummy-not-a-real-user-password')


def digest(value):
    return hmac.new(config.JWT_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def address(request):
    return request.client.host if request.client else 'unknown'


def bucket(db, key):
    lock(db, 'login:' + key)
    obj = db.scalar(select(LoginBucket).where(LoginBucket.bucket_key == key))
    now = utcnow()
    if not obj:
        obj = LoginBucket(bucket_key=key, window_started=now)
        db.add(obj); db.flush()
    if (now - obj.window_started).total_seconds() >= config.LOGIN_WINDOW_SECONDS:
        obj.window_started, obj.attempts, obj.failures, obj.blocked_until = now, 0, 0, None
    return obj


def limited(message, retry=60):
    raise HTTPException(429, message, headers={'Retry-After': str(max(1, retry))})


def consume(db, ip, username=None):
    keys = [('ip:' + digest(ip), config.LOGIN_IP_LIMIT)]
    if username is not None:
        keys.append(('account:' + digest(username.casefold()), config.LOGIN_ACCOUNT_LIMIT))
    result = []
    for key, limit in keys:  # 先IP再账号：IP已超额时不能继续创建无限账号桶。
        obj = bucket(db, key)
        if obj.attempts >= limit or (obj.blocked_until and obj.blocked_until > utcnow()):
            db.commit()
            limited('登录请求过多或失败退避中，请稍后重试')
        obj.attempts += 1
        result.append(obj)
    db.commit()  # 限流必须先持久化，认证失败/挑战失败不能撤销计数。
    return result


def create_challenge(db, ip):
    consume(db, ip)
    obj = AuthChallenge(challenge_id=secrets.token_urlsafe(24), ip_hash=digest(ip),
        nonce=secrets.token_urlsafe(24), difficulty=3, expires_at=utcnow()+timedelta(minutes=5))
    db.add(obj);db.commit()
    return {'challenge_id':obj.challenge_id,'nonce':obj.nonce,'difficulty':obj.difficulty,
            'algorithm':'sha256(nonce+solution) begins with difficulty zero hex chars','expires_at':obj.expires_at}


def verify_challenge(db, body, ip):
    if not body.challenge_id or not body.challenge_solution:
        return False
    lock(db, 'challenge:' + body.challenge_id)
    challenge = db.scalar(select(AuthChallenge).where(AuthChallenge.challenge_id == body.challenge_id))
    if not challenge or challenge.used_at or challenge.expires_at <= utcnow() or not hmac.compare_digest(challenge.ip_hash, digest(ip)):
        return False
    challenge.used_at = utcnow()
    ok = hashlib.sha256((challenge.nonce+body.challenge_solution).encode()).hexdigest().startswith('0'*challenge.difficulty)
    db.commit()
    return ok


def authenticate(db, body, request):
    if not _gate.acquire(blocking=False):
        limited('认证繁忙，请稍后重试', 2)
    try:
        ip = address(request)
        buckets = consume(db, ip, body.username)
        if max(b.failures for b in buckets) >= config.LOGIN_CHALLENGE_AFTER:
            if not verify_challenge(db, body, ip):
                raise HTTPException(428, {'message':'请完成登录挑战后重试','challenge_url':'/api/v1/auth/challenge'})
        user = db.scalar(select(User).where(User.username == body.username, User.enabled.is_(True)))
        ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if not user and config.AUTO_REGISTER_MODE == 'invite' and config.REGISTER_INVITE_CODE and hmac.compare_digest(body.invite_code or '', config.REGISTER_INVITE_CODE):
            if len(body.password) < 10 or len(body.password.encode()) > 72:
                raise HTTPException(422, '新账号密码至少10字符且UTF-8不超过72字节')
            lock(db, 'registration:' + body.username)
            existing = db.scalar(select(User).where(User.username == body.username).execution_options(include_deleted=True))
            if not existing:
                user = User(username=body.username, name=body.username, role='sales', password_hash=hash_password(body.password))
                db.add(user);db.flush();ok=True
        if not user or not ok:
            for b in buckets:
                lock(db,'login:'+b.bucket_key);db.refresh(b)
                b.failures += 1
                b.blocked_until = utcnow()+timedelta(seconds=min(60,2**min(b.failures,6)))
            db.commit()
            raise HTTPException(401, '账号或密码错误')
        for b in buckets:
            lock(db,'login:'+b.bucket_key);db.refresh(b)
            b.failures, b.blocked_until = 0, None
        db.commit()
        return user
    finally:
        _gate.release()
