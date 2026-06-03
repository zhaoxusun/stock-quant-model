import os
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 覆盖缓存目录到 /tmp（Vercel 可写目录）
os.environ.setdefault('CACHE_DIR', '/tmp')

from app import app

# Vercel serverless handler
handler = app
