"""Compact drawing-first toolbar shared by the RT dialog and its UI checks."""
import math
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QComboBox, QCheckBox, QLabel, QSlider, QSpinBox, QMenu)


def slider_width(value):
    return round(1 + 499 * (value / 1000) ** 2)


def width_slider(value):
    return round(1000 * math.sqrt((max(1, min(500, value)) - 1) / 499))


COLORS = [('黒', '#000000'), ('白', '#ffffff'), ('灰', '#808080'), ('赤', '#e53935'),
          ('橙', '#fb8c00'), ('黄', '#fdd835'), ('緑', '#43a047'), ('水色', '#4fc3f7'),
          ('青', '#1e88e5'), ('紫', '#8e24aa'), ('茶', '#795548'), ('肌色', '#f3c6a5')]


def build_toolbar(owner, layout):
    canvas = owner.canvas
    container = QWidget()
    rows = QVBoxLayout(container)
    rows.setContentsMargins(0, 0, 0, 0)
    rows.setSpacing(5)
    primary = QHBoxLayout()
    primary.setSpacing(6)

    def button(row, text, action, tip):
        result = QPushButton(text)
        result.setToolTip(tip)
        result.clicked.connect(action)
        row.addWidget(result)
        return result

    owner.undo_button = button(primary, '↶ 戻す', canvas.undo, 'Ctrl+Z：下描きを1操作戻す')
    owner.redo_button = button(primary, '↷ やり直す', canvas.redo, 'Ctrl+Shift+Z / Ctrl+Y')
    owner.tool_selector = QComboBox()
    for label, tool in [('ペン', 'フリーハンド'), ('直線', '直線'), ('四角', '四角'), ('楕円', '楕円'), ('バケツ', 'バケツ')]:
        owner.tool_selector.addItem(label, tool)
    owner.tool_selector.setMinimumWidth(82)
    owner.tool_selector.setToolTip('描画ツール。図形はドラッグで確定、Escで取り消し。')
    primary.addWidget(owner.tool_selector)
    owner.eraser_checkbox = QCheckBox('消しゴム')
    owner.eraser_checkbox.setToolTip('E：下描きを消す。元画像は変更しません。')
    owner.eraser_checkbox.toggled.connect(canvas.set_eraser)
    primary.addWidget(owner.eraser_checkbox)
    primary.addSpacing(6)
    primary.addWidget(QLabel('太さ'))
    owner.brush_slider = QSlider(Qt.Horizontal)
    owner.brush_slider.setRange(0, 1000)
    owner.brush_slider.setMinimumWidth(120)
    owner.brush_slider.setMaximumWidth(280)
    owner.brush_slider.setAccessibleName('ブラシの太さ')
    owner.brush_slider.setToolTip('原稿上の太さ：1～500 px。細い範囲を細かく調整できます。')
    owner.brush_slider.valueChanged.connect(lambda value: canvas.set_brush_width(slider_width(value)))
    primary.addWidget(owner.brush_slider, 1)
    owner.brush_size = QSpinBox()
    owner.brush_size.setRange(1, 500)
    owner.brush_size.setSuffix(' px')
    owner.brush_size.setFixedWidth(80)
    owner.brush_size.valueChanged.connect(canvas.set_brush_width)
    primary.addWidget(owner.brush_size)
    owner.color_button = button(primary, '色…', canvas.choose_color, '任意の色を選ぶ')
    owner.color_button.setFixedWidth(66)
    owner.fill_shapes_checkbox = QCheckBox('塗りつぶす')
    owner.fill_shapes_checkbox.setToolTip('四角・楕円の内側を現在の色で塗る')
    owner.fill_shapes_checkbox.toggled.connect(lambda value: setattr(canvas, 'fill_shapes', value))
    owner.fill_shapes_checkbox.hide()
    primary.addWidget(owner.fill_shapes_checkbox)
    primary.addStretch()
    rows.addLayout(primary)

    secondary = QHBoxLayout()
    secondary.setSpacing(5)
    owner.color_swatches = []
    for name, color in COLORS:
        swatch = QPushButton()
        swatch.setFixedSize(24, 24)
        swatch.setToolTip(name + ' ' + color)
        swatch.setAccessibleName(name)
        swatch.setCheckable(True)
        swatch.setStyleSheet('QPushButton {background:%s; border:1px solid #777; border-radius:3px;} '
                            'QPushButton:checked {border:3px solid #36b9ff;}' % color)
        def choose(checked=False, value=color):
            canvas.brush_color = QColor(value)
            canvas.set_eraser(False)
        swatch.clicked.connect(choose)
        owner.color_swatches.append((swatch, color))
        secondary.addWidget(swatch)
    secondary.addSpacing(10)
    layers = QPushButton('レイヤー')
    owner.layer_menu = QMenu(layers)
    owner.layer_menu.aboutToShow.connect(owner._populate_layer_menu)
    layers.setMenu(owner.layer_menu)
    secondary.addWidget(layers)
    button(secondary, '全体表示', canvas.fit_view, 'コマ全体が見える倍率に戻す')
    secondary.addStretch()
    button(secondary, '人形を編集…', owner.edit_pose, 'OpenPoseの関節編集。編集だけでは生成しません。')
    button(secondary, 'ポーズで1回生成', owner.generate_pose_once, 'この生成だけPose ControlNetを使用')
    secondary.addSpacing(10)
    button(secondary, '下描きをクリア', canvas.clear_sketch, '下描きを全消去。戻す操作で復元できます。')
    rows.addLayout(secondary)
    layout.addWidget(container)
    owner.drawing_toolbar = container

    def changed(index):
        tool = owner.tool_selector.itemData(index)
        canvas.set_draw_tool(tool)
        owner.fill_shapes_checkbox.setVisible(tool in ('四角', '楕円'))
        bucket = tool == 'バケツ'
        for widget in (owner.eraser_checkbox, owner.brush_slider, owner.brush_size):
            widget.setEnabled(not bucket)
        if bucket:
            canvas.set_eraser(False)
    owner.tool_selector.currentIndexChanged.connect(changed)
    sync_toolbar(owner)


def sync_toolbar(owner):
    canvas = owner.canvas
    for widget, value in ((owner.brush_size, canvas.brush_width),
                          (owner.brush_slider, width_slider(canvas.brush_width))):
        widget.blockSignals(True)
        widget.setValue(value)
        widget.blockSignals(False)
    owner.eraser_checkbox.blockSignals(True)
    owner.eraser_checkbox.setChecked(canvas.eraser)
    owner.eraser_checkbox.blockSignals(False)
    owner.color_button.setStyleSheet('border-left: 12px solid %s' % canvas.brush_color.name())
    owner.color_button.setToolTip('任意の色を選ぶ：' + canvas.brush_color.name())
    owner.brush_size.setToolTip(('消しゴム' if canvas.eraser else canvas.brush_kind) + ' · 実径 %d px' % canvas.effective_width())
    for swatch, color in owner.color_swatches:
        swatch.setChecked(canvas.brush_color.name() == color)
