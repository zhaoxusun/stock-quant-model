import os
import shutil
import glob
import site
import sys
import gzip as _gzip


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


def clean():
    sitepkgs = get_site_packages()
    if not sitepkgs or not os.path.isdir(sitepkgs):
        print('Cannot find site-packages, skipping cleanup')
        return

    print(f'Site-packages: {sitepkgs}')
    total_before = dir_size(sitepkgs)
    print(f'Total BEFORE: {total_before / 1e6:.1f} MB\n')

    total_saved = 0

    # 1. Remove scipy
    scipy_dir = os.path.join(sitepkgs, 'scipy')
    if os.path.isdir(scipy_dir):
        saved = dir_size(scipy_dir)
        shutil.rmtree(scipy_dir)
        total_saved += saved
        print(f'  Removed scipy ({saved / 1e6:.1f} MB)')

    # 2. Clean xgb_pkgs - GZIP libxgboost.so
    xgb_pkgs = os.path.join(os.getcwd(), 'xgb_pkgs')
    if os.path.isdir(xgb_pkgs):
        xgb_dir = os.path.join(xgb_pkgs, 'xgboost')
        if os.path.isdir(xgb_dir):
            # Remove unnecessary files
            for mod in ('plotting.py', 'dask', 'spark', 'testing', 'federated.py'):
                fp = os.path.join(xgb_dir, mod)
                saved = rm(fp)
                if saved:
                    total_saved += saved
                    print(f'  Removed xgb_pkgs/xgboost/{mod} ({saved / 1e6:.1f} MB)')

            # GZIP libxgboost.so
            lib_dir = os.path.join(xgb_dir, 'lib')
            if os.path.isdir(lib_dir):
                libxgboost = os.path.join(lib_dir, 'libxgboost.so')
                if os.path.isfile(libxgboost):
                    old = os.path.getsize(libxgboost)
                    with open(libxgboost, 'rb') as src, _gzip.open(libxgboost + '.gz', 'wb', 9) as dst:
                        dst.writelines(src)
                    os.remove(libxgboost)
                    new = os.path.getsize(libxgboost + '.gz')
                    total_saved += old - new
                    print(f'  Gzipped libxgboost.so ({old / 1e6:.1f} MB → {new / 1e6:.1f} MB)')

            # 修改 libpath.py，让它优先查找 /tmp/libxgboost.so
            libpath_file = os.path.join(xgb_dir, 'libpath.py')
            if os.path.isfile(libpath_file):
                new_libpath_content = '''import os
import sys
import platform

def find_lib_path():
    """Find the path to xgboost library."""
    # 首先检查 /tmp/libxgboost.so（运行时解压的）
    if os.path.exists('/tmp/libxgboost.so'):
        return ['/tmp/libxgboost.so']

    # 回退到默认路径
    curr_path = os.path.dirname(os.path.abspath(os.path.expanduser(__file__)))
    dll_path = [curr_path]
    if os.name != 'nt':
        dll_path.append(os.path.join(curr_path, '..', 'lib'))
    else:
        dll_path.append(os.path.join(curr_path, '..', 'lib'))
        dll_path.append(os.path.join(curr_path, '..', 'bin'))

    lib_path = []
    for p in dll_path:
        if os.path.isdir(p):
            if os.name == 'nt':
                lib_path += [os.path.join(p, 'xgboost.dll')]
            elif platform.system() == 'Darwin':
                lib_path += [os.path.join(p, 'libxgboost.dylib')]
            else:
                lib_path += [os.path.join(p, 'libxgboost.so')]

    # Find the library
    dll_found = [p for p in lib_path if os.path.exists(p) and os.path.isfile(p)]

    if not dll_found:
        return None

    return dll_found
'''
                with open(libpath_file, 'w') as f:
                    f.write(new_libpath_content)
                print(f'  Modified libpath.py to check /tmp/libxgboost.so first')

        # Remove .dist-info
        for item in os.listdir(xgb_pkgs):
            if item.endswith('.dist-info'):
                saved = rm(os.path.join(xgb_pkgs, item))
                if saved:
                    total_saved += saved
                    print(f'  Removed xgb_pkgs/{item} ({saved / 1e6:.1f} MB)')

    # 3. Gzip model.pkl files
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
                print(f'  Gzipped {os.path.relpath(fp)} ({old / 1e6:.1f} MB → {new / 1e6:.1f} MB)')

    print()
    print(f'Total saved: {total_saved / 1e6:.1f} MB')
    total_after = dir_size(sitepkgs)
    print(f'Total AFTER:  {total_after / 1e6:.1f} MB')
    if os.path.isdir(os.path.join(os.getcwd(), 'xgb_pkgs')):
        print(f'xgb_pkgs AFTER: {dir_size(os.path.join(os.getcwd(), "xgb_pkgs")) / 1e6:.1f} MB')
    print('Cleanup done')


if __name__ == '__main__':
    clean()