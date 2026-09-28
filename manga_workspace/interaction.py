"""Canvas selection bridge. Native drawing/move/transform keep their own events."""
import math
import time
from PyQt5.QtCore import QObject, QEvent, Qt, QPointF, QTimer
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QAbstractButton
from krita import Krita
from . import geometry

ARROW = 'InteractionTool'
BRUSH = 'KritaShape/KisToolBrush'
MOVE = 'KritaTransform/KisToolMove'
TRANSFORM = 'KisToolTransform'
PICKABLE_TYPES = ('paintlayer', 'vectorlayer', 'shapelayer', 'filelayer',
                  'filllayer', 'clonelayer')


def identity(node):
    return node.uniqueId().toString() if node else ''


def tool_name(main):
    # Qt widget names verified on Krita 5.2.14. No private C++ calls.
    return next((b.objectName() for b in main.findChildren(QAbstractButton)
                 if b.metaObject().className() == 'KoToolBoxButton' and b.isChecked()), '')


def editable(node):
    while node and node.type() != 'root':
        if node.locked() or not node.visible():
            return False
        node = node.parentNode()
    return True


def drawing_nodes(group, excluded):
    for child in reversed(group.childNodes()):
        if identity(child) in excluded or not child.visible():
            continue
        if child.type() == 'grouplayer':
            yield from drawing_nodes(child, excluded)
        elif child.type() in PICKABLE_TYPES:
            yield child


def pixel_hit(node, point):
    if not node.visible() or node.opacity() == 0 or not editable(node):
        return False
    # Krita returns native U8 channel bytes. These color models all keep
    # alpha as the final byte. Unknown layouts fall back to the layer bounds.
    channels = {'RGBA': 4, 'GRAYA': 2, 'CMYKA': 5, 'LABA': 4, 'XYZA': 4}
    size = channels.get(node.colorModel()) if node.colorDepth() == 'U8' else None
    if not size:
        return False
    x, y = int(math.floor(point[0])), int(math.floor(point[1]))
    if not node.bounds().contains(x, y):
        return False
    data = bytes(node.projectionPixelData(x, y, 1, 1))
    return len(data) == size and data[-1] != 0


def hit_layer(group, point, excluded):
    for child in reversed(group.childNodes()):
        if identity(child) in excluded or not pixel_hit(child, point):
            continue
        if child.type() == 'grouplayer':
            result = hit_layer(child, point, excluded)
            if result:
                return result
        elif child.type() in PICKABLE_TYPES:
            return child
    return None


class CanvasSelection(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.press = None
        self.last_node = None
        self.last_tool = None
        self.pending = None
        self.keep_arrow = False
        self.native_drag = False
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(200)

    def poll(self):
        try:
            window = Krita.instance().activeWindow()
            doc = window.activeView().document() if window and window.activeView() else None
            if not doc or doc != self.owner.document or window.qwindow() != self.owner.window():
                self.press = self.last_node = self.last_tool = None
                self.native_drag = False
                return
            tool = tool_name(window.qwindow())
            node = doc.activeNode()
            if self.pending:
                key, wanted, deadline = self.pending
                if key == self.owner.document_key() and identity(node) != wanted and time.monotonic() < deadline:
                    return
                self.pending = None
                if self.keep_arrow and identity(node) == wanted and tool == BRUSH:
                    Krita.instance().action(ARROW).trigger()
                    tool = ARROW
                self.keep_arrow = False
            if tool == BRUSH and self.last_tool == ARROW and self.owner.is_frame(node):
                self.owner.activate_drawing()
                node = doc.activeNode()
            key = (self.owner.document_key(), identity(node))
            if key != self.last_node:
                self.owner.sync_layer(node)
                self.last_node = key
            self.last_tool = tool
        except (RuntimeError, AttributeError):
            self.press = self.last_node = self.last_tool = None
        except ValueError as error:
            self.owner.status.setText(str(error))
            self.last_tool = tool

    def select_node(self, node, keep_arrow=None):
        window = Krita.instance().activeWindow()
        self.keep_arrow = bool(window and tool_name(window.qwindow()) == ARROW) if keep_arrow is None else keep_arrow
        self.pending = (self.owner.document_key(), identity(node), time.monotonic()+2)
        self.owner.document.setActiveNode(node)
        QTimer.singleShot(0, self.poll)

    def eventFilter(self, obj, event):
        typ = event.type()
        # Canvas painting, text confirmation, visibility changes and layer
        # reordering all end in a release/key event. Debounce them into one
        # panel-thumbnail update without rebuilding the layer tree.
        if typ in (QEvent.MouseButtonRelease, QEvent.TabletRelease, QEvent.KeyRelease):
            self.owner.schedule_thumbnail_refresh()
        if typ == QEvent.KeyPress or (typ == QEvent.MouseButtonPress and isinstance(obj, QAbstractButton)):
            # A deliberate tool switch takes precedence over restoring the arrow.
            self.keep_arrow = False
        if (typ == QEvent.MouseButtonPress and isinstance(obj, QAbstractButton)
                and obj.metaObject().className() == 'KoToolBoxButton'):
            # Never carry an unfinished arrow press into a newly selected
            # Krita toolbox tool. All following canvas events belong to Krita.
            self.press = None
            self.pending = None
            self.native_drag = False
            self.last_tool = None
            QTimer.singleShot(0, self.poll)
            return False
        pointer = (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease,
                   QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease)
        if typ not in pointer or obj.metaObject().className() not in ('KisOpenGLCanvas2', 'KisQPainterCanvas'):
            return False
        owner = self.owner
        window = Krita.instance().activeWindow()
        if (not window or obj.window() != owner.window() or owner.overlay
                or not window.activeView() or window.activeView().document() != owner.document):
            self.press = None
            self.native_drag = False
            return False
        if self.native_drag:
            if typ == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.native_drag = False
                # Let the native move tool commit the release before restoring
                # the arrow. The move remains in Krita's own Undo stack.
                QTimer.singleShot(0, lambda: Krita.instance().action(ARROW).trigger())
            return False
        if tool_name(window.qwindow()) != ARROW and not self.press:
            return False
        # Modifier/pan gestures remain native. A plain click is always layer
        # selection, including text/vector content, matching a manga editor's
        # canvas layer-selection tool.
        if not self.press and event.modifiers() != Qt.NoModifier:
            return False
        if typ in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease) and event.button() != Qt.LeftButton:
            return False
        view = window.activeView()
        inverse, ok = view.flakeToCanvasTransform().inverted()
        if not ok:
            return False
        pos = event.posF() if typ in (QEvent.TabletPress, QEvent.TabletMove, QEvent.TabletRelease) else event.localPos()
        point = view.flakeToImageTransform().map(inverse.map(pos))
        point = [point.x(), point.y()]
        inverse_image, ok = view.flakeToImageTransform().inverted()
        if not ok:
            return False
        # Map separately: QTransform multiplication ordering is easy to misread.
        a = view.flakeToCanvasTransform().map(inverse_image.map(QPointF(0, 0)))
        b = view.flakeToCanvasTransform().map(inverse_image.map(QPointF(1, 0)))
        scale = math.hypot(b.x()-a.x(), b.y()-a.y())
        try:
            if typ in (QEvent.MouseButtonPress, QEvent.TabletPress):
                target = owner.pick_canvas(point, scale)
                self.press = (point, target, owner.document_key(), QPointF(pos))
                self.last_tool = ARROW
            elif typ == QEvent.MouseMove and self.press:
                start, target, key, local_start = self.press
                distance = math.hypot(point[0]-start[0], point[1]-start[1])*scale
                if target and target.get('kind') == 'layer' and distance >= QApplication.startDragDistance():
                    node = target.get('node')
                    if node and editable(node):
                        self.press = None
                        owner.native_tool(MOVE)
                        self.native_drag = True
                        # The arrow consumed the original press so replay only
                        # that press to Krita's move tool. The current move and
                        # following release continue through the native tool.
                        QApplication.sendEvent(obj, QMouseEvent(
                            QEvent.MouseButtonPress, local_start,
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
                        return False
            elif typ in (QEvent.MouseButtonRelease, QEvent.TabletRelease):
                press, self.press = self.press, None
                if press and press[2] == owner.document_key() and press[1] and press[1].get('kind') == 'edge':
                    start, panel = press[0], press[1]['panel']
                    if math.hypot(point[0]-start[0], point[1]-start[1])*scale >= QApplication.startDragDistance():
                        owner.move_canvas_edge(panel, start, point)
            elif not self.press:
                return False
            event.accept()
            return True
        except Exception as error:
            self.press = None
            owner.status.setText(str(error))
            return True
