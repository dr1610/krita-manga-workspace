"""Convex frame geometry in document pixels, independent of zoom and DPI."""
import math


def clip_halfplane(poly, a, b, inside):
    def side(p):
        return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
    sign = 1 if side(inside) >= 0 else -1
    result = []
    for p, q in zip(poly, poly[1:]+poly[:1]):
        dp, dq = sign*side(p), sign*side(q)
        if dp >= -1e-7:
            result.append(list(p))
        if (dp >= 0) != (dq >= 0):
            t = dp/(dp-dq)
            result.append([p[0]+t*(q[0]-p[0]), p[1]+t*(q[1]-p[1])])
    return result


def overlap(a, b):
    center = [sum(p[i] for p in b)/len(b) for i in (0, 1)]
    for p, q in zip(b, b[1:]+b[:1]):
        a = clip_halfplane(a, p, q, center)
        if len(a) < 3:
            return 0
    return area(a)


def nearest_edge(poly, point):
    def distance(i):
        a, b = poly[i], poly[(i+1) % len(poly)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        t = max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
        return math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy)
    i = min(range(len(poly)), key=distance)
    return i, distance(i)


def move_edge(poly, index, delta, width, height):
    center = [sum(p[i] for p in poly)/len(poly) for i in (0,1)]
    result = [[0,0],[width,0],[width,height],[0,height]]
    for i, (a, b) in enumerate(zip(poly, poly[1:]+poly[:1])):
        inside = center
        if i == index:
            a = [a[0]+delta[0], a[1]+delta[1]]
            b = [b[0]+delta[0], b[1]+delta[1]]
            inside = [center[0]+delta[0], center[1]+delta[1]]
        result = clip_halfplane(result, a, b, inside)
        if len(result) < 3:
            raise ValueError("境界を移動するとコマが消失します")
    clean = []
    for p in result:
        if not clean or math.dist(clean[-1], p) > 1e-6:
            clean.append(p)
    if len(clean)>1 and math.dist(clean[0],clean[-1])<1e-6:
        clean.pop()
    if len(clean)<3 or area(clean)<4:
        raise ValueError("コマをこれ以上小さくできません")
    return clean


def area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(poly, poly[1:]+poly[:1]))) / 2


def rectangle(a, b, width, height):
    x0, x1 = sorted((max(0, min(width, a[0])), max(0, min(width, b[0]))))
    y0, y1 = sorted((max(0, min(height, a[1])), max(0, min(height, b[1]))))
    if x1-x0 < 2 or y1-y0 < 2:
        raise ValueError("枠をもう少し大きく描いてください")
    return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]


def split(poly, a, b, gap):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if length < 2 or not math.isfinite(gap) or gap < 0:
        raise ValueError("有効な分割線を引いてください")
    def distance(p):
        return (dx*(p[1]-a[1])-dy*(p[0]-a[0])) / length
    def clip(sign):
        result = []
        for p, q in zip(poly, poly[1:]+poly[:1]):
            d0, d1 = sign*distance(p)-gap/2, sign*distance(q)-gap/2
            if d0 >= 0:
                result.append(list(p))
            if (d0 >= 0) != (d1 >= 0):
                t = d0/(d0-d1)
                result.append([p[0]+t*(q[0]-p[0]), p[1]+t*(q[1]-p[1])])
        return result
    parts = [clip(1), clip(-1)]
    if any(len(p) < 3 or area(p) < 4 for p in parts):
        raise ValueError("線がコマを横切っていないか、コマ間隔が広すぎます")
    return parts


def segment_crosses(poly, a, b):
    """Return True when the finite gesture enters and exits a polygon.

    Frame-divider gestures use a finite segment.  ``split`` intentionally uses
    the corresponding infinite line for the actual cut, while this predicate
    prevents distant frames on the same line from being changed.
    """
    dx, dy = b[0]-a[0], b[1]-a[1]
    if math.hypot(dx, dy) < 2:
        return False
    hits = []
    for p, q in zip(poly, poly[1:]+poly[:1]):
        ex, ey = q[0]-p[0], q[1]-p[1]
        denominator = dx*ey-dy*ex
        if abs(denominator) < 1e-9:
            continue
        px, py = p[0]-a[0], p[1]-a[1]
        t = (px*ey-py*ex)/denominator
        u = (px*dy-py*dx)/denominator
        if -1e-7 <= t <= 1+1e-7 and -1e-7 <= u <= 1+1e-7:
            if not any(abs(t-old) < 1e-6 for old in hits):
                hits.append(t)
    return len(hits) >= 2


def contains(poly, point):
    signs = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
             for a,b in zip(poly, poly[1:]+poly[:1])]
    return all(v >= -1e-6 for v in signs) or all(v <= 1e-6 for v in signs)
