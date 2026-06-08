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

    # 3. Remove dist-info for akshare/baostock/numpy/scipy (prevents Vercel from deferring them)
    for item in os.listdir(sitepkgs):
        if item.endswith('.dist-info') and item.startswith(('akshare', 'baostock', 'numpy', 'scipy')):
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

    # 5. scipy: keep only sparse + special (xgboost needs scipy.special.softmax) + _lib
    scipy_dir = os.path.join(sitepkgs, 'scipy')
    if os.path.isdir(scipy_dir):
        keep_dirs = {'_lib', 'sparse', 'special', 'linalg'}
        keep_files = {'__init__.py', '__config__.py', 'version.py', '_distributor_init.py'}
        for item in os.listdir(scipy_dir):
            item_path = os.path.join(scipy_dir, item)
            if os.path.isdir(item_path) and item not in keep_dirs:
                sz = dir_size(item_path)
                shutil.rmtree(item_path)
                total_saved += sz
                print(f'  Removed scipy/{item} ({sz/1e6:.1f} MB)')
            elif os.path.isfile(item_path) and item not in keep_files and not item.endswith(('.so', '.pyd')):
                sz = os.path.getsize(item_path)
                os.remove(item_path)
                total_saved += sz
                print(f'  Removed scipy/{item} ({sz/1e6:.1f} MB)')

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

    # 10. Remove scipy modules not needed for inference
    scipy_dir = os.path.join(sitepkgs, 'scipy')
    if os.path.isdir(scipy_dir):
        scipy_remove = ['cluster', 'constants', 'fft', 'integrate', 'interpolate', 'io',
                        'ndimage', 'odr', 'optimize', 'signal', 'spatial', 'stats']
        for d in scipy_remove:
            saved = rm(os.path.join(scipy_dir, d))
            if saved:
                total_saved += saved
                print(f'  Removed scipy/{d}/ ({saved/1e6:.1f} MB)')

    # 10b. Remove sklearn subpackages not needed for inference
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
        # Remove stale numpy/scipy from cached xgb_pkgs (they belong in site-packages)
        for _stale in ('numpy', 'scipy', 'numpy.libs', 'scipy.libs'):
            _stale_path = os.path.join(xgb_pkgs, _stale)
            saved = rm(_stale_path)
            if saved:
                total_saved += saved
                print(f'  Removed stale xgb_pkgs/{_stale} ({saved/1e6:.1f} MB)')
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
            # Remove bundled helper .so files except libxgboost.so
            lib_dir = os.path.join(xgb_dir, 'lib')
            if os.path.isdir(lib_dir):
                for f in os.listdir(lib_dir):
                    if f != 'libxgboost.so' and ('.so' in f or f.endswith('.so')):
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
                if os.path.isfile(lib_so) and not os.path.islink(lib_so):
                    old = os.path.getsize(lib_so)
                    so_gz = lib_so + '.gz'
                    import gzip as _gz
                    with open(lib_so, 'rb') as fi, _gz.open(so_gz, 'wb', 9) as fo:
                        fo.writelines(fi)
                    os.remove(lib_so)
                    new = os.path.getsize(so_gz)
                    total_saved += old - new
                    print(f'  Gzipped xgb_pkgs/xgboost/lib/libxgboost.so ({old/1e6:.1f} MB \u2192 {new/1e6:.1f} MB)')
                    # Patch libpath.py to auto-decompress at runtime
                    libpath_py = os.path.join(xgb_dir, 'libpath.py')
                    if os.path.isfile(libpath_py):
                        with open(libpath_py, 'r') as f:
                            content = f.read()
                        _DECOMP = '''
def _xgb_decompress() -> None:
    so_gz = os.path.join(os.path.dirname(__file__), "lib", "libxgboost.so.gz")
    tmp_so = "/tmp/libxgboost.so"
    if os.path.exists(so_gz) and (
        not os.path.exists(tmp_so)
        or os.path.getmtime(tmp_so) < os.path.getmtime(so_gz)
    ):
        try:
            import gzip as _g
            with _g.open(so_gz, "rb") as fi, open(tmp_so, "wb") as fo:
                fo.writelines(fi)
            os.chmod(tmp_so, 0o755)
        except Exception:
            pass

_xgb_decompress()
'''
                        pos = content.find('\ndef is_sphinx_build')
                        if pos > 0:
                            content = content[:pos] + _DECOMP + content[pos:]
                        old_line = '    lib_path = [p for p in dll_path if os.path.exists(p) and os.path.isfile(p)]'
                        new_lines = '''    tmp_so = "/tmp/libxgboost.so"
    if os.path.exists(tmp_so) and os.path.isfile(tmp_so):
        return [tmp_so]
''' + old_line
                        content = content.replace(old_line, new_lines)
                        with open(libpath_py, 'w') as f:
                            f.write(content)
                        print('  Patched xgb_pkgs/xgboost/libpath.py (/tmp decompression)')
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
    print(f'Total AFTER:  {total_after / 1e6:.1f} MB')
    if os.path.isdir(xgb_pkgs):
        print(f'xgb_pkgs AFTER: {dir_size(xgb_pkgs) / 1e6:.1f} MB')
    print('Cleanup done')


if __name__ == '__main__':
    clean()
