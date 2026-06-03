"""
防作弊中间件：速率限制、防重放、用户配额
"""

import time
import hashlib
import json
from collections import defaultdict
from threading import Lock
from functools import wraps

from flask import request, make_response, jsonify

from logger import create_log
from ml.model_api_config import (
    ANTI_CHEAT_ENABLED,
    RATE_LIMIT,
    ANTI_REPLAY,
    API_AUTH,
    IP_ACCESS,
    USER_QUOTA,
    RATE_LIMIT_RESPONSE,
    AUDIT_LOG,
)

logger = create_log("anti_cheat")


class SlidingWindowRateLimiter:
    """滑动窗口速率限制器（线程安全）"""

    def __init__(self):
        self._windows = defaultdict(list)
        self._lock = Lock()

    def _get_user_limits(self, user: str) -> dict:
        """获取用户配额，支持 overrides 覆写"""
        default = USER_QUOTA.get("default_quota", {})
        overrides = USER_QUOTA.get("overrides", {})
        return overrides.get(user, default)

    def is_allowed(self, user: str) -> tuple[bool, dict]:
        """
        检查请求是否允许
        返回: (allowed, headers)
        """
        limits = self._get_user_limits(user)
        now = time.time()
        window_min = 60
        window_hour = 3600
        window_day = 86400

        with self._lock:
            windows = self._windows[user]
            # 清理过期记录
            cutoff = now - window_day
            self._windows[user] = [t for t in windows if t > cutoff]
            windows = self._windows[user]

            # 统计各窗口请求数
            count_minute = sum(1 for t in windows if t > now - window_min)
            count_hour = sum(1 for t in windows if t > now - window_hour)
            count_day = len(windows)

            limit_min = limits.get("per_minute", RATE_LIMIT.get("per_minute", 60))
            limit_hour = limits.get("per_hour", RATE_LIMIT.get("per_hour", 1000))
            limit_day = limits.get("per_day", RATE_LIMIT.get("per_day", 5000))
            burst = RATE_LIMIT.get("burst", limit_min // 2)

            # 无限制
            if limit_min == -1:
                return True, {}

            allowed = (
                count_minute < limit_min + burst
                and count_hour < limit_hour
                and count_day < limit_day
            )

            headers = {
                "X-RateLimit-Limit-Minute": str(limit_min),
                "X-RateLimit-Remaining-Minute": str(max(0, limit_min + burst - count_minute)),
                "X-RateLimit-Limit-Hour": str(limit_hour),
                "X-RateLimit-Remaining-Hour": str(max(0, limit_hour - count_hour)),
                "X-RateLimit-Limit-Day": str(limit_day),
                "X-RateLimit-Remaining-Day": str(max(0, limit_day - count_day)),
            }

            if allowed:
                self._windows[user].append(now)

            return allowed, headers

    def get_wait_time(self, user: str) -> int:
        """获取还需要等待多少秒"""
        limits = self._get_user_limits(user)
        now = time.time()
        limit_min = limits.get("per_minute", RATE_LIMIT.get("per_minute", 60))

        with self._lock:
            windows = self._windows[user]
            recent = [t for t in windows if t > now - 60]

        if len(recent) < limit_min:
            return 0

        oldest = min(recent)
        return max(0, int(60 - (now - oldest)))


class NonceValidator:
    """防重放攻击 - Nonce 校验"""

    def __init__(self):
        self._cache = set()
        self._lock = Lock()

    def validate(self, nonce: str, timestamp: int) -> tuple[bool, str]:
        """
        校验 nonce
        返回: (valid, reason)
        """
        if not ANTI_REPLAY.get("enabled", True):
            return True, ""

        if not nonce or not timestamp:
            return False, "缺少 nonce 或 timestamp"

        # 校验时间偏差
        now = int(time.time())
        skew = ANTI_REPLAY.get("timestamp_skew_seconds", 60)
        if abs(now - timestamp) > skew:
            return False, f"时间戳偏差过大 (|{now} - {timestamp}| > {skew}s)"

        # 校验 nonce 是否已使用过
        with self._lock:
            key = f"{nonce}:{timestamp}"
            if key in self._cache:
                return False, "nonce 已使用过（重放攻击）"

            max_cache = ANTI_REPLAY.get("max_nonce_cache", 10000)
            if len(self._cache) > max_cache:
                self._cache.clear()

            self._cache.add(key)

        return True, ""


class IPAccessController:
    """IP 访问控制"""

    @staticmethod
    def is_allowed(ip: str) -> tuple[bool, str]:
        """检查 IP 是否允许访问"""
        blacklist = IP_ACCESS.get("blacklist", [])
        whitelist = IP_ACCESS.get("whitelist", [])
        whitelist_enabled = IP_ACCESS.get("whitelist_enabled", False)

        if ip in blacklist:
            return False, f"IP {ip} 已被封禁"

        if whitelist_enabled and ip not in whitelist:
            return False, f"IP {ip} 不在白名单中"

        return True, ""


class APIKeyAuth:
    """API Key 认证"""

    @staticmethod
    def authenticate() -> tuple[bool, str]:
        """
        认证 API Key
        返回: (authenticated, username)
        """
        if not API_AUTH.get("enabled", False):
            return True, API_AUTH.get("default_user", "anonymous")

        header = API_AUTH.get("header_name", "X-API-Key")
        api_key = request.headers.get(header, "")

        if not api_key:
            return False, ""

        api_keys = API_AUTH.get("api_keys", {})
        if not api_keys:
            return True, API_AUTH.get("default_user", "anonymous")

        username = api_keys.get(api_key)
        if username is None:
            return False, ""

        return True, username


# 全局实例
rate_limiter = SlidingWindowRateLimiter()
nonce_validator = NonceValidator()


def _make_error_response(message: str, status_code: int, extra: dict = None) -> make_response:
    """构造统一错误响应"""
    data = {"success": False, "message": message}
    if extra:
        data.update(extra)
    resp = make_response(json.dumps(data, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.status_code = status_code
    return resp


def anti_cheat_required(f):
    """
    防作弊装饰器：API Key 认证 + IP 黑白名单 + 防重放 + 速率限制
    用法：
        @app.route('/api/some-endpoint', methods=['POST'])
        @anti_cheat_required
        def my_endpoint():
            ...
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not ANTI_CHEAT_ENABLED:
            return f(*args, **kwargs)

        client_ip = request.remote_addr or "unknown"

        # 1. IP 黑白名单
        ip_allowed, ip_reason = IPAccessController.is_allowed(client_ip)
        if not ip_allowed:
            logger.warning(f"IP 被拒绝: {client_ip} - {ip_reason}")
            return _make_error_response(ip_reason, 403)

        # 2. API Key 认证
        auth_ok, username = APIKeyAuth.authenticate()
        if not auth_ok:
            logger.warning(f"API Key 认证失败: {client_ip}")
            return _make_error_response("API Key 无效或缺失", 401)

        # 3. 防重放（仅 POST/PUT/DELETE）
        if request.method in ("POST", "PUT", "DELETE"):
            nonce = request.headers.get("X-Nonce", "") or request.args.get("nonce", "")
            ts_str = request.headers.get("X-Timestamp", "") or request.args.get("timestamp", "")
            try:
                timestamp = int(ts_str)
            except (ValueError, TypeError):
                timestamp = 0

            valid, reason = nonce_validator.validate(nonce, timestamp)
            if not valid:
                logger.warning(f"防重放拦截: user={username}, ip={client_ip}, reason={reason}")
                return _make_error_response(reason, 400)

        # 4. 速率限制
        allowed, rate_headers = rate_limiter.is_allowed(username)
        if not allowed:
            wait = rate_limiter.get_wait_time(username)
            retry = RATE_LIMIT_RESPONSE.get("retry_after_seconds", 60)
            logger.warning(f"速率限制触发: user={username}, ip={client_ip}, wait={wait}s")

            resp = _make_error_response(
                RATE_LIMIT_RESPONSE.get("message", "请求过于频繁"),
                RATE_LIMIT_RESPONSE.get("status_code", 429),
                {"retry_after": wait or retry},
            )
            resp.headers["Retry-After"] = str(wait or retry)
            for k, v in rate_headers.items():
                resp.headers[k] = v
            return resp

        # 5. 审计日志
        if AUDIT_LOG.get("enabled", False) and AUDIT_LOG.get("log_all_requests", False):
            logger.info(f"API请求: user={username}, ip={client_ip}, method={request.method}, path={request.path}")

        # 将用户名注入请求上下文
        request.current_user = username
        request.client_ip = client_ip

        return f(*args, **kwargs)

    return decorated


def get_rate_limit_status(username: str = None) -> dict:
    """获取当前用户的速率限制状态"""
    if username is None:
        username = getattr(request, "current_user", "anonymous")

    limits = rate_limiter._get_user_limits(username)
    now = time.time()
    windows = rate_limiter._windows.get(username, [])
    recent_minute = sum(1 for t in windows if t > now - 60)
    recent_hour = sum(1 for t in windows if t > now - 3600)
    recent_day = sum(1 for t in windows if t > now - 86400)

    return {
        "username": username,
        "limits": limits,
        "usage": {
            "current_minute": recent_minute,
            "current_hour": recent_hour,
            "current_day": recent_day,
        },
    }
