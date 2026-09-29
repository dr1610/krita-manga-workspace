"""Package separate setup and Krita-import ZIPs; the updater needs the latter."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.7.1-alpha'


def main():
    release = ROOT / 'release'
    exe = release / f'MangaWorkspace-Setup-{VERSION}.exe'
    if not exe.is_file():
        raise RuntimeError('Build the EXE first')
    setup_zip = release / f'MangaWorkspace-Setup-{VERSION}-Windows.zip'
    with zipfile.ZipFile(setup_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, exe.name)
        archive.write(ROOT / 'installer/導入方法.txt', '最初にお読みください・導入方法.txt')
        archive.write(ROOT / 'manga_workspace/manual.html', '使い方.html')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
            archive.write(ROOT / name, name)
        for path in (release / 'installer-build/payload/runtime-licenses').iterdir():
            archive.write(path, 'runtime-licenses/' + path.name)
    plugin_zip = release / f'manga-workspace-{VERSION}.zip'
    with zipfile.ZipFile(plugin_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / 'manga_workspace').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                archive.write(path, path.relative_to(ROOT).as_posix())
        for name in ('manga_workspace.desktop', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
            archive.write(ROOT / name, name)
    paths = [exe, setup_zip, plugin_zip]
    (release / 'SHA256SUMS-0.7.1-alpha.txt').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in paths), encoding='ascii')
    for path in paths:
        print(path.name, path.stat().st_size)


if __name__ == '__main__':
    main()
