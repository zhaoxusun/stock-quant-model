"""
模型 API 防作弊配置
所有项均可按需调整，支持热加载
"""

# ── 全局开关 ──
ANTI_CHEAT_ENABLED = True

# ── 速率限制（按用户 / IP）──
RATE_LIMIT = {
    "enabled": True,
    "strategy": "sliding_window",          # sliding_window | token_bucket
    "per_minute": 10,                       # 每分钟最多请求数
    "per_hour": 100,                        # 每小时最多请求数
    "per_day": 500,                         # 每天最多请求数
    "burst": 5,                             # 突发允许（超过 per_minute 的最大瞬时请求）
}

# ── 防重放攻击（Nonce）──
ANTI_REPLAY = {
    "enabled": False,                           # 默认关闭，前端页面无需 nonce
    "nonce_ttl_seconds": 300,
    "max_nonce_cache": 10000,
    "timestamp_skew_seconds": 60,
}

# ── API 认证 ──
API_AUTH = {
    "enabled": False,                           # 默认关闭，前端页面无需 Key
    "header_name": "X-API-Key",
    "api_keys": {},
    "default_user": "anonymous",
}

# ── IP 黑白名单 ──
IP_ACCESS = {
    "whitelist_enabled": False,              # True=仅白名单IP可访问
    "whitelist": [],                         # 白名单IP列表
    "blacklist": [],                         # 黑名单IP列表（优先于白名单）
}

# ── 用户配额 ──
USER_QUOTA = {
    "enabled": True,
    "default_quota": {                       # 未在 overrides 中的用户默认配额
        "per_minute": 10,
        "per_hour": 100,
        "per_day": 500,
    },
    "overrides": {                           # 特定用户配额覆写
        # "vip_user": {"per_minute": 60, "per_hour": 500, "per_day": 2000},
        # "admin": {"per_minute": -1},       # -1 = 无限制
    },
}

# ── 频率限制响应 ──
RATE_LIMIT_RESPONSE = {
    "status_code": 429,
    "message": "请求过于频繁，请稍后再试",
    "retry_after_seconds": 60,
}

# ── 日志 ──
AUDIT_LOG = {
    "enabled": True,
    "log_all_requests": False,               # True=记录所有请求，False=仅记录被限制的
}
