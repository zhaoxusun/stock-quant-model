import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)
_xgb_pkgs = os.path.join(_PROJECT_ROOT, 'xgb_pkgs')
if os.path.isdir(_xgb_pkgs):
    sys.path.insert(0, _xgb_pkgs)
os.environ.setdefault('CACHE_DIR', '/tmp')

# Pre-warm numpy import (forces Vercel deferred install before handler runs)
import numpy as _np

# Fix numpy ELF alignment on Lambda (strip bundled openblas .so)
import subprocess as _sp, glob as _gl
for _dir in ('/var/task/_vendor', '/tmp/_vc_deps'):
    for _fp in _gl.glob(f'{_dir}/lib/python*/site-packages/numpy.libs/*.so'):
        try:
            _sp.run(['strip', '--strip-all', _fp], capture_output=True, timeout=10)
        except Exception:
            pass

from flask import Flask, jsonify, request, render_template

from flask_cors import CORS

from ml.api_rate_limiter import RateLimitError, resolve_client_ip

app = Flask(__name__)
CORS(app)


@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    return '', 204

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/blog')
def blog():
    return render_template('blog.html')

@app.route('/blog/how-to-use')
def blog_how_to_use():
    return render_template('blog_how_to_use.html')

@app.route('/api/health')
def health():
    deps = {}
    for mod_name in ('numpy', 'pandas', 'xgboost', 'scipy'):
        try:
            mod = __import__(mod_name)
            info = {"ok": True, "version": getattr(mod, "__version__", "?")}
            if mod_name == 'numpy':
                import importlib.util as _iu
                info["has_testing"] = _iu.find_spec("numpy.testing") is not None
            deps[mod_name] = info
        except Exception as e:
            deps[mod_name] = {"ok": False, "error": str(e)}
    return jsonify(deps)

@app.route('/api/debug/import')
def debug_import():
    import sys, traceback, json as _json, os as _os
    results = {}
    for mod_name in ('scipy', 'xgboost'):
        try:
            __import__(mod_name)
            results[mod_name] = "ok"
        except Exception:
            results[mod_name] = traceback.format_exc()
    # Dump xgboost lib dir and .libs dir
    _xgb_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "xgb_pkgs", "xgboost")
    _lib_files = {}
    for _sub in ("lib", ".libs"):
        _d = _os.path.join(_xgb_dir, _sub)
        _files = {}
        if _os.path.isdir(_d):
            for _f in sorted(_os.listdir(_d)):
                _fp = _os.path.join(_d, _f)
                _files[_f] = _os.path.getsize(_fp) if _os.path.isfile(_fp) else "<dir>"
        _lib_files[_sub] = _files
    results["xgb_lib_dir"] = _lib_files
    return _json.dumps({"sys.path": sys.path[:10], "results": results}, indent=2), 200, {'Content-Type': 'application/json'}

@app.route('/api/predict', methods=['POST'])
def predict():
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({"success": False, "message": "缺少股票代码"}), 400

    code = data['code'].strip()
    strategy = data.get('strategy', 'EnhancedVolumeStrategy')

    if not code:
        return jsonify({"success": False, "message": "股票代码不能为空"}), 400

    try:
        from ml.test_model import test_single_stock
        client_ip = resolve_client_ip(request)
        result = test_single_stock(code, strategy, client_ip=client_ip)
        if result is None:
            return jsonify({"success": False, "message": f"未找到股票 {code} 的K线文件"}), 404
        return jsonify(result)
    except RateLimitError as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "retry_after": e.retry_after,
        }), 429
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"  🚀 启动服务: http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)


handler = app
