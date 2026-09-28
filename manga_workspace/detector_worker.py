"""Standalone CPU inference. No Krita, Bridge, network, or shared Python imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path

MODEL_SHA256 = 'fba50583bfaaba3eed33f3eac6ca37be09b8c4882bac05da93f96697010a45b1'
MODEL_REVISION = '717acd6efd5362e830c7d2d8be5f74a7a5f56282'

def detect(image_path, model_path, threshold=0.5):
    import numpy as np
    import onnxruntime as ort
    from PIL import Image
    if not 0 <= threshold <= 1:
        raise ValueError('Threshold must be between 0 and 1')
    with open(model_path, 'rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError('Model checksum mismatch. Reinstall the detector model.')
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(8, os.cpu_count() or 2)
    session = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
    with Image.open(image_path) as source:
        w, h = source.size
        rgba = source.convert('RGBA')
        background = Image.new('RGBA', rgba.size, 'white')
        image = Image.alpha_composite(background, rgba).convert('RGB').resize((1280, 1280), Image.Resampling.BILINEAR)
    tensor = np.asarray(image, dtype=np.float32).transpose(2, 0, 1)[None] / 255
    labels, boxes, scores = session.run(['labels', 'boxes', 'scores'], {
        'images': tensor, 'orig_target_sizes': np.array([[w, h]], dtype=np.int64)})
    items = []
    for label, box, score in zip(labels[0], boxes[0], scores[0]):
        if not np.isfinite(score) or score < threshold or int(label) not in (0, 1, 2) or not np.isfinite(box).all():
            continue
        x1, y1, x2, y2 = [round(float(v)) for v in box]
        x1, x2 = max(0, min(w, x1)), max(0, min(w, x2))
        y1, y2 = max(0, min(h, y1)), max(0, min(h, y2))
        if x2 > x1 and y2 > y1:
            items.append({'kind': ('character', 'text', 'frame')[int(label)],
                          'bbox': [x1, y1, x2-x1, y2-y1], 'score': float(score)})
    return {'width': w, 'height': h, 'model_sha256': digest, 'revision': MODEL_REVISION,
            'threshold': threshold, 'detections': items}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--threshold', type=float, default=.5)
    args = parser.parse_args()
    result = detect(args.image, args.model, args.threshold)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
