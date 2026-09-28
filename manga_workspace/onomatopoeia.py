"""Onomatopoeia material generator for the manga workspace."""
import math
from krita import Krita
from PyQt5.QtCore import QByteArray, Qt, QSize, QRectF, QPointF
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QTransform,
)
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)


SECTION = "manga_workspace_onomatopoeia"
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
}


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
    font.setLetterSpacing(QFont.PercentageSpacing, 92 if values["preset"] == "衝撃" else 100)
    path = text_path(text, font, bool(values["vertical"]))
    shear = QTransform()
    shear.shear(float(values["slant"]), 0.0)
    path = shear.map(path)
    bounds = path.boundingRect()
    margin = max(16.0, float(values["outline"]) * 4.0)
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
        offset = max(3.0, float(values["outline"]) * 0.65)
        painter.translate(offset, offset)
        painter.fillPath(path, QColor(0, 0, 0, 115))
        painter.restore()

    outline = QPen(QColor(values["outline_color"]), max(0.5, float(values["outline"])))
    outline.setJoinStyle(Qt.RoundJoin)
    painter.setPen(outline)
    painter.setBrush(QColor(values["fill"]))
    painter.drawPath(path)
    painter.end()
    return image


class ColorButton(QPushButton):
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

    def update_label(self):
        self.setText(self.color.name())
        contrast = "#ffffff" if self.color.lightness() < 120 else "#111111"
        self.setStyleSheet("background:%s;color:%s" % (self.color.name(), contrast))


class OnomatopoeiaSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オノマトペ設定")
        values = load_defaults()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox(); self.preset.addItems(PRESETS); self.preset.setCurrentText(values["preset"])
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont(values["font"]))
        self.fill = ColorButton(values["fill"])
        self.outline_color = ColorButton(values["outline_color"])
        self.target = QComboBox()
        self.target.addItem("選択範囲", "selection")
        self.target.addItem("現在のコマ", "current_panel")
        self.target.addItem("ページ中央", "page_center")
        index = self.target.findData(values["target"])
        self.target.setCurrentIndex(max(0, index))
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

    def save(self):
        current = load_defaults()
        current.update({"preset": self.preset.currentText(), "font": self.font.currentFont().family(),
                        "fill": self.fill.color.name(), "outline_color": self.outline_color.color.name(),
                        "target": self.target.currentData()})
        current.update(PRESETS[self.preset.currentText()])
        save_defaults(current)
        self.accept()


class OnomatopoeiaMaterialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オノマトペ素材")
        self.setMinimumWidth(560)
        values = load_defaults()
        outer = QVBoxLayout(self)
        self.text = QLineEdit("ドン")
        self.text.setPlaceholderText("例：ドン、ザワザワ、キラッ")
        outer.addWidget(QLabel("オノマトペ")); outer.addWidget(self.text)
        quick = QHBoxLayout()
        for word in ("ドン", "バン", "ゴゴゴ", "ザワザワ", "キラッ", "シーン"):
            button = QPushButton(word); button.clicked.connect(lambda checked=False, value=word: self.text.setText(value))
            quick.addWidget(button)
        outer.addLayout(quick)

        form = QFormLayout()
        self.preset = QComboBox(); self.preset.addItems(PRESETS); self.preset.setCurrentText(values["preset"])
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont(values["font"]))
        self.fill = ColorButton(values["fill"]); self.outline_color = ColorButton(values["outline_color"])
        self.outline = QDoubleSpinBox(); self.outline.setRange(0, 60); self.outline.setValue(values["outline"]); self.outline.setSuffix(" px")
        self.slant = QDoubleSpinBox(); self.slant.setRange(-0.6, 0.6); self.slant.setSingleStep(0.05); self.slant.setValue(values["slant"])
        self.angle = QDoubleSpinBox(); self.angle.setRange(-45, 45); self.angle.setValue(values["angle"]); self.angle.setSuffix("°")
        self.target = QComboBox(); self.target.addItem("選択範囲", "selection"); self.target.addItem("現在のコマ", "current_panel"); self.target.addItem("ページ中央", "page_center")
        self.target.setCurrentIndex(max(0, self.target.findData(values["target"])))
        self.bold = QCheckBox("太字"); self.bold.setChecked(values["bold"])
        self.vertical = QCheckBox("縦書き"); self.vertical.setChecked(values["vertical"])
        self.shadow = QCheckBox("影"); self.shadow.setChecked(values["shadow"])
        self.burst = QCheckBox("集中線"); self.burst.setChecked(values["burst"])
        effects = QHBoxLayout()
        for widget in (self.bold, self.vertical, self.shadow, self.burst): effects.addWidget(widget)
        form.addRow("プリセット", self.preset); form.addRow("フォント", self.font)
        form.addRow("文字色", self.fill); form.addRow("縁取り色", self.outline_color)
        form.addRow("縁取り幅", self.outline); form.addRow("傾き", self.slant)
        form.addRow("回転", self.angle); form.addRow("効果", effects); form.addRow("配置先", self.target)
        outer.addLayout(form)
        self.preview = QLabel(); self.preview.setMinimumSize(520, 220); self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#d0d0d0;border:1px solid #777")
        outer.addWidget(self.preview)
        self.remember = QCheckBox("今回の設定を既定値にする")
        outer.addWidget(self.remember)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.generate = QPushButton("素材レイヤーを作成")
        buttons.addButton(self.generate, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject); self.generate.clicked.connect(self.create_layer)
        outer.addWidget(buttons)
        self.preset.currentTextChanged.connect(self.apply_preset)
        self.text.textChanged.connect(self.update_preview)
        for widget in (self.font, self.fill, self.outline_color, self.outline, self.slant, self.angle,
                       self.bold, self.vertical, self.shadow, self.burst):
            signal = getattr(widget, "currentFontChanged", None) or getattr(widget, "clicked", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None)
            if signal: signal.connect(self.update_preview)
        self.update_preview()

    def values(self):
        return {"preset": self.preset.currentText(), "font": self.font.currentFont().family(),
                "fill": self.fill.color.name(), "outline_color": self.outline_color.color.name(),
                "outline": self.outline.value(), "slant": self.slant.value(), "angle": self.angle.value(),
                "bold": self.bold.isChecked(), "vertical": self.vertical.isChecked(),
                "shadow": self.shadow.isChecked(), "burst": self.burst.isChecked(),
                "target": self.target.currentData()}

    def apply_preset(self, name):
        preset = PRESETS.get(name, {})
        self.bold.setChecked(preset.get("bold", True)); self.outline.setValue(preset.get("outline", 6))
        self.slant.setValue(preset.get("slant", 0)); self.angle.setValue(preset.get("angle", 0))
        self.shadow.setChecked(preset.get("shadow", False)); self.burst.setChecked(preset.get("burst", False))
        self.update_preview()

    def update_preview(self, *args):
        text = self.text.text().strip() or "オノマトペ"
        image = render_material(text, self.values(), 520, 220)
        self.preview.setPixmap(QPixmap.fromImage(image))

    @staticmethod
    def current_panel(document):
        window = Krita.instance().activeWindow()
        dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        return dock.current() if dock and getattr(dock, "document", None) == document else None

    def target_geometry(self, document):
        mode = self.target.currentData()
        polygon = None
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

    @staticmethod
    def destination_parent(document):
        root = document.rootNode()
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
            image = render_material(text, self.values(), width, height)
            if polygon:
                mask = QImage(width, height, QImage.Format_ARGB32)
                mask.fill(Qt.transparent)
                painter = QPainter(mask)
                painter.setBrush(Qt.white); painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygonF([QPointF(px - x, py - y) for px, py in polygon]))
                painter.end()
                painter = QPainter(image)
                painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                painter.drawImage(0, 0, mask); painter.end()
            layer = document.createNode("オノマトペ：" + text[:24], "paintlayer")
            self.destination_parent(document).addChildNode(layer, None)
            bits = image.constBits(); bits.setsize(image.byteCount())
            layer.setPixelData(QByteArray(bytes(bits)), x, y, width, height)
            document.setActiveNode(layer); document.setModified(True); document.refreshProjection()
            if self.remember.isChecked(): save_defaults(self.values())
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "オノマトペ素材", str(error))
