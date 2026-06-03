from pathlib import Path


def get_project_root():
    current_file = Path(__file__).resolve()  # 当前文件的绝对路径
    root_markers = ['README.md', 'requirements-7.txt','requirements-13.txt']  # 根目录标志

    for parent in current_file.parents:
        if any((parent / marker).exists() for marker in root_markers):
            return parent
    raise FileNotFoundError("未找到项目根目录")


project_root = get_project_root()
data_root = project_root / 'data'
stock_data_root = data_root / 'stock'
log_root = project_root / 'log'
result_root = project_root / 'result'
html_root = result_root / 'html'
signals_root = result_root / 'signals'

# ── API 限流（akshare / baostock 调用频率）──
ENABLE_API_RATE_LIMIT = True           # 总开关
API_RATE_LIMIT_STRATEGY = "ip"         # "ip" | "off"
API_RATE_LIMIT_PER_MINUTE = 3          # 每 IP 每分钟最多调几次外盘 API
API_RATE_LIMIT_LOCKOUT_SECONDS = 60    # 超限后冷却秒数

# ── 可信代理 IP 列表（用于正确识别客户端 IP）──
# 当服务部署在 nginx/Cloudflare 后方时，填入代理的内网 IP
# 留空则直接信任 X-Forwarded-For 的第一个 IP
TRUSTED_PROXIES = []