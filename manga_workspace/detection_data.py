"""Validate and merge independent detector results without overwriting edits."""
import math
from . import state

def merge(target, result, width, height):
    if result.get('width') != width or result.get('height') != height:
        raise ValueError('検出後にページ寸法が変わりました。再検出してください。')
    items = result.get('detections')
    if not isinstance(items, list) or len(items) > 300:
        raise ValueError('検出結果の形式が不正です')
    valid = []
    for item in items:
        kind = item.get('kind')
        box = state.bbox(item.get('bbox'))
        if kind not in ('character', 'text', 'frame') or box[0]+box[2] > width or box[1]+box[3] > height:
            raise ValueError('検出範囲が不正です')
        score = item.get('score')
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('検出スコアが不正です')
        valid.append((kind, box, score))
    def iou(a, b):
        inter = max(0, min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])) * max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
        return inter / max(1, a[2]*a[3]+b[2]*b[3]-inter)
    added = []
    for kind, box, score in valid:
        if any(r['kind'] == kind and iou(r['bbox'], box) >= .7 for r in target['regions']):
            continue
        if len(target['regions']) >= 1000:
            break
        r = state.add_region(target, box)
        type_number = sum(1 for existing in target['regions'] if existing.get('kind') == kind)
        r.update(kind=kind, name={'character':'人物','text':'文字','frame':'コマ'}[kind] + ' %d（自動）' % type_number,
                 detection={'score':score, 'revision':result.get('revision'), 'model_sha256':result.get('model_sha256')})
        added.append(r['id'])
    return added
