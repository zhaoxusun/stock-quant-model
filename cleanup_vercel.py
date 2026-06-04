import os
import shutil
import glob
import site
import sys


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


def report_size(label, path):
    if os.path.exists(path):
        sz = dir_size(path)
        print(f'  [{sz/1e6:7.1f} MB] {label}')
        return sz
    print(f'  [  -- MB] {label} (not found)')
    return 0


def clean():
    sitepkgs = get_site_packages()
    if not sitepkgs or not os.path.isdir(sitepkgs):
        print('Cannot find site-packages, skipping cleanup')
        return

    print(f'Site-packages: {sitepkgs}')
    total_before = dir_size(sitepkgs)
    print(f'Total BEFORE: {total_before / 1e6:.1f} MB')
    print()

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
                    print(f'  Removed {os.path.relpath(f, racer_dir)} ({sz/1e6:.1f} MB)')

    # 2. Remove pip (build tool)
    saved = rm(os.path.join(sitepkgs, 'pip'))
    if saved:
        total_saved += saved
        print(f'  Removed pip ({saved/1e6:.1f} MB)')

    # 3. Remove rich, pygments, tabulate (UI libs)
    for pkg in ('rich', 'pygments', 'tabulate'):
        saved = rm(os.path.join(sitepkgs, pkg))
        if saved:
            total_saved += saved
            print(f'  Removed {pkg} ({saved/1e6:.1f} MB)')

    # 4. scipy: strip everything except scipy.sparse (needed by sklearn)
    scipy_dir = os.path.join(sitepkgs, 'scipy')
    if os.path.isdir(scipy_dir):
        keep = {'__init__.py', '__pycache__', '_lib', 'sparse'}
        for item in os.listdir(scipy_dir):
            item_path = os.path.join(scipy_dir, item)
            if os.path.isdir(item_path) and item not in keep:
                sz = dir_size(item_path)
                shutil.rmtree(item_path)
                total_saved += sz
                print(f'  Removed scipy/{item} ({sz/1e6:.1f} MB)')
            elif os.path.isfile(item_path) and item not in keep:
                sz = os.path.getsize(item_path)
                os.remove(item_path)
                total_saved += sz
                print(f'  Removed scipy/{item} ({sz/1e6:.1f} MB)')

    # 5. sklearn: remove datasets (built-in data), tests
    sklearn_dir = os.path.join(sitepkgs, 'sklearn')
    if os.path.isdir(sklearn_dir):
        for item in os.listdir(sklearn_dir):
            lower = item.lower()
            if 'test' in lower or 'example' in lower:
                saved = rm(os.path.join(sklearn_dir, item))
                if saved:
                    total_saved += saved
                    print(f'  Removed sklearn/{item} ({saved/1e6:.1f} MB)')
        # remove datasets (built-in data is large but likely needed... let's keep it)

    # 6. pandas: remove .pyi type stubs, test dirs
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

    # 7. numpy: remove test dirs
    numpy_dir = os.path.join(sitepkgs, 'numpy')
    if os.path.isdir(numpy_dir):
        for root, dirs, files in os.walk(numpy_dir):
            for d in dirs:
                if 'test' in d.lower():
                    saved = rm(os.path.join(root, d))
                    if saved:
                        total_saved += saved
                        print(f'  Removed numpy/.../{d} ({saved/1e6:.1f} MB)')
            break  # only top-level

    # 8. Remove all .pyi and test dirs across all packages
    for root, dirs, files in os.walk(sitepkgs):
        # remove test dirs
        for d in list(dirs):
            if d == 'tests' or d == 'test':
                saved = rm(os.path.join(root, d))
                if saved:
                    total_saved += saved
            elif d == '__pycache__':
                saved = rm(os.path.join(root, d))
                if saved:
                    total_saved += saved
        # remove .pyc files
        for f in files:
            if f.endswith('.pyc'):
                fp = os.path.join(root, f)
                sz = os.path.getsize(fp)
                os.remove(fp)
                total_saved += sz

    # 9. Remove dist-info RECORD/METADATA (small but every bit helps)
    for item in os.listdir(sitepkgs):
        if item.endswith('.dist-info'):
            for f in ('RECORD', 'METADATA', 'INSTALLER', 'REQUESTED', 'WHEEL'):
                fp = os.path.join(sitepkgs, item, f)
                if os.path.isfile(fp):
                    os.remove(fp)

    print()
    print(f'Total saved: {total_saved / 1e6:.1f} MB')
    total_after = dir_size(sitepkgs)
    print(f'Total AFTER:  {total_after / 1e6:.1f} MB')
    print('Cleanup done')


if __name__ == '__main__':
    clean()
