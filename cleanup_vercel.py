import os
import shutil
import glob
import site
import sys
import subprocess


def get_site_packages():
    try:
        return site.getsitepackages()[0]
    except Exception:
        paths = [p for p in sys.path if 'site-packages' in p]
        if paths:
            return paths[0]
        candidates = glob.glob('.vercel/**/site-packages', recursive=True)
        if candidates:
            return candidates[0]
        return None


def dir_size(path):
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def rm(path):
    if os.path.isfile(path):
        sz = os.path.getsize(path)
        os.remove(path)
        return sz
    if os.path.isdir(path):
        sz = dir_size(path)
        shutil.rmtree(path)
        return sz
    return 0


def strip_so(path):
    saved = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            if '.so' in f:
                fp = os.path.join(root, f)
                if os.path.islink(fp):
                    continue
                old = os.path.getsize(fp)
                try:
                    subprocess.run(['strip', '--strip-all', fp], capture_output=True, timeout=30)
                    new = os.path.getsize(fp)
                    saved += old - new
                except Exception:
                    pass
    if saved:
        print(f'  Stripped .so files in {os.path.basename(path)} (saved {saved/1e6:.1f} MB)')
    return saved


def clean():
    sitepkgs = get_site_packages()
    if not sitepkgs or not os.path.isdir(sitepkgs):
        print('Cannot find site-packages, skipping cleanup')
        return

    print(f'CLEANUP_VERCEL v2 (libgomp fix - 9671aa7)')
    print(f'Site-packages: {sitepkgs}')
    total_before = dir_size(sitepkgs)
    print(f'Total BEFORE: {total_before / 1e6:.1f} MB\n')

    # -- large package size report --
    print('--- Package size report (pre-cleanup) ---')
    for pkg in sorted(os.listdir(sitepkgs)):
        pkg_path = os.path.join(sitepkgs, pkg)
        if os.path.isdir(pkg_path) and not pkg.startswith('_') and not pkg.endswith('.dist-info') and not pkg.endswith('.egg-info'):
            sz = dir_size(pkg_path)
            if sz > 5 * 1e6:
                print(f'  {sz/1e6:7.1f} MB  {pkg}')
    print()

    total_saved = 0

    # 1. py_mini_racer: remove ALL V8 binaries + ICU data
    racer_dir = os.path.join(sitepkgs, 'py_mini_racer')
    if os.path.isdir(racer_dir):
        for pattern in ['libmini_racer*', 'icudtl.dat', '*.so', '*.dylib', 'v8*']:
            for f in glob.glob(os.path.join(racer_dir, '**', pattern), recursive=True):
                if os.path.isfile(f):
                    sz = os.path.getsize(f)
                    os.remove(f)
                    total_saved += sz
                    print(f'  Removed py_mini_racer/{os.path.basename(f)} ({sz/1e6:.1f} MB)')

    # 2. Remove pip (build tool)
    saved = rm(os.path.join(sitepkgs, 'pip'))
    if saved:
        total_saved += saved
        print(f'  Removed pip ({saved/1e6:.1f} MB)')

    # 3. Remove dist-info for akshare/baostock (prevents Vercel from deferring them)
    for item in os.listdir(sitepkgs):
        if item.endswith('.dist-info') and item.startswith(('akshare', 'baostock')):
            saved = rm(os.path.join(sitepkgs, item))
            if saved:
                total_saved += saved
                print(f'  Removed {item} ({saved/1e6:.1f} MB)')

    # 4. Remove rich, pygments, tabulate (UI libs)
    for pkg in ('rich', 'pygments', 'tabulate'):
        saved = rm(os.path.join(sitepkgs, pkg))
        if saved:
            total_saved += saved
            print(f'  Removed {pkg} ({saved/1e6:.1f} MB)')

    # 4. Remove nvidia CUDA libs (413 MB, GPU training only, not needed for inference)
    for item in os.listdir(sitepkgs):
        if item.startswith('nvidia') or 'nvidia' in item.lower():
            saved = rm(os.path.join(sitepkgs, item))
            if saved:
                total_saved += saved
                print(f'  Removed {item} ({saved/1e6:.1f} MB)')

    # 5. scipy: keep (xgboost's core.py imports scipy.sparse at module level)

    # 6. sklearn: remove tests
    sklearn_dir = os.path.join(sitepkgs, 'sklearn')
    if os.path.isdir(sklearn_dir):
        for item in os.listdir(sklearn_dir):
            lower = item.lower()
            if 'test' in lower or 'example' in lower:
                saved = rm(os.path.join(sklearn_dir, item))
                if saved:
                    total_saved += saved
                    print(f'  Removed sklearn/{item} ({saved/1e6:.1f} MB)')

    # 7. pandas: remove .pyi type stubs, test dirs
    pandas_dir = os.path.join(sitepkgs, 'pandas')
    if os.path.isdir(pandas_dir):
        for root, dirs, files in os.walk(pandas_dir):
            for f in files:
                if f.endswith('.pyi'):
                    fp = os.path.join(root, f)
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    total_saved += sz
            for d in dirs:
                if 'test' in d.lower():
                    saved = rm(os.path.join(root, d))
                    if saved:
                        total_saved += saved
                        print(f'  Removed pandas/.../{d} ({saved/1e6:.1f} MB)')

    # 8. numpy: remove test dirs, C headers (not needed at runtime), .pyi stubs
    numpy_dir = os.path.join(sitepkgs, 'numpy')
    if os.path.isdir(numpy_dir):
        for root, dirs, files in os.walk(numpy_dir):
            for d in dirs:
                if 'test' in d.lower():
                    saved = rm(os.path.join(root, d))
                    if saved:
                        total_saved += saved
                        print(f'  Removed numpy/.../{d} ({saved/1e6:.1f} MB)')
            break
        saved = rm(os.path.join(numpy_dir, 'core', 'include'))
        if saved:
            total_saved += saved
            print(f'  Removed numpy/core/include ({saved/1e6:.1f} MB)')
        # numpy .pyi stubs
        for root, dirs, files in os.walk(numpy_dir):
            for f in files:
                if f.endswith('.pyi'):
                    fp = os.path.join(root, f)
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    total_saved += sz

    # 9. xgboost: strip GPU/CUDA shared libs (keep CPU inference only)
    xgb_dir = os.path.join(sitepkgs, 'xgboost')
    if os.path.isdir(xgb_dir):
        for root, dirs, files in os.walk(xgb_dir):
            for f in files:
                if 'cuda' in f.lower() or 'nccl' in f.lower() or 'gpu' in f.lower():
                    fp = os.path.join(root, f)
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    total_saved += sz
                    print(f'  Removed xgboost/{f} ({sz/1e6:.1f} MB)')
            for d in list(dirs):
                if 'cuda' in d.lower() or 'nccl' in d.lower() or 'gpu' in d.lower():
                    saved = rm(os.path.join(root, d))
                    if saved:
                        total_saved += saved
                        print(f'  Removed xgboost/{d} ({saved/1e6:.1f} MB)')

    # 10. Remove sklearn subpackages not needed for inference
    # Keep: base, utils, metrics, exceptions, preprocessing
    sklearn_dir = os.path.join(sitepkgs, 'sklearn')
    if os.path.isdir(sklearn_dir):
        sklearn_keep = {'__init__.py', 'base', 'utils', 'metrics', 'exceptions', 'preprocessing', '_loss', '_config.py', 'conftest.py'}
        for item in os.listdir(sklearn_dir):
            item_path = os.path.join(sklearn_dir, item)
            base = item.replace('.py', '')
            if base in sklearn_keep or item in sklearn_keep:
                continue
            if os.path.isdir(item_path) or (os.path.isfile(item_path) and item.endswith('.py')):
                saved = rm(item_path) if os.path.isdir(item_path) else None
                if not saved and os.path.isfile(item_path):
                    saved = os.path.getsize(item_path)
                    os.remove(item_path)
                if saved:
                    total_saved += saved
                    print(f'  Removed sklearn/{item} ({saved/1e6:.1f} MB)')

    # 11. Remove all .pyi stubs globally
    for root, dirs, files in os.walk(sitepkgs):
        for f in files:
            if f.endswith('.pyi'):
                fp = os.path.join(root, f)
                total_saved += os.path.getsize(fp)
                os.remove(fp)

    # 11. Remove all __pycache__ and .pyc
    for root, dirs, files in os.walk(sitepkgs):
        for d in list(dirs):
            if d == '__pycache__':
                saved = rm(os.path.join(root, d))
                if saved:
                    total_saved += saved
        for f in files:
            if f.endswith('.pyc'):
                fp = os.path.join(root, f)
                total_saved += os.path.getsize(fp)
                os.remove(fp)

    # 11. Strip .so files in site-packages (debug symbols, 30-50% savings)
    total_saved += strip_so(sitepkgs)

    # 12. Gzip model.pkl files (8-10x smaller, decompressed at runtime)
    import gzip as _gzip
    for root, dirs, files in os.walk(os.getcwd()):
        for f in files:
            if f == 'model.pkl':
                fp = os.path.join(root, f)
                old = os.path.getsize(fp)
                with open(fp, 'rb') as src, _gzip.open(fp + '.gz', 'wb', 9) as dst:
                    dst.writelines(src)
                os.remove(fp)
                new = os.path.getsize(fp + '.gz')
                total_saved += old - new
                print(f'  Gzipped {os.path.relpath(fp)} ({old/1e6:.1f} MB → {new/1e6:.1f} MB)')

    # 13. Remove dead code files
    for dead in ('ml/anti_cheat.py',):
        fp = os.path.join(os.getcwd(), dead)
        s = rm(fp)
        if s:
            total_saved += s
            print(f'  Removed {dead} ({s/1e6:.1f} MB)')

    # 13. Clean xgb_pkgs (xgboost installed separately to avoid nvidia deps)
    xgb_pkgs = os.path.join(os.getcwd(), 'xgb_pkgs')
    if os.path.isdir(xgb_pkgs):
        total_saved += strip_so(xgb_pkgs)
        xgb_dir = os.path.join(xgb_pkgs, 'xgboost')
        if os.path.isdir(xgb_dir):
            # Remove directories (dask, spark, testing - not needed for inference)
            for item in os.listdir(xgb_dir):
                item_path = os.path.join(xgb_dir, item)
                if os.path.isdir(item_path) and item != 'lib':
                    saved = rm(item_path)
                    if saved:
                        total_saved += saved
                        print(f'  Removed xgb_pkgs/xgboost/{item}/ ({saved/1e6:.1f} MB)')
            # Remove .dist-info from xgb_pkgs (metadata not needed)
            for item in os.listdir(xgb_pkgs):
                if item.endswith('.dist-info') or item.endswith('.egg-info'):
                    saved = rm(os.path.join(xgb_pkgs, item))
                    if saved:
                        total_saved += saved
                        print(f'  Removed xgb_pkgs/{item} ({saved/1e6:.1f} MB)')
            # Clean akshare: keep only stock-related modules
            ak_dir = os.path.join(xgb_pkgs, 'akshare')
            if os.path.isdir(ak_dir):
                ak_stock_only = {'__init__.py', 'stock', 'stock_', 'setting', 'utils', 'constants'}
                for item in os.listdir(ak_dir):
                    item_path = os.path.join(ak_dir, item)
                    if os.path.isdir(item_path):
                        keep = False
                        for prefix in ak_stock_only:
                            if item == prefix or item.startswith(prefix):
                                keep = True
                                break
                        if not keep:
                            saved = rm(item_path)
                            if saved:
                                total_saved += saved
                                print(f'  Removed akshare/{item}/ ({saved/1e6:.1f} MB)')
                for item in os.listdir(ak_dir):
                    if item.endswith('.py') and item != '__init__.py':
                        saved = rm(os.path.join(ak_dir, item))
                        if saved:
                            total_saved += saved
                            print(f'  Removed akshare/{item} ({saved/1e6:.1f} MB)')

            # Bundle system libgomp.so (libxgboost.so needs it at runtime on Lambda)
            lib_dir = os.path.join(xgb_dir, 'lib')
            if os.path.isdir(lib_dir):
                import shutil as _sh, ctypes.util as _cu, subprocess as _sp
                _found_libgomp = []
                _p = _cu.find_library('gomp')
                if _p and os.path.exists(_p):
                    _found_libgomp.append(os.path.realpath(_p))
                try:
                    _out = _sp.run(['ldconfig', '-p'], capture_output=True, text=True, timeout=10)
                    for _line in _out.stdout.split('\n'):
                        if 'libgomp' in _line and '=>' in _line:
                            _fp = _line.split('=>')[-1].strip()
                            if _fp and os.path.exists(_fp):
                                _found_libgomp.append(os.path.realpath(_fp))
                except Exception:
                    pass
                for _root in ('/usr/lib64', '/usr/lib', '/usr/lib/x86_64-linux-gnu', '/lib64', '/lib'):
                    if os.path.isdir(_root):
                        for _f in sorted(os.listdir(_root)):
                            if _f.startswith('libgomp') and '.so' in _f:
                                _fp = os.path.join(_root, _f)
                                if os.path.isfile(_fp):
                                    _found_libgomp.append(os.path.realpath(_fp))
                for _src in set(_found_libgomp):
                    _dst = os.path.join(lib_dir, os.path.basename(_src))
                    if not os.path.exists(_dst):
                        try:
                            _sh.copy2(_src, _dst)
                            _sz = os.path.getsize(_dst)
                            print(f'  Copied libgomp ({os.path.basename(_src)} {_sz/1e6:.1f} MB) to xgb_pkgs/xgboost/lib/')
                        except Exception:
                            pass
            # Binary-patch DT_NEEDED in libxgboost.so to use SONAME instead of hashed name
            _libx_so = os.path.join(lib_dir, 'libxgboost.so')
            if os.path.isfile(_libx_so):
                with open(_libx_so, 'rb') as _fb:
                    _xdata = _fb.read()
                _old_dep = b'libgomp-e985bcbb.so.1.0.0'
                _cnt = _xdata.count(_old_dep)
                if _cnt >= 1:
                    _new_dep = b'libgomp.so.1\0' + b'\0' * (len(_old_dep) - len(b'libgomp.so.1'))
                    _xdata = _xdata.replace(_old_dep, _new_dep)
                    with open(_libx_so, 'wb') as _fb:
                        _fb.write(_xdata)
                    print(f'  Patched DT_NEEDED libgomp-e985bcbb.so.1.0.0 → libgomp.so.1 ({_cnt} occurrences)')
            # Create DT_NEEDED symlinks so libxgboost.so finds its deps by name
            _xgb_real = os.path.join(lib_dir, 'libxgboost.so')
            if not os.path.isfile(_xgb_real):
                _xgb_gz = _xgb_real + '.gz'
                if os.path.isfile(_xgb_gz):
                    import gzip as _gz_tmp
                    _xgb_real = '/tmp/_xgb_dt.so'
                    try:
                        with _gz_tmp.open(_xgb_gz, 'rb') as _fi, open(_xgb_real, 'wb') as _fo:
                            _fo.writelines(_fi)
                    except Exception:
                        _xgb_real = None
                else:
                    _xgb_real = None
            if _xgb_real and os.path.isfile(_xgb_real):
                try:
                    _out = _sp.run(['readelf', '-d', _xgb_real], capture_output=True, text=True, timeout=15)
                    for _line in _out.stdout.split('\n'):
                        if 'NEEDED' in _line and 'lib' in _line and '[' in _line:
                            _need = _line.split('[')[1].split(']')[0]
                            _need_path = os.path.join(lib_dir, _need)
                            if not os.path.exists(_need_path):
                                _stem = _need.replace('-', ' ').replace('_', ' ').split()[0]
                                for _existing in sorted(os.listdir(lib_dir)):
                                    if _existing.startswith(_stem) and '.so' in _existing and not os.path.islink(os.path.join(lib_dir, _existing)):
                                        os.symlink(_existing, _need_path)
                                        print(f'  Symlinked {_need} → {_existing}')
                                        break
                except Exception:
                    pass
            # Remove unnecessary .so helpers, keep runtime deps + libgomp
            if os.path.isdir(lib_dir):
                _keep_prefixes = ('libxgboost', 'libgomp', 'libgcc_s', 'libstdc++')
                for f in list(os.listdir(lib_dir)):
                    if '.so' in f and not any(f.startswith(p) for p in _keep_prefixes):
                        fp = os.path.join(lib_dir, f)
                        if not os.path.islink(fp):
                            sz = os.path.getsize(fp)
                            os.remove(fp)
                            total_saved += sz
                            print(f'  Removed xgb_pkgs/xgboost/lib/{f} ({sz/1e6:.1f} MB)')
                        else:
                            os.remove(fp)
            # Gzip libxgboost.so (~50% size, decompressed at runtime to /tmp)
            lib_so = os.path.join(lib_dir, 'libxgboost.so')
            lib_gz = lib_so + '.gz'
            if os.path.isfile(lib_so) and not os.path.islink(lib_so):
                old = os.path.getsize(lib_so)
                import gzip as _gz
                with open(lib_so, 'rb') as fi, _gz.open(lib_gz, 'wb', 9) as fo:
                    fo.writelines(fi)
                os.remove(lib_so)
                new = os.path.getsize(lib_gz)
                total_saved += old - new
                print(f'  Gzipped xgb_pkgs/xgboost/lib/libxgboost.so ({old/1e6:.1f} MB \u2192 {new/1e6:.1f} MB)')
            elif os.path.isfile(lib_gz):
                print(f'  libxgboost.so.gz exists ({os.path.getsize(lib_gz)/1e6:.1f} MB), skipping gzip')
            # Patch libpath.py (always, even if cached build already has .gz)
            libpath_py = os.path.join(xgb_dir, 'libpath.py')
            if os.path.isfile(libpath_py):
                with open(libpath_py, 'r') as f:
                    content = f.read()
                _DECOMP = r'''
import ctypes as _ct, os as _os, glob as _gl

def _xgb_decompress() -> None:
    lib_dir = _os.path.join(_os.path.dirname(__file__), "lib")
    so_gz = _os.path.join(lib_dir, "libxgboost.so.gz")
    tmp_so = "/tmp/libxgboost.so"
    if _os.path.exists(so_gz) and (
        not _os.path.exists(tmp_so)
        or _os.path.getmtime(tmp_so) < _os.path.getmtime(so_gz)
    ):
        try:
            import gzip as _g
            with _g.open(so_gz, "rb") as fi, open(tmp_so, "wb") as fo:
                fo.writelines(fi)
            _os.chmod(tmp_so, 0o755)
        except Exception:
            pass
    # Pre-load runtime deps from lib/ before xgboost loads
    if _os.path.isdir(lib_dir):
        for _dep in sorted(_gl.glob(_os.path.join(lib_dir, "*.so*"))):
            if "libxgboost" not in _dep:
                try:
                    _ct.CDLL(_dep, mode=_ct.RTLD_GLOBAL)
                except Exception:
                    pass

_xgb_decompress()
'''
                has_patch = '_xgb_decompress' in content
                if not has_patch:
                    pos = content.find('\ndef is_sphinx_build')
                    if pos > 0:
                        content = content[:pos] + _DECOMP + content[pos:]
                    old_line = '    lib_path = [p for p in dll_path if os.path.exists(p) and os.path.isfile(p)]'
                    new_lines = '''    tmp_so = "/tmp/libxgboost.so"
    if os.path.exists(tmp_so) and os.path.isfile(tmp_so):
        return [tmp_so]
''' + old_line
                    if old_line in content and new_lines.split('\n')[0] != old_line:
                        content = content.replace(old_line, new_lines)
                    with open(libpath_py, 'w') as f:
                        f.write(content)
                    print('  Patched xgb_pkgs/xgboost/libpath.py (/tmp decompression)')
                else:
                    print('  libpath.py already patched (cached)')
        # Remove .pyi stubs, __pycache__, and .pyc from xgb_pkgs
        for root, dirs, files in os.walk(xgb_pkgs):
            for d in list(dirs):
                if d == '__pycache__':
                    saved = rm(os.path.join(root, d))
                    if saved:
                        total_saved += saved
            for f in files:
                if f.endswith('.pyc') or f.endswith('.pyi'):
                    fp = os.path.join(root, f)
                    total_saved += os.path.getsize(fp)
                    os.remove(fp)

    print()
    print(f'Total saved: {total_saved / 1e6:.1f} MB')
    total_after = dir_size(sitepkgs)
    print(f'sitepkgs AFTER: {total_after / 1e6:.1f} MB')
    _xgb_size = dir_size(xgb_pkgs) if os.path.isdir(xgb_pkgs) else 0
    if _xgb_size:
        print(f'xgb_pkgs AFTER: {_xgb_size / 1e6:.1f} MB')
    # Source code (root minus data, cache, vendor dirs)
    _root_exclude = {'ml/data', 'ml/data_standalone', '.git', sitepkgs, xgb_pkgs}
    _src_size = 0
    for _item in os.listdir(_PROJECT_ROOT):
        _ip = os.path.join(_PROJECT_ROOT, _item)
        if os.path.isdir(_ip) and _item not in _root_exclude and not _item.startswith('.'):
            _src_size += dir_size(_ip)
        elif os.path.isfile(_ip) and _item.endswith('.py'):
            _src_size += os.path.getsize(_ip)
    print(f'source code:   {_src_size / 1e6:.1f} MB')
    _total_bundle = total_after + _xgb_size + _src_size
    print(f'>>> Bundle size estimate: {_total_bundle / 1e6:.1f} MB <<<')
    print('Cleanup done')


if __name__ == '__main__':
    clean()
