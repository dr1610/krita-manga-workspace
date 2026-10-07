"""Version-specific public model examples; cached separately from model files."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen


def version_id(value):
    value = value.strip()
    if value.isdigit():
        return int(value)
    url = urlparse(value)
    if url.hostname not in ('civitai.com', 'www.civitai.com', 'civitai.red', 'www.civitai.red'):
        return None
    query = parse_qs(url.query).get('modelVersionId', [''])[0]
    if query.isdigit():
        return int(query)
    match = re.fullmatch(r'/api/v1/model-versions/(\d+)/?', url.path)
    return int(match[1]) if match else None


def guessed_version(checkpoint):
    if entry := catalog_entry(checkpoint):
        return entry['version_id']
    match = re.search(r'_(\d+)\.(?:safetensors|ckpt)$', checkpoint, re.I)
    return int(match[1]) if match else None


def catalog_entry(checkpoint):
    name = Path(checkpoint.replace('\\', '/')).name.casefold()
    try:
        entries = json.loads(Path(__file__).with_name('model_catalog.json').read_text(encoding='utf-8'))
        return next((entry for entry in entries if entry['checkpoint'].casefold() == name), {})
    except (OSError, ValueError):
        return {}


def filename_matches(checkpoint, files):
    name = Path(checkpoint.replace('\\', '/')).stem.casefold()
    for file in files:
        stem = Path(file.get('name', '')).stem.casefold()
        if stem and (name == stem or name.startswith(stem + '_')):
            return True
    return False


def cache_key(checkpoint):
    return hashlib.sha256(checkpoint.encode('utf-8')).hexdigest()


def read_preview(cache, checkpoint):
    path = Path(cache) / (cache_key(checkpoint) + '.json')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def fetch_preview(cache, checkpoint, version, manual=False):
    root = Path(cache)
    root.mkdir(parents=True, exist_ok=True)
    request = Request(f'https://civitai.com/api/v1/model-versions/{int(version)}',
                      headers={'User-Agent': 'Krita-Manga-Workspace/1.0'})
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read(4_000_000))
    if int(data['id']) != int(version):
        raise ValueError('取得バージョンが一致しません')
    if not manual and not filename_matches(checkpoint, data.get('files', [])):
        raise ValueError('ファイル名と配布バージョンが一致しません。配布元URLを指定してください')
    result = dict(url=f"https://civitai.com/models/{int(data['modelId'])}?modelVersionId={int(version)}",
                  version=str(data.get('name', '')), model=str(data.get('model', {}).get('name', '')),
                  images=[], manual=manual, errors=[])
    for entry in data.get('images', [])[:8]:
        url = entry.get('url', '')
        if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'image.civitai.com':
            continue
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Krita-Manga-Workspace/1.0'}), timeout=15) as response:
                if not response.headers.get('Content-Type', '').startswith('image/'):
                    continue
                blob = response.read(12_000_001)
            if len(blob) > 12_000_000:
                continue
            filename = hashlib.sha256(url.encode()).hexdigest() + '.img'
            (root / filename).write_bytes(blob)
            result['images'].append(filename)
        except Exception as error:
            result['errors'].append(str(error))
    path = root / (cache_key(checkpoint) + '.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return result
