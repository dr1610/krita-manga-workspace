"""One-shot canvas placement without changing Krita's active native tool."""
import json
from krita import Krita
from PyQt5.QtCore import QObject, QEvent, Qt, QPointF, QMimeData
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import QApplication, QToolButton, QMessageBox
from .geometry import contains

MIME = 'application/x-manga-material'

class MaterialButton(QToolButton):
    def __init__(self, editor, name, word=False):
        super().__init__()
        self.editor, self.name, self.press = editor, name, None
        self.word = word

    def mousePressEvent(self, event):
        self.press = event.pos() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press is not None and event.buttons() & Qt.LeftButton and (event.pos()-self.press).manhattanLength() >= QApplication.startDragDistance():
            self.press = None
            self.setDown(False)
            if self.word: self.editor.choose_library_word(self.name)
            else: self.editor.select_preset(self.name)
            if self.editor.placement.arm():
                drag = QDrag(self)
                mime = QMimeData(); mime.setData(MIME, b'1'); drag.setMimeData(mime)
                drag.setPixmap(self.icon().pixmap(116,58))
                drag.exec_(Qt.CopyAction)
                self.editor.placement.cancel()
            return
        super().mouseMoveEvent(event)

class MaterialPlacement(QObject):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor, self.canvas, self.view, self.document = editor, None, None, None
        self.start = None

    def arm(self):
        self.cancel()
        if self.editor.current_kind == '描き文字' and not self.editor.text.text().strip():
            self.editor.text.setText(self.editor.preset_buttons[self.editor.current_preset].property('sample_text') or 'ドン')
            self.editor.library_word_selected = True
        window = Krita.instance().activeWindow()
        view = window.activeView() if window else None
        if not view:
            return False
        canvases = [w for w in QApplication.allWidgets() if w.isVisible() and
                    w.window() == window.qwindow() and not w.visibleRegion().isEmpty() and
                    w.metaObject().className() in ('KisOpenGLCanvas2','KisQPainterCanvas')]
        if len(canvases) != 1:
            return False
        for docker in window.dockers():
            if hasattr(docker, 'stop_tool'):
                docker.stop_tool()
        self.canvas, self.view, self.document = canvases[0], view, view.document()
        self.was_drops = self.canvas.acceptDrops()
        self.old_cursor = self.canvas.cursor()
        self.canvas.setAcceptDrops(True); self.canvas.setCursor(Qt.CrossCursor)
        QApplication.instance().installEventFilter(self)
        self.editor.target_hint.setText('原稿をクリックで配置／ドラッグで大きさ指定。Esc・右クリックで取消')
        return True

    def cancel(self):
        QApplication.instance().removeEventFilter(self)
        if self.canvas:
            try:
                self.canvas.setAcceptDrops(self.was_drops)
                self.canvas.setCursor(self.old_cursor)
            except RuntimeError:
                pass
        self.canvas = self.view = self.document = self.start = None

    def point(self, point):
        inverse, ok = self.view.flakeToCanvasTransform().inverted()
        if not ok: raise ValueError('Canvas座標を変換できません')
        point = self.view.flakeToImageTransform().map(inverse.map(QPointF(point)))
        return [point.x(),point.y()]

    def place(self, point):
        doc = self.document
        end = self.point(point)
        start = self.start or end
        raw = bytes(doc.annotation('manga_workspace/frames-v1'))
        panels = json.loads(raw).get('panels',[]) if raw else []
        panel = next((p for p in reversed(panels) if p.get('active',True) and contains(p['polygon'],start)),None)
        polygon = panel['polygon'] if panel else None
        if abs(start[0]-end[0])+abs(start[1]-end[1]) > 8:
            x,y = min(start[0],end[0]),min(start[1],end[1])
            w,h = abs(end[0]-start[0]),abs(end[1]-start[1])
        else:
            pw = max(p[0] for p in polygon)-min(p[0] for p in polygon) if polygon else doc.width()
            ph = max(p[1] for p in polygon)-min(p[1] for p in polygon) if polygon else doc.height()
            w,h = max(32,pw*.4),max(32,ph*.3)
            x,y = end[0]-w/2,end[1]-h/2
        w,h = min(doc.width(),max(32,w)),min(doc.height(),max(32,h))
        x,y = max(0,min(x,doc.width()-w)),max(0,min(y,doc.height()-h))
        self.cancel()
        self.editor.placement_override = ([round(x),round(y),round(w),round(h)],polygon,panel.get('node') if panel else None)
        try: self.editor.create_layer()
        finally: self.editor.placement_override = None

    def eventFilter(self, obj, event):
        try:
            return self.handle_event(obj,event)
        except Exception as error:
            self.cancel()
            QMessageBox.warning(self.editor,'素材配置',str(error))
            return True

    def handle_event(self, obj, event):
        kind = event.type()
        if not self.canvas: return False
        window = Krita.instance().activeWindow()
        if not window or window.activeView() != self.view or not self.editor.isVisible():
            self.cancel(); return False
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel(); return True
        if kind == QEvent.MouseButtonPress and obj.metaObject().className() == 'KoToolBoxButton':
            self.cancel(); return False
        if obj != self.canvas: return False
        if kind in (QEvent.DragEnter,QEvent.DragMove,QEvent.Drop):
            if event.mimeData().hasFormat(MIME) and isinstance(event.source(),MaterialButton) and event.source().editor == self.editor:
                event.acceptProposedAction()
                if kind == QEvent.Drop: self.place(event.pos())
                return True
            return False
        if kind in (QEvent.MouseButtonPress,QEvent.TabletPress):
            if kind == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                self.cancel(); return True
            if kind == QEvent.MouseButtonPress and event.button() != Qt.LeftButton:
                self.cancel(); return False
            self.start = self.point(event.pos()); return True
        if kind in (QEvent.MouseMove,QEvent.TabletMove): return True
        if kind in (QEvent.MouseButtonRelease,QEvent.TabletRelease):
            if self.start is not None: self.place(event.pos())
            return True
        return False
