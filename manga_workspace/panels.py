"""Explicit frame tool; only intercepts the canvas while the user enables it."""
import json
import math
from copy import deepcopy
from uuid import uuid4
from krita import Krita, DockWidget, Selection
from PyQt5.QtCore import Qt, QPointF, QEvent, QTimer, QByteArray, QSize
from PyQt5.QtGui import QPainter, QPen, QColor, QPolygonF, QImage, QPixmap, QIcon, QPainterPath
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                            QComboBox, QDoubleSpinBox, QListWidget, QListWidgetItem, QMessageBox, QApplication,
                            QToolButton, QMenu, QCheckBox, QSizePolicy, QBoxLayout, QDockWidget)
from .theme import apply_panel_theme
from . import geometry
from .interaction import (CanvasSelection, identity, drawing_nodes, editable,
                          hit_layer, BRUSH, MOVE, TRANSFORM, PICKABLE_TYPES)

KEY = "manga_workspace/frames-v1"
PANEL_COLOR_LABEL = 3


def node_by_id(document, identity):
    def walk(node):
        if node.uniqueId().toString() == identity:
            return node
        for child in node.childNodes():
            result = walk(child)
            if result:
                return result
    return walk(document.rootNode())


def image_bytes(image):
    ptr = image.constBits()
    ptr.setsize(image.byteCount())
    return bytes(ptr)


class FrameOverlay(QWidget):
    def __init__(self, canvas, owner, view, passive=False):
        super().__init__(canvas)
        self.owner, self.view = owner, view
        self.start = self.end = None
        self.passive = passive
        self.setAttribute(Qt.WA_TransparentForMouseEvents, passive)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TabletTracking)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(canvas.rect())
        canvas.installEventFilter(self)
        self.show()
        self.raise_()
        if not passive:
            self.setFocus()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(100)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def to_doc(self, p):
        inverse, ok = self.view.flakeToCanvasTransform().inverted()
        if not ok:
            raise ValueError("Canvas座標を変換できません")
        p = self.view.flakeToImageTransform().map(inverse.map(p))
        return [p.x(), p.y()]

    def to_canvas(self, p):
        inverse, ok = self.view.flakeToImageTransform().inverted()
        return self.view.flakeToCanvasTransform().map(inverse.map(QPointF(*p)))

    def begin(self, p):
        self.start = self.end = self.to_doc(p)
        self.update()

    def finish(self, p):
        if self.start is not None:
            a, b = self.start, self.to_doc(p)
            self.start = self.end = None
            self.owner.gesture(a, b)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.begin(event.localPos())
        elif event.button() == Qt.RightButton:
            self.owner.stop_tool()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = self.to_doc(event.localPos())
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.finish(event.localPos())
        event.accept()

    def tabletEvent(self, event):
        if event.type() == QEvent.TabletPress:
            self.begin(event.posF())
        elif event.type() == QEvent.TabletMove and self.start is not None:
            self.end = self.to_doc(event.posF())
            self.update()
        elif event.type() == QEvent.TabletRelease:
            self.finish(event.posF())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.owner.stop_tool()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        current = self.owner.current()
        for panel in ([current] if self.passive and current else [] if self.passive else self.owner.active_panels()):
            selected = current and panel["id"] == current["id"]
            painter.setPen(QPen(QColor("#36bcff" if selected else "#8095a0"), 3 if selected else 1, Qt.DashLine))
            painter.drawPolygon(QPolygonF([self.to_canvas(p) for p in panel["polygon"]]))
        if self.start is not None:
            a, b = self.to_canvas(self.start), self.to_canvas(self.end)
            if self.owner.mode.currentIndex() == 0:
                x0,y0 = self.start
                x1,y1 = self.end
                painter.drawPolygon(QPolygonF([self.to_canvas(p) for p in
                                               [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]]))
            elif self.owner.mode.currentIndex() == 3:
                try:
                    poly = self.owner.boundary_polygon(self.start, self.end)
                    painter.drawPolygon(QPolygonF([self.to_canvas(p) for p in poly]))
                except ValueError:
                    pass
            else:
                painter.drawLine(a,b)
        painter.end()


class PanelDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("コマ割り")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(self.features() | QDockWidget.DockWidgetMovable |
                         QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.document = None
        self.data = None
        self.overlay = None
        self.highlight = None
        self.selection_by_document = {}
        self.drawing_by_panel = {}
        body = QWidget()
        apply_panel_theme(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(5,4,5,4)
        layout.setSpacing(3)
        top = QHBoxLayout()
        self.controls_layout = top
        self.status = QLabel("コマを選択")
        self.status.setMinimumWidth(120)
        top.addWidget(self.status)
        self.mode = QComboBox()
        self.mode.addItems(["枠を描く", "枠を分割", "コマを選択して描画", "境界を移動"])
        self.mode.setMaximumWidth(210)
        self.tool = QPushButton("操作開始")
        self.tool.setCheckable(True)
        self.tool.toggled.connect(self.toggle_tool)
        top.addWidget(self.mode)
        top.addWidget(self.tool)
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 100)
        self.gap.setValue(3)
        self.gap.setSuffix(" mm")
        self.gap.setMaximumWidth(95)
        self.line = QDoubleSpinBox()
        self.line.setRange(.05, 10)
        self.line.setValue(.5)
        self.line.setSuffix(" mm")
        self.line.setMaximumWidth(95)
        for title, control in [("コマ間隔", self.gap), ("枠線の太さ", self.line)]:
            top.addWidget(QLabel(title))
            top.addWidget(control)
        self.show_frame = QCheckBox("選択枠を表示")
        self.show_frame.setChecked(True)
        self.show_frame.toggled.connect(lambda _: self.update_highlight())
        top.addWidget(self.show_frame)
        top.addStretch(1)
        layout.addLayout(top)
        content = QHBoxLayout()
        self.content_layout = content
        content.setSpacing(5)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(86,66))
        self.list.setGridSize(QSize(98,88))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setMinimumHeight(92)
        self.list.currentRowChanged.connect(lambda row: self.run(lambda: self.select_panel(row, True)))
        self.list.itemDoubleClicked.connect(lambda item: self.run(self.draw_selected))
        content.addWidget(self.list, 1)
        actions = QVBoxLayout()
        self.actions_layout = actions
        actions.setSpacing(3)
        draw = QPushButton("このコマに描く")
        draw.clicked.connect(lambda: self.run(self.draw_selected))
        actions.addWidget(draw)
        native = QHBoxLayout()
        for title, action in [("画像を移動", MOVE), ("画像を変形", TRANSFORM)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, a=action: self.run(lambda: self.native_tool(a)))
            native.addWidget(button)
        actions.addLayout(native)
        more = QToolButton()
        more.setText("枠の作成・調整・復元…")
        more.setToolTip("基本枠、選択範囲、間隔、分割の復元")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        for title, fn in [("現在のコマを縦4列に分割", lambda: self.grid_split(4, 1)),
                          ("現在のコマを横4段に分割", lambda: self.grid_split(1, 4)),
                          ("現在のコマを2×2に分割", lambda: self.grid_split(2, 2)),
                          ("選択範囲に枠を作成", self.from_selection),
                          ("基本枠を作成", self.basic_frame),
                          ("選択した分割の間隔を適用", self.adjust_gap),
                          ("直前の境界・間隔変更を戻す", self.undo_geometry),
                          ("直前の分割を戻す（描画を保持）", self.restore_split),
                          ("サムネイル更新", self.refresh)]:
            menu.addAction(title, lambda checked=False, f=fn: self.run(f))
        more.setMenu(menu)
        actions.addWidget(more)
        actions.addStretch(1)
        content.addLayout(actions)
        layout.addLayout(content, 1)
        self.tool.setToolTip("ドラッグで枠・分割・境界を操作。Escで作画に戻ります")
        body.setMinimumHeight(145)
        self.setWidget(body)
        self.visibilityChanged.connect(self.visibility_changed)
        self.dockLocationChanged.connect(self.set_dock_orientation)
        self.topLevelChanged.connect(lambda _: QTimer.singleShot(0, self.sync_dock_orientation))
        self.selection_bridge = CanvasSelection(self)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.update_thumbnails)

    def set_dock_orientation(self, area):
        vertical = area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)
        self.controls_layout.setDirection(QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight)
        self.content_layout.setDirection(QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight)
        self.actions_layout.setDirection(QBoxLayout.TopToBottom)
        if vertical:
            self.list.setMinimumHeight(240)
            self.list.setMinimumWidth(150)
            self.list.setGridSize(QSize(98, 88))
        else:
            self.list.setMinimumHeight(92)
            self.list.setMinimumWidth(0)
            self.list.setGridSize(QSize(98, 88))
        self.widget().updateGeometry()

    def sync_dock_orientation(self):
        window = Krita.instance().activeWindow()
        main = window.qwindow() if window else None
        area = main.dockWidgetArea(self) if main else Qt.NoDockWidgetArea
        if area == Qt.NoDockWidgetArea:
            area = Qt.LeftDockWidgetArea if self.height() > self.width() else Qt.BottomDockWidgetArea
        self.set_dock_orientation(area)

    def visibility_changed(self, visible):
        if not visible:
            self.stop_tool()
        self.update_highlight()

    def canvas_widget(self):
        window = Krita.instance().activeWindow()
        if not window:
            return None, None
        view = window.activeView()
        canvases = [w for w in QApplication.allWidgets() if w.isVisible()
                    and w.window() == window.qwindow() and not w.visibleRegion().isEmpty()
                    and w.metaObject().className() in ("KisOpenGLCanvas2", "KisQPainterCanvas")]
        return (canvases[0], view) if len(canvases) == 1 else (None, view)

    def update_highlight(self):
        if self.highlight:
            self.highlight.hide()
            self.highlight.deleteLater()
            self.highlight = None
        if self.isVisible() and self.show_frame.isChecked() and self.current() and not self.overlay:
            widget, view = self.canvas_widget()
            if widget and view and view.document() == self.document:
                self.highlight = FrameOverlay(widget,self,view,True)

    def run(self, fn):
        try:
            if not self.document or self.data is None:
                raise ValueError("編集可能な原稿を開いてください")
            fn()
        except Exception as error:
            self.status.setText(str(error))

    def canvasChanged(self, canvas):
        self.stop_tool()
        self.document = canvas.view().document() if canvas and canvas.view() else None
        self.data = None
        try:
            if self.document:
                try:
                    page_settings=json.loads(bytes(self.document.annotation("manga_workspace/page-settings-v1")))
                    self.line.setValue(page_settings.get("frame_line_mm",self.line.value()))
                    self.gap.setValue(page_settings.get("panel_gap_mm",self.gap.value()))
                except Exception:
                    pass
                raw = bytes(self.document.annotation(KEY))
                self.data = json.loads(raw) if raw else {"version": 1, "panels": [], "history": []}
                if self.data.get("version") != 1 or not isinstance(self.data.get("panels"), list):
                    raise ValueError("コマ情報の形式が未対応です。元データを保持します")
                if self.reconcile_group_names():
                    self.save_annotation()
                self.status.setText("コマを選択")
        except Exception as error:
            self.data = None
            self.status.setText(str(error))
        self.refresh()
        QTimer.singleShot(0, self.update_highlight)

    def active_panels(self):
        if not self.document or not self.data:
            return []
        return [p for p in self.data["panels"] if p.get("active", True)
                and node_by_id(self.document, p["node"])]

    def refresh(self):
        identity = self.selection_by_document.get(self.document_key()) if self.document else None
        self.list.blockSignals(True)
        self.list.clear()
        thumb = self.document.thumbnail(640,640) if self.document and self.active_panels() else None
        for i, panel in enumerate(self.active_panels()):
            item = QListWidgetItem("コマ %02d" % (i+1))
            item.setData(Qt.UserRole, panel["id"])
            group = node_by_id(self.document, panel["node"])
            item.setToolTip("%s\nクリックでこのコマの描画レイヤーを選択" % group.name())
            self.set_thumbnail(item, panel, thumb)
            self.list.addItem(item)
            if panel["id"] == identity:
                self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentRow()<0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.select_panel(self.list.currentRow())

    def set_thumbnail(self, item, panel, thumb):
        if not thumb or thumb.isNull() or not self.document:
            return
        sx, sy = thumb.width()/self.document.width(), thumb.height()/self.document.height()
        points = QPolygonF([QPointF(p[0]*sx, p[1]*sy) for p in panel["polygon"]])
        bounds = points.boundingRect().toAlignedRect().intersected(thumb.rect())
        if bounds.isEmpty():
            return
        clipped = QImage(thumb.size(), QImage.Format_ARGB32)
        clipped.fill(Qt.transparent)
        painter = QPainter(clipped)
        path = QPainterPath()
        path.addPolygon(points)
        painter.setClipPath(path)
        painter.drawImage(0, 0, thumb)
        painter.setPen(QPen(QColor("#78909c"), 1))
        painter.drawPolygon(points)
        painter.end()
        item.setIcon(QIcon(QPixmap.fromImage(clipped.copy(bounds))))

    def schedule_thumbnail_refresh(self, delay=450):
        if self.document and self.data is not None and self.isVisible():
            self.thumbnail_timer.start(delay)

    def update_thumbnails(self):
        """Refresh rendered panel previews without changing current selection."""
        if not self.document or self.data is None or not self.isVisible():
            return
        panels = {panel["id"]: panel for panel in self.active_panels()}
        if not panels:
            return
        thumb = self.document.thumbnail(640, 640)
        for row in range(self.list.count()):
            item = self.list.item(row)
            panel = panels.get(item.data(Qt.UserRole))
            if panel:
                self.set_thumbnail(item, panel, thumb)
        self.list.viewport().update()

    def current(self):
        item = self.list.currentItem()
        return next((p for p in self.active_panels() if item and p["id"] == item.data(Qt.UserRole)), None)

    def document_key(self):
        return (self.document.fileName(), identity(self.document.rootNode())) if self.document else None

    def select_panel(self, row, activate=False):
        panel = self.current()
        if panel:
            self.selection_by_document[self.document_key()] = panel["id"]
            self.status.setText("現在のコマ：%d / %d" % (row+1,self.list.count()))
            if activate:
                self.activate_drawing()
        else:
            self.status.setText("コマはありません。基本枠を作成できます")
        self.update_highlight()

    def save_annotation(self):
        self.document.setAnnotation(KEY, "漫画コマ枠", QByteArray(json.dumps(self.data).encode("utf-8")))
        self.document.setModified(True)

    def reconcile_group_names(self):
        """Number managed frame folders without taking over user-renamed folders."""
        if not self.document or not self.data:
            return False
        changed = False
        number = 0
        for panel in self.data["panels"]:
            group = node_by_id(self.document, panel["node"])
            if not group:
                continue
            if panel.get("active", True):
                number += 1
                desired = "コマ %02d" % number
            else:
                previous = panel.get("managed_name", "コマ " + panel["id"][:8])
                if previous.startswith("分割前｜"):
                    previous = previous[len("分割前｜"):]
                desired = "分割前｜" + previous
            managed = panel.get("managed_name")
            legacy = "コマ " + panel["id"][:8]
            is_managed = group.name() == managed if managed is not None else group.name() == legacy
            if not is_managed:
                # Krita's layer docker permits renaming; preserve those edits.
                continue
            if group.name() != desired:
                group.setName(desired)
                changed = True
            if managed != desired:
                panel["managed_name"] = desired
                changed = True
            if not panel.get("color_label_initialized"):
                if group.colorLabel() == 0:
                    group.setColorLabel(PANEL_COLOR_LABEL)
                panel["color_label_initialized"] = True
                changed = True
        return changed

    def persist(self):
        self.reconcile_group_names()
        self.save_annotation()
        self.document.refreshProjection()
        self.refresh()
        for widget in QApplication.allWidgets():
            if widget.objectName() == "manga_page_guide_overlay":
                widget.update()

    def create_frame(self, poly, source=None):
        doc = self.document
        if doc.colorModel() != "RGBA" or doc.colorDepth() != "U8":
            raise ValueError("現在のコマ枠描画はRGB/Alpha・8bit原稿に対応しています")
        identity = str(uuid4())
        initial_name = "コマ " + identity[:8]
        group = doc.createGroupLayer(initial_name)
        doc.rootNode().addChildNode(group, None)
        try:
            if source:
                old = node_by_id(doc, source["node"])
                if not old:
                    raise ValueError("元コマのレイヤーが見つかりません")
                for child in old.childNodes():
                    if child.uniqueId().toString() not in (source["mask"], source["frame"]):
                        group.addChildNode(child.duplicate(), None)
            if not group.childNodes():
                group.addChildNode(doc.createNode("描画", "paintlayer"), None)
            width = self.line.value() * doc.resolution() / 25.4
            mask, frame = self.build_shape(poly, group, width)
            return {"id":identity,"polygon":poly,"node":group.uniqueId().toString(),
                    "mask":mask.uniqueId().toString(),"frame":frame.uniqueId().toString(),
                    "active":True,"width":width,"managed_name":initial_name}
        except Exception:
            group.remove()
            raise

    def add(self, polygon):
        self.data["panels"].append(self.create_frame(polygon))
        self.persist()
        self.list.setCurrentRow(self.list.count()-1)

    def grid_split(self, columns, rows):
        """Split the current panel into an evenly spaced reversible grid."""
        parent = self.current()
        if not parent:
            raise ValueError("分割するコマを選択してください")
        polygon = parent["polygon"]
        left = min(point[0] for point in polygon)
        top = min(point[1] for point in polygon)
        right = max(point[0] for point in polygon)
        bottom = max(point[1] for point in polygon)
        gap = self.gap.value() * self.document.resolution() / 25.4
        cell_width = (right - left - gap * (columns - 1)) / columns
        cell_height = (bottom - top - gap * (rows - 1)) / rows
        if cell_width <= 2 or cell_height <= 2:
            raise ValueError("コマが小さすぎるため、この分割を適用できません")
        created = []
        try:
            for row in range(rows):
                for column in range(columns):
                    x1 = left + column * (cell_width + gap)
                    y1 = top + row * (cell_height + gap)
                    x2, y2 = x1 + cell_width, y1 + cell_height
                    poly = geometry.rectangle([x1, y1], [x2, y2],
                                              self.document.width(), self.document.height())
                    created.append(self.create_frame(poly, parent))
        except Exception:
            for child in created:
                node = node_by_id(self.document, child["node"])
                if node:
                    node.remove()
            raise
        node_by_id(self.document, parent["node"]).setVisible(False)
        parent["active"] = False
        self.data["panels"].extend(created)
        self.data["history"].append({
            "parent": parent["id"], "children": [child["id"] for child in created],
            "gap": self.gap.value(), "operation": str(uuid4()),
            "preset": {"columns": columns, "rows": rows},
        })
        self.data["geometry_history"] = []
        self.persist()
        self.list.setCurrentRow(max(0, self.list.count() - len(created)))
        self.status.setText("現在のコマを%d列×%d段に分割しました" % (columns, rows))

    def from_selection(self):
        s = self.document.selection()
        if not s:
            raise ValueError("矩形選択で枠の範囲を指定してください")
        self.add(geometry.rectangle([s.x(),s.y()], [s.x()+s.width(),s.y()+s.height()],self.document.width(),self.document.height()))

    def basic_frame(self):
        doc = self.document
        try:
            settings = json.loads(bytes(doc.annotation("manga_workspace/page-settings-v1")))
            rect = settings.get("basic_frame_px")
        except Exception:
            rect = None
        if rect and len(rect) == 4:
            self.add(geometry.rectangle(rect[:2],rect[2:],doc.width(),doc.height()))
        else:
            margin = min(doc.width(),doc.height()) * .06
            self.add(geometry.rectangle([margin,margin], [doc.width()-margin,doc.height()-margin],doc.width(),doc.height()))

    def gesture(self, a, b):
        def execute():
            if self.mode.currentIndex() == 0:
                self.add(geometry.rectangle(a,b,self.document.width(),self.document.height()))
            elif self.mode.currentIndex() == 2:
                found = next((p for p in reversed(self.active_panels()) if geometry.contains(p["polygon"],a)),None)
                if found:
                    self.list.setCurrentRow(self.active_panels().index(found))
                    self.draw_selected()
            elif self.mode.currentIndex() == 3:
                panel = self.current()
                poly = self.boundary_polygon(a,b)
                self.change_geometry([(panel,poly)])
            else:
                targets = [p for p in self.active_panels() if geometry.segment_crosses(p["polygon"],a,b)]
                if not targets:
                    raise ValueError("分割線をコマの外から外まで横切るように引いてください")
                staged = []
                try:
                    for panel in targets:
                        parts = geometry.split(panel["polygon"],a,b,self.gap.value()*self.document.resolution()/25.4)
                        created = []
                        staged.append((panel,created))
                        for poly in parts:
                            created.append(self.create_frame(poly,panel))
                except Exception:
                    for panel, created in staged:
                        for p in created:
                            node = node_by_id(self.document,p["node"])
                            if node:
                                node.remove()
                    raise
                operation = str(uuid4())
                for panel, created in staged:
                    node_by_id(self.document,panel["node"]).setVisible(False)
                    panel["active"] = False
                    self.data["panels"].extend(created)
                    self.data["history"].append({"parent":panel["id"],"children":[p["id"] for p in created],
                                                 "line":[a,b],"gap":self.gap.value(),"operation":operation})
                self.data["geometry_history"] = []
                self.persist()
                self.status.setText("%dコマを分割しました。元コマは非表示で保持しています" % len(targets))
        self.run(execute)

    def restore_split(self):
        if not self.data["history"]:
            return
        last = self.data["history"][-1]
        operation = last.get("operation")
        records = []
        for record in reversed(self.data["history"]):
            if records and (not operation or record.get("operation") != operation):
                break
            records.append(record)
            if not operation:
                break
        all_relevant = []
        for record in records:
            relevant = [p for p in self.data["panels"] if p["id"] in [record["parent"]]+record["children"]]
            if (any(not node_by_id(self.document,p["node"]) for p in relevant) or
                    len(relevant) != 1 + len(record["children"])):
                raise ValueError("対象レイヤーが変更されています。レイヤーパネルで確認してください")
            all_relevant.append((record,relevant))
        for record, relevant in all_relevant:
            for p in relevant:
                p["active"] = p["id"] == record["parent"]
                node_by_id(self.document,p["node"]).setVisible(p["active"])
        del self.data["history"][-len(records):]
        self.data["geometry_history"] = []
        self.persist()

    def draw_selected(self):
        self.activate_drawing()
        self.native_tool(BRUSH)

    def is_frame(self, node):
        return any(identity(node) == p['frame'] for p in self.active_panels())

    def panel_for_node(self, node):
        groups = {p['node']: p for p in self.active_panels()}
        while node:
            if identity(node) in groups:
                return groups[identity(node)]
            node = node.parentNode()
        return None

    def sync_layer(self, node):
        panel = self.panel_for_node(node)
        if not panel:
            # A normal layer-panel operation may move the active layer out of
            # a panel group. Reflect that immediately instead of leaving a
            # stale panel highlight that suggests a different edit target.
            self.list.blockSignals(True)
            self.list.setCurrentRow(-1)
            self.list.blockSignals(False)
            self.selection_by_document.pop(self.document_key(), None)
            self.update_highlight()
            if node:
                self.status.setText('ページ上のレイヤー：' + node.name())
            return
        if node.type() in PICKABLE_TYPES and identity(node) != panel['frame'] and editable(node):
            self.drawing_by_panel[(self.document_key(), panel['id'])] = identity(node)
        self.list.blockSignals(True)
        self.list.setCurrentRow(self.active_panels().index(panel))
        self.list.blockSignals(False)
        self.select_panel(self.list.currentRow())
        kind = '枠' if identity(node) == panel['frame'] else node.name()
        self.status.setText('現在のコマ：%d / %d ｜ %s' % (self.list.currentRow()+1, self.list.count(), kind))

    def activate_drawing(self):
        panel = self.current()
        if not panel:
            return
        group = node_by_id(self.document, panel['node'])
        candidates = [n for n in drawing_nodes(group, {panel['frame'], panel['mask']})
                      if n.type() in PICKABLE_TYPES and editable(n)]
        remembered = self.drawing_by_panel.get((self.document_key(), panel['id']))
        drawing = next((n for n in candidates if identity(n) == remembered), candidates[0] if candidates else None)
        if not drawing:
            raise ValueError('このコマに表示中・ロック解除済みの描画レイヤーがありません')
        self.selection_bridge.select_node(drawing)
        self.sync_layer(drawing)

    def native_tool(self, action):
        node = self.document.activeNode()
        pending = self.selection_bridge.pending
        if pending and pending[0] == self.document_key():
            node = node_by_id(self.document, pending[1])
        if self.is_frame(node) and action != BRUSH:
            raise ValueError('枠は矢印で辺をドラッグして編集します。画像は画像部分を選択してください')
        if not node or not editable(node):
            raise ValueError('選択レイヤーが非表示またはロックされています。レイヤーパネルで確認してください')
        self.stop_tool()
        native = Krita.instance().action(action)
        if not native:
            raise ValueError('このKritaでは標準ツールを利用できません')
        native.trigger()
        widget, view = self.canvas_widget()
        if widget:
            widget.setFocus()

    def pick_canvas(self, point, scale):
        panels = self.active_panels()
        visible = [p for p in panels if node_by_id(self.document, p['node']).visible()]
        distances = [(geometry.nearest_edge(p['polygon'], point)[1]*scale, p) for p in visible]
        edge = min(distances, key=lambda item:item[0]) if distances else None
        panel = edge[1] if edge and edge[0] <= 6 else next((p for p in reversed(visible) if geometry.contains(p['polygon'], point)), None)
        excluded = {p[k] for p in self.data['panels'] for k in ('frame', 'mask')}
        if edge and edge[0] <= 6:
            node = node_by_id(self.document, panel['frame'])
            self.selection_bridge.select_node(node)
            self.sync_layer(node)
            self.status.setText('現在のコマ：%d ｜ 枠を選択。辺をドラッグで移動／Bで描画' % (panels.index(panel)+1))
            return {'kind': 'edge', 'panel': panel}
        # Traverse the complete visible stack, including standalone imported images.
        node = hit_layer(self.document.rootNode(), point, excluded)
        if node:
            node_panel = self.panel_for_node(node)
            if node_panel and not geometry.contains(node_panel['polygon'], point):
                node = None
        bottom = self.document.rootNode().childNodes()[0] if self.document.rootNode().childNodes() else None
        if node and identity(node) != identity(bottom):
            self.selection_bridge.select_node(node)
            self.sync_layer(node)
            if not self.panel_for_node(node):
                self.list.blockSignals(True)
                self.list.setCurrentRow(-1)
                self.list.blockSignals(False)
                self.selection_by_document.pop(self.document_key(), None)
                self.update_highlight()
                self.status.setText('ページ上の画像：' + node.name())
            else:
                self.status.setText('画像：%s ｜ ドラッグで移動／クリックで選択' % node.name())
            return {'kind': 'layer', 'node': node}
        elif panel:
            self.list.blockSignals(True)
            self.list.setCurrentRow(panels.index(panel))
            self.list.blockSignals(False)
            self.select_panel(self.list.currentRow(), True)
        return None

    def move_canvas_edge(self, panel, a, b):
        if not editable(node_by_id(self.document, panel['node'])):
            raise ValueError('このコマのグループはロックされています')
        index = geometry.nearest_edge(panel['polygon'], a)[0]
        poly = geometry.move_edge(panel['polygon'], index, [b[0]-a[0], b[1]-a[1]], self.document.width(), self.document.height())
        if any(geometry.overlap(poly, p['polygon']) > 1 for p in self.active_panels() if p['id'] != panel['id']):
            raise ValueError('隣のコマと重なるため移動できません')
        self.change_geometry([(panel, poly)])
        self.selection_bridge.select_node(node_by_id(self.document, panel['frame']), keep_arrow=True)
        self.status.setText('境界を変更しました。⋯ →「直前の境界・間隔変更を戻す」で復元できます')

    def toggle_tool(self, enabled):
        if not enabled:
            self.stop_tool()
            return
        try:
            widget, view = self.canvas_widget()
            if not view or self.data is None:
                raise ValueError("原稿を開いてください")
            if not widget:
                raise ValueError("Canvasを特定できません。単一の原稿タブで操作してください")
            self.overlay = FrameOverlay(widget,self,view)
            self.update_highlight()
            self.tool.setText("終了")
        except Exception as error:
            self.status.setText(str(error))
            self.stop_tool()

    def stop_tool(self):
        if self.overlay:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None
        self.tool.blockSignals(True)
        self.tool.setChecked(False)
        self.tool.setText("操作開始")
        self.tool.blockSignals(False)
        QTimer.singleShot(0, self.update_highlight)

    def boundary_polygon(self, a, b):
        panel = self.current()
        if not panel:
            raise ValueError("移動するコマを選択してください")
        index, distance = geometry.nearest_edge(panel["polygon"], a)
        # Hit tolerance is in screen pixels, independent of zoom.
        scale = 1
        if self.overlay:
            p,q = self.overlay.to_canvas([0,0]),self.overlay.to_canvas([1,0])
            scale = math.hypot(p.x()-q.x(),p.y()-q.y())
        if distance*scale > 20:
            raise ValueError("選択コマの辺からドラッグしてください")
        poly = geometry.move_edge(panel["polygon"],index,[b[0]-a[0],b[1]-a[1]],self.document.width(),self.document.height())
        if any(geometry.overlap(poly,p["polygon"])>1 for p in self.active_panels() if p["id"]!=panel["id"]):
            raise ValueError("隣のコマと重なるため移動できません")
        return poly

    def change_geometry(self, changes, record=True):
        staged = []
        before = [{"id":p["id"],"polygon":deepcopy(p["polygon"])} for p,poly in changes]
        try:
            for panel, poly in changes:
                group = node_by_id(self.document,panel["node"])
                oldmask, oldframe = node_by_id(self.document,panel["mask"]),node_by_id(self.document,panel["frame"])
                if not group or not oldmask or not oldframe:
                    raise ValueError("枠レイヤーが変更されています。操作を中止しました")
                width = panel.get("width", self.line.value()*self.document.resolution()/25.4)
                mask,frame = self.build_shape(poly,group,width)
                staged.append((panel,poly,mask,frame,oldmask,oldframe))
        except Exception:
            for p,poly,mask,frame,oldmask,oldframe in staged:
                mask.remove()
                frame.remove()
            raise
        for panel,poly,mask,frame,oldmask,oldframe in staged:
            oldmask.remove()
            oldframe.remove()
            panel.update(polygon=poly,mask=mask.uniqueId().toString(),frame=frame.uniqueId().toString())
        if record:
            self.data.setdefault("geometry_history",[]).append(before)
        self.persist()

    def undo_geometry(self):
        history = self.data.get("geometry_history",[])
        if not history:
            raise ValueError("戻せる境界・間隔変更はありません")
        active = {p["id"]:p for p in self.active_panels()}
        before = history[-1]
        if any(p["id"] not in active for p in before):
            raise ValueError("対象コマが変更されているため復元できません")
        self.change_geometry([(active[p["id"]],p["polygon"]) for p in before],False)
        gap = before[0].get("split_gap")
        if gap:
            for split in self.data["history"]:
                if split["parent"] == gap["parent"]:
                    split["gap"] = gap["gap"]
        history.pop()
        self.persist()

    def adjust_gap(self):
        current = self.current()
        record = next((r for r in reversed(self.data["history"]) if current and current["id"] in r["children"]),None)
        active = {p["id"]:p for p in self.active_panels()}
        if not record or not record.get("line") or any(i not in active for i in record["children"]):
            raise ValueError("この版で分割した、両側が残っているコマを選択してください")
        parent = next(p for p in self.data["panels"] if p["id"]==record["parent"])
        polys = geometry.split(parent["polygon"],*record["line"],self.gap.value()*self.document.resolution()/25.4)
        # Do not erase later independent boundary edits by recomputing from parent.
        previous = geometry.split(parent["polygon"],*record["line"],record["gap"]*self.document.resolution()/25.4)
        if any(active[i]["polygon"] != poly for i,poly in zip(record["children"],previous)):
            raise ValueError("境界が変更済みです。境界変更を戻してから間隔を変更してください")
        oldgap = record["gap"]
        self.change_geometry([(active[i],poly) for i,poly in zip(record["children"],polys)])
        self.data["geometry_history"][-1][0]["split_gap"] = {"parent":record["parent"],"gap":oldgap}
        record["gap"] = self.gap.value()
        self.persist()

    def build_shape(self, poly, group, width):
        doc = self.document
        x = max(0, math.floor(min(p[0] for p in poly)-width-2))
        y = max(0, math.floor(min(p[1] for p in poly)-width-2))
        w = min(doc.width(), math.ceil(max(p[0] for p in poly)+width+2))-x
        h = min(doc.height(), math.ceil(max(p[1] for p in poly)+width+2))-y
        if w*h > 100_000_000:
            raise ValueError("コマ領域が大きすぎます。1億画素以下にしてください")
        points = QPolygonF([QPointF(p[0]-x, p[1]-y) for p in poly])
        mask_image = QImage(w,h,QImage.Format_Grayscale8)
        mask_image.fill(0)
        painter = QPainter(mask_image)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawPolygon(points)
        painter.end()
        raw = image_bytes(mask_image)
        stride = mask_image.bytesPerLine()
        packed = b"".join(raw[i*stride:i*stride+w] for i in range(h))
        selection = Selection()
        selection.setPixelData(QByteArray(packed), x,y,w,h)
        mask = doc.createTransparencyMask("コマ外を隠す")
        group.addChildNode(mask, None)
        mask.setSelection(selection)
        frame = doc.createNode("枠線", "paintlayer")
        group.addChildNode(frame, None)
        image = QImage(w,h,QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        # Mask clips the outside half, leaving the requested width inside.
        painter.setPen(QPen(Qt.black, 2*width, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        painter.drawPolygon(points)
        painter.end()
        frame.setPixelData(QByteArray(image_bytes(image)),x,y,w,h)
        frame.setLocked(True)
        return mask, frame
