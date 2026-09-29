"""Per-user installer. No admin rights, model downloads, or manuscript access."""
import csv
import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def read_text(path):
    return path.read_text(encoding='utf-8-sig') if path.exists() else ''


def setting(text, section, key):
    current = ''
    for line in text.splitlines():
        if line.startswith('['):
            current = line.strip()[1:-1]
        elif current == section and line.startswith(key + '='):
            return line.split('=', 1)[1]
    return None


def update_setting(text, section, key, value):
    """Preserve unrelated KConfig contents, including its unsectioned header."""
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == '[' + section + ']'), None)
    if start is None:
        lines.extend(['', '[' + section + ']', key + '=' + value])
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('[')), len(lines))
        found = [i for i in range(start + 1, end) if lines[i].startswith(key + '=')]
        if found:
            lines[found[0]] = key + '=' + value
            for i in reversed(found[1:]):
                del lines[i]
        else:
            lines.insert(end, key + '=' + value)
    return newline.join(lines) + newline


def default_paths():
    config = Path(os.environ['LOCALAPPDATA']) / 'kritarc'
    resource = setting(read_text(config), '', 'ResourceDirectory')
    root = Path(resource) if resource else Path(os.environ['APPDATA']) / 'krita'
    candidates = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / name / 'bin/krita.exe'
                  for name in ('Krita (x64)', 'Krita')]
    located = shutil.which('krita.exe')
    if located:
        candidates.insert(0, Path(located))
    return next((str(p) for p in candidates if p.is_file()), ''), root, config


def krita_running():
    result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq krita.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Kritaの起動状態を確認できません。再度お試しください。')
    return any(row and row[0].lower() == 'krita.exe'
               for row in csv.reader(io.StringIO(result.stdout.decode('mbcs', errors='replace'))))


def krita_version(exe):
    exe = Path(exe)
    if not exe.is_file() or exe.name.lower() != 'krita.exe':
        raise ValueError('Kritaのkrita.exeを選択してください。')
    dll = ctypes.windll.version
    size = dll.GetFileVersionInfoSizeW(str(exe), None)
    if not size:
        raise ValueError('Kritaのバージョンを読み取れません。')
    buffer = ctypes.create_string_buffer(size)
    if not dll.GetFileVersionInfoW(str(exe), 0, size, buffer):
        raise ValueError('Kritaのバージョンを読み取れません。')
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    if not dll.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)):
        raise ValueError('Kritaのバージョン情報がありません。')
    numbers = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    major, minor, patch = numbers[2] >> 16, numbers[2] & 65535, numbers[3] >> 16
    if (major, minor) < (5, 2):
        raise ValueError('Krita 5.2以降が必要です。')
    return f'{major}.{minor}.{patch}'


def check_comfy(url):
    url = url.strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('接続先を http://127.0.0.1:8188 の形式で入力してください。')
    if any(c in url for c in '\r\n'):
        raise ValueError('接続先に改行は使えません。')
    def request(path):
        with urlopen(url + path, timeout=6) as response:
            return json.loads(response.read(4 * 1024 * 1024))
    stats = request('/system_stats')
    if not isinstance(stats, dict) or 'system' not in stats:
        raise ValueError('ComfyUIの応答を確認できません。接続先を確認してください。')
    info = request('/object_info/CheckpointLoaderSimple')
    names = info['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
    if not isinstance(names, list):
        raise ValueError('モデル一覧を読み取れません。')
    return url, len(names)


def verify_payload(payload):
    manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('同梱ファイル情報が不正です。')
        actual = hashlib.sha256((payload / rel).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('同梱ファイルの検証に失敗しました：' + name)
    return manifest


def install(payload, root, config, server=None):
    """Transaction confined to this plugin and two explicit configuration keys."""
    payload, root, config = Path(payload), Path(root).resolve(), Path(config).resolve()
    manifest = verify_payload(payload)
    plugin_root = root / 'pykrita'
    plugin_root.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    target = plugin_root / 'manga_workspace'
    desktop = plugin_root / 'manga_workspace.desktop'
    if target.is_symlink() or desktop.is_symlink() or target.resolve().parent != plugin_root.resolve():
        raise ValueError('拡張の保存先がリンクになっています。通常の保存先を選んでください。')
    backup = root / 'manga-workspace-backups' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True)
    existed = [target.exists(), desktop.exists(), config.exists()]
    if existed[0]:
        shutil.copytree(target, backup / target.name)
    if existed[1]:
        shutil.copy2(desktop, backup / desktop.name)
    original = config.read_bytes() if existed[2] else b''
    if existed[2]:
        (backup / 'kritarc').write_bytes(original)
    text = original.decode('utf-8-sig')
    text = update_setting(text, 'python', 'enable_manga_workspace', 'true')
    if server:
        text = update_setting(text, 'manga_workspace', 'ai_server', server)
    text = ('\ufeff' if original.startswith(b'\xef\xbb\xbf') else '') + text
    stage = Path(tempfile.mkdtemp(prefix='.manga-install-', dir=str(plugin_root)))
    config_temp = config.with_name(config.name + '.' + uuid.uuid4().hex + '.tmp')
    old = stage / 'previous'
    moved = installed = desktop_written = config_written = False
    try:
        shutil.copytree(payload / 'manga_workspace', stage / 'manga_workspace')
        shutil.copy2(payload / 'manga_workspace.desktop', stage / desktop.name)
        config_temp.write_bytes(text.encode('utf-8'))
        if target.exists():
            target.rename(old)
            moved = True
        (stage / 'manga_workspace').rename(target)
        installed = True
        os.replace(stage / desktop.name, desktop)
        desktop_written = True
        os.replace(config_temp, config)
        config_written = True
    except Exception:
        if installed:
            shutil.rmtree(target)
        if moved:
            old.rename(target)
        if desktop_written:
            if existed[1]:
                shutil.copy2(backup / desktop.name, desktop)
            else:
                desktop.unlink(missing_ok=True)
        if config_written:
            if existed[2]:
                config.write_bytes(original)
            else:
                config.unlink(missing_ok=True)
        raise
    finally:
        config_temp.unlink(missing_ok=True)
        shutil.rmtree(stage)
    (backup / 'restore.txt').write_text(
        f'導入版: {manifest["version"]}\nKritaを閉じてから復元してください。\n'
        f'拡張の復元先: {plugin_root}\n設定の復元先: {config}\n'
        'このフォルダ内の旧ファイルを同じ名前の導入先へ戻します。\n'
        '設定全体を戻すと、導入後に変更したKrita設定も戻ります。\n', encoding='utf-8')
    return backup
