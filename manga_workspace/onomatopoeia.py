"""Onomatopoeia material generator for the manga workspace."""
import math
from krita import Krita
from PyQt5.QtCore import QByteArray, Qt, QSize, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath,
    QPen, QPixmap, QPolygonF, QTransform,
)
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QToolButton, QWidget, QScrollArea, QSizePolicy,
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
    def __init__(self, parent=None, initial_text="", fixed_bounds=None, fixed_parent_node=None):
        super().__init__(parent)
        self.fixed_bounds = list(fixed_bounds) if fixed_bounds else None
        self.fixed_parent_node = fixed_parent_node
        self.setWindowTitle("オノマトペ素材")
        self.setMinimumSize(760, 680)
        self.resize(860, 760)
        values = load_defaults()
        self.current_preset = values["preset"] if values["preset"] in PRESETS else "衝撃"
        self.preset_buttons = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        title = QLabel("オノマトペ素材を作成")
        title.setStyleSheet("font-size:18px;font-weight:700")
        subtitle = QLabel("文字とスタイルを選び、原稿上へ透明な素材レイヤーとして配置します。")
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
        preset_grid = QGridLayout()
        preset_grid.setSpacing(6)
        sample_words = {"衝撃": "ドン", "速度": "シュッ", "不穏": "ゴゴゴ", "小声": "ひそ…", "可愛い": "キラッ"}
        for index, name in enumerate(PRESETS):
            button = QToolButton()
            button.setText(name)
            button.setCheckable(True)
            button.setChecked(name == self.current_preset)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(132, 64))
            button.setMinimumSize(150, 94)
            button.clicked.connect(lambda checked=False, value=name: self.select_preset(value))
            self.preset_buttons[name] = button
            preset_grid.addWidget(button, index // 2, index % 2)
        style_column.addLayout(preset_grid)
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
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.generate = QPushButton("原稿に素材レイヤーを作成")
        self.generate.setMinimumHeight(40)
        self.generate.setDefault(True)
        self.generate.setStyleSheet("QPushButton{font-weight:700;padding:8px 20px}")
        buttons.addButton(self.generate, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject); self.generate.clicked.connect(self.create_layer)
        outer.addWidget(buttons)
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
        self.target.currentIndexChanged.connect(self.update_target_hint)
        self.refresh_preset_icons(sample_words)
        self.update_target_hint()
        self.update_preview()

    def values(self):
        return {"preset": self.current_preset, "font": self.font.currentFont().family(),
                "fill": self.fill.color.name(), "outline_color": self.outline_color.color.name(),
                "outline": self.outline.value(), "slant": self.slant.value(), "angle": self.angle.value(),
                "bold": self.bold.isChecked(), "vertical": self.vertical.isChecked(),
                "shadow": self.shadow.isChecked(), "burst": self.burst.isChecked(),
                "target": self.target.currentData()}

    def select_preset(self, name):
        self.current_preset = name
        for preset_name, button in self.preset_buttons.items():
            button.setChecked(preset_name == name)
        preset = PRESETS.get(name, {})
        self.bold.setChecked(preset.get("bold", True)); self.outline.setValue(preset.get("outline", 6))
        self.slant.setValue(preset.get("slant", 0)); self.angle.setValue(preset.get("angle", 0))
        self.shadow.setChecked(preset.get("shadow", False)); self.burst.setChecked(preset.get("burst", False))
        self.update_preview()

    def refresh_preset_icons(self, sample_words):
        base = self.values()
        for name, button in self.preset_buttons.items():
            preview_values = dict(base)
            preview_values["preset"] = name
            preview_values.update(PRESETS[name])
            image = render_material(sample_words[name], preview_values, 132, 64)
            button.setIcon(QIcon(QPixmap.fromImage(image)))

    def update_target_hint(self, *args):
        hints = {
            "selection": "Canvasで囲んだ範囲へ配置します。最も細かく位置を決められます。",
            "current_panel": "コマ一覧で選択中のコマ内へ収めます。コマ外にはみ出しません。",
            "page_center": "ページ中央へ大きめに配置します。作成後に移動・変形できます。",
            "fixed_region": "MANGA BRIDGE v2形式で登録した文字領域へ正確に配置します。",
        }
        self.target_hint.setText(hints.get(self.target.currentData(), ""))

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
            if self.remember.isChecked():
                remembered = self.values()
                if remembered["target"] == "fixed_region":
                    remembered["target"] = "selection"
                save_defaults(remembered)
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "オノマトペ素材", str(error))
