"""Onomatopoeia material generator for the manga workspace."""
import math
from pathlib import Path
from krita import Krita
from PyQt5.QtCore import QByteArray, Qt, QSize, QRectF, QPointF, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QTransform,
)
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QToolButton, QWidget, QScrollArea, QSizePolicy, QFileDialog,
)


SECTION = "manga_workspace_onomatopoeia"
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
    "思考": {"shape": "thought", "tail": "bottom_left"},
    "叫び": {"shape": "spike", "tail": "none"},
    "トゲ": {"shape": "jagged", "tail": "none"},
    "四角": {"shape": "box", "tail": "bottom"},
    "ナレーション": {"shape": "narration", "tail": "none"},
    "電話・機械声": {"shape": "electronic", "tail": "bottom_right", "dashed": True},
}

PRESET_GROUPS = {"描き文字": PRESETS, "吹き出し": BALLOON_PRESETS}


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
        "target": read_setting("target", "selection"),
    }


def save_defaults(values):
    app = Krita.instance()
    for name, value in values.items():
        if isinstance(value, bool):
            value = "true" if value else "false"
        app.writeSetting(SECTION, name, str(value))


def make_icon(size=32):
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
    painter.drawText(0, 0, size, size, Qt.AlignCenter, "ド")
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
    elif shape in ("spike", "jagged"):
        points = []
        count = 32 if shape == "spike" else 22
        for index in range(count):
            angle = math.radians(-90 + index * 360.0 / count)
            outer = index % 2 == 0
            factor = (1.0 if outer else (0.70 if shape == "spike" else 0.82))
            points.append(QPointF(rect.center().x() + math.cos(angle) * rect.width() * 0.5 * factor,
                                  rect.center().y() + math.sin(angle) * rect.height() * 0.5 * factor))
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
    elif shape in ("cloud", "thought"):
        body = QPainterPath()
        for cx, cy, rw, rh in (
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


def _tail_path(rect, direction):
    tail = QPainterPath()
    if direction == "bottom_left":
        points = (QPointF(rect.left() + rect.width() * .27, rect.bottom() - 3),
                  QPointF(rect.left() + rect.width() * .16, rect.bottom() + rect.height() * .22),
                  QPointF(rect.left() + rect.width() * .43, rect.bottom() - 4))
    elif direction == "bottom_right":
        points = (QPointF(rect.left() + rect.width() * .57, rect.bottom() - 4),
                  QPointF(rect.left() + rect.width() * .84, rect.bottom() + rect.height() * .22),
                  QPointF(rect.left() + rect.width() * .73, rect.bottom() - 3))
    elif direction == "bottom":
        points = (QPointF(rect.left() + rect.width() * .43, rect.bottom() - 4),
                  QPointF(rect.center().x(), rect.bottom() + rect.height() * .22),
                  QPointF(rect.left() + rect.width() * .58, rect.bottom() - 4))
    else:
        return tail
    tail.addPolygon(QPolygonF(points)); tail.closeSubpath()
    return tail


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
    body = _balloon_body_path(shape, rect)
    tail_direction = values.get("tail") or preset.get("tail", "none")
    if shape == "thought":
        tail_direction = "none"
    combined = body.united(_tail_path(rect, tail_direction))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    line_width = max(1.0, float(values.get("balloon_width", 4.0)))
    pen = QPen(QColor(values.get("balloon_line", "#111111")), line_width)
    pen.setJoinStyle(Qt.RoundJoin)
    if preset.get("dashed"):
        pen.setStyle(Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(QColor(values.get("balloon_fill", "#ffffff")))
    painter.drawPath(combined)
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
        self.setWindowTitle("オノマトペ設定")
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


class OnomatopoeiaMaterialDialog(QDialog):
    def __init__(self, parent=None, initial_text="", fixed_bounds=None, fixed_parent_node=None):
        super().__init__(parent)
        self.fixed_bounds = list(fixed_bounds) if fixed_bounds else None
        self.fixed_parent_node = fixed_parent_node
        self.setWindowTitle("オノマトペ・吹き出し素材")
        self.setMinimumSize(760, 680)
        self.resize(860, 760)
        values = load_defaults()
        self.current_kind = values.get("kind", "描き文字")
        if self.current_kind not in PRESET_GROUPS:
            self.current_kind = "描き文字"
        group = PRESET_GROUPS[self.current_kind]
        self.current_preset = values["preset"] if values["preset"] in group else next(iter(group))
        self.preset_buttons = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        title = QLabel("オノマトペ・吹き出し素材を作成")
        title.setStyleSheet("font-size:18px;font-weight:700")
        subtitle = QLabel("描き文字または吹き出しを選び、原稿上へ透明な素材レイヤーとして配置します。")
        subtitle.setStyleSheet("color:palette(mid)")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.preview = QLabel()
        self.preview.setMinimumHeight(230)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "QLabel{background:palette(base);border:1px solid palette(mid);border-radius:5px;padding:8px}")
        outer.addWidget(self.preview, 1)

        entry = QHBoxLayout()
        entry.addWidget(QLabel("種類"))
        self.kind = QComboBox(); self.kind.addItems(PRESET_GROUPS); self.kind.setCurrentText(self.current_kind)
        self.kind.setMinimumWidth(110)
        entry.addWidget(self.kind)
        entry.addWidget(QLabel("文字"))
        self.text = QLineEdit(initial_text or "ドン")
        self.text.setPlaceholderText("例：ドン、ザワザワ、キラッ")
        self.text.setMinimumHeight(34)
        self.text.setClearButtonEnabled(True)
        entry.addWidget(self.text, 1)
        outer.addLayout(entry)
        quick = QHBoxLayout()
        for word in ("ドン", "バン", "ゴゴゴ", "ザワザワ", "キラッ", "シーン"):
            button = QPushButton(word)
            button.setFlat(True)
            button.clicked.connect(lambda checked=False, value=word: self.text.setText(value))
            quick.addWidget(button)
        quick.addStretch(1)
        outer.addLayout(quick)

        body = QHBoxLayout()
        body.setSpacing(12)
        style_column = QVBoxLayout()
        style_column.addWidget(QLabel("スタイル"))
        self.preset_grid = QGridLayout()
        self.preset_grid.setSpacing(6)
        preset_widget = QWidget(); preset_widget.setLayout(self.preset_grid)
        preset_scroll = QScrollArea(); preset_scroll.setWidgetResizable(True); preset_scroll.setWidget(preset_widget)
        preset_scroll.setMinimumHeight(285)
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
            self.target.setCurrentIndex(max(0, self.target.findData(values["target"])))
        self.bold = QCheckBox("太字"); self.bold.setChecked(values["bold"])
        self.vertical = QCheckBox("縦書き"); self.vertical.setChecked(values["vertical"])
        self.shadow = QCheckBox("影"); self.shadow.setChecked(values["shadow"])
        self.burst = QCheckBox("集中線"); self.burst.setChecked(values["burst"])
        effects = QHBoxLayout()
        for widget in (self.bold, self.vertical, self.shadow, self.burst): effects.addWidget(widget)

        text_form = QFormLayout()
        text_form.addRow("フォント", self.font)
        text_form.addRow("文字色", self.fill)
        text_form.addRow("縁取り色", self.outline_color)
        text_form.addRow("縁取り幅", self.outline)
        option_column.addWidget(CollapsibleSection("文字と縁取り", text_form, True))

        transform_form = QFormLayout()
        transform_form.addRow("傾き", self.slant)
        transform_form.addRow("回転", self.angle)
        transform_form.addRow("効果", effects)
        option_column.addWidget(CollapsibleSection("変形と効果", transform_form, False))

        self.balloon_fill = ColorButton(values["balloon_fill"])
        self.balloon_line = ColorButton(values["balloon_line"])
        self.balloon_width = QDoubleSpinBox(); self.balloon_width.setRange(0.5, 30); self.balloon_width.setValue(values["balloon_width"]); self.balloon_width.setSuffix(" px")
        self.tail = QComboBox()
        self.tail.addItem("左下", "bottom_left"); self.tail.addItem("中央下", "bottom"); self.tail.addItem("右下", "bottom_right"); self.tail.addItem("なし", "none")
        self.tail.setCurrentIndex(max(0, self.tail.findData(values.get("tail", "bottom_left"))))
        balloon_form = QFormLayout(); balloon_form.addRow("内側", self.balloon_fill); balloon_form.addRow("枠線", self.balloon_line)
        balloon_form.addRow("枠線幅", self.balloon_width); balloon_form.addRow("しっぽ", self.tail)
        self.balloon_section = CollapsibleSection("吹き出し設定", balloon_form, self.current_kind == "吹き出し")
        self.balloon_section.setVisible(self.current_kind == "吹き出し")
        option_column.addWidget(self.balloon_section)

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

        self.remember = QCheckBox("今回の設定を既定値にする")
        outer.addWidget(self.remember)
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
        outer.addLayout(library_row)
        import_row = QHBoxLayout()
        self.import_material_button = QPushButton("取得済みPNG・JPG・SVGを読み込む…")
        self.import_material_button.setToolTip(
            "自分で利用条件を確認して取得した画像素材を、現在の配置先へ透明レイヤーとして追加します")
        self.import_material_button.clicked.connect(self.import_external_material)
        import_row.addWidget(self.import_material_button, 1)
        outer.addLayout(import_row)
        license_note = QLabel(
            "外部素材は同梱・自動取得しません。利用数、改変、商用利用などは各配布元の条件を確認してください。")
        license_note.setWordWrap(True)
        license_note.setStyleSheet("color:palette(mid);font-size:11px")
        outer.addWidget(license_note)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
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
        self.target.currentIndexChanged.connect(self.update_target_hint)
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
                "target": self.target.currentData()})
        return result

    def change_kind(self, kind):
        self.current_kind = kind
        self.current_preset = next(iter(PRESET_GROUPS[kind]))
        self.balloon_section.setVisible(kind == "吹き出し")
        self.rebuild_preset_buttons()
        self.select_preset(self.current_preset)

    def rebuild_preset_buttons(self):
        while self.preset_grid.count():
            item = self.preset_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preset_buttons = {}
        for index, name in enumerate(PRESET_GROUPS[self.current_kind]):
            button = QToolButton(); button.setText(name); button.setCheckable(True)
            button.setChecked(name == self.current_preset)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(116, 58)); button.setMinimumSize(130, 88)
            button.clicked.connect(lambda checked=False, value=name: self.select_preset(value))
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
        elif preset.get("tail"):
            self.tail.setCurrentIndex(max(0, self.tail.findData(preset["tail"])))
        self.update_preview()

    def refresh_preset_icons(self):
        lettering_words = {"衝撃": "ドン", "速度": "シュッ", "不穏": "ゴゴゴ", "小声": "ひそ…", "可愛い": "キラッ",
                           "爆発": "ドカン", "振動": "ガタガタ", "恐怖": "ゾッ", "怒り": "バン！", "叫び": "ワッ",
                           "機械": "ピピッ", "重低音": "ズン", "静寂": "シーン", "きらめき": "キラリ", "コミカル": "ポン"}
        base = self.values()
        for name, button in self.preset_buttons.items():
            preview_values = dict(base)
            preview_values["preset"] = name
            preview_values.update(PRESET_GROUPS[self.current_kind][name])
            image = (render_material(lettering_words.get(name, "文字"), preview_values, 116, 58)
                     if self.current_kind == "描き文字" else render_balloon("あ", preview_values, 116, 58))
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
        text = self.text.text().strip() or "オノマトペ"
        image = (render_material(text, self.values(), 520, 220) if self.current_kind == "描き文字"
                 else render_balloon(text, self.values(), 520, 220))
        self.preview.setPixmap(QPixmap.fromImage(image))

    @staticmethod
    def current_panel(document):
        window = Krita.instance().activeWindow()
        dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        return dock.current() if dock and getattr(dock, "document", None) == document else None

    def target_geometry(self, document):
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
        if self.fixed_parent_node:
            pending = [root]
            while pending:
                candidate = pending.pop()
                if candidate.uniqueId().toString() == self.fixed_parent_node:
                    return candidate
                pending.extend(candidate.childNodes())
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
        if not text:
            QMessageBox.information(self, "オノマトペ素材", "文字を入力してください")
            return
        try:
            bounds, polygon = self.target_geometry(document)
            x, y, width, height = bounds
            image = (render_material(text, self.values(), width, height) if self.current_kind == "描き文字"
                     else render_balloon(text, self.values(), width, height))
            apply_polygon_mask(image, polygon, x, y)
            prefix = "オノマトペ：" if self.current_kind == "描き文字" else "吹き出し："
            self.place_image(document, image, bounds, prefix + text[:24])
            if self.remember.isChecked():
                remembered = self.values()
                if remembered["target"] == "fixed_region":
                    remembered["target"] = "selection"
                save_defaults(remembered)
            self.accept()
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
