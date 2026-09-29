"""Run with Python + PyInstaller on Windows. Builds from this repository only."""
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.7.1-alpha'
BUILD = ROOT / 'release/installer-build'
PAYLOAD = BUILD / 'payload'


def main():
    if PAYLOAD.exists():
        if not PAYLOAD.resolve().is_relative_to((ROOT / 'release').resolve()):
            raise RuntimeError('Invalid build path')
        shutil.rmtree(PAYLOAD)
    PAYLOAD.mkdir(parents=True)
    shutil.copytree(ROOT / 'manga_workspace', PAYLOAD / 'manga_workspace',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    for name in ('manga_workspace.desktop', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'CHANGELOG.md'):
        shutil.copy2(ROOT / name, PAYLOAD / name)
    runtime_licenses = PAYLOAD / 'runtime-licenses'
    runtime_licenses.mkdir()
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime license not found')
    shutil.copy2(python_license, runtime_licenses / 'Python-LICENSE.txt')
    for file in importlib.metadata.files('pyinstaller'):
        if file.name in ('COPYING.txt', 'LICENSE', 'LICENSE.txt'):
            shutil.copy2(file.locate(), runtime_licenses / ('PyInstaller-' + file.name))
    # Tcl/Tk runtime is redistributed by PyInstaller; preserve both licenses.
    for name in ('tcl8.6', 'tk8.6'):
        license_path = Path(sys.base_prefix) / 'tcl' / name / 'license.terms'
        if not license_path.is_file():
            license_path = ROOT / 'installer/licenses' / (name + '-license.txt')
        if not license_path.is_file():
            raise RuntimeError('Tcl/Tk license not found: ' + str(license_path))
        shutil.copy2(license_path, runtime_licenses / (name + '-license.txt'))
    files = {p.relative_to(PAYLOAD).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(PAYLOAD.rglob('*')) if p.is_file()}
    (PAYLOAD / 'manifest.json').write_text(json.dumps({'version': VERSION, 'files': files}, indent=2), encoding='utf-8')
    name = 'MangaWorkspace-Setup-' + VERSION
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', name, '--distpath', str(ROOT / 'release'), '--workpath', str(BUILD / 'work'),
        '--specpath', str(BUILD), '--add-data', str(PAYLOAD) + ';payload',
        str(ROOT / 'installer/setup.py')], check=True)
    exe = ROOT / 'release' / (name + '.exe')
    (ROOT / 'release' / (name + '.sha256')).write_text(hashlib.sha256(exe.read_bytes()).hexdigest() + '  ' + exe.name + '\n', encoding='ascii')
    print(exe)


if __name__ == '__main__':
    main()
