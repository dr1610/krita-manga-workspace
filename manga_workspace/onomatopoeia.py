"""Onomatopoeia material generator for the manga workspace."""
import math
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from krita import Krita, Selection
from PyQt5.QtCore import QByteArray, Qt, QSize, QRectF, QPointF, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QTransform,
)
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QToolButton, QWidget, QScrollArea, QSizePolicy, QFileDialog,
)

from .asset_library import EFFECT_PRESETS, WORD_LIBRARY, WORD_CATEGORY_KEYWORDS
from .material_placement import MaterialButton, MaterialPlacement


SECTION = "manga_workspace_onomatopoeia"

class MaterialPreview(QLabel):
    def setPixmap(self, pixmap):
        self.source_pixmap = pixmap
        self.fit_preview()

    def fit_preview(self):
        if hasattr(self, 'source_pixmap'):
            size = self.contentsRect().size() - QSize(16,16)
            super().setPixmap(self.source_pixmap.scaled(size,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_preview()

EXTERNAL_MATERIAL_SITES = (
    ("DDD FONT（擬音・効果音）", "https://dddfont.com/", "https://dddfont.com/term/"),
    ("マンガパーツSTOCK（集中線・効果線）", "https://mangasozai.com/", "https://mangasozai.com/terms"),
    ("フキダシデザイン（吹き出し）", "https://fukidesign.com/", "https://fukidesign.com/terms/"),
)
PRESETS = {
    "衝撃": {"bold": True, "outline": 10.0, "slant": -0.10, "angle": -4.0,
             "shadow": True, "burst": True},
    "速度": {"bold": True, "outline": 7.0, "slant": -0.25, "angle": -8.0,
             "shadow": False, "burst": False},
    "不穏": {"bold": True, "outline": 5.0, "slant": 0.0, "angle": 0.0,
             "shadow": True, "burst": False},
    "小声": {"bold": False, "outline": 2.0, "slant": 0.0, "angle": 0.0,
             "shadow": False, "burst": False},
    "可愛い": {"bold": True, "outline": 6.0, "slant": 0.08, "angle": 3.0,
              "shadow": False, "burst": False},
    "爆発": {"bold": True, "outline": 13.0, "slant": -0.05, "angle": -2.0,
             "shadow": True, "burst": True, "double_outline": True},
    "振動": {"bold": True, "outline": 8.0, "slant": 0.08, "angle": 2.0,
             "shadow": True, "burst": False, "echo": True},
    "恐怖": {"bold": False, "outline": 4.0, "slant": -0.08, "angle": -3.0,
             "shadow": True, "burst": False, "echo": True},
    "怒り": {"bold": True, "outline": 11.0, "slant": -0.18, "angle": -5.0,
             "shadow": True, "burst": True},
    "叫び": {"bold": True, "outline": 9.0, "slant": -0.12, "angle": 0.0,
             "shadow": False, "burst": True, "double_outline": True},
    "機械": {"bold": True, "outline": 5.0, "slant": 0.0, "angle": 0.0,
             "shadow": True, "burst": False, "wide_spacing": True},
    "重低音": {"bold": True, "outline": 14.0, "slant": 0.0, "angle": 0.0,
              "shadow": True, "burst": False, "double_outline": True},
    "静寂": {"bold": False, "outline": 1.5, "slant": 0.0, "angle": 0.0,
             "shadow": False, "burst": False, "wide_spacing": True},
    "きらめき": {"bold": True, "outline": 4.0, "slant": 0.12, "angle": 5.0,
               "shadow": False, "burst": True},
    "コミカル": {"bold": True, "outline": 7.0, "slant": 0.16, "angle": 7.0,
               "shadow": True, "burst": False, "wide_spacing": True},
}

BALLOON_PRESETS = {
    "通常": {"shape": "ellipse", "tail": "bottom_left"},
    "縦長": {"shape": "vertical", "tail": "bottom"},
    "角丸": {"shape": "rounded", "tail": "bottom_right"},
    "雲形": {"shape": "cloud", "tail": "bottom_left"},
    "波形": {"shape": "wave", "tail": "bottom_left"},
    "思考": {"shape": "thought", "tail": "bottom_left"},
    "爆発": {"shape": "spike", "tail": "none"},
    "叫び": {"shape": "spike", "tail": "none"},
    "トゲ": {"shape": "jagged", "tail": "none"},
    "四角": {"shape": "box", "tail": "none"},
    "フラッシュ": {"shape": "flash", "tail": "none"},
    "ウニフラッシュ": {"shape": "uni_flash", "tail": "none"},
    "ナレーション": {"shape": "narration", "tail": "none"},
    "電話・機械声": {"shape": "electronic", "tail": "bottom_right", "dashed": True},
}

PRESET_GROUPS = {"描き文字": PRESETS, "吹き出し": BALLOON_PRESETS, "効果線": EFFECT_PRESETS}


def read_setting(name, default):
    return Krita.instance().readSetting(SECTION, name, str(default))


def default_font_family():
    available = set(QFontDatabase().families())
    for family in ("源暎アンチック", "Noto Sans CJK JP", "Yu Gothic", "Meiryo"):
        if family in available:
            return family
    return QFont().family()


def load_defaults():
    return {
        "kind": read_setting("kind", "描き文字"),
        "preset": read_setting("preset", "衝撃"),
        "font": read_setting("font", default_font_family()),
        "fill": read_setting("fill", "#111111"),
        "outline_color": read_setting("outline_color", "#ffffff"),
        "outline": float(read_setting("outline", "10")),
        "slant": float(read_setting("slant", "-0.10")),
        "angle": float(read_setting("angle", "-4")),
        "bold": read_setting("bold", "true").lower() == "true",
        "vertical": read_setting("vertical", "false").lower() == "true",
        "shadow": read_setting("shadow", "true").lower() == "true",
        "burst": read_setting("burst", "true").lower() == "true",
        "balloon_fill": read_setting("balloon_fill", "#ffffff"),
        "balloon_line": read_setting("balloon_line", "#111111"),
        "balloon_width": float(read_setting("balloon_width", "4")),
        "tail": read_setting("tail", "bottom_left"),
        "tail_length": float(read_setting("tail_length", "28")),
        "tail_width": float(read_setting("tail_width", "22")),
        "effect_density": int(read_setting("effect_density", "36")),
        "effect_width": float(read_setting("effect_width", "3")),
        "effect_color": read_setting("effect_color", "#111111"),
        "target": read_setting("target", "selection"),
    }


def save_defaults(values):
    app = Krita.instance()
    for name, value in values.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        app.writeSetting(SECTION, name, str(value))


def make_icon(size=32, label="ド"):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#202020"), max(1, size // 14)))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 5, 5)
    font = QFont(default_font_family(), max(9, size // 2))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(0, 0, size, size, Qt.AlignCenter, label)
    painter.end()
    return QIcon(pixmap)


def text_path(text, font, vertical=False):
    path = QPainterPath()
    if vertical:
        y = 0.0
        line_height = max(1.0, font.pixelSize() * 1.05)
        for character in text.replace("\n", ""):
            item = QPainterPath()
            item.addText(0, 0, font, character)
            bounds = item.boundingRect()
            transform = QTransform()
            transform.translate(-bounds.center().x(), y - bounds.top())
            path.addPath(transform.map(item))
            y += line_height
    else:
        path.addText(0, 0, font, text)
    bounds = path.boundingRect()
    transform = QTransform()
    transform.translate(-bounds.left(), -bounds.top())
    return transform.map(path)


def render_material(text, values, width, height):
    width, height = max(32, int(width)), max(32, int(height))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    font = QFont(values["font"])
    font.setPixelSize(max(18, int(height * (0.48 if not values["vertical"] else 0.18))))
    font.setBold(bool(values["bold"]))
    spacing = 118 if values.get("wide_spacing") else (92 if values["preset"] == "衝撃" else 100)
    font.setLetterSpacing(QFont.PercentageSpacing, spacing)
    path = text_path(text, font, bool(values["vertical"]))
    shear = QTransform()
    shear.shear(float(values["slant"]), 0.0)
    path = shear.map(path)
    bounds = path.boundingRect()
    # Keep thick production outlines from collapsing small preset thumbnails.
    margin = min(max(6.0, float(values["outline"]) * 3.0), min(width, height) * 0.28)
    fit = min((width - margin * 2) / max(1.0, bounds.width()),
              (height - margin * 2) / max(1.0, bounds.height()))
    fit = max(0.02, fit * (0.82 if abs(float(values["angle"])) > 5 else 0.92))
    scale = QTransform()
    scale.scale(fit, fit)
    path = scale.map(path)
    bounds = path.boundingRect()

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(width / 2.0, height / 2.0)
    painter.rotate(float(values["angle"]))
    painter.translate(-bounds.center().x(), -bounds.center().y())
    stroke_width = min(float(values["outline"]), min(width, height) * 0.12)

    if values["burst"]:
        painter.save()
        painter.translate(bounds.center())
        radius = max(bounds.width(), bounds.height()) * 0.58
        pen = QPen(QColor(values["fill"]), max(1.0, width / 350.0))
        painter.setPen(pen)
        for index in range(18):
            angle = math.radians(index * 20)
            start = radius * 1.08
            end = radius * 1.38
            painter.drawLine(QPointF(math.cos(angle) * start, math.sin(angle) * start),
                             QPointF(math.cos(angle) * end, math.sin(angle) * end))
        painter.restore()

    if values["shadow"]:
        painter.save()
        offset = max(2.0, stroke_width * 0.65)
        painter.translate(offset, offset)
        painter.fillPath(path, QColor(0, 0, 0, 115))
        painter.restore()

    if values.get("echo"):
        painter.save()
        echo_pen = QPen(QColor(0, 0, 0, 65), max(1.0, stroke_width * 0.65))
        echo_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(echo_pen)
        painter.setBrush(Qt.NoBrush)
        for offset in (5.0, 10.0):
            painter.save()
            painter.translate(offset, -offset * 0.35)
            painter.drawPath(path)
            painter.restore()
        painter.restore()

    if values.get("double_outline"):
        outer = QPen(QColor(values["fill"]), max(1.0, stroke_width * 2.1))
        outer.setJoinStyle(Qt.RoundJoin)
        painter.setPen(outer)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    outline = QPen(QColor(values["outline_color"]), max(0.5, stroke_width))
    outline.setJoinStyle(Qt.RoundJoin)
    painter.setPen(outline)
    painter.setBrush(QColor(values["fill"]))
    painter.drawPath(path)
    painter.end()
    return image


def _balloon_body_path(shape, rect):
    path = QPainterPath()
    if shape == "ellipse":
        path.addEllipse(rect)
    elif shape == "vertical":
        narrow = QRectF(rect.center().x() - rect.width() * 0.34, rect.top(),
                        rect.width() * 0.68, rect.height())
        path.addEllipse(narrow)
    elif shape in ("rounded", "electronic"):
        path.addRoundedRect(rect, rect.height() * 0.18, rect.height() * 0.18)
    elif shape in ("box", "narration"):
        path.addRect(rect)
    elif shape == "flash":
        oval = _flash_oval(rect)
        path.addEllipse(oval.adjusted(oval.width() * .14, oval.height() * .14,
                                      -oval.width() * .14, -oval.height() * .14))
    elif shape == "uni_flash":
        oval = _flash_oval(rect)
        path.addEllipse(oval.adjusted(oval.width() * .11, oval.height() * .11,
                                      -oval.width() * .11, -oval.height() * .11))
    elif shape in ("spike", "jagged", "wave"):
        points = []
        count = 48 if shape == "wave" else (32 if shape == "spike" else 22)
        for index in range(count):
            angle = math.radians(-90 + index * 360.0 / count)
            outer = index % 2 == 0
            factor = (1.0 if outer else (0.94 if shape == "wave" else (0.70 if shape == "spike" else 0.82)))
            points.append(QPointF(rect.center().x() + math.cos(angle) * rect.width() * 0.5 * factor,
                                  rect.center().y() + math.sin(angle) * rect.height() * 0.5 * factor))
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
    elif shape in ("cloud", "thought"):
        body = QPainterPath()
        for cx, cy, rw, rh in (
                (0.50, 0.48, 0.62, 0.58),
                (0.20, 0.38, 0.30, 0.48), (0.36, 0.24, 0.35, 0.43),
                (0.57, 0.22, 0.37, 0.43), (0.78, 0.39, 0.32, 0.47),
                (0.67, 0.66, 0.40, 0.48), (0.39, 0.70, 0.48, 0.47),
                (0.18, 0.58, 0.31, 0.42)):
            ellipse = QPainterPath()
            ellipse.addEllipse(QRectF(rect.left() + rect.width() * (cx - rw / 2),
                                      rect.top() + rect.height() * (cy - rh / 2),
                                      rect.width() * rw, rect.height() * rh))
            body = body.united(ellipse)
        path = body
    else:
        path.addEllipse(rect)
    return path


TAIL_DIRECTIONS = {
    "bottom_left": (-0.55, 1.0), "bottom": (0.0, 1.0), "bottom_right": (0.55, 1.0),
    "left": (-1.0, 0.0), "right": (1.0, 0.0),
    "top_left": (-0.55, -1.0), "top": (0.0, -1.0), "top_right": (0.55, -1.0),
}


def _tail_path(rect, direction, width_percent=22.0, length_percent=28.0):
    tail = QPainterPath()
    vector = TAIL_DIRECTIONS.get(direction)
    if not vector:
        return tail
    dx, dy = vector
    magnitude = math.hypot(dx, dy)
    dx, dy = dx / magnitude, dy / magnitude
    radius_x, radius_y = rect.width() * .5, rect.height() * .5
    scale = 1.0 / math.sqrt((dx / max(1.0, radius_x)) ** 2 +
                            (dy / max(1.0, radius_y)) ** 2)
    join = QPointF(rect.center().x() + dx * scale, rect.center().y() + dy * scale)
    tangent_x, tangent_y = -dy, dx
    half_width = min(rect.width(), rect.height()) * max(.04, min(.45, width_percent / 100.0)) * .5
    root_one = QPointF(join.x() + tangent_x * half_width, join.y() + tangent_y * half_width)
    root_two = QPointF(join.x() - tangent_x * half_width, join.y() - tangent_y * half_width)
    length = min(rect.width(), rect.height()) * max(.05, min(.90, length_percent / 100.0))
    tip = QPointF(join.x() + dx * length, join.y() + dy * length)
    tail.addPolygon(QPolygonF((root_one, tip, root_two)))
    tail.closeSubpath()
    return tail


def _ellipse_with_tail(rect, direction, width_percent=22.0, length_percent=28.0):
    """Build a low-node ellipse whose outline directly includes the tail."""
    vector = TAIL_DIRECTIONS.get(direction)
    if not vector:
        path = QPainterPath(); path.addEllipse(rect); return path
    dx, dy = vector
    magnitude = math.hypot(dx, dy); dx, dy = dx / magnitude, dy / magnitude
    center_angle = math.degrees(-math.atan2(dy, dx))
    half_arc = max(5.0, min(32.0, float(width_percent) * .78))
    start_angle = center_angle + half_arc
    path = QPainterPath(); path.arcMoveTo(rect, start_angle)
    root_start = path.currentPosition()
    path.arcTo(rect, start_angle, 360.0 - half_arc * 2.0)
    root_end = path.currentPosition()
    radius_x, radius_y = rect.width() * .5, rect.height() * .5
    scale = 1.0 / math.sqrt((dx / max(1.0, radius_x)) ** 2 +
                            (dy / max(1.0, radius_y)) ** 2)
    join = QPointF(rect.center().x() + dx * scale, rect.center().y() + dy * scale)
    length = min(rect.width(), rect.height()) * max(.05, min(.90, length_percent / 100.0))
    tip = QPointF(join.x() + dx * length, join.y() + dy * length)
    path.lineTo(tip); path.lineTo(root_start)
    path.closeSubpath()
    return path


def _combined_balloon_path(shape, rect, values, tail_direction):
    if shape in ("ellipse", "vertical"):
        return _ellipse_with_tail(rect, tail_direction, float(values.get("tail_width", 22.0)),
                                  float(values.get("tail_length", 28.0)))
    body = _balloon_body_path(shape, rect)
    return body.united(_tail_path(rect, tail_direction, float(values.get("tail_width", 22.0)),
                                  float(values.get("tail_length", 28.0))))


def _flash_oval(rect):
    width = min(rect.width(), rect.height() * .76)
    return QRectF(rect.center().x() - width * .5, rect.top(), width, rect.height())


def _uni_flash_lines(rect, count=144):
    rect = _flash_oval(rect)
    lines = []
    for index in range(count):
        angle = index * 2.0 * math.pi / count
        cs, sn = math.cos(angle), math.sin(angle)
        inner = QPointF(rect.center().x() + cs * rect.width() * .39,
                        rect.center().y() + sn * rect.height() * .39)
        reach = .50 if index % 3 else .47
        outer = QPointF(rect.center().x() + cs * rect.width() * reach,
                        rect.center().y() + sn * rect.height() * reach)
        lines.append((inner, outer))
    return lines


def _flash_lines(rect, count=96):
    rect = _flash_oval(rect)
    lines = []
    for index in range(count):
        angle = math.radians(index * 360.0 / count)
        cs, sn = math.cos(angle), math.sin(angle)
        inner = QPointF(rect.center().x() + cs * rect.width() * .35,
                        rect.center().y() + sn * rect.height() * .35)
        reach = .50 if index % 2 == 0 else .46
        outer = QPointF(rect.center().x() + cs * rect.width() * reach,
                        rect.center().y() + sn * rect.height() * reach)
        lines.append((inner, outer))
    return lines


def render_balloon(text, values, width, height):
    """Render an original local speech balloon without external assets."""
    width, height = max(64, int(width)), max(64, int(height))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    preset = BALLOON_PRESETS.get(values.get("preset"), BALLOON_PRESETS["通常"])
    shape = preset.get("shape", "ellipse")
    margin = max(10.0, float(values.get("balloon_width", 4.0)) * 2.5)
    tail_room = height * 0.15 if preset.get("tail", "none") != "none" else 0
    rect = QRectF(margin, margin, width - margin * 2, height - margin * 2 - tail_room)
    tail_direction = values.get("tail") or preset.get("tail", "none")
    if shape in ("thought", "spike", "jagged", "flash", "uni_flash"):
        tail_direction = "none"
    combined = _combined_balloon_path(shape, rect, values, tail_direction)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    line_width = max(1.0, float(values.get("balloon_width", 4.0)))
    pen = QPen(QColor(values.get("balloon_line", "#111111")), line_width)
    pen.setJoinStyle(Qt.RoundJoin)
    if preset.get("dashed"):
        pen.setStyle(Qt.DashLine)
    painter.setPen(Qt.NoPen if shape in ("flash", "uni_flash") else pen)
    painter.setBrush(QColor(values.get("balloon_line", "#111111")) if shape == "uni_flash"
                     else QColor(values.get("balloon_fill", "#ffffff")))
    painter.drawPath(combined)
    if shape == "flash":
        painter.setPen(QPen(QColor(values.get("balloon_line", "#111111")), max(.5, line_width * .28)))
        for start, end in _flash_lines(rect):
            painter.drawLine(start, end)
    elif shape == "uni_flash":
        painter.setPen(QPen(QColor(values.get("balloon_line", "#111111")), max(.5, line_width * .28)))
        for start, end in _uni_flash_lines(rect):
            painter.drawLine(start, end)
    if shape == "thought":
        painter.drawEllipse(QRectF(rect.left() + rect.width() * .10, rect.bottom() + 4,
                                   rect.width() * .10, rect.height() * .10))
        painter.drawEllipse(QRectF(rect.left() + rect.width() * .03, rect.bottom() + rect.height() * .13,
                                   rect.width() * .055, rect.height() * .055))
    if shape == "electronic":
        inner = rect.adjusted(line_width * 2.2, line_width * 2.2,
                              -line_width * 2.2, -line_width * 2.2)
        painter.drawRoundedRect(inner, inner.height() * .15, inner.height() * .15)

    if text.strip():
        font = QFont(values["font"])
        font.setBold(bool(values.get("bold", False)))
        font.setPixelSize(max(12, int(rect.height() * (0.16 if values.get("vertical") else 0.23))))
        path = text_path(text.strip(), font, bool(values.get("vertical")))
        bounds = path.boundingRect()
        text_rect = rect.adjusted(rect.width() * .15, rect.height() * .16,
                                  -rect.width() * .15, -rect.height() * .16)
        fit = min(text_rect.width() / max(1.0, bounds.width()),
                  text_rect.height() / max(1.0, bounds.height()))
        transform = QTransform(); transform.scale(max(.05, fit), max(.05, fit))
        path = transform.map(path); bounds = path.boundingRect()
        painter.translate(text_rect.center() - bounds.center())
        painter.setPen(Qt.NoPen); painter.setBrush(QColor(values.get("fill", "#111111")))
        painter.drawPath(path)
    painter.end()
    return image


def _svg_path_data(path):
    """Serialize a QPainterPath without flattening its editable cubic curves."""
    parts = []
    index = 0
    while index < path.elementCount():
        element = path.elementAt(index)
        if element.type == QPainterPath.MoveToElement:
            parts.append("M %.3f %.3f" % (element.x, element.y))
            index += 1
        elif element.type == QPainterPath.LineToElement:
            parts.append("L %.3f %.3f" % (element.x, element.y))
            index += 1
        elif element.type == QPainterPath.CurveToElement and index + 2 < path.elementCount():
            second = path.elementAt(index + 1)
            end = path.elementAt(index + 2)
            parts.append("C %.3f %.3f %.3f %.3f %.3f %.3f" % (
                element.x, element.y, second.x, second.y, end.x, end.y))
            index += 3
        else:
            index += 1
    return " ".join(parts)


def _svg_document(document, content):
    resolution = max(1.0, float(document.resolution()))
    width_points = document.width() * 72.0 / resolution
    height_points = document.height() * 72.0 / resolution
    return ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"%.4fpt\" height=\"%.4fpt\" "
            "viewBox=\"0 0 %d %d\">%s</svg>" %
            (width_points, height_points, document.width(), document.height(), content))


def balloon_svg(document, values, bounds):
    """Create one editable SVG outline from the united balloon and tail geometry."""
    x, y, width, height = [float(value) for value in bounds]
    preset = BALLOON_PRESETS.get(values.get("preset"), BALLOON_PRESETS["通常"])
    shape = preset.get("shape", "ellipse")
    line_width = max(1.0, float(values.get("balloon_width", 4.0)))
    margin = max(10.0, line_width * 2.5)
    tail_direction = values.get("tail") or preset.get("tail", "none")
    if shape in ("thought", "spike", "jagged", "flash", "uni_flash"):
        tail_direction = "none"
    tail_room = height * .18 if tail_direction != "none" else 0.0
    rect = QRectF(margin, margin, max(8.0, width - margin * 2),
                  max(8.0, height - margin * 2 - tail_room))
    combined = _combined_balloon_path(shape, rect, values, tail_direction)
    transform = QTransform(); transform.translate(x, y)
    combined = transform.map(combined)
    fill = QColor(values.get("balloon_line", "#111111") if shape == "uni_flash"
                  else values.get("balloon_fill", "#ffffff")).name()
    stroke = QColor(values.get("balloon_line", "#111111")).name()
    dash = " stroke-dasharray=\"%.3f %.3f\"" % (line_width * 2.4, line_width * 1.8) if preset.get("dashed") else ""
    shape_stroke = "none" if shape in ("flash", "uni_flash") else stroke
    items = ["<path d=%s fill=%s stroke=%s stroke-width=\"%.3f\" stroke-linejoin=\"round\"%s/>" %
             (quoteattr(_svg_path_data(combined)), quoteattr(fill), quoteattr(shape_stroke), line_width, dash)]
    if shape == "flash":
        items.extend("<path d=\"M %.3f %.3f L %.3f %.3f\" fill=\"none\" stroke=%s stroke-width=\"%.3f\"/>" %
                     (x + start.x(), y + start.y(), x + end.x(), y + end.y(), quoteattr(stroke), max(.5, line_width * .28))
                     for start, end in _flash_lines(rect))
    elif shape == "uni_flash":
        items.extend("<path d=\"M %.3f %.3f L %.3f %.3f\" fill=\"none\" stroke=%s stroke-width=\"%.3f\"/>" %
                     (x + start.x(), y + start.y(), x + end.x(), y + end.y(), quoteattr(stroke), max(.5, line_width * .28))
                     for start, end in _uni_flash_lines(rect))
    if shape == "thought":
        items.append("<ellipse cx=\"%.3f\" cy=\"%.3f\" rx=\"%.3f\" ry=\"%.3f\" fill=%s stroke=%s stroke-width=\"%.3f\"/>" %
                     (x + rect.left() + rect.width() * .15, y + rect.bottom() + rect.height() * .05,
                      rect.width() * .05, rect.height() * .05, quoteattr(fill), quoteattr(stroke), line_width))
        items.append("<ellipse cx=\"%.3f\" cy=\"%.3f\" rx=\"%.3f\" ry=\"%.3f\" fill=%s stroke=%s stroke-width=\"%.3f\"/>" %
                     (x + rect.left() + rect.width() * .06, y + rect.bottom() + rect.height() * .16,
                      rect.width() * .027, rect.height() * .027, quoteattr(fill), quoteattr(stroke), line_width))
    return _svg_document(document, "".join(items))


def balloon_text_svg(document, text, values, bounds):
    x, y, width, height = [float(value) for value in bounds]
    lines = text.splitlines() or [text]
    font_size = max(12.0, min(height * .22 / max(1, len(lines)), width / max(3, max(map(len, lines))) * 1.35))
    family = values.get("font") or default_font_family()
    fill = QColor(values.get("fill", "#111111")).name()
    weight = "700" if values.get("bold") else "400"
    if values.get("vertical"):
        content = ("<text x=\"%.3f\" y=\"%.3f\" text-anchor=\"middle\" writing-mode=\"vertical-rl\" "
                   "font-family=%s font-size=\"%.3f\" font-weight=\"%s\" fill=%s>%s</text>" %
                   (x + width * .5, y + height * .18, quoteattr(family), font_size, weight,
                    quoteattr(fill), escape(text.replace("\n", ""))))
    else:
        line_height = font_size * 1.25
        first_y = y + height * .5 - line_height * (len(lines) - 1) * .5
        spans = []
        for index, line in enumerate(lines):
            spans.append("<tspan x=\"%.3f\" y=\"%.3f\">%s</tspan>" %
                         (x + width * .5, first_y + index * line_height, escape(line)))
        content = ("<text text-anchor=\"middle\" dominant-baseline=\"middle\" font-family=%s "
                   "font-size=\"%.3f\" font-weight=\"%s\" fill=%s>%s</text>" %
                   (quoteattr(family), font_size, weight, quoteattr(fill), "".join(spans)))
    return _svg_document(document, content)


def _edge_point(width, height, angle):
    dx, dy = math.cos(angle), math.sin(angle)
    scale = min(width * .5 / max(.0001, abs(dx)), height * .5 / max(.0001, abs(dy)))
    return QPointF(width * .5 + dx * scale, height * .5 + dy * scale)


def _star_path(center, outer, inner, points=4):
    polygon = []
    for index in range(points * 2):
        angle = math.radians(-90 + index * 180.0 / points)
        radius = outer if index % 2 == 0 else inner
        polygon.append(QPointF(center.x() + math.cos(angle) * radius,
                               center.y() + math.sin(angle) * radius))
    path = QPainterPath(); path.addPolygon(QPolygonF(polygon)); path.closeSubpath()
    return path


def render_effect(values, width, height):
    """Render common manga effect lines procedurally and deterministically."""
    width, height = max(64, int(width)), max(64, int(height))
    image = QImage(width, height, QImage.Format_ARGB32); image.fill(Qt.transparent)
    definition = EFFECT_PRESETS.get(values.get("preset"), EFFECT_PRESETS["集中線"])
    effect = definition["effect"]
    density = max(6, int(values.get("effect_density") or definition.get("density", 30)))
    line_width = max(.5, float(values.get("effect_width", 3.0)))
    color = QColor(values.get("effect_color", "#111111"))
    painter = QPainter(image); painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, line_width); pen.setCapStyle(Qt.RoundCap); painter.setPen(pen); painter.setBrush(Qt.NoBrush)
    cx, cy = width * .5, height * .5

    if effect in ("focus", "radial", "shock"):
        inner_ratio = .34 if effect == "focus" else (.12 if effect == "radial" else .24)
        for index in range(density):
            angle = math.radians(index * 360.0 / density + math.sin(index * 2.31) * 2.4)
            edge = _edge_point(width, height, angle)
            if effect == "shock":
                start = QPointF(cx + math.cos(angle) * min(width, height) * inner_ratio,
                                cy + math.sin(angle) * min(width, height) * inner_ratio)
                middle = QPointF((start.x() + edge.x()) * .5 + math.sin(index * 4.7) * 8,
                                 (start.y() + edge.y()) * .5 + math.cos(index * 3.9) * 8)
                path = QPainterPath(start); path.lineTo(middle); path.lineTo(edge); painter.drawPath(path)
            else:
                ratio = inner_ratio + (index % 5) * .014
                start = QPointF(cx + (edge.x() - cx) * ratio, cy + (edge.y() - cy) * ratio)
                painter.drawLine(start, edge)
    elif effect in ("speed_horizontal", "speed_vertical", "speed_diagonal", "rain"):
        for index in range(density):
            phase = (index + .5) / density
            length = (.28 + ((index * 37) % 65) / 100.0)
            if effect == "speed_horizontal":
                y = height * phase; x = width * (((index * 29) % 23) / 100.0)
                painter.drawLine(QPointF(x, y), QPointF(min(width, x + width * length), y))
            elif effect == "speed_vertical":
                x = width * phase; y = height * (((index * 29) % 23) / 100.0)
                painter.drawLine(QPointF(x, y), QPointF(x, min(height, y + height * length)))
            else:
                x = width * phase - width * .22; y = 0
                dx = width * (.30 if effect == "rain" else .62)
                painter.drawLine(QPointF(x, y), QPointF(x + dx, height))
    elif effect == "flash":
        painter.setBrush(color); painter.setPen(Qt.NoPen)
        painter.drawPath(_star_path(QPointF(cx, cy), min(width, height) * .46,
                                    min(width, height) * .12, max(8, density // 2)))
    elif effect == "sparkle":
        painter.setBrush(color); painter.setPen(Qt.NoPen)
        for index in range(density):
            x = width * (.08 + ((index * 43) % 83) / 100.0)
            y = height * (.08 + ((index * 61) % 83) / 100.0)
            radius = min(width, height) * (.025 + (index % 4) * .009)
            painter.drawPath(_star_path(QPointF(x, y), radius, radius * .18, 4))
    elif effect == "gloom":
        for index in range(density):
            x = width * (index + .5) / density
            end = height * (.34 + ((index * 47) % 55) / 100.0)
            painter.drawLine(QPointF(x, 0), QPointF(x + math.sin(index) * 4, end))
    elif effect == "vibration":
        for index in range(density):
            y = height * (index + .5) / density
            path = QPainterPath(QPointF(0, y))
            for step in range(1, 13):
                x = width * step / 12.0
                path.lineTo(x, y + math.sin(step * 2.3 + index) * height * .018)
            painter.drawPath(path)
    elif effect == "motion_arc":
        for index in range(density):
            inset = index * min(width, height) * .025
            rect = QRectF(-width * .15 + inset, height * .18 + inset,
                          width * 1.15 - inset * 2, height * 1.15 - inset * 2)
            painter.drawArc(rect, 25 * 16, 112 * 16)
    painter.end()
    return image


def load_external_material(path, maximum=4096):
    """Load a user-selected raster/SVG without downloading or bundling assets."""
    suffix = Path(path).suffix.lower()
    if suffix == ".svg":
        try:
            from PyQt5.QtSvg import QSvgRenderer
        except ImportError as error:
            raise ValueError("このKrita環境ではSVG読込機能を利用できません。PNGを使用してください。") from error
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            raise ValueError("SVG素材を読み込めませんでした")
        size = renderer.defaultSize()
        width, height = max(1, size.width()), max(1, size.height())
        scale = min(1.0, float(maximum) / max(width, height))
        image = QImage(max(1, int(width * scale)), max(1, int(height * scale)), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return image
    image = QImage(path)
    if image.isNull():
        raise ValueError("画像素材を読み込めませんでした")
    if max(image.width(), image.height()) > maximum:
        image = image.scaled(maximum, maximum, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image.convertToFormat(QImage.Format_ARGB32)


def fit_external_material(source, width, height):
    target = QImage(max(1, int(width)), max(1, int(height)), QImage.Format_ARGB32)
    target.fill(Qt.transparent)
    scaled = source.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(target)
    painter.drawImage((target.width() - scaled.width()) // 2,
                      (target.height() - scaled.height()) // 2, scaled)
    painter.end()
    return target


def apply_polygon_mask(image, polygon, offset_x, offset_y):
    if not polygon:
        return
    mask = QImage(image.width(), image.height(), QImage.Format_ARGB32)
    mask.fill(Qt.transparent)
    painter = QPainter(mask)
    painter.setBrush(Qt.white)
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(QPolygonF([QPointF(px - offset_x, py - offset_y) for px, py in polygon]))
    painter.end()
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()


class ColorButton(QPushButton):
    colorChanged = pyqtSignal(QColor)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.clicked.connect(self.choose)
        self.update_label()

    def choose(self):
        selected = QColorDialog.getColor(self.color, self, "色を選択")
        if selected.isValid():
            self.color = selected
            self.update_label()
            self.colorChanged.emit(self.color)

    def update_label(self):
        self.setText(self.color.name())
        contrast = "#ffffff" if self.color.lightness() < 120 else "#111111"
        self.setStyleSheet("background:%s;color:%s" % (self.color.name(), contrast))


class CollapsibleSection(QWidget):
    """Compact native-looking section that works in narrow Krita windows."""
    def __init__(self, title, content_layout, expanded=False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle.setStyleSheet("QToolButton{text-align:left;padding:6px;font-weight:600}")
        self.content = QWidget()
        self.content.setLayout(content_layout)
        self.content.setVisible(expanded)
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

    def set_expanded(self, expanded):
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


class OnomatopoeiaSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("漫画表現素材設定")
        values = load_defaults()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox(); self.kind.addItems(PRESET_GROUPS); self.kind.setCurrentText(values.get("kind", "描き文字"))
        self.preset = QComboBox()
        self.kind.currentTextChanged.connect(self.reload_presets)
        self.reload_presets(self.kind.currentText(), values["preset"])
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont(values["font"]))
        self.fill = ColorButton(values["fill"])
        self.outline_color = ColorButton(values["outline_color"])
        self.target = QComboBox()
        self.target.addItem("選択範囲", "selection")
        self.target.addItem("現在のコマ", "current_panel")
        self.target.addItem("ページ中央", "page_center")
        index = self.target.findData(values["target"])
        self.target.setCurrentIndex(max(0, index))
        form.addRow("素材の種類", self.kind)
        form.addRow("既定プリセット", self.preset)
        form.addRow("既定フォント", self.font)
        form.addRow("文字色", self.fill)
        form.addRow("縁取り色", self.outline_color)
        form.addRow("既定の配置先", self.target)
        layout.addLayout(form)
        note = QLabel("設定はこのPCに保存され、原稿画像や文字列は外部送信しません。")
        note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reload_presets(self, kind, selected=None):
        previous = selected or self.preset.currentText()
        self.preset.clear(); self.preset.addItems(PRESET_GROUPS.get(kind, PRESETS))
        if previous in PRESET_GROUPS.get(kind, {}):
            self.preset.setCurrentText(previous)

    def save(self):
        current = load_defaults()
        current.update({"kind": self.kind.currentText(), "preset": self.preset.currentText(), "font": self.font.currentFont().family(),
                        "fill": self.fill.color.name(), "outline_color": self.outline_color.color.name(),
                        "target": self.target.currentData()})
        current.update(PRESET_GROUPS[self.kind.currentText()][self.preset.currentText()])
        save_defaults(current)
        self.accept()


class MaterialEditorMixin:
    def done(self, result):
        if getattr(self, 'embedded', False):
            if hasattr(self, 'placement'):
                self.placement.cancel()
            return
        super().done(result)

    def reject(self):
        if getattr(self, 'embedded', False):
            if hasattr(self, 'placement'):
                self.placement.cancel()
            return
        super().reject()

    def __init__(self, parent=None, initial_text="", fixed_bounds=None, fixed_parent_node=None,
                 initial_kind=None, embedded=False):
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.fixed_bounds = list(fixed_bounds) if fixed_bounds else None
        self.fixed_parent_node = fixed_parent_node
        self.library_word_selected = False
        self.setWindowTitle("オノマトペ・吹き出し素材")
        self.setMinimumSize(300, 560) if embedded else self.setMinimumSize(820, 700)
        if not embedded:
            self.resize(960, 820)
        values = load_defaults()
        self.current_kind = initial_kind or values.get("kind", "描き文字")
        if self.current_kind not in PRESET_GROUPS:
            self.current_kind = "描き文字"
        group = PRESET_GROUPS[self.current_kind]
        self.current_preset = values["preset"] if values["preset"] in group else next(iter(group))
        self.preset_buttons = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        title = QLabel("漫画表現素材を作成")
        title.setStyleSheet("font-size:18px;font-weight:700")
        subtitle = QLabel("見本を選んで原稿をクリック、または見本を原稿へドラッグして配置。Escで取消。")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:palette(text)")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.preview = MaterialPreview()
        self.preview.setMinimumHeight(130 if embedded else 190)
        self.preview.setMaximumHeight(180 if embedded else 16777215)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview.setStyleSheet(
            "QLabel{background:#f6f6f6;border:1px solid palette(mid);border-radius:5px;padding:8px}")
        outer.addWidget(self.preview, 1)

        self.kind = QComboBox(); self.kind.addItems(PRESET_GROUPS); self.kind.setCurrentText(self.current_kind)
        self.kind.hide()
        mode_row = QHBoxLayout(); mode_row.setSpacing(6)
        self.mode_group = QButtonGroup(self); self.mode_buttons = {}
        mode_descriptions = {
            "描き文字": "文字・オノマトペ",
            "吹き出し": "会話・心情・ナレーション",
            "効果線": "集中・速度・感情演出",
        }
        for kind in PRESET_GROUPS:
            button = QPushButton(kind + "\n" + mode_descriptions[kind])
            button.setCheckable(True); button.setChecked(kind == self.current_kind)
            button.setMinimumHeight(48)
            button.setStyleSheet("QPushButton{text-align:left;padding:6px 12px;font-weight:600}")
            button.clicked.connect(lambda checked=False, value=kind: self.kind.setCurrentText(value))
            self.mode_group.addButton(button); self.mode_buttons[kind] = button
            mode_row.addWidget(button, 1)
        outer.addLayout(mode_row)

        entry = QHBoxLayout()
        self.text_label = QLabel("文字")
        entry.addWidget(self.text_label)
        self.text = QLineEdit(initial_text)
        self.text.setPlaceholderText("例：ドン、ザワザワ、キラッ")
        self.text.setMinimumHeight(34)
        self.text.setClearButtonEnabled(True)
        entry.addWidget(self.text, 1)
        outer.addLayout(entry)

        self.recent_words = tuple(filter(None, read_setting("recent_words", "").split("|")))
        word_layout = QVBoxLayout(); word_layout.setContentsMargins(4, 4, 4, 4)
        word_tools = QHBoxLayout()
        self.word_category = QComboBox()
        if self.recent_words:
            self.word_category.addItem("最近使った")
        self.word_category.addItems(WORD_LIBRARY)
        self.word_search = QLineEdit(); self.word_search.setPlaceholderText("擬音や場面を検索　例：ドキ、雨、機械")
        word_tools.addWidget(self.word_category, 1); word_tools.addWidget(self.word_search, 2)
        word_layout.addLayout(word_tools)
        self.word_grid = QGridLayout(); self.word_grid.setSpacing(4)
        word_widget = QWidget(); word_widget.setLayout(self.word_grid)
        word_scroll = QScrollArea(); word_scroll.setWidgetResizable(True); word_scroll.setWidget(word_widget)
        word_scroll.setMinimumHeight(92); word_scroll.setMaximumHeight(116)
        word_layout.addWidget(word_scroll)
        self.word_section = CollapsibleSection("ことばを用途から選ぶ", word_layout, True)
        outer.addWidget(self.word_section)

        body = QVBoxLayout() if embedded else QHBoxLayout()
        body.setSpacing(12)
        style_column = QVBoxLayout()
        style_column.addWidget(QLabel("スタイル"))
        self.preset_grid = QGridLayout()
        self.preset_grid.setSpacing(6)
        preset_widget = QWidget(); preset_widget.setLayout(self.preset_grid)
        preset_scroll = QScrollArea(); preset_scroll.setWidgetResizable(True); preset_scroll.setWidget(preset_widget)
        if embedded:
            preset_scroll.takeWidget()
            preset_scroll.deleteLater()
            style_column.addWidget(preset_widget)
        else:
            preset_scroll.setMinimumHeight(225)
            style_column.addWidget(preset_scroll)
        style_column.addStretch(1)
        body.addLayout(style_column, 1)

        option_column = QVBoxLayout()
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont(values["font"]))
        self.fill = ColorButton(values["fill"]); self.outline_color = ColorButton(values["outline_color"])
        self.outline = QDoubleSpinBox(); self.outline.setRange(0, 60); self.outline.setValue(values["outline"]); self.outline.setSuffix(" px")
        self.slant = QDoubleSpinBox(); self.slant.setRange(-0.6, 0.6); self.slant.setSingleStep(0.05); self.slant.setValue(values["slant"])
        self.angle = QDoubleSpinBox(); self.angle.setRange(-45, 45); self.angle.setValue(values["angle"]); self.angle.setSuffix("°")
        self.target = QComboBox(); self.target.addItem("選択範囲", "selection"); self.target.addItem("現在のコマ", "current_panel"); self.target.addItem("ページ中央", "page_center")
        if self.fixed_bounds:
            self.target.insertItem(0, "選択した文字領域", "fixed_region")
            self.target.setCurrentIndex(0)
        else:
            preferred_target = values["target"]
            document = Krita.instance().activeDocument()
            selection = document.selection() if document else None
            has_selection = bool(selection and selection.width() > 0 and selection.height() > 0)
            if preferred_target == "selection" and not has_selection:
                preferred_target = "current_panel" if document and self.current_panel(document) else "page_center"
            self.target.setCurrentIndex(max(0, self.target.findData(preferred_target)))
        self.bold = QCheckBox("太字"); self.bold.setChecked(values["bold"])
        self.vertical = QCheckBox("縦書き"); self.vertical.setChecked(values["vertical"])
        self.shadow = QCheckBox("影"); self.shadow.setChecked(values["shadow"])
        self.burst = QCheckBox("集中線"); self.burst.setChecked(values["burst"])
        effects = QHBoxLayout()
        for widget in (self.bold, self.vertical, self.shadow, self.burst): effects.addWidget(widget)

        text_form = QFormLayout(); self.text_form = text_form
        text_form.addRow("フォント", self.font)
        text_form.addRow("文字色", self.fill)
        self.outline_color_label = QLabel("縁取り色"); self.outline_width_label = QLabel("縁取り幅")
        text_form.addRow(self.outline_color_label, self.outline_color)
        text_form.addRow(self.outline_width_label, self.outline)
        self.text_section = CollapsibleSection("文字と縁取り", text_form, True)
        option_column.addWidget(self.text_section)

        transform_form = QFormLayout()
        transform_form.addRow("傾き", self.slant)
        transform_form.addRow("回転", self.angle)
        transform_form.addRow("効果", effects)
        self.transform_section = CollapsibleSection("文字の変形", transform_form, False)
        option_column.addWidget(self.transform_section)

        self.balloon_fill = ColorButton(values["balloon_fill"])
        self.balloon_line = ColorButton(values["balloon_line"])
        self.balloon_width = QDoubleSpinBox(); self.balloon_width.setRange(0.5, 30); self.balloon_width.setValue(values["balloon_width"]); self.balloon_width.setSuffix(" px")
        self.tail = QComboBox()
        for title, value in (("左下", "bottom_left"), ("中央下", "bottom"), ("右下", "bottom_right"),
                             ("左", "left"), ("右", "right"), ("左上", "top_left"),
                             ("中央上", "top"), ("右上", "top_right"), ("なし", "none")):
            self.tail.addItem(title, value)
        self.tail.setCurrentIndex(max(0, self.tail.findData(values.get("tail", "bottom_left"))))
        self.tail_length = QDoubleSpinBox(); self.tail_length.setRange(5, 90); self.tail_length.setSuffix(" %"); self.tail_length.setValue(values.get("tail_length", 28.0))
        self.tail_width = QDoubleSpinBox(); self.tail_width.setRange(4, 45); self.tail_width.setSuffix(" %"); self.tail_width.setValue(values.get("tail_width", 22.0))
        balloon_form = QFormLayout(); balloon_form.addRow("内側", self.balloon_fill); balloon_form.addRow("枠線", self.balloon_line)
        balloon_form.addRow("枠線幅", self.balloon_width); balloon_form.addRow("しっぽ方向", self.tail)
        balloon_form.addRow("しっぽの長さ", self.tail_length)
        balloon_form.addRow("しっぽの付け根幅", self.tail_width)
        tail_help = QLabel("作成後は吹き出しベクターレイヤーを選び、Kritaの図形編集ツールで尻尾の点を調整できます。")
        tail_help.setWordWrap(True); tail_help.setStyleSheet("color:palette(mid);font-size:11px")
        balloon_form.addRow("", tail_help)
        self.balloon_section = CollapsibleSection("吹き出し設定", balloon_form, self.current_kind == "吹き出し")
        self.balloon_section.setVisible(self.current_kind == "吹き出し")
        option_column.addWidget(self.balloon_section)

        self.effect_color = ColorButton(values["effect_color"])
        self.effect_density = QSpinBox(); self.effect_density.setRange(6, 120); self.effect_density.setValue(values["effect_density"])
        self.effect_width = QDoubleSpinBox(); self.effect_width.setRange(.5, 20); self.effect_width.setSingleStep(.5); self.effect_width.setValue(values["effect_width"]); self.effect_width.setSuffix(" px")
        effect_form = QFormLayout(); effect_form.addRow("線の色", self.effect_color); effect_form.addRow("線の本数・密度", self.effect_density); effect_form.addRow("線の太さ", self.effect_width)
        self.effect_section = CollapsibleSection("効果線設定", effect_form, self.current_kind == "効果線")
        self.effect_section.setVisible(self.current_kind == "効果線")
        option_column.addWidget(self.effect_section)
        initial_uses_text = self.current_kind != "効果線"
        self.text_label.setVisible(initial_uses_text); self.text.setVisible(initial_uses_text)
        self.word_section.setVisible(self.current_kind == "描き文字")
        self.text_section.setVisible(initial_uses_text)
        self.transform_section.setVisible(self.current_kind == "描き文字")
        if self.current_kind == "吹き出し":
            self.text_label.setText("文字（任意）")
            self.text.setPlaceholderText("空のまま作成できます。必要な場合だけ台詞を入力")
            self.text_section.toggle.setText("吹き出し内の文字（任意）")
            for widget in (self.outline_color_label, self.outline_color,
                           self.outline_width_label, self.outline):
                widget.hide()

        placement_form = QFormLayout()
        placement_form.addRow("配置先", self.target)
        self.target_hint = QLabel()
        self.target_hint.setWordWrap(True)
        self.target_hint.setStyleSheet("color:palette(mid)")
        placement_form.addRow("", self.target_hint)
        option_column.addWidget(CollapsibleSection("配置", placement_form, True))
        option_column.addStretch(1)
        body.addLayout(option_column, 1)
        outer.addLayout(body)

        from .user_materials import UserMaterials
        personal_layout = QVBoxLayout()
        self.user_materials = UserMaterials(self)
        personal_layout.addWidget(self.user_materials)
        outer.insertWidget(2, CollapsibleSection("マイ素材 — 登録・選択・配置", personal_layout, False))

        self.remember = QCheckBox("今回の設定を既定値にする")
        outer.addWidget(self.remember)
        external_layout = QVBoxLayout(); external_layout.setContentsMargins(4, 4, 4, 4)
        library_row = QHBoxLayout()
        self.material_site = QComboBox()
        for title, url, terms in EXTERNAL_MATERIAL_SITES:
            self.material_site.addItem(title, url)
        self.material_site.setToolTip("外部素材は各公式サイトから利用者自身で取得します")
        library_row.addWidget(self.material_site, 1)
        self.open_material_site_button = QPushButton("配布元を開く ↗")
        self.open_material_site_button.clicked.connect(self.open_material_site)
        library_row.addWidget(self.open_material_site_button)
        self.open_material_terms_button = QPushButton("利用条件")
        self.open_material_terms_button.clicked.connect(self.open_material_terms)
        library_row.addWidget(self.open_material_terms_button)
        self.material_site.currentIndexChanged.connect(self.update_material_site_actions)
        external_layout.addLayout(library_row)
        import_row = QHBoxLayout()
        self.import_material_button = QPushButton("取得済みPNG・JPG・SVGを読み込む…")
        self.import_material_button.setToolTip(
            "自分で利用条件を確認して取得した画像素材を、現在の配置先へ透明レイヤーとして追加します")
        self.import_material_button.clicked.connect(self.import_external_material)
        import_row.addWidget(self.import_material_button, 1)
        external_layout.addLayout(import_row)
        license_note = QLabel(
            "外部素材は同梱・自動取得しません。利用数、改変、商用利用などは各配布元の条件を確認してください。")
        license_note.setWordWrap(True)
        license_note.setStyleSheet("color:palette(mid);font-size:11px")
        external_layout.addWidget(license_note)
        outer.addWidget(CollapsibleSection("外部で取得した素材を使う", external_layout, False))
        buttons = QDialogButtonBox(QDialogButtonBox.NoButton if embedded else QDialogButtonBox.Cancel)
        self.generate = QPushButton("原稿に素材レイヤーを作成")
        self.generate.setMinimumHeight(40)
        self.generate.setDefault(True)
        self.generate.setStyleSheet("QPushButton{font-weight:700;padding:8px 20px}")
        buttons.addButton(self.generate, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject); self.generate.clicked.connect(self.create_layer)
        outer.addWidget(buttons)
        self.kind.currentTextChanged.connect(self.change_kind)
        self.text.textChanged.connect(self.update_preview)
        self.font.currentFontChanged.connect(self.update_preview)
        self.fill.colorChanged.connect(self.update_preview)
        self.outline_color.colorChanged.connect(self.update_preview)
        self.outline.valueChanged.connect(self.update_preview)
        self.slant.valueChanged.connect(self.update_preview)
        self.angle.valueChanged.connect(self.update_preview)
        self.bold.toggled.connect(self.update_preview)
        self.vertical.toggled.connect(self.update_preview)
        self.shadow.toggled.connect(self.update_preview)
        self.burst.toggled.connect(self.update_preview)
        self.balloon_fill.colorChanged.connect(self.update_preview)
        self.balloon_line.colorChanged.connect(self.update_preview)
        self.balloon_width.valueChanged.connect(self.update_preview)
        self.tail.currentIndexChanged.connect(self.update_preview)
        self.tail_length.valueChanged.connect(self.update_preview)
        self.tail_width.valueChanged.connect(self.update_preview)
        self.effect_color.colorChanged.connect(self.update_preview)
        self.effect_density.valueChanged.connect(self.update_preview)
        self.effect_width.valueChanged.connect(self.update_preview)
        self.word_category.currentTextChanged.connect(self.rebuild_word_buttons)
        self.word_search.textChanged.connect(self.rebuild_word_buttons)
        self.target.currentIndexChanged.connect(self.update_target_hint)
        self.rebuild_word_buttons()
        self.placement = MaterialPlacement(self)
        self.placement_override = None
        self.rebuild_preset_buttons()
        self.update_material_site_actions()
        self.update_target_hint()
        self.update_preview()

    def values(self):
        result = dict(PRESET_GROUPS.get(self.current_kind, {}).get(self.current_preset, {}))
        result.update({"kind": self.current_kind, "preset": self.current_preset, "font": self.font.currentFont().family(),
                "fill": self.fill.color.name(), "outline_color": self.outline_color.color.name(),
                "outline": self.outline.value(), "slant": self.slant.value(), "angle": self.angle.value(),
                "bold": self.bold.isChecked(), "vertical": self.vertical.isChecked(),
                "shadow": self.shadow.isChecked(), "burst": self.burst.isChecked(),
                "balloon_fill": self.balloon_fill.color.name(), "balloon_line": self.balloon_line.color.name(),
                "balloon_width": self.balloon_width.value(), "tail": self.tail.currentData(),
                "tail_length": self.tail_length.value(), "tail_width": self.tail_width.value(),
                "effect_color": self.effect_color.color.name(), "effect_density": self.effect_density.value(),
                "effect_width": self.effect_width.value(),
                "target": self.target.currentData()})
        return result

    def change_kind(self, kind):
        previous_kind = self.current_kind
        self.current_kind = kind
        self.current_preset = next(iter(PRESET_GROUPS[kind]))
        for name, button in self.mode_buttons.items():
            button.setChecked(name == kind)
        uses_text = kind != "効果線"
        self.text_label.setVisible(uses_text); self.text.setVisible(uses_text)
        if kind == "吹き出し":
            self.text_label.setText("文字（任意）")
            self.text.setPlaceholderText("空のまま作成できます。必要な場合だけ台詞を入力")
            if previous_kind == "描き文字" and self.library_word_selected:
                self.text.clear(); self.library_word_selected = False
        elif kind == "描き文字":
            self.text_label.setText("文字")
            self.text.setPlaceholderText("自由入力、または下の候補から選択")
        self.word_section.setVisible(kind == "描き文字")
        self.text_section.setVisible(uses_text)
        balloon_text = kind == "吹き出し"
        self.text_section.toggle.setText("吹き出し内の文字（任意）" if balloon_text else "文字と縁取り")
        for widget in (self.outline_color_label, self.outline_color,
                       self.outline_width_label, self.outline):
            widget.setVisible(not balloon_text)
        self.transform_section.setVisible(kind == "描き文字")
        self.balloon_section.setVisible(kind == "吹き出し")
        self.effect_section.setVisible(kind == "効果線")
        self.balloon_section.toggle.setChecked(kind == "吹き出し")
        self.effect_section.toggle.setChecked(kind == "効果線")
        self.rebuild_preset_buttons()
        self.select_preset(self.current_preset)

    def rebuild_word_buttons(self, *args):
        while self.word_grid.count():
            item = self.word_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.word_search.text().strip().lower()
        if query:
            words = []
            for category, entries in WORD_LIBRARY.items():
                keywords = WORD_CATEGORY_KEYWORDS.get(category, "")
                if query in category.lower() or query in keywords.lower():
                    words.extend(entries)
                else:
                    words.extend(word for word in entries if query in word.lower())
        elif self.word_category.currentText() == "最近使った":
            words = list(self.recent_words)
        else:
            words = list(WORD_LIBRARY.get(self.word_category.currentText(), ()))
        words = list(dict.fromkeys(words))[:36]
        if not words:
            label = QLabel("該当することばがありません。自由入力できます。")
            label.setStyleSheet("color:palette(mid)"); self.word_grid.addWidget(label, 0, 0, 1, 4)
            return
        for index, word in enumerate(words):
            button = MaterialButton(self,word,word=True); button.setText(word); button.setMinimumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            button.setToolTip("クリックして原稿へ配置／原稿へドラッグ")
            button.clicked.connect(lambda checked=False, value=word: self.choose_library_word(value))
            button.clicked.connect(lambda checked=False: self.placement.arm())
            self.word_grid.addWidget(button, index // 6, index % 6)

    def choose_library_word(self, word):
        self.library_word_selected = True
        self.text.setText(word)

    def rebuild_preset_buttons(self):
        while self.preset_grid.count():
            item = self.preset_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preset_buttons = {}
        for index, name in enumerate(PRESET_GROUPS[self.current_kind]):
            button = MaterialButton(self, name); button.setText(name); button.setCheckable(True)
            button.setChecked(name == self.current_preset)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(116, 58)); button.setMinimumSize(130, 88)
            button.clicked.connect(lambda checked=False, value=name: self.select_preset(value))
            button.clicked.connect(lambda checked=False: self.placement.arm())
            button.setToolTip(name + "：クリックして原稿へ配置／原稿へドラッグ")
            self.preset_buttons[name] = button
            self.preset_grid.addWidget(button, index // 2, index % 2)
        self.refresh_preset_icons()

    def select_preset(self, name):
        self.current_preset = name
        for preset_name, button in self.preset_buttons.items():
            button.setChecked(preset_name == name)
        preset = PRESET_GROUPS[self.current_kind].get(name, {})
        if self.current_kind == "描き文字":
            self.bold.setChecked(preset.get("bold", True)); self.outline.setValue(preset.get("outline", 6))
            self.slant.setValue(preset.get("slant", 0)); self.angle.setValue(preset.get("angle", 0))
            self.shadow.setChecked(preset.get("shadow", False)); self.burst.setChecked(preset.get("burst", False))
        elif self.current_kind == "吹き出し" and preset.get("tail"):
            self.tail.setCurrentIndex(max(0, self.tail.findData(preset["tail"])))
        elif self.current_kind == "効果線":
            self.effect_density.setValue(preset.get("density", 30))
        self.update_preview()

    def refresh_preset_icons(self):
        lettering_words = {"衝撃": "ドン", "速度": "シュッ", "不穏": "ゴゴゴ", "小声": "ひそ…", "可愛い": "キラッ",
                           "爆発": "ドカン", "振動": "ガタガタ", "恐怖": "ゾッ", "怒り": "バン！", "叫び": "ワッ",
                           "機械": "ピピッ", "重低音": "ズン", "静寂": "シーン", "きらめき": "キラリ", "コミカル": "ポン"}
        base = self.values()
        for name, button in self.preset_buttons.items():
            button.setProperty('sample_text',lettering_words.get(name,'ドン'))
            preview_values = dict(base)
            preview_values["preset"] = name
            preview_values.update(PRESET_GROUPS[self.current_kind][name])
            if self.current_kind == "描き文字":
                image = render_material(lettering_words.get(name, "文字"), preview_values, 464, 232)
            elif self.current_kind == "吹き出し":
                image = render_balloon("", preview_values, 464, 232)
            else:
                image = render_effect(preview_values, 464, 232)
            image = image.scaled(116,58,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            background = QImage(116,58,QImage.Format_ARGB32)
            background.fill(QColor('#b0b0b0'))
            painter = QPainter(background); painter.drawImage(0,0,image); painter.end()
            image = background
            button.setIcon(QIcon(QPixmap.fromImage(image)))

    def update_target_hint(self, *args):
        hints = {
            "selection": "Canvasで囲んだ範囲へ配置します。最も細かく位置を決められます。",
            "current_panel": "コマ一覧で選択中のコマ内へ収めます。コマ外にはみ出しません。",
            "page_center": "ページ中央へ大きめに配置します。作成後に移動・変形できます。",
            "fixed_region": "MANGA BRIDGE v2形式で登録した文字領域へ正確に配置します。",
        }
        self.target_hint.setText(hints.get(self.target.currentData(), ""))

    def selected_material_site(self):
        index = self.material_site.currentIndex()
        return EXTERNAL_MATERIAL_SITES[index] if 0 <= index < len(EXTERNAL_MATERIAL_SITES) else ("", "", "")

    def update_material_site_actions(self, *args):
        title, url, terms = self.selected_material_site()
        self.open_material_site_button.setEnabled(bool(url))
        self.open_material_terms_button.setEnabled(bool(terms))
        self.open_material_site_button.setToolTip(title + "をブラウザで開きます")
        self.open_material_terms_button.setToolTip("選択した配布元の利用条件を開きます")

    def open_material_site(self):
        QDesktopServices.openUrl(QUrl(self.selected_material_site()[1]))

    def open_material_terms(self):
        terms = self.selected_material_site()[2]
        if terms:
            QDesktopServices.openUrl(QUrl(terms))

    def update_preview(self, *args):
        entered_text = self.text.text().strip()
        text = entered_text or ("オノマトペ" if self.current_kind == "描き文字" else "")
        if self.current_kind == "描き文字":
            image = render_material(text, self.values(), 520, 220)
        elif self.current_kind == "吹き出し":
            image = render_balloon(text, self.values(), 520, 220)
        else:
            image = render_effect(self.values(), 520, 220)
        self.preview.setPixmap(QPixmap.fromImage(image))

    @staticmethod
    def current_panel(document):
        window = Krita.instance().activeWindow()
        dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        return dock.current() if dock and getattr(dock, "document", None) == document else None

    def target_geometry(self, document):
        if getattr(self, 'placement_override', None):
            return self.placement_override[:2]
        mode = self.target.currentData()
        polygon = None
        if mode == "fixed_region" and self.fixed_bounds:
            return list(self.fixed_bounds), polygon
        if mode == "selection":
            selection = document.selection()
            if selection and selection.width() > 0 and selection.height() > 0:
                x, y = max(0, selection.x()), max(0, selection.y())
                right = min(document.width(), selection.x() + selection.width())
                bottom = min(document.height(), selection.y() + selection.height())
                if right > x and bottom > y:
                    return [x, y, right - x, bottom - y], polygon
            raise ValueError("矩形選択ツールで配置範囲を指定してください")
        if mode == "current_panel":
            panel = self.current_panel(document)
            if not panel:
                raise ValueError("コマ一覧で配置先のコマを選択してください")
            polygon = panel.get("polygon")
            xs, ys = [point[0] for point in polygon], [point[1] for point in polygon]
            x, y = max(0, int(min(xs))), max(0, int(min(ys)))
            right, bottom = min(document.width(), int(max(xs))), min(document.height(), int(max(ys)))
            return [x, y, right - x, bottom - y], polygon
        width, height = int(document.width() * 0.68), int(document.height() * 0.26)
        return [(document.width() - width) // 2, (document.height() - height) // 2, width, height], polygon

    def destination_parent(self, document):
        root = document.rootNode()
        override = getattr(self, 'placement_override', None)
        if override:
            from .panels import node_by_id
            return node_by_id(document, override[2]) or root if override[2] else root
        wanted_node = self.fixed_parent_node
        if not wanted_node and self.target.currentData() == "current_panel":
            panel = self.current_panel(document)
            wanted_node = panel.get("node") if panel else None
        if wanted_node:
            pending = [root]
            while pending:
                candidate = pending.pop()
                if candidate.uniqueId().toString() == wanted_node:
                    return candidate
                pending.extend(candidate.childNodes())
        if self.target.currentData() == "page_center":
            return root
        node = document.activeNode()
        while node and node != root:
            if node.type() == "grouplayer" and node.name().startswith("コマ"):
                return node
            node = node.parentNode()
        return root

    def create_layer(self):
        document = Krita.instance().activeDocument()
        text = self.text.text().strip()
        if not document:
            QMessageBox.information(self, "オノマトペ素材", "原稿を開いてください")
            return
        if not text and self.current_kind == "描き文字":
            QMessageBox.information(self, "オノマトペ素材", "文字を入力してください")
            return
        try:
            bounds, polygon = self.target_geometry(document)
            x, y, width, height = bounds
            if self.current_kind == "描き文字":
                image = render_material(text, self.values(), width, height)
            elif self.current_kind == "吹き出し":
                self.place_balloon_vector(document, text, self.values(), bounds, polygon)
                image = None
            else:
                image = render_effect(self.values(), width, height)
            if image is not None:
                apply_polygon_mask(image, polygon, x, y)
            if self.current_kind == "描き文字":
                layer_name = "描き文字：" + text[:24]
            elif self.current_kind == "吹き出し":
                layer_name = "吹き出し" + (("：" + text[:24]) if text else "（空）")
            else:
                layer_name = "効果線：" + self.current_preset
            if image is not None:
                self.place_image(document, image, bounds, layer_name)
            if text and self.current_kind == "描き文字":
                recent = [text] + [word for word in self.recent_words if word != text]
                self.recent_words = tuple(recent[:18])
                Krita.instance().writeSetting(SECTION, "recent_words", "|".join(self.recent_words))
            if self.remember.isChecked():
                remembered = self.values()
                if remembered["target"] == "fixed_region":
                    remembered["target"] = "selection"
                save_defaults(remembered)
            if not self.embedded:
                self.accept()
            else:
                self.generate.setText("作成しました")
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(1200, lambda: self.generate.setText("原稿に素材レイヤーを作成"))
        except Exception as error:
            QMessageBox.warning(self, "オノマトペ素材", str(error))

    def import_external_material(self):
        document = Krita.instance().activeDocument()
        if not document:
            QMessageBox.information(self, "画像素材を読み込む", "原稿を開いてください")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "取得済みの画像素材を選択", "", "画像素材 (*.png *.jpg *.jpeg *.svg)")
        if not path:
            return
        try:
            bounds, polygon = self.target_geometry(document)
            x, y, width, height = bounds
            image = fit_external_material(load_external_material(path), width, height)
            apply_polygon_mask(image, polygon, x, y)
            self.place_image(document, image, bounds, "画像素材：" + Path(path).stem[:32])
            if not self.embedded:
                self.accept()
        except Exception as error:
            QMessageBox.warning(self, "画像素材を読み込む", str(error))

    def place_image(self, document, image, bounds, layer_name):
        x, y, width, height = [int(round(value)) for value in bounds]
        layer = document.createNode(layer_name, "paintlayer")
        self.destination_parent(document).addChildNode(layer, None)
        bits = image.constBits()
        bits.setsize(image.byteCount())
        layer.setPixelData(QByteArray(bytes(bits)), x, y, width, height)
        document.setActiveNode(layer)
        document.setModified(True)
        document.refreshProjection()

    def place_balloon_vector(self, document, text, values, bounds, polygon=None):
        """Create an editable balloon group with text above one united body/tail shape."""
        group_name = "吹き出し" + (("：" + text[:24]) if text else "（空）")
        group = document.createGroupLayer(group_name)
        parent = self.destination_parent(document)
        parent.addChildNode(group, None)
        try:
            balloon_layer = document.createVectorLayer("吹き出し本体・尻尾")
            group.addChildNode(balloon_layer, None)
            balloon_shapes = balloon_layer.addShapesFromSvg(balloon_svg(document, values, bounds))
            if not balloon_shapes:
                raise RuntimeError("編集可能な吹き出し形状を作成できませんでした")
            for index, shape in enumerate(balloon_shapes):
                shape.setName("吹き出し形状" if index == 0 else "吹き出し補助形状%d" % index)
                shape.setSelectable(True)

            active = balloon_layer
            if text:
                text_layer = document.createVectorLayer("テキスト：" + text[:24])
                group.addChildNode(text_layer, balloon_layer)
                text_shapes = text_layer.addShapesFromSvg(balloon_text_svg(document, text, values, bounds))
                if not text_shapes:
                    raise RuntimeError("編集可能なテキストを作成できませんでした")
                for shape in text_shapes:
                    shape.setName("吹き出しテキスト")
                    shape.setSelectable(True)
                active = text_layer

            if polygon:
                self.add_polygon_mask(document, group, polygon)
            group.setCollapsed(False)
            document.setActiveNode(active)
            document.setModified(True)
            document.refreshProjection()
        except Exception:
            parent.removeChildNode(group)
            raise

    @staticmethod
    def add_polygon_mask(document, group, polygon):
        x = max(0, int(math.floor(min(point[0] for point in polygon))))
        y = max(0, int(math.floor(min(point[1] for point in polygon))))
        right = min(document.width(), int(math.ceil(max(point[0] for point in polygon))))
        bottom = min(document.height(), int(math.ceil(max(point[1] for point in polygon))))
        width, height = right - x, bottom - y
        if width <= 0 or height <= 0 or width * height > 100_000_000:
            raise ValueError("コマのマスク範囲が不正です")
        mask_image = QImage(width, height, QImage.Format_Grayscale8); mask_image.fill(0)
        painter = QPainter(mask_image); painter.setPen(Qt.NoPen); painter.setBrush(Qt.white)
        painter.drawPolygon(QPolygonF([QPointF(px - x, py - y) for px, py in polygon])); painter.end()
        bits = mask_image.constBits(); bits.setsize(mask_image.byteCount()); raw = bytes(bits)
        stride = mask_image.bytesPerLine()
        packed = b"".join(raw[row * stride:row * stride + width] for row in range(height))
        selection = Selection(); selection.setPixelData(QByteArray(packed), x, y, width, height)
        mask = document.createTransparencyMask("コマ外を隠す")
        group.addChildNode(mask, None); mask.setSelection(selection)


class OnomatopoeiaMaterialDialog(MaterialEditorMixin, QDialog):
    """Standalone modal editor used by fixed AI regions."""
    pass


class OnomatopoeiaMaterialWidget(MaterialEditorMixin, QWidget):
    """Ordinary child widget for docks, rather than a nested dialog window."""
    def __init__(self, parent=None, **kwargs):
        kwargs['embedded'] = True
        super().__init__(parent, **kwargs)
