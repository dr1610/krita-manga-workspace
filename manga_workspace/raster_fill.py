"""Scanline flood fill on the visible canvas, restricted to the panel mask."""
from PyQt5.QtGui import QImage


def raw(image):
    ptr = image.constBits()
    ptr.setsize(image.byteCount())
    return bytes(ptr)


def flood_mask(image, clip, x, y, tolerance=20):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    w, h = image.width(), image.height()
    pixels, allowed = raw(image), raw(clip)
    stride, clip_stride = image.bytesPerLine(), clip.bytesPerLine()
    result = bytearray(w*h)
    if not (0 <= x < w and 0 <= y < h) or not allowed[y*clip_stride+x]:
        return result
    start = y*stride+x*4
    target = pixels[start:start+3]

    def matches(px, py):
        if result[py*w+px] or not allowed[py*clip_stride+px]:
            return False
        pos = py*stride+px*4
        return all(abs(pixels[pos+i]-target[i]) <= tolerance for i in range(3))

    stack = [(x, y)]
    while stack:
        x, y = stack.pop()
        if not matches(x, y):
            continue
        left = x
        while left > 0 and matches(left-1, y):
            left -= 1
        right = x
        while right+1 < w and matches(right+1, y):
            right += 1
        result[y*w+left:y*w+right+1] = b'\x01'*(right-left+1)
        for ny in (y-1, y+1):
            if 0 <= ny < h:
                span = False
                for nx in range(left, right+1):
                    match = matches(nx, ny)
                    if match and not span:
                        stack.append((nx, ny))
                    span = match
    return result
