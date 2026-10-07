"""A focused manga-panel canvas backed by Krita AI Diffusion's Live model.

The AI plugin is optional.  No copy of its code or model files is bundled.
"""
import math
import json
from pathlib import Path

from krita import Krita, Selection
from PyQt5.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFileDialog, QFrame,
                             QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                             QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QComboBox)

from .prompt_edit import TagPromptEdit
from .reference_prompt import png_metadata, prompt_from_metadata



class ContentHeightTabs(QTabWidget):
    """Inactive catalog pages must not reserve height on reference pages."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._height_pending = False
        self.currentChanged.connect(self.queue_height)

    def addTab(self, widget, title):
        widget.installEventFilter(self)
        result = super().addTab(widget, title)
        self.queue_height()
        return result

    def queue_height(self, *_):
        if not self._height_pending:
            self._height_pending = True
            QTimer.singleShot(0, self.fit_current_page)

    def fit_current_page(self):
        self._height_pending = False
        page = self.currentWidget()
        if page is None or page.layout() is None:
            return
        page.layout().activate()
        height = page.layout().sizeHint().height() + self.tabBar().sizeHint().height() + 8
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def eventFilter(self, obj, event):
        if obj is self.currentWidget() and event.type() == QEvent.LayoutRequest:
            self.queue_height()
        return super().eventFilter(obj, event)


def image_bytes(image):
    bits = image.constBits()
    bits.setsize(image.byteCount())
    return bytes(bits)


def activate_layer_later(document, node):
    """Select only after Krita has processed the queued layer/shape changes."""
    if node is None:
        return
    node_id = node.uniqueId().toString()
    document.waitForDone()

    def activate():
        if Krita.instance().activeDocument() != document:
            return
        from .panels import node_by_id
        existing = node_by_id(document, node_id)
        if existing is not None:
            document.setActiveNode(existing)

    QTimer.singleShot(0, activate)


def disconnect_live_widgets(live_ui):
    """Release KAD's model bindings before deleting its borrowed widgets."""
    from ai_diffusion.model.properties import Binding
    for widget in [live_ui, *live_ui.findChildren(QWidget)]:
        for name in ('_model_bindings', '_bindings', '_connections', '_model_connections'):
            bindings = getattr(widget, name, None)
            if isinstance(bindings, list):
                Binding.disconnect_all(bindings)
                setattr(widget, name, [])


def add_panel_artwork(group, layer, panel):
    """Keep generated art below the existing panel border."""
    children = group.childNodes()
    frame_index = next((i for i, node in enumerate(children)
                        if node.uniqueId().toString() == panel['frame']), -1)
    above = children[frame_index - 1] if frame_index > 0 else None
    group.addChildNode(layer, above)


class PanelLiveDocument:
    """Restrict the official Live input crop to this panel, without page padding."""

    def __init__(self, document, bounds, selection, image_provider=None):
        self.document, self.bounds, self.selection = document, bounds, selection
        self.image_provider = image_provider

    def __getattr__(self, name):
        return getattr(self.document, name)

    def get_image(self, bounds, *args, **kwargs):
        if self.image_provider is None:
            return self.document.get_image(bounds, *args, **kwargs)
        from ai_diffusion.image import Image
        return Image(self.image_provider(bounds))

    def create_mask_from_selection(self, modifiers):
        from ai_diffusion.image import Bounds, Mask
        bounds = Bounds(*self.bounds)
        return Mask(bounds, self.selection.pixelData(*self.bounds)), bounds


def prepare_panel_live(model, prepare, bounds, selection, image_provider=None):
    # Workflow preparation is synchronous. Restore the shared document before
    # enqueueing work, including when model validation raises an exception.
    document = model._doc
    try:
        model._doc = PanelLiveDocument(document, bounds, selection, image_provider)
        return prepare()
    finally:
        model._doc = document


def panel_bounds(polygon, document):
    x = max(0, math.floor(min(p[0] for p in polygon)))
    y = max(0, math.floor(min(p[1] for p in polygon)))
    right = min(document.width(), math.ceil(max(p[0] for p in polygon)))
    bottom = min(document.height(), math.ceil(max(p[1] for p in polygon)))
    if right <= x or bottom <= y or (right - x) * (bottom - y) > 16_000_000:
        raise ValueError("このコマの範囲はLive作画に使えません（最大1600万画素）")
    return x, y, right - x, bottom - y


def polygon_selection(polygon, bounds):
    x, y, width, height = bounds
    image = QImage(width, height, QImage.Format_Grayscale8)
    image.fill(0)
    painter = QPainter(image)
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.white)
    painter.drawPolygon(QPolygonF([QPointF(px - x, py - y) for px, py in polygon]))
    painter.end()
    raw = image_bytes(image)
    stride = image.bytesPerLine()
    selection = Selection()
    selection.setPixelData(QByteArray(b"".join(
        raw[row * stride:row * stride + width] for row in range(height))),
        x, y, width, height)
    return selection


class SketchCanvas(QWidget):
    """Enlarged input canvas; strokes are stored in a real Krita paint layer."""

    settings_changed = pyqtSignal()
    history_changed = pyqtSignal()

    def __init__(self, document, layer, polygon, bounds, parent=None, source_node=None):
        super().__init__(parent)
        self.document, self.layer, self.bounds = document, layer, bounds
        x, y, width, height = bounds
        self.source_node = source_node
        self.source_enabled = True
        raw = bytes(source_node.projectionPixelData(x, y, width, height))
        self.background = QImage(raw, width, height, QImage.Format_ARGB32).copy()
        self.strokes = QImage(width, height, QImage.Format_ARGB32)
        self.strokes.fill(Qt.transparent)
        self.polygon = QPolygonF([QPointF(px - x, py - y) for px, py in polygon])
        self.last_point = None
        self.draw_tool = 'フリーハンド'
        self.fill_shapes = False
        self.shape_start = self.shape_end = None
        self.pointer = None
        self.pan_start = None
        self.space_down = False
        self.zoom = 1.0
        self.pan = QPointF()
        self.undo_stack, self.redo_stack = [], []
        self.history_limit = max(1, min(30, 128_000_000 // (width * height * 4)))
        self.stroke_started = False
        self.has_strokes = False
        self.eraser = False
        self.brush_color = QColor(Qt.black)
        self.brush_kind = "ペン"
        self.brush_width = max(2, min(16, round(min(width, height) / 180)))
        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.timeout.connect(self.flush)
        self.setMinimumSize(360, 360)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("ホイール：拡大縮小／中ボタン・Space＋ドラッグ：移動／E：消しゴム／[ ]：太さ")

    def image_rect(self):
        width, height = self.bounds[2:]
        scale = min(self.width() / width, self.height() / height) * self.zoom
        target = QRectF(0, 0, width * scale, height * scale)
        target.moveCenter(QPointF(self.rect().center()) + self.pan)
        return target

    def to_image(self, pos):
        rect = self.image_rect()
        if not rect.contains(pos):
            return None
        return QPointF((pos.x() - rect.x()) * self.bounds[2] / rect.width(),
                       (pos.y() - rect.y()) * self.bounds[3] / rect.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#272b30"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        target = self.image_rect()
        painter.fillRect(target, Qt.white)
        if self.source_enabled:
            painter.drawImage(target, self.background)
        if self.layer.visible():
            painter.drawImage(target, self.strokes)
        if self.shape_start is not None:
            painter.save()
            painter.translate(target.topLeft())
            painter.scale(target.width() / self.bounds[2], target.height() / self.bounds[3])
            self.paint_shape(painter)
            painter.restore()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#48c7ff"), 2))
        painter.drawPolygon(QPolygonF([
            QPointF(target.x() + p.x() * target.width() / self.bounds[2],
                    target.y() + p.y() * target.height() / self.bounds[3])
            for p in self.polygon]))
        if self.pointer is not None and self.pan_start is None:
            radius = self.effective_width() * target.width() / self.bounds[2] / 2
            radius = max(0.75, radius)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(Qt.black, 3))
            painter.drawEllipse(self.pointer, radius, radius)
            painter.setPen(QPen(QColor('#ffad48') if self.eraser else Qt.white, 1))
            painter.drawEllipse(self.pointer, radius, radius)

    def effective_width(self):
        return self.brush_width * (2 if self.brush_kind == 'マーカー' and not self.eraser else 1)

    def remember(self):
        self.undo_stack.append((self.strokes.copy(), self.has_strokes))
        self.undo_stack = self.undo_stack[-self.history_limit:]
        self.redo_stack.clear()
        self.history_changed.emit()

    def undo(self):
        self.restore_history(self.undo_stack, self.redo_stack)

    def redo(self):
        self.restore_history(self.redo_stack, self.undo_stack)

    def restore_history(self, source, target):
        if self.shape_start is not None:
            self.cancel_shape()
        if not source:
            return
        target.append((self.strokes, self.has_strokes))
        self.strokes, self.has_strokes = source.pop()
        self.last_point = None
        self.flush()
        self.update()
        self.history_changed.emit()

    def clear_sketch(self):
        if not self.has_strokes:
            return
        self.remember()
        self.strokes.fill(Qt.transparent)
        self.has_strokes = False
        self.flush()
        self.update()

    def fit_view(self):
        self.zoom, self.pan = 1.0, QPointF()
        self.update()

    def refresh_background(self):
        x, y, width, height = self.bounds
        raw = bytes(self.source_node.projectionPixelData(x, y, width, height))
        self.background = QImage(raw, width, height, QImage.Format_ARGB32).copy()
        self.update()

    def input_image(self, bounds):
        image = QImage(bounds.width, bounds.height, QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        x, y = self.bounds[0] - bounds.x, self.bounds[1] - bounds.y
        if self.source_enabled:
            painter.drawImage(x, y, self.background)
        if self.layer.visible():
            painter.drawImage(x, y, self.strokes)
        painter.end()
        return image

    def draw_to(self, point):
        if not self.layer.visible() or point is None or not self.polygon.containsPoint(point, Qt.OddEvenFill):
            self.last_point = None
            return
        painter = QPainter(self.strokes)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addPolygon(self.polygon)
        painter.setClipPath(clip)
        if self.eraser:
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
        color = QColor(self.brush_color)
        width = self.effective_width()
        if self.brush_kind == "鉛筆" and not self.eraser:
            color.setAlpha(155)
        elif self.brush_kind == "マーカー" and not self.eraser:
            color.setAlpha(135)
        painter.setPen(QPen(color, width, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        if self.last_point is None:
            painter.drawPoint(point)
        else:
            painter.drawLine(self.last_point, point)
        painter.end()
        self.has_strokes = True
        self.last_point = point
        self.update()
        self.flush_timer.start(120)

    def set_draw_tool(self, tool):
        self.cancel_shape()
        self.draw_tool = tool

    def cancel_shape(self):
        self.shape_start = self.shape_end = None
        self.stroke_started = False
        self.update()

    def paint_shape(self, painter):
        clip = QPainterPath()
        clip.addPolygon(self.polygon)
        painter.setClipPath(clip)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.brush_color if self.fill_shapes and self.draw_tool in ('四角', '楕円') else Qt.NoBrush)
        painter.setPen(QPen(self.brush_color, self.effective_width(), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.eraser:
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
        if self.draw_tool == '直線':
            painter.drawLine(self.shape_start, self.shape_end)
        elif self.draw_tool == '四角':
            painter.drawRect(QRectF(self.shape_start, self.shape_end).normalized())
        elif self.draw_tool == '楕円':
            painter.drawEllipse(QRectF(self.shape_start, self.shape_end).normalized())

    def bucket_fill(self, point):
        from .raster_fill import flood_mask
        from types import SimpleNamespace
        w, h = self.bounds[2:]
        clip = QImage(w, h, QImage.Format_Grayscale8)
        clip.fill(0)
        painter = QPainter(clip)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawPolygon(self.polygon)
        painter.end()
        bounds = SimpleNamespace(x=self.bounds[0], y=self.bounds[1], width=w, height=h)
        mask = flood_mask(self.input_image(bounds), clip, int(point.x()), int(point.y()))
        if not any(mask):
            return
        image = QImage(bytes(mask), w, h, w, QImage.Format_Indexed8).copy()
        image.setColorTable([0, self.brush_color.rgba()])
        self.remember()
        painter = QPainter(self.strokes)
        painter.drawImage(0, 0, image)
        painter.end()
        self.has_strokes = True
        self.flush()
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MiddleButton or (self.space_down and event.button() == Qt.LeftButton):
            self.pan_start = event.localPos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.LeftButton:
            point = self.to_image(event.localPos())
            self.stroke_started = bool(self.layer.visible() and point is not None and
                                       self.polygon.containsPoint(point, Qt.OddEvenFill))
            if not self.stroke_started:
                return
            if self.draw_tool == 'バケツ':
                self.stroke_started = False
                self.bucket_fill(point)
                event.accept()
                return
            if self.draw_tool != 'フリーハンド':
                self.shape_start = self.shape_end = point
                self.update()
                event.accept()
                return
            self.remember()
            self.last_point = None
            self.draw_to(point)
            event.accept()

    def mouseMoveEvent(self, event):
        self.pointer = event.localPos()
        if self.pan_start is not None:
            self.pan += event.localPos() - self.pan_start
            self.pan_start = event.localPos()
        elif event.buttons() & Qt.LeftButton and self.stroke_started:
            if self.shape_start is not None:
                self.shape_end = self.to_image(event.localPos()) or self.shape_end
            else:
                self.draw_to(self.to_image(event.localPos()))
            event.accept()
        self.update()

    def mouseReleaseEvent(self, event):
        if self.pan_start is not None:
            self.pan_start = None
            self.setCursor(Qt.CrossCursor)
            self.update()
            return
        if event.button() == Qt.LeftButton and self.stroke_started:
            if self.shape_start is not None:
                self.shape_end = self.to_image(event.localPos()) or self.shape_end
                if self.layer.visible() and self.shape_start != self.shape_end:
                    self.remember()
                    painter = QPainter(self.strokes)
                    self.paint_shape(painter)
                    painter.end()
                    self.has_strokes = True
                    self.flush()
                self.cancel_shape()
                event.accept()
                return
            self.draw_to(self.to_image(event.localPos()))
            self.last_point = None
            self.stroke_started = False
            self.flush()
            event.accept()

    def leaveEvent(self, event):
        self.pointer = None
        self.update()

    def wheelEvent(self, event):
        before = self.image_rect()
        self.zoom = max(0.25, min(8.0, self.zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2)))
        ratio = self.image_rect().width() / before.width()
        point = QPointF(event.pos())
        self.pan += (point - before.center()) * (1 - ratio)
        self.update()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.shape_start is not None:
            self.cancel_shape()
            event.accept()
            return
        control = bool(event.modifiers() & Qt.ControlModifier)
        if control and event.key() == Qt.Key_Z:
            self.redo() if event.modifiers() & Qt.ShiftModifier else self.undo()
        elif control and event.key() == Qt.Key_Y:
            self.redo()
        elif event.key() == Qt.Key_E:
            self.set_eraser(not self.eraser)
        elif event.key() in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            self.set_brush_width(max(1, min(500, self.brush_width + (1 if event.key() == Qt.Key_BracketRight else -1))))
        elif event.key() == Qt.Key_Space:
            self.space_down = True
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.space_down = False
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_down = False
        if self.shape_start is not None:
            self.cancel_shape()
        super().focusOutEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        for kind in ("ペン", "鉛筆", "マーカー"):
            action = menu.addAction(kind)
            action.setCheckable(True)
            action.setChecked(not self.eraser and self.brush_kind == kind)
            action.triggered.connect(lambda checked=False, value=kind: self.set_brush_kind(value))
        menu.addSeparator()
        erase = menu.addAction("消しゴム")
        erase.setCheckable(True)
        erase.setChecked(self.eraser)
        erase.triggered.connect(lambda: self.set_eraser(True))
        size_menu = menu.addMenu("太さ")
        for size in (2, 4, 8, 16, 32, 64):
            action = size_menu.addAction("%d px" % size)
            action.setCheckable(True)
            action.setChecked(self.brush_width == size)
            action.triggered.connect(lambda checked=False, value=size: self.set_brush_width(value))
        menu.addAction("色を選ぶ…", self.choose_color)
        menu.exec_(event.globalPos())
        event.accept()

    def set_brush_kind(self, value):
        self.brush_kind = value
        self.eraser = False
        self.settings_changed.emit()
        self.update()

    def set_eraser(self, value):
        self.eraser = bool(value)
        self.settings_changed.emit()
        self.update()

    def set_brush_width(self, value):
        self.brush_width = int(value)
        self.settings_changed.emit()
        self.update()

    def choose_color(self):
        color = QColorDialog.getColor(self.brush_color, self, "ブラシの色")
        if color.isValid():
            self.brush_color = color
            self.eraser = False
            self.settings_changed.emit()

    def flush(self):
        self.flush_timer.stop()
        x, y, width, height = self.bounds
        self.layer.setPixelData(QByteArray(image_bytes(self.strokes)), x, y, width, height)
        self.document.setModified(True)
        self.document.refreshProjection()


class ReferenceDropBox(QFrame):
    """Drop target for a character image; the image is never painted into the panel."""

    image_dropped = pyqtSignal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("QFrame { border: 1px dashed #72a8c8; border-radius: 5px; }")
        row = QHBoxLayout(self)
        self.thumbnail = QLabel("画像")
        self.thumbnail.setFixedSize(72, 72)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumbnail)
        self.description = QLabel("キャラ画像をここへドロップ\nPNG・JPG・WebP")
        row.addWidget(self.description, 1)
        choose = QPushButton("選ぶ…")
        choose.clicked.connect(self.choose_file)
        row.addWidget(choose)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "参照画像を選択", "", "画像 (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.image_dropped.emit(None, path)

    def dragEnterEvent(self, event):
        if self._usable_mime(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData()
        for url in mime.urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                self.image_dropped.emit(None, path)
                event.acceptProposedAction()
                return
        if mime.hasImage():
            image = mime.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
            if isinstance(image, QImage) and not image.isNull():
                self.image_dropped.emit(image, "")
                event.acceptProposedAction()

    @staticmethod
    def _usable_mime(mime):
        return mime.hasImage() or any(
            url.isLocalFile() and Path(url.toLocalFile()).suffix.lower()
            in (".png", ".jpg", ".jpeg", ".webp") for url in mime.urls())

    def show_image(self, image, name):
        self.thumbnail.setPixmap(QPixmap.fromImage(image).scaled(
            72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.description.setText(name or "貼り付けた画像")


class LivePanelDialog(QDialog):
    """Use the installed official Live engine, with a panel-scoped input view."""

    def __init__(self, document, panel, parent=None):
        super().__init__(parent)
        try:
            from ai_diffusion.model.root import root
            from ai_diffusion.model.model import Workspace
            from ai_diffusion.ui.live import LiveWidget
        except ImportError as error:
            raise RuntimeError("Krita AI Diffusionを有効化してKritaを再起動してください") from error

        if Krita.instance().activeDocument() != document:
            raise RuntimeError("対象の原稿をアクティブにしてから開いてください")
        self.document, self.panel = document, panel
        self.bounds = panel_bounds(panel["polygon"], document)
        selection = document.selection()
        # selection() wraps the document-owned mask. Reattaching that object
        # asserts in KisPaintDevice::setParentNode; keep an independent copy.
        self.previous_selection = selection.duplicate() if selection is not None else None
        self.previous_node = document.activeNode()
        self._applied = False
        self._applying = False
        self._ready = False
        self._closing = False
        self.reference_image = None
        self.reference_layer = None
        self.reference_control = None
        self.model = root.model_for_active_document()
        self.connection = root.connection
        if self.model is None:
            raise RuntimeError("Krita AI Diffusionの文書モデルを取得できません")
        if getattr(self.model.live, "is_active", False):
            raise RuntimeError("既存のLive生成を停止してからコマ作画を開いてください")
        from ai_diffusion.model.jobs import JobKind, JobState
        if any(job.kind is JobKind.live_preview and
               job.state in (JobState.queued, JobState.executing) for job in self.model.jobs):
            raise RuntimeError("前のRT生成が終了処理中です。完了後にこのレイヤーで開いてください")

        from .panels import node_by_id
        group = node_by_id(document, panel["node"])
        if group is None:
            raise RuntimeError("選択コマのレイヤーフォルダが見つかりません")
        from .live_layer_state import read_states, owner_id, apply_settings
        from ai_diffusion.model.region import RootRegion
        from ai_diffusion.style import Styles
        self._layer_states = read_states(document)
        selected = self.previous_node
        if selected is None:
            raise RuntimeError("RT生成する描画レイヤーを選択してください")
        self._owner_id = owner_id(self._layer_states, selected.uniqueId().toString())
        self.source_node = node_by_id(document, self._owner_id)
        if self.source_node is None:
            self.source_node = selected
            self._owner_id = selected.uniqueId().toString()
        node = self.source_node
        belongs = False
        while node is not None:
            if node.uniqueId() == group.uniqueId():
                belongs = True
                break
            node = node.parentNode()
        if not belongs or self.source_node.type() not in ('paintlayer', 'vectorlayer', 'filelayer') or self._owner_id == panel['frame']:
            raise RuntimeError("コマ内の描画レイヤーを選択してください（枠線・フォルダは対象外です）")
        self.group = group
        saved = self._layer_states.get(self._owner_id, {})
        self.sketch_layer = node_by_id(document, saved.get('sketch', ''))
        if self.sketch_layer is None:
            self.sketch_layer = document.createNode("RT下描き · " + self.source_node.name(), "paintlayer")
            add_panel_artwork(group, self.sketch_layer, panel)
        self.sketch_layer.setVisible(True)
        self.canvas = SketchCanvas(document, self.sketch_layer,
                                   panel["polygon"], self.bounds, self, self.source_node)
        x, y, w, h = self.bounds
        self.canvas.strokes = QImage(bytes(self.sketch_layer.pixelData(x, y, w, h)),
                                     w, h, QImage.Format_ARGB32).copy()
        self.canvas.has_strokes = bool(saved.get('has_strokes', False))
        self.canvas.source_enabled = saved.get('source_enabled', True)
        self._previous_rt = (self.model.regions, self.model.edit_mode, self.model.style,
                             self.model.seed, self.model.live.strength)
        self.model.regions = RootRegion(self.model)
        self.model.edit_mode = False
        apply_settings(self.model, saved, Styles.list().find)
        self.canvas.settings_changed.connect(self._sync_brush_controls)
        self._previous_workspace = self.model.workspace
        self.model.workspace = Workspace.live
        self.model.live._result = None
        self.model.live._result_params = None
        self.model.live._result_composition = None
        self.model.live.has_result = False
        document.setSelection(polygon_selection(panel["polygon"], self.bounds))

        self.setWindowTitle("RT生成 · " + self.source_node.name())
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(1150, 760)
        layout = QVBoxLayout(self)
        status = QLabel("対象：" + self.source_node.name() + "（このレイヤー＋専用下描きだけを生成入力に使用）")
        layout.addWidget(status)
        self._pose_points = saved.get('pose_points')
        from .live_toolbar import build_toolbar
        build_toolbar(self, layout)
        self.canvas.history_changed.connect(self._update_history)
        self._update_history()
        main = QHBoxLayout()
        main.addWidget(self.canvas, 3)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 4, 0)
        self.connection_status = QLabel()
        self.connection_status.setWordWrap(True)
        right_layout.addWidget(self.connection_status)
        connection_button = QPushButton("RT生成の接続設定…")
        connection_button.clicked.connect(self._open_connection_settings)
        right_layout.addWidget(connection_button)
        references = ContentHeightTabs()
        self.reference_tabs = references
        character = QWidget()
        character_layout = QVBoxLayout(character)
        character_layout.setAlignment(Qt.AlignTop)
        character_layout.setSpacing(6)
        self.reference_drop = ReferenceDropBox(self)
        self.reference_drop.image_dropped.connect(self.load_reference)
        character_layout.addWidget(self.reference_drop)
        self.reference_enabled = QCheckBox("使用")
        self.reference_enabled.setChecked(True)
        self.reference_enabled.toggled.connect(self.toggle_reference)
        self.reference_status = QLabel("画像未選択")
        self.reference_status.setWordWrap(True)
        character_layout.addWidget(self.reference_status)
        self.candidate = TagPromptEdit(self)
        self.candidate.setMaximumHeight(72)
        self.candidate.setPlaceholderText("画像に埋め込まれたプロンプト候補")
        self.candidate.hide()
        character_layout.addWidget(self.candidate)
        self.add_prompt_button = QPushButton("候補をプロンプトに追加")
        self.add_prompt_button.clicked.connect(self.add_candidate_prompt)
        self.add_prompt_button.hide()
        character_layout.addWidget(self.add_prompt_button)
        char_row = QHBoxLayout()
        char_row.addWidget(self.reference_enabled)
        char_row.addWidget(QLabel("効き具合"))
        self.reference_strength = QSpinBox()
        self.reference_strength.setRange(0, 100)
        self.reference_strength.setValue(100)
        self.reference_strength.setSuffix("%")
        self.reference_strength.valueChanged.connect(self._set_reference_strength)
        self.reference_strength.setFixedWidth(76)
        char_row.addWidget(self.reference_strength)
        remove_reference = QPushButton("削除")
        remove_reference.clicked.connect(self.clear_reference)
        remove_reference.setFixedWidth(54)
        char_row.addWidget(remove_reference)
        char_row.addStretch()
        character_layout.insertLayout(1, char_row)
        references.addTab(character, "キャラクター")
        from .live_reference import ReferenceSlot
        self.extra_references = [
            ReferenceSlot(self, "ポーズ", "pose", ReferenceDropBox),
            ReferenceSlot(self, "背景", "composition", ReferenceDropBox),
        ]
        for slot in self.extra_references:
            references.addTab(slot, slot.title)
        right_layout.addWidget(references)
        prompt_header = QHBoxLayout()
        prompt_header.addWidget(QLabel("Liveプロンプト（日本語TagComplete対応）"))
        self.monochrome_sketch = QCheckBox("白黒スケッチ")
        self.monochrome_sketch.setToolTip("生成時に monochrome, sketch を追加します。入力文は変更しません。モデルによって色が残る場合があります。")
        self.monochrome_sketch.setChecked(bool(saved.get('monochrome_sketch', False)))
        prompt_header.addWidget(self.monochrome_sketch)
        self.lineart = QCheckBox("線画")
        self.lineart.setToolTip("生成時に monochrome, lineart を追加。両方オンなら線画を優先し、sketchは自動追加しません。手入力のタグは保持します。")
        self.lineart.setChecked(bool(saved.get('lineart', False)))
        prompt_header.addWidget(self.lineart)
        right_layout.addLayout(prompt_header)
        self.prompt_editor = TagPromptEdit(self)
        self.prompt_editor.setMaximumHeight(84)
        self.prompt_editor.setPlaceholderText("このコマに描きたい内容")
        self.prompt_editor.setPlainText(self.model.regions.positive)
        self.prompt_editor.textChanged.connect(self._prompt_edited)
        self.model.regions.positive_changed.connect(self._sync_prompt)
        self.monochrome_sketch.toggled.connect(self._prompt_edited)
        self.lineart.toggled.connect(self._prompt_edited)
        self._prompt_edited()
        right_layout.addWidget(self.prompt_editor)
        self.live_ui = LiveWidget()
        # LiveWidget starts with root.active_model but binds signals only when
        # its model property changes. Force its initial binding in this dialog.
        self.live_ui._model = None
        self.live_ui.model = self.model
        self.live_ui.setEnabled(False)
        # The manga editor is the single positive-prompt input; keep KAD's
        # negative prompt and all native Live controls underneath it.
        self.live_ui.prompt_widget.positive.hide()
        self.live_ui.apply_button.hide()
        self.live_ui.apply_layer_button.hide()
        # This editor owns one fixed panel and layer. Native region creation or
        # edit-mode switching escapes that scope and can immediately activate
        # newly created Krita nodes before their shapes have been registered.
        self.live_ui.add_region_button.setEnabled(False)
        self.live_ui.add_region_button.hide()
        self.live_ui.edit_toggle.setEnabled(False)
        self.live_ui.edit_toggle.hide()
        self.preview_apply_button = QPushButton("編集していたコマへ反映")
        self.preview_apply_button.setToolTip("生成結果を元のコマ内の新しいレイヤーへ追加し、RT画面を閉じます")
        self.preview_apply_button.setEnabled(False)
        self.preview_apply_button.clicked.connect(self.apply_result)
        right_layout.addWidget(self.preview_apply_button)
        # KAD scales the first result to the preview's current size. Reserve
        # space before it arrives instead of initially scaling to a few pixels.
        self.live_ui.preview_area.setMinimumSize(256, 256)
        right_layout.addWidget(self.live_ui, 1)
        live_scroll = QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setWidget(right)
        main.addWidget(live_scroll, 2)
        layout.addLayout(main, 1)
        footer = QHBoxLayout()
        self.apply_button = QPushButton("編集していたコマへ反映")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_result)
        self.model.live.has_result_changed.connect(self._update_apply_enabled)
        footer.addWidget(self.apply_button)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        # Krita 5.2 registers GUI shapes via queued node-added events. Selecting
        # Live下描き inside this constructor can assert in KisNodeManager.
        document.waitForDone()
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._finish_start)
        self._original_prepare_live = self.model._prepare_live_workflow
        self._panel_selection = polygon_selection(panel["polygon"], self.bounds)
        self.model._prepare_live_workflow = lambda: prepare_panel_live(
            self.model, self._original_prepare_live, self.bounds, self._panel_selection, self.canvas.input_image)
        self._start_timer.start(0)
        self.connection.state_changed.connect(self._update_connection_state)
        self._update_connection_state()

    def _open_connection_settings(self):
        from ai_diffusion.ui.settings import SettingsDialog
        SettingsDialog.instance().show()

    def _update_history(self):
        self.undo_button.setEnabled(bool(self.canvas.undo_stack))
        self.redo_button.setEnabled(bool(self.canvas.redo_stack))

    def _populate_layer_menu(self):
        self.layer_menu.clear()
        source = self.layer_menu.addAction("入力元：" + self.source_node.name())
        source.setCheckable(True)
        source.setChecked(self.canvas.source_enabled)
        source.toggled.connect(self._toggle_source)
        sketch = self.layer_menu.addAction("このレイヤーのRT下描き")
        sketch.setCheckable(True)
        sketch.setChecked(self.sketch_layer.visible())
        sketch.toggled.connect(self._toggle_sketch)

    def _toggle_source(self, visible):
        self.canvas.source_enabled = visible
        self.canvas.flush()
        self.canvas.update()

    def _toggle_sketch(self, visible):
        self.sketch_layer.setVisible(visible)
        self.document.refreshProjection()
        self.canvas.update()

    def _save_layer_session(self):
        from .live_layer_state import KEY, settings_snapshot
        state = settings_snapshot(self.model)
        state['positive'] = self.prompt_editor.toPlainText()
        state['monochrome_sketch'] = self.monochrome_sketch.isChecked()
        state['lineart'] = self.lineart.isChecked()
        state['pose_points'] = self._pose_points
        state['sketch'] = self.sketch_layer.uniqueId().toString()
        state['has_strokes'] = self.canvas.has_strokes
        state['source_enabled'] = self.canvas.source_enabled
        state['outputs'] = self._layer_states.get(self._owner_id, {}).get('outputs', [])
        if self._applied:
            state['outputs'] = state['outputs'] + [self._applied_layer.uniqueId().toString()]
            # A generated result is itself an independent editable source.
            output_state = settings_snapshot(self.model)
            output_state.update(positive=state['positive'], monochrome_sketch=state['monochrome_sketch'], lineart=state['lineart'])
            self._layer_states[self._applied_layer.uniqueId().toString()] = output_state
        self._layer_states[self._owner_id] = state
        self.document.setAnnotation(KEY, "レイヤー別RT設定", QByteArray(
            json.dumps(self._layer_states, ensure_ascii=False).encode('utf-8')))
        self.document.setModified(True)

    def _restore_rt_model(self):
        temporary = self.model.regions
        regions, edit_mode, style, seed, strength = self._previous_rt
        self.model.regions = regions
        self.model.edit_mode = edit_mode
        self.model.style, self.model.seed = style, seed
        self.model.live.strength = strength
        temporary.control.deleteLater()
        temporary.deleteLater()

    def _update_connection_state(self, *_):
        connected = self.connection.state.name == "connected"
        self.connection_status.setText(
            "RT生成：接続済み" if connected else
            "RT生成：未接続。接続設定でKrita AI Diffusionのサーバーを接続してください。")
        self.live_ui.active_button.setEnabled(self._ready and connected)
        self.live_ui.record_button.setEnabled(self._ready and connected)

    def _finish_start(self):
        if self._closing:
            return
        from .panels import node_by_id
        if Krita.instance().activeDocument() != self.document:
            self.reference_status.setText("対象ページに戻って、この画面を開き直してください")
            return
        node = node_by_id(self.document, self.sketch_layer.uniqueId().toString())
        if node is None:
            self.reference_status.setText("下描きレイヤーがありません。画面を開き直してください")
            return
        # Input is supplied by canvas.input_image; selecting the new sketch is unnecessary.
        self.model.layers.updated()
        self._ready = True
        self.live_ui.setEnabled(True)
        self._update_connection_state()
        self._update_apply_enabled()

    def _update_apply_enabled(self, *_):
        enabled = (self._ready and not self._closing and not self._applying
                   and self.model.live.result is not None and self.model.live._result_params is not None)
        self.apply_button.setEnabled(enabled)
        self.preview_apply_button.setEnabled(enabled)

    def _sync_brush_controls(self):
        from .live_toolbar import sync_toolbar
        sync_toolbar(self)

    def edit_pose(self):
        from .pose_editor import PoseEditor
        slot = self.extra_references[0]
        if slot.pending:
            QMessageBox.information(self, 'OpenPose', '骨格抽出が終わってから編集してください。')
            return
        editor = PoseEditor(self.bounds[2:], self._pose_points, self)
        if editor.exec_() == QDialog.Accepted:
            self._pose_points = editor.canvas.points
            slot.pose_ready.blockSignals(True)
            slot.pose_ready.setChecked(True)
            slot.pose_ready.blockSignals(False)
            slot.enabled.setChecked(False)
            slot.load(editor.canvas.render_pose(*self.bounds[2:]), '')
            self.reference_tabs.setCurrentWidget(slot)
            if slot.control and not slot.control.is_supported:
                QMessageBox.information(self, 'ポーズ参照', '骨格を設定しましたが、現在のモデルではポーズ参照が使えません。\n' + slot.control.error_text)

    def generate_pose_once(self):
        from ai_diffusion.model.jobs import JobState
        slot = self.extra_references[0]
        if slot.image is None or slot.pending:
            QMessageBox.information(self, 'ポーズ生成', '先に人形を編集してポーズ参照へ適用してください。')
            return
        was_active = self.model.live.is_active
        self.model.live.is_active = False
        if was_active or any(job.state in (JobState.queued, JobState.executing) for job in self.model.jobs):
            QMessageBox.information(self, 'ポーズ生成', 'RTを停止しました。処理中の生成が完了してから、もう一度押してください。')
            return
        try:
            slot.enabled.setChecked(True)
            slot.sync()
            if not slot.control or not slot.control.is_supported:
                raise RuntimeError(slot.control.error_text if slot.control else slot.status.text())
            # generate_live snapshots the control image synchronously before enqueueing.
            self.model.generate_live()
        except Exception as error:
            QMessageBox.information(self, 'ポーズ生成', str(error))
        finally:
            slot.enabled.setChecked(False)
            slot.sync()

    def _prompt_edited(self, *_):
        from .live_prompt import effective_prompt
        self.model.regions.positive = effective_prompt(
            self.prompt_editor.toPlainText(), self.monochrome_sketch.isChecked(), self.lineart.isChecked())

    def _sync_prompt(self, text):
        from .live_prompt import effective_prompt
        if text == effective_prompt(self.prompt_editor.toPlainText(), self.monochrome_sketch.isChecked(), self.lineart.isChecked()):
            return
        if self.prompt_editor.toPlainText() != text:
            self.prompt_editor.blockSignals(True)
            self.prompt_editor.setPlainText(text)
            self.prompt_editor.blockSignals(False)
            self._prompt_edited()

    def _set_reference_strength(self, *_):
        if self.reference_control:
            self.reference_control.use_custom_strength = True
            self.reference_control.strength = round(self.reference_strength.value() / 2)

    def clear_reference(self):
        self._remove_reference()
        self.reference_image = None
        self.reference_drop.thumbnail.clear()
        self.reference_drop.description.setText("キャラ画像をここへドロップ")
        self.reference_status.setText("画像未選択")
        self.candidate.clear()
        self.candidate.hide()
        self.add_prompt_button.hide()

    def load_reference(self, dropped_image, path):
        try:
            metadata = {}
            if path:
                reader = QImageReader(path)
                reader.setAutoTransform(True)
                image = reader.read()
                if image.isNull():
                    raise ValueError("画像を読み込めませんでした")
                metadata.update({key: reader.text(key) for key in reader.textKeys()})
                if Path(path).suffix.lower() == ".png":
                    with open(path, "rb") as source:
                        metadata.update(png_metadata(source.read()))
                name = Path(path).name
            else:
                image = dropped_image
                name = "貼り付けた画像"
            if image is None or image.isNull():
                raise ValueError("画像データがありません")
            image = image.scaled(1536, 1536, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32)
            self._remove_reference()
            self.reference_image = image
            self.reference_drop.show_image(image, name)
            candidate = prompt_from_metadata(metadata)
            self.candidate.setPlainText(candidate)
            self.candidate.setVisible(bool(candidate))
            self.add_prompt_button.setVisible(bool(candidate))
            if self.reference_enabled.isChecked():
                self._install_reference()
            else:
                self.reference_status.setText("画像を読み込みました。参照はオフです")
            if not candidate:
                self.reference_status.setText(
                    self.reference_status.text() + "／埋め込みプロンプトは見つかりませんでした")
        except Exception as error:
            QMessageBox.warning(self, "キャラクター参照", str(error))

    def toggle_reference(self, enabled):
        if self.reference_image is None:
            return
        try:
            if enabled:
                self._install_reference()
            else:
                self._remove_reference()
                self.reference_status.setText("参照はオフです。画像と候補は保持しています")
        except Exception as error:
            QMessageBox.warning(self, "キャラクター参照", str(error))

    def _install_reference(self):
        if self.reference_image is None or self.reference_control is not None:
            return
        from ai_diffusion.backend.resources import ControlMode
        image = self.reference_image
        node = self.document.createNode("Liveキャラ参照（非表示）", "paintlayer")
        self.document.rootNode().addChildNode(node, None)
        node.setPixelData(QByteArray(image_bytes(image)), 0, 0, image.width(), image.height())
        node.setVisible(False)
        self.reference_layer = node
        self.model.layers.updated()
        control = self.model.regions.control.emplace()
        if control is None:
            node.remove()
            self.reference_layer = None
            raise RuntimeError("参照レイヤーをLiveへ登録できませんでした")
        # KAD's active-layer cache can lag one polling interval behind Krita.
        # Bind the control to this exact node instead of relying on that cache.
        control.layer_id = node.uniqueId()
        control.mode = ControlMode.reference
        self.reference_control = control
        self._set_reference_strength()
        self.model.layers.updated()
        self._update_reference_status()
        control.is_supported_changed.connect(self._update_reference_status)

    def _update_reference_status(self, *_):
        control = self.reference_control
        if control is None:
            return
        if control.is_supported:
            self.reference_status.setText("参照を設定済み")
            self.reference_status.setToolTip("")
        else:
            self.reference_status.setText("参照は未使用（詳細）")
            self.reference_status.setToolTip(control.error_text)

    def _remove_reference(self):
        if self.reference_control is not None:
            self.model.regions.control.remove(self.reference_control)
            self.reference_control = None
        if self.reference_layer is not None:
            self.reference_layer.remove()
            self.reference_layer = None
        self.model.layers.updated()

    def add_candidate_prompt(self):
        candidate = self.candidate.toPlainText().strip()
        if candidate:
            current = self.prompt_editor.toPlainText().strip()
            separator = ", " if current and not current.endswith((",", "、")) else " "
            self.prompt_editor.setPlainText(current + (separator if current else "") + candidate)
            self.prompt_editor.setFocus()

    def apply_result(self):
        if self._closing or self._applying:
            return
        from .panels import node_by_id
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, "RT生成", "編集していたページに戻ってから反映してください")
            return
        group = node_by_id(self.document, self.group.uniqueId().toString())
        frame = node_by_id(self.document, self.panel['frame'])
        if group is None or frame is None:
            QMessageBox.warning(self, "RT生成", "元のコマが見つからないため反映できません")
            return
        result = self.model.live.result
        params = self.model.live._result_params
        if result is None or params is None:
            QMessageBox.information(self, "Live作画", "生成結果がまだありません")
            return
        try:
            self._applying = True
            self.model.live.is_active = False
            self._update_apply_enabled()
            bounds = params.bounds
            x, y = bounds.x, bounds.y
            width, height = bounds.width, bounds.height
            source = result._qimage.scaled(width, height, Qt.IgnoreAspectRatio,
                                           Qt.SmoothTransformation)
            image = source.convertToFormat(QImage.Format_ARGB32)
            mask = QImage(width, height, QImage.Format_ARGB32)
            mask.fill(Qt.transparent)
            painter = QPainter(mask)
            painter.setPen(Qt.NoPen)
            painter.setBrush(Qt.white)
            painter.drawPolygon(QPolygonF([QPointF(px - x, py - y)
                                           for px, py in self.panel["polygon"]]))
            painter.end()
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawImage(0, 0, mask)
            painter.end()
            layer = self.document.createNode("RT生成 · " + self.source_node.name(), "paintlayer")
            add_panel_artwork(group, layer, self.panel)
            layer.setPixelData(QByteArray(image_bytes(image)), x, y, width, height)
            self._applied = True
            self.document.setModified(True)
            self.document.refreshProjection()
            self.document.waitForDone()
            self.apply_button.setEnabled(False)
            # A modal confirmation runs a nested event loop before Krita finishes
            # registering the new layer's shape. Finish on the normal GUI loop.
            self._applied_layer = layer
            self._apply_timer = QTimer(self)
            self._apply_timer.setSingleShot(True)
            self._apply_timer.timeout.connect(self._finish_apply)
            self._apply_timer.start(0)
        except Exception as error:
            self._applying = False
            self._update_apply_enabled()
            QMessageBox.warning(self, "RT生成の反映", str(error))

    def _finish_apply(self):
        if self._closing:
            return
        self.sketch_layer.setVisible(False)
        # Leave selection untouched; the result is already visible in the original panel.
        self.close()

    def _cleanup_session(self):
        if self._closing:
            return
        self._save_layer_session()
        self._closing = True
        self.canvas.flush_timer.stop()
        self.canvas.flush()
        self._start_timer.stop()
        disconnect_live_widgets(self.live_ui)
        self.model.live.is_active = False
        self.model._prepare_live_workflow = self._original_prepare_live
        self._remove_reference()
        for slot in self.extra_references:
            slot.cleanup()
        if not self.canvas.has_strokes:
            self.sketch_layer.remove()
        self.document.setSelection(self.previous_selection)
        self.model.workspace = self._previous_workspace
        self._restore_rt_model()

    def done(self, result):
        # Escape/reject also needs to stop Live and restore the selection.
        self._cleanup_session()
        super().done(result)

    def closeEvent(self, event):
        self._cleanup_session()
        super().closeEvent(event)
