import time
import ipaddress
from collections import defaultdict
from threading import Lock

from flask import Request

from logger import create_log
from settings import TRUSTED_PROXIES


logger = create_log("api_rate_limiter")


def _normalize_ip(ip: str) -> str:
    """规范化 IP：
    1. IPv4-mapped IPv6 (::ffff:1.2.3.4) → 1.2.3.4
    2. 其他原样返回
    """
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 6 and addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return ip
    except ValueError:
        return ip


def resolve_client_ip(flask_request: Request) -> str:
    """从请求中解析真实客户端 IP，支持反向代理场景。"""
    remote = flask_request.remote_addr or "unknown"

    trusted = set(TRUSTED_PROXIES) if TRUSTED_PROXIES else None

    # X-Forwarded-For: client, proxy1, proxy2
    xff = flask_request.headers.get("X-Forwarded-For", "")
    if xff:
        ips = [ip.strip() for ip in xff.split(",")]
        if trusted:
            # 从右向左找第一个不在可信列表里的 IP
            for ip in reversed(ips):
                if ip not in trusted:
                    return _normalize_ip(ip)
            # 全部可信 → 取最左（真实客户端）
            return _normalize_ip(ips[0])
        # 没有配置可信代理 → 直接取第一个
        return _normalize_ip(ips[0])

    # X-Real-IP (nginx 常用)
    xri = flask_request.headers.get("X-Real-IP", "")
    if xri:
        return _normalize_ip(xri)

    return _normalize_ip(remote)


class ApiRateLimiter:
    """按 IP 限制外盘 API（akshare/baostock）调用频率——滑动窗口"""

    def __init__(self, per_minute=3, lockout_seconds=60):
        self._per_minute = per_minute
        self._lockout_seconds = lockout_seconds
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    @property
    def per_minute(self):
        return self._per_minute

    @per_minute.setter
    def per_minute(self, value):
        self._per_minute = value

    def check_and_record(self, ip: str) -> tuple[bool, int]:
        """
        原子操作：检查 + 记录。
        在同一个锁内完成清理旧记录、判断、写入。

        返回 (allowed, retry_after_seconds)
        """
        ip = _normalize_ip(ip)
        now = time.time()
        with self._lock:
            cutoff = now - 60
            self._windows[ip] = [t for t in self._windows[ip] if t > cutoff]
            recent = self._windows[ip]

            if len(recent) >= self._per_minute:
                oldest = recent[0]
                retry_after = int(60 - (now - oldest)) + self._lockout_seconds
                logger.warning(
                    f"IP {ip} 触发限流: {len(recent)}次/{self._per_minute}次每分钟, "
                    f"retry_after={retry_after}s"
                )
                return False, max(retry_after, 1)

            self._windows[ip].append(now)
            return True, 0

    def remaining(self, ip: str) -> int:
        """返回该 IP 在当前窗口还剩多少次调用机会"""
        ip = _normalize_ip(ip)
        now = time.time()
        with self._lock:
            cutoff = now - 60
            cleaned = [t for t in self._windows[ip] if t > cutoff]
            if cleaned:
                self._windows[ip] = cleaned
            else:
                # 淘汰空 IP 条目，避免内存泄露
                self._windows.pop(ip, None)
                return self._per_minute
            return max(0, self._per_minute - len(cleaned))

    def _collect_garbage(self):
        """淘汰所有无记录的 IP（可被定期调用）"""
        with self._lock:
            now = time.time()
            cutoff = now - 60
            expired = []
            for ip, timestamps in self._windows.items():
                alive = [t for t in timestamps if t > cutoff]
                if alive:
                    self._windows[ip] = alive
                else:
                    expired.append(ip)
            for ip in expired:
                del self._windows[ip]


class RateLimitError(Exception):
    """被限流时抛出的异常"""
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


_rate_limiter = None


def get_rate_limiter():
    from settings import (
        ENABLE_API_RATE_LIMIT,
        API_RATE_LIMIT_PER_MINUTE,
        API_RATE_LIMIT_LOCKOUT_SECONDS,
    )
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ApiRateLimiter(
            per_minute=API_RATE_LIMIT_PER_MINUTE,
            lockout_seconds=API_RATE_LIMIT_LOCKOUT_SECONDS,
        )
    return _rate_limiter
