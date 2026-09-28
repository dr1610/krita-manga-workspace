"""A small, atomic manifest. Original .kra files are never deleted/reordered on disk."""
import json
import os
from pathlib import Path
from uuid import uuid4


def page(path):
    return {"id": str(uuid4()), "file": str(Path(path).resolve())}


def read(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("pages"), list):
        raise ValueError("未対応のページ管理ファイルです")
    ids, files = set(), set()
    for p in value["pages"]:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not isinstance(p.get("file"), str):
            raise ValueError("ページ情報が壊れています")
        f = Path(p["file"])
        if not f.is_absolute():
            f = Path(path).parent / f
        p["file"] = str(f.resolve())
        if p["id"] in ids or os.path.normcase(p["file"]) in files or f.suffix.lower() != ".kra":
            raise ValueError("重複ページまたは不正な原稿形式です")
        ids.add(p["id"])
        files.add(os.path.normcase(p["file"]))
    if "settings" in value and not isinstance(value["settings"], dict):
        raise ValueError("原稿設定が壊れています")
    return value


def write(path, value):
    path = Path(path)
    portable = {"version": 1, "pages": [dict(p, file=os.path.relpath(p["file"], path.parent))
                                        for p in value["pages"]]}
    if isinstance(value.get("settings"), dict):
        portable["settings"] = value["settings"]
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(portable, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(temp), str(path))
    finally:
        if temp.exists():
            temp.unlink()
