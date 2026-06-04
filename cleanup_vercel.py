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


def clean():
    sitepkgs = get_site_packages()
    if not sitepkgs or not os.path.isdir(sitepkgs):
        print(f'Cannot find site-packages, skipping cleanup')
        return

    print(f'Cleaning site-packages: {sitepkgs}')
    total_saved = 0

    # 1. Remove py_mini_racer V8 binary
    racer_dir = os.path.join(sitepkgs, 'py_mini_racer')
    if os.path.isdir(racer_dir):
        for pattern in ['libmini_racer*', 'icudtl.dat']:
            for f in glob.glob(os.path.join(racer_dir, pattern)):
                sz = os.path.getsize(f)
                os.remove(f)
                total_saved += sz
                print(f'  Removed {f} ({sz / 1e6:.1f} MB)')

    # 2. Remove pip (build tool, not needed at runtime)
    pip_dir = os.path.join(sitepkgs, 'pip')
    if os.path.isdir(pip_dir):
        sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(pip_dir) for f in fs)
        shutil.rmtree(pip_dir)
        total_saved += sz
        print(f'  Removed pip ({sz / 1e6:.1f} MB)')

    # 3. Remove rich and pygments (UI libraries, not needed for API)
    for pkg in ('rich', 'pygments'):
        pkg_dir = os.path.join(sitepkgs, pkg)
        if os.path.isdir(pkg_dir):
            sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(pkg_dir) for f in fs)
            shutil.rmtree(pkg_dir)
            total_saved += sz
            print(f'  Removed {pkg} ({sz / 1e6:.1f} MB)')

    # 4. Remove any remaining __pycache__ and .pyc files
    pycache_count = 0
    for root, dirs, files in os.walk(sitepkgs):
        for d in dirs:
            if d == '__pycache__':
                dp = os.path.join(root, d)
                sz = sum(os.path.getsize(os.path.join(dp, f)) for f in os.listdir(dp) if os.path.isfile(os.path.join(dp, f)))
                shutil.rmtree(dp)
                total_saved += sz
                pycache_count += 1
        for f in files:
            if f.endswith('.pyc'):
                fp = os.path.join(root, f)
                total_saved += os.path.getsize(fp)
                os.remove(fp)
    if pycache_count:
        print(f'  Removed {pycache_count} __pycache__ dirs')

    print(f'Total saved: {total_saved / 1e6:.1f} MB')
    print('Cleanup done')


if __name__ == '__main__':
    clean()
