from pathlib import Path
import json
import os
import zipfile
from uuid import uuid4
from krita import Krita, DockWidget
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal, QByteArray, QPointF, QEvent, QRectF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                            QListWidget, QListWidgetItem, QAbstractItemView,
                            QFileDialog, QMessageBox, QSizePolicy, QToolButton, QMenu, QApplication, QRubberBand,
                            QCheckBox, QDialog, QFormLayout, QDialogButtonBox, QComboBox,
                            QDoubleSpinBox, QSpinBox)
from . import project
from .compact import scroll_content
from .theme import apply_panel_theme

PAGE_SETTINGS_KEY = "manga_workspace/page-settings-v1"
FRAME_SETTINGS_KEY = "manga_workspace/frames-v1"
AI_SETTINGS_KEY = "manga_workspace/v1"
DERIVED_PAGE_KEYS = {"page_number","paper_px","bleed_px","finish_px","basic_frame_px","resize_canvas"}


def has_active_frames(document):
    """Whether this page already has a usable panel layout annotation."""
    try:
        raw=bytes(document.annotation(FRAME_SETTINGS_KEY))
        value=json.loads(raw) if raw else None
        return bool(value and any(panel.get("active",True) for panel in value.get("panels",[])))
    except Exception:
        return False


def mm_to_px(value, dpi):
    return round(value*dpi/25.4)


def common_page_settings(value):
    """Return only the reusable project-wide settings, never per-page pixel results."""
    return {key:value[key] for key in value if key not in DERIVED_PAGE_KEYS}


def validate_page_geometry(settings):
    required=("paper_mm","finish_mm","bleed_mm","dpi","binding","frame_top_mm",
              "frame_bottom_mm","frame_gutter_mm","frame_outside_mm","frame_line_mm","panel_gap_mm")
    if any(key not in settings for key in required):
        raise ValueError("漫画原稿の共通設定が不足しています")
    paper,finish=settings["paper_mm"],settings["finish_mm"]
    if (not isinstance(paper,list) or len(paper)!=2 or not isinstance(finish,list) or len(finish)!=2 or
            any(type(v) not in (int,float) or v<=0 for v in paper+finish)):
        raise ValueError("原稿用紙または仕上がり寸法が不正です")
    bleed=settings["bleed_mm"]
    if type(bleed) not in (int,float) or bleed<0:
        raise ValueError("裁ち落とし寸法が不正です")
    if finish[0]+2*bleed>paper[0]+.2 or finish[1]+2*bleed>paper[1]+.2:
        raise ValueError("仕上がり＋裁ち落としが原稿用紙内に収まりません")
    if settings["frame_top_mm"]+settings["frame_bottom_mm"]>=finish[1] or \
       settings["frame_gutter_mm"]+settings["frame_outside_mm"]>=finish[0]:
        raise ValueError("基本枠の余白が仕上がり寸法を超えています")
    return settings


def shift_document_metadata(document, dx, dy):
    """Keep panel and AI coordinates aligned when canvas expansion shifts pixels."""
    def point(value):
        return [value[0]+dx,value[1]+dy]
    try:
        raw=bytes(document.annotation(FRAME_SETTINGS_KEY))
        frames=json.loads(raw) if raw else None
    except Exception:
        frames=None
    if frames:
        for panel in frames.get("panels",[]):
            panel["polygon"]=[point(p) for p in panel.get("polygon",[])]
        for record in frames.get("history",[]):
            if record.get("line"):
                record["line"]=[point(p) for p in record["line"]]
        for operation in frames.get("geometry_history",[]):
            for record in operation:
                if record.get("polygon"):
                    record["polygon"]=[point(p) for p in record["polygon"]]
        document.setAnnotation(FRAME_SETTINGS_KEY,"漫画コマ枠",
                               QByteArray(json.dumps(frames,ensure_ascii=False).encode("utf-8")))
    try:
        raw=bytes(document.annotation(AI_SETTINGS_KEY))
        ai=json.loads(raw) if raw else None
    except Exception:
        ai=None
    if ai:
        if ai.get("target"):
            ai["target"][0]+=dx; ai["target"][1]+=dy
        for region in ai.get("regions",[]):
            if region.get("bbox"):
                region["bbox"][0]+=dx; region["bbox"][1]+=dy
            if region.get("point"):
                region["point"]=point(region["point"])
        document.setAnnotation(AI_SETTINGS_KEY,"漫画AI作画",
                               QByteArray(json.dumps(ai,ensure_ascii=False).encode("utf-8")))


def page_settings(settings, number):
    """Build the per-page pixel geometry stored in each .kra document."""
    validate_page_geometry(settings)
    dpi = settings["dpi"]
    paper_w, paper_h = settings["paper_mm"]
    finish_w, finish_h = settings["finish_mm"]
    fx = (paper_w-finish_w)/2
    fy = (paper_h-finish_h)/2
    bleed = settings["bleed_mm"]
    top, bottom = settings["frame_top_mm"], settings["frame_bottom_mm"]
    gutter, outside = settings["frame_gutter_mm"], settings["frame_outside_mm"]
    gutter_right = (settings["binding"] == "right") == (number % 2 == 1)
    left = outside if gutter_right else gutter
    right = gutter if gutter_right else outside
    result = dict(settings)
    result.update({
        "page_number": number,
        "paper_px": [mm_to_px(paper_w,dpi),mm_to_px(paper_h,dpi)],
        "bleed_px": [mm_to_px(fx-bleed,dpi),mm_to_px(fy-bleed,dpi),
                     mm_to_px(fx+finish_w+bleed,dpi),mm_to_px(fy+finish_h+bleed,dpi)],
        "finish_px": [mm_to_px(fx,dpi),mm_to_px(fy,dpi),
                      mm_to_px(fx+finish_w,dpi),mm_to_px(fy+finish_h,dpi)],
        "basic_frame_px": [mm_to_px(fx+left,dpi),mm_to_px(fy+top,dpi),
                           mm_to_px(fx+finish_w-right,dpi),mm_to_px(fy+finish_h-bottom,dpi)]
    })
    return result


class MangaPageSetupDialog(QDialog):
    """Apply print geometry to the current standard Krita document."""
    PRESETS = [
        ("商業誌 B4原稿 → A4仕上がり", [257,364], [210,297], 5, [15,15,20,15]),
        ("同人誌 B5仕上がり（裁ち落とし3 mm）", [188,263], [182,257], 3, [15,15,20,15]),
        ("同人誌 A4原稿 → B5仕上がり", [210,297], [182,257], 3, [15,15,20,15]),
        ("用紙全体を仕上がりにする", None, None, 0, [12,12,15,12]),
    ]

    def __init__(self, document, parent=None, default_page_number=1):
        super().__init__(parent)
        self.document=document
        self.dpi=float(document.resolution())
        self.paper=[document.width()*25.4/self.dpi,document.height()*25.4/self.dpi]
        self.setWindowTitle("漫画原稿設定")
        self.setMinimumWidth(460)
        form=QFormLayout(self)
        form.addRow("現在の原稿用紙",QLabel("%.1f × %.1f mm　%d × %d px　%.0f ppi" %
                    (self.paper[0],self.paper[1],document.width(),document.height(),self.dpi)))
        self.preset=QComboBox()
        for title,*_ in self.PRESETS:
            self.preset.addItem(title)
        form.addRow("原稿規格",self.preset)
        self.finish_w,self.finish_h=self.length(self.paper[0]),self.length(self.paper[1])
        self.bleed=self.length(0)
        self.top,self.bottom=self.length(12),self.length(12)
        self.gutter,self.outside=self.length(15),self.length(12)
        self.page_number=QSpinBox(); self.page_number.setRange(1,9999); self.page_number.setValue(default_page_number)
        self.binding=QComboBox(); self.binding.addItem("右綴じ（縦書き漫画）","right"); self.binding.addItem("左綴じ","left")
        self.frame_line=self.length(.5,.05,10,2)
        self.panel_gap=self.length(3,0,100,2)
        for label,widget in [("仕上がり 幅",self.finish_w),("仕上がり 高さ",self.finish_h),
                             ("裁ち落とし",self.bleed),("ページ番号",self.page_number),("綴じ方",self.binding),
                             ("基本枠 上",self.top),("基本枠 下",self.bottom),
                             ("基本枠 ノド側",self.gutter),("基本枠 外側",self.outside),
                             ("枠線の太さ",self.frame_line),("コマ間隔",self.panel_gap)]:
            form.addRow(label,widget)
        self.guides=QCheckBox("仕上がり・裁ち落とし・基本枠をガイド表示")
        self.guides.setChecked(True)
        self.expand_canvas=QCheckBox("不足する裁ち落とし領域を中央基準でキャンバスに追加")
        self.expand_canvas.setChecked(False)
        self.canvas_note=QLabel("")
        self.canvas_note.setWordWrap(True)
        self.create_frame=QCheckBox("最初に基本枠いっぱいの大ゴマを作成")
        self.create_frame.setChecked(not has_active_frames(document))
        form.addRow(self.guides); form.addRow(self.expand_canvas); form.addRow(self.canvas_note); form.addRow(self.create_frame)
        note=QLabel("ガイドは画像に焼き込みません。最初の大ゴマを分割してコマ割りを始めます。自動で複数分割はしません。")
        note.setWordWrap(True); form.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate); buttons.rejected.connect(self.reject); form.addRow(buttons)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        self.load_existing_or_infer()

    @staticmethod
    def length(value,minimum=0,maximum=1000,decimals=1):
        box=QDoubleSpinBox(); box.setRange(minimum,maximum); box.setDecimals(decimals)
        box.setValue(value); box.setSuffix(" mm"); return box

    def load_existing_or_infer(self):
        try:
            existing=json.loads(bytes(self.document.annotation(PAGE_SETTINGS_KEY)))
        except Exception:
            existing=None
        if existing:
            self.target_paper=list(existing.get("paper_mm",self.paper))
            self.finish_w.setValue(existing["finish_mm"][0]); self.finish_h.setValue(existing["finish_mm"][1])
            self.bleed.setValue(existing.get("bleed_mm",0)); self.top.setValue(existing.get("frame_top_mm",12))
            self.bottom.setValue(existing.get("frame_bottom_mm",12)); self.gutter.setValue(existing.get("frame_gutter_mm",15))
            self.outside.setValue(existing.get("frame_outside_mm",12)); self.page_number.setValue(existing.get("page_number",1))
            self.binding.setCurrentIndex(0 if existing.get("binding","right")=="right" else 1)
            self.frame_line.setValue(existing.get("frame_line_mm",.5)); self.panel_gap.setValue(existing.get("panel_gap_mm",3))
            self.guides.setChecked(existing.get("show_guides",True)); self.update_canvas_action(); return
        if abs(self.paper[0]-257)<1 and abs(self.paper[1]-364)<1:
            self.preset.setCurrentIndex(0)
        elif abs(self.paper[0]-182)<1 and abs(self.paper[1]-257)<1:
            self.preset.setCurrentIndex(1)
        elif abs(self.paper[0]-188)<1 and abs(self.paper[1]-263)<1:
            self.preset.setCurrentIndex(1)
        elif abs(self.paper[0]-210)<1 and abs(self.paper[1]-297)<1:
            self.preset.setCurrentIndex(2)
        else:
            self.preset.setCurrentIndex(3)
        self.apply_preset(self.preset.currentIndex())

    def apply_preset(self,index):
        title,paper,finish,bleed,margins=self.PRESETS[index]
        self.target_paper=list(paper or self.paper)
        finish=finish or self.paper
        self.finish_w.setValue(finish[0]); self.finish_h.setValue(finish[1]); self.bleed.setValue(bleed)
        self.top.setValue(margins[0]); self.bottom.setValue(margins[1])
        self.gutter.setValue(margins[2]); self.outside.setValue(margins[3])
        self.update_canvas_action()

    def update_canvas_action(self):
        target=getattr(self,"target_paper",self.paper)
        expand=target[0]>self.paper[0]+.2 or target[1]>self.paper[1]+.2
        self.expand_canvas.setEnabled(expand)
        self.expand_canvas.setChecked(expand)
        if expand:
            self.canvas_note.setText("現在の %.1f × %.1f mm から %.1f × %.1f mm へ、内容を中央に保って拡張します。" %
                                     (self.paper[0],self.paper[1],target[0],target[1]))
        else:
            self.canvas_note.setText("現在のキャンバス寸法を維持します。")

    def values(self):
        paper=(self.target_paper if self.expand_canvas.isChecked() else self.paper)
        return {"paper_mm":paper,"finish_mm":[self.finish_w.value(),self.finish_h.value()],
                "bleed_mm":self.bleed.value(),"dpi":self.dpi,"binding":self.binding.currentData(),
                "frame_top_mm":self.top.value(),"frame_bottom_mm":self.bottom.value(),
                "frame_gutter_mm":self.gutter.value(),"frame_outside_mm":self.outside.value(),
                "frame_line_mm":self.frame_line.value(),"panel_gap_mm":self.panel_gap.value(),
                "show_guides":self.guides.isChecked(),"page_number":self.page_number.value(),
                "resize_canvas":self.expand_canvas.isChecked()}

    def validate(self):
        value=self.values(); finish=value["finish_mm"]; bleed=value["bleed_mm"]; paper=value["paper_mm"]
        if finish[0]+2*bleed>paper[0]+.2 or finish[1]+2*bleed>paper[1]+.2:
            QMessageBox.warning(self,"漫画原稿設定",
                                "仕上がり＋裁ち落としがキャンバス内に収まりません。\n"
                                "キャンバス拡張を有効にするか、裁ち落としを調整してください。")
            return
        if value["frame_top_mm"]+value["frame_bottom_mm"]>=finish[1] or value["frame_gutter_mm"]+value["frame_outside_mm"]>=finish[0]:
            QMessageBox.warning(self,"漫画原稿設定","基本枠の余白が仕上がり寸法を超えています")
            return
        self.accept()


class PageGuideOverlay(QWidget):
    def __init__(self, canvas, view, settings):
        super().__init__(canvas)
        self.view,self.settings=view,settings
        self.setObjectName("manga_page_guide_overlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(canvas.rect()); canvas.installEventFilter(self); self.show(); self.raise_()

    def eventFilter(self,obj,event):
        if event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def to_canvas(self,p):
        inverse,ok=self.view.flakeToImageTransform().inverted()
        return self.view.flakeToCanvasTransform().map(inverse.map(QPointF(*p)))

    def draw_rect(self,painter,rect,color,style,label,corners=False):
        a,b=self.to_canvas(rect[:2]),self.to_canvas(rect[2:])
        painter.setPen(QPen(QColor(color),1,style))
        if corners:
            points=[self.to_canvas(p) for p in ((rect[0],rect[1]),(rect[2],rect[1]),
                                               (rect[2],rect[3]),(rect[0],rect[3]))]
            for i,point in enumerate(points):
                for neighbor in (points[(i-1)%4],points[(i+1)%4]):
                    delta=neighbor-point
                    length=(delta.x()**2+delta.y()**2)**.5
                    if length:
                        painter.drawLine(point,point+delta*min(.08,10/length))
        else:
            painter.drawRect(QRectF(a,b).normalized())
        painter.drawText(a+QPointF(4,-4),label)

    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        self.draw_rect(painter,self.settings["bleed_px"],"#e57373",Qt.DotLine,"裁ち落とし")
        self.draw_rect(painter,self.settings["finish_px"],"#606060",Qt.SolidLine,"仕上がり")
        # The page guide is not a printable frame. Do not visually reconnect
        # gutters after splitting a panel with an uninterrupted guide rectangle.
        try:
            frames=json.loads(bytes(self.view.document().annotation(FRAME_SETTINGS_KEY)))
            divided=sum(bool(p.get("active",True)) for p in frames.get("panels",[]))>1
        except (ValueError,TypeError,AttributeError):
            divided=False
        self.draw_rect(painter,self.settings["basic_frame_px"],"#42a5f5",Qt.DashLine,
                       "基本枠ガイド",corners=divided)
        painter.end()


class PageList(QListWidget):
    reordered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.press_position = None
        self.drag_row = -1
        self.dragging = False
        self.indicator = QRubberBand(QRubberBand.Rectangle,self.viewport())

    def mousePressEvent(self, event):
        self.press_position = event.pos() if event.button()==Qt.LeftButton else None
        self.drag_row = self.row(self.itemAt(event.pos()))
        self.dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_position is not None and self.drag_row>=0 and event.buttons() & Qt.LeftButton:
            if (event.pos()-self.press_position).manhattanLength()>=QApplication.startDragDistance():
                self.dragging = True
            if self.dragging:
                self.viewport().setCursor(Qt.ClosedHandCursor)
                target = self.itemAt(event.pos())
                if target:
                    self.indicator.setGeometry(self.visualItemRect(target))
                    self.indicator.show()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.indicator.hide()
        self.viewport().unsetCursor()
        self.press_position = None
        if self.dragging:
            target = self.row(self.itemAt(event.pos()))
            if target>=0 and target!=self.drag_row:
                item = self.takeItem(self.drag_row)
                self.insertItem(target,item)
                self.setCurrentItem(item)
                self.reordered.emit()
            self.dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        source = self.currentRow()
        target = self.row(self.itemAt(event.pos()))
        if source < 0:
            event.ignore()
            return
        if target < 0:
            target = self.count()-1
        item = self.takeItem(source)
        self.insertItem(target,item)
        self.setCurrentItem(item)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.reordered.emit()


class PageDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ページ管理")
        self.document = None
        self.project_path = None
        self.data = {"version": 1, "pages": []}
        self.session_pages = False
        self.session_documents = {}
        self.loading = False
        self.restored = False
        self.guide_overlay = None
        body = QWidget()
        apply_panel_theme(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel("1ページから管理できます")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        row = QHBoxLayout()
        for title, fn in [("＋追加", self.add_page), ("複製", self.duplicate), ("削除", self.delete_page)]:
            button = QPushButton(title)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, f=fn: self.run(f))
            row.addWidget(button)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("作品・ページの操作")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        for title, fn in [("コミック作品として保存…", self.new_project), ("コミック作品を開く…", self.open_project),
                          ("現在のページを保存", self.save),
                          ("作品の全ページを保存", self.save_all), ("サムネイル更新", self.refresh),
                          ("前へ並べ替え", lambda: self.move(-1)), ("後へ並べ替え", lambda: self.move(1)),
                          ("選択ページを作品から削除（KRAは保持）", self.delete_page)]:
            menu.addAction(title, lambda checked=False, f=fn: self.run(f))
        more.setMenu(menu)
        row.addWidget(more)
        layout.addLayout(row)
        ai_button = QPushButton("AI作画パネルを開く  ▶")
        ai_button.setToolTip("右側にAI作画の生成・Prompt設定を表示します")
        ai_button.clicked.connect(self.show_ai)
        layout.addWidget(ai_button)
        self.list = PageList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(80, 112))
        self.list.setGridSize(QSize(90, 140))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Snap)
        self.list.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.list.setMinimumSize(100, 140)
        self.list.setAccessibleName("ページ一覧。クリックで開く、ドラッグで並べ替え")
        self.list.itemClicked.connect(self.activate)
        self.list.itemActivated.connect(self.activate)
        self.list.reordered.connect(self.reorder)
        layout.addWidget(self.list, 1)
        self.add_buttons(layout, [("‹ 前ページ", lambda: self.step(-1)), ("次ページ ›", lambda: self.step(1))])
        settings_row=QHBoxLayout()
        settings_button=QPushButton("漫画原稿設定…")
        settings_button.clicked.connect(lambda: self.run(self.configure_page))
        settings_row.addWidget(settings_button)
        self.show_guides = QCheckBox("ガイド表示")
        self.show_guides.setChecked(False)
        self.show_guides.toggled.connect(self.update_guides)
        settings_row.addWidget(self.show_guides)
        layout.addLayout(settings_row)
        self.info = QLabel("クリックで編集・ドラッグで並べ替え")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        scroll_content(self, body)

    @staticmethod
    def path_key(path):
        return os.path.normcase(os.path.abspath(path)) if path else ""

    def remember(self):
        app = Krita.instance()
        if self.project_path:
            app.writeSetting("manga_workspace", "last_project", self.project_path)
            item = self.selected()
            if item:
                app.writeSetting("manga_workspace", "last_page", item["id"])

    def restore_project(self):
        if self.restored:
            return
        self.restored = True
        app = Krita.instance()
        path = app.readSetting("manga_workspace", "last_project", "")
        if path and Path(path).is_file():
            try:
                self.load_project(path, app.readSetting("manga_workspace", "last_page", ""))
            except Exception as error:
                self.info.setText("前回の作品を復帰できません：" + str(error))

    def load_project(self, path, identity=None):
        data = project.read(path)
        self.session_pages = False
        self.session_documents = {}
        self.project_path, self.data = str(path), data
        self.refresh()
        self.remember()
        if data["pages"]:
            identity = identity if any(p["id"] == identity for p in data["pages"]) else data["pages"][0]["id"]
            self.open_page(identity)

    def add_buttons(self, layout, entries):
        row = QHBoxLayout()
        for title, fn in entries:
            button = QPushButton(title)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setToolTip(title)
            button.clicked.connect(lambda checked=False, f=fn: self.run(f))
            row.addWidget(button)
        layout.addLayout(row)

    def run(self, fn):
        try:
            fn()
        except Exception as error:
            QMessageBox.warning(self, "ページ管理", str(error))

    def show_ai(self):
        window = Krita.instance().activeWindow()
        if not window:
            raise ValueError("Kritaの画面を開いてください")
        dock = next((d for d in window.dockers() if d.objectName() == "manga_workspace"), None)
        if not dock:
            raise ValueError("AI作画パネルを読み込めませんでした")
        main = window.qwindow()
        if not dock.isFloating() and main.dockWidgetArea(dock) == Qt.NoDockWidgetArea:
            main.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.show()
        dock.raise_()

    def canvasChanged(self, canvas):
        self.clear_guides()
        view = canvas.view() if canvas else None
        self.document = view.document() if view else None
        QTimer.singleShot(0, self.refresh)
        QTimer.singleShot(0, self.update_guides)

    def clear_guides(self):
        if self.guide_overlay:
            self.guide_overlay.hide()
            self.guide_overlay.deleteLater()
            self.guide_overlay = None

    def configure_page(self):
        if not self.document:
            raise ValueError("設定するドキュメントを開いてください")
        default_number=1
        if self.project_path:
            key=self.path_key(self.document.fileName())
            default_number=next((i+1 for i,p in enumerate(self.data["pages"]) if self.path_key(p["file"])==key),1)
        dialog=MangaPageSetupDialog(self.document,self,default_number)
        if dialog.exec_()!=QDialog.Accepted:
            return
        settings=dialog.values()
        window=Krita.instance().activeWindow()
        panel=next((d for d in window.dockers() if d.objectName()=="manga_panels"),None) if window else None
        if dialog.create_frame.isChecked() and not panel:
            raise ValueError("コマ割りパネルを表示してから基本枠を作成してください")
        if dialog.create_frame.isChecked() and panel and panel.document==self.document and panel.active_panels():
            raise ValueError("既存のコマ枠があります。基本枠の自動作成を外して設定だけ適用してください")
        if settings.pop("resize_canvas",False):
            width=mm_to_px(settings["paper_mm"][0],settings["dpi"])
            height=mm_to_px(settings["paper_mm"][1],settings["dpi"])
            if width>self.document.width() or height>self.document.height():
                width=max(width,self.document.width()); height=max(height,self.document.height())
                dx=(width-self.document.width())//2; dy=(height-self.document.height())//2
                self.document.resizeImage(dx,dy,width,height)
                self.document.waitForDone()
                shift_document_metadata(self.document,dx,dy)
        per_page=page_settings(settings,settings["page_number"])
        per_page["paper_px"]=[self.document.width(),self.document.height()]
        self.document.setAnnotation(PAGE_SETTINGS_KEY,"漫画原稿設定",
                                    QByteArray(json.dumps(per_page,ensure_ascii=False).encode("utf-8")))
        self.document.setModified(True)
        if self.project_path:
            self.data["settings"]=common_page_settings(settings)
            self.persist()
        self.show_guides.setChecked(settings["show_guides"])
        self.update_guides()
        if panel:
            view=window.activeView()
            if view and view.document()==self.document:
                panel.canvasChanged(view.canvas())
            panel.line.setValue(settings["frame_line_mm"])
            panel.gap.setValue(settings["panel_gap_mm"])
        if dialog.create_frame.isChecked():
            if panel.document!=self.document:
                view=window.activeView()
                if view:
                    panel.canvasChanged(view.canvas())
            panel.run(panel.basic_frame)
        self.info.setText("漫画原稿設定を適用しました")

    def update_guides(self, *args):
        self.clear_guides()
        if not self.document or not self.show_guides.isChecked():
            return
        try:
            raw = bytes(self.document.annotation(PAGE_SETTINGS_KEY))
            settings = json.loads(raw) if raw else None
        except Exception:
            settings = None
        if not settings or not settings.get("show_guides",True):
            return
        window=Krita.instance().activeWindow()
        view=window.activeView() if window else None
        canvases=[w for w in QApplication.allWidgets() if w.isVisible() and window and w.window()==window.qwindow()
                  and not w.visibleRegion().isEmpty() and w.metaObject().className() in ("KisOpenGLCanvas2","KisQPainterCanvas")]
        if len(canvases)==1 and view and view.document()==self.document:
            self.guide_overlay=PageGuideOverlay(canvases[0],view,settings)

    def refresh(self):
        self.loading = True
        try:
            self.list.clear()
            pages = (self.data["pages"] if self.project_path or self.session_pages else
                     ([{"id": "single", "file": self.document.fileName()}] if self.document else []))
            current = self.path_key(self.document.fileName()) if self.document else None
            opened = {self.path_key(d.fileName()): d for d in Krita.instance().documents() if d.fileName()}
            for index, p in enumerate(pages):
                item = QListWidgetItem("%02d" % (index + 1))
                item.setData(Qt.UserRole, p["id"])
                item.setToolTip(p["file"] or "未保存の原稿")
                doc = (self.session_documents.get(p["id"]) if self.session_pages else
                       opened.get(self.path_key(p["file"])) or (self.document if not self.project_path else None))
                if doc:
                    item.setIcon(QIcon(QPixmap.fromImage(doc.thumbnail(160, 224))))
                    if doc.modified():
                        item.setText(item.text() + " *")
                elif p["file"] and Path(p["file"]).is_file():
                    try:
                        with zipfile.ZipFile(p["file"]) as archive:
                            pix = QPixmap()
                            pix.loadFromData(archive.read("preview.png"))
                            item.setIcon(QIcon(pix))
                    except (OSError, KeyError, zipfile.BadZipFile):
                        item.setText(item.text() + " !")
                else:
                    item.setText(item.text() + " !")
                self.list.addItem(item)
                if doc is self.document or (p["file"] and self.path_key(p["file"]) == current):
                    self.list.setCurrentItem(item)
            name = (Path(self.project_path).name.removesuffix(".manga.json") if self.project_path else
                    "未保存のコミック" if self.session_pages else "単ページ")
            self.title.setText(name + " · %dページ" % len(pages))
            if self.project_path and current and not any(self.path_key(p["file"])==current for p in pages):
                self.info.setText("現在の原稿はこの作品の一覧外です")
            else:
                self.info.setText("クリックで編集・ドラッグで並べ替え")
            self.remember()
        finally:
            self.loading = False

    def persist(self):
        if self.project_path:
            project.write(self.project_path, self.data)
            self.remember()

    def new_project(self):
        if not self.document:
            raise ValueError("先に「ファイル」→「新しいドキュメント」でコミック原稿を作成してください")
        path, _ = QFileDialog.getSaveFileName(self, "コミック作品の管理ファイル", "コミック作品.manga.json", "漫画作品 (*.manga.json)")
        if not path:
            return False
        if not path.endswith(".manga.json"):
            path += ".manga.json"
        # Do not silently overwrite a manifest after extension normalization.
        if Path(path).exists():
            raise ValueError("新しいファイル名を指定してください。既存の作品は「開く」で選択できます。")
        if self.session_pages:
            entries = []
            used_files = set()
            for index, old in enumerate(self.data["pages"], 1):
                doc = self.session_documents.get(old["id"])
                if not doc:
                    continue
                file_key = self.path_key(doc.fileName())
                needs_file = (not doc.fileName() or Path(doc.fileName()).suffix.lower() != ".kra" or
                              file_key in used_files)
                if needs_file:
                    target = Path(path).parent / ("ページ-%03d.kra" % index)
                    if target.exists():
                        target = Path(path).parent / ("ページ-%03d-%s.kra" % (index, uuid4().hex[:8]))
                    if not doc.saveAs(str(target)):
                        raise OSError("ページ%03dをKRA形式で保存できませんでした" % index)
                    file_key = self.path_key(doc.fileName())
                used_files.add(file_key)
                entries.append({"id": old["id"], "file": str(Path(doc.fileName()).resolve())})
            data = {"version": 1, "pages": entries}
        else:
            if not self.document.fileName() or Path(self.document.fileName()).suffix.lower() != ".kra":
                target = Path(path).parent / "ページ-001.kra"
                if target.exists():
                    target = Path(path).parent / ("ページ-001-%s.kra" % uuid4().hex[:8])
                if not self.document.saveAs(str(target)):
                    raise OSError("現在のドキュメントをKRA形式で保存できませんでした")
            data = {"version": 1, "pages": [project.page(self.document.fileName())]}
        inherited=self.data.get("settings") or self.document_page_settings(self.document)
        if inherited:
            data["settings"]=inherited
        project.write(path, data)
        self.project_path, self.data = path, data
        self.session_pages = False
        self.session_documents = {}
        self.refresh()
        return True

    def begin_session_pages(self):
        """Turn a single open document into an in-memory multi-page work without a dialog."""
        if self.project_path or self.session_pages:
            return
        if not self.document:
            raise ValueError("ページを追加するドキュメントを開いてください")
        identity = str(uuid4())
        self.data = {"version": 1, "pages": [{"id": identity, "file": self.document.fileName() or ""}]}
        inherited = self.document_page_settings(self.document)
        if inherited:
            self.data["settings"] = inherited
        self.session_pages = True
        self.session_documents = {identity: self.document}
        self.refresh()

    def create_manga_document(self, settings, number):
        per_page = page_settings(settings,number)
        width,height = per_page["paper_px"]
        doc = Krita.instance().createDocument(width,height,"ページ %03d" % number,"RGBA","U8","",settings["dpi"])
        layer = doc.createNode("下描き", "paintlayer")
        doc.rootNode().addChildNode(layer,None)
        doc.setActiveNode(layer)
        doc.setAnnotation(PAGE_SETTINGS_KEY,"漫画原稿設定",QByteArray(json.dumps(per_page,ensure_ascii=False).encode("utf-8")))
        return doc

    def document_page_settings(self, document):
        if not document:
            return None
        try:
            raw=bytes(document.annotation(PAGE_SETTINGS_KEY))
            value=json.loads(raw) if raw else None
            if value:
                result=common_page_settings(value)
                validate_page_geometry(result)
                return result
        except Exception:
            return None
        return None

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "作品を開く", "", "漫画作品 (*.manga.json)")
        if path:
            self.load_project(path)

    def selected(self):
        item = self.list.currentItem()
        identity = item.data(Qt.UserRole) if item else None
        return next((p for p in self.data["pages"] if p["id"] == identity), None)

    def activate(self, item):
        self.run(lambda: self.open_page(item.data(Qt.UserRole)))

    def synchronize_view(self):
        window = Krita.instance().activeWindow()
        view = window.activeView() if window else None
        if view:
            for dock in window.dockers():
                if dock.objectName() in ("manga_pages", "manga_panels", "manga_workspace"):
                    dock.canvasChanged(view.canvas())

    def open_page(self, identity):
        if self.session_pages:
            doc = self.session_documents.get(identity)
            if not doc:
                raise OSError("作業中のページを開けませんでした")
            window = Krita.instance().activeWindow()
            view = next((v for v in window.views() if v.document() == doc), None)
            if view:
                view.setVisible()
            else:
                window.addView(doc)
            self.document = doc
            QTimer.singleShot(0, self.synchronize_view)
            return doc
        if not self.project_path:
            return self.document
        p = next(p for p in self.data["pages"] if p["id"] == identity)
        app, window = Krita.instance(), Krita.instance().activeWindow()
        same = lambda f: self.path_key(f) == self.path_key(p["file"])
        for view in window.views():
            if view.document().fileName() and same(view.document().fileName()):
                # Do not detach/rebind the active canvas on a repeated click.
                if window.activeView() != view:
                    view.setVisible()
                self.document = view.document()
                QTimer.singleShot(0, self.synchronize_view)
                return view.document()
        doc = next((d for d in app.documents() if d.fileName() and same(d.fileName())), None)
        if doc is None:
            if not Path(p["file"]).is_file():
                raise OSError("原稿が見つかりません：" + p["file"])
            doc = app.openDocument(p["file"])
        if not doc:
            raise OSError("原稿を開けませんでした")
        # addView handles initial activation and loading notifications itself.
        # Re-activating during initialization can leave native dockers detached.
        window.addView(doc)
        self.document = doc
        QTimer.singleShot(0, self.synchronize_view)
        return doc

    def step(self, delta):
        row = self.list.currentRow() + delta
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
            self.activate(self.list.item(row))

    def create_page(self, duplicate=False):
        if not self.project_path:
            self.begin_session_pages()
        source = self.open_page(self.selected()["id"]) if self.selected() else self.document
        app = Krita.instance()
        settings = None
        if duplicate:
            if not source:
                raise ValueError("複製するページを選択してください")
            doc = source.clone()
        else:
            settings = self.data.get("settings")
            if not settings:
                settings=self.document_page_settings(source)
                if settings:
                    self.data["settings"]=settings
                    self.persist()
            if settings:
                doc = self.create_manga_document(settings,len(self.data["pages"])+1)
            else:
                doc = app.createDocument(source.width() if source else 2480, source.height() if source else 3508,
                                         "新しいページ", "RGBA", "U8", "", source.resolution() if source else 300)
                layer = doc.createNode("描画", "paintlayer")
                doc.rootNode().addChildNode(layer, None)
                doc.setActiveNode(layer)
        prepared_view=None
        if settings and not duplicate:
            window=app.activeWindow()
            panel=next((d for d in window.dockers() if d.objectName()=="manga_panels"),None) if window else None
            if not panel:
                raise ValueError("コマ割りパネルを読み込めないため、最初の大ゴマを作成できません")
            prepared_view=window.addView(doc)
            prepared_view.setVisible()
            self.document=doc
            panel.canvasChanged(prepared_view.canvas())
            panel.line.setValue(settings["frame_line_mm"])
            panel.gap.setValue(settings["panel_gap_mm"])
            if not panel.active_panels():
                panel.basic_frame()
        # A new page belongs at the end of the work regardless of which page
        # is currently open. A duplicate stays beside its source page.
        index = self.list.currentRow() + 1 if duplicate else len(self.data["pages"])
        if self.project_path:
            target = Path(self.project_path).parent / ("ページ-%03d-%s.kra" % (len(self.data["pages"])+1, uuid4().hex[:8]))
            if not doc.saveAs(str(target)):
                app.activeWindow().addView(doc)
                raise OSError("ページ保存に失敗。未保存原稿として開きました")
            entry = project.page(target)
        else:
            entry = {"id": str(uuid4()), "file": doc.fileName() or ""}
            self.session_documents[entry["id"]] = doc
        self.data["pages"].insert(max(0, min(index, len(self.data["pages"]))), entry)
        try:
            self.persist()
        except Exception:
            self.data["pages"].remove(entry)
            app.activeWindow().addView(doc)
            raise
        if prepared_view is None:
            app.activeWindow().addView(doc)
        self.document = doc
        self.refresh()

    def add_page(self):
        self.create_page()

    def duplicate(self):
        self.create_page(True)

    def detach(self):
        p = self.selected()
        if p:
            self.commit_pages([item for item in self.data["pages"] if item["id"]!=p["id"]])
            self.session_documents.pop(p["id"], None)
            self.refresh()

    def delete_page(self):
        if not self.project_path and not self.session_pages:
            raise ValueError("このページはまだコミック作品へ追加されていません")
        p = self.selected()
        if not p:
            raise ValueError("削除するページを選択してください")
        detail = ("KRA原稿ファイルは復元用に残します。" if self.project_path else
                  "開いている原稿自体は閉じず、ページ一覧から外します。")
        answer = QMessageBox.question(self,"ページを削除",
                                      "選択ページを作品のページ一覧から削除します。\n" + detail,
                                      QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.detach()

    def commit_pages(self, pages):
        data = dict(self.data, pages=pages)
        if self.project_path:
            project.write(self.project_path,data)
        self.data = data
        self.remember()

    def reorder(self, *args):
        if self.loading or (not self.project_path and not self.session_pages):
            return
        by_id = {p["id"]: p for p in self.data["pages"]}
        ordered = [by_id[self.list.item(i).data(Qt.UserRole)] for i in range(self.list.count())]
        self.run(lambda: self.commit_pages(ordered))
        QTimer.singleShot(0, self.refresh)

    def move(self, delta):
        row = self.list.currentRow()
        if (self.project_path or self.session_pages) and 0 <= row + delta < len(self.data["pages"]):
            pages = list(self.data["pages"])
            pages[row], pages[row + delta] = pages[row + delta], pages[row]
            self.commit_pages(pages)
            self.refresh()
            self.list.setCurrentRow(row + delta)

    def save(self):
        if self.document:
            if not self.document.fileName():
                Krita.instance().action("file_save").trigger()
            elif not self.document.save():
                raise OSError("原稿を保存できませんでした")
            if self.session_pages and self.document.fileName():
                for identity, doc in self.session_documents.items():
                    if doc == self.document:
                        page = next((p for p in self.data["pages"] if p["id"] == identity), None)
                        if page:
                            page["file"] = self.document.fileName()
                        break
        self.persist()
        self.refresh()

    def save_all(self):
        if self.session_pages and not self.project_path:
            self.new_project()
            return
        keys = {self.path_key(p["file"]) for p in self.data["pages"]}
        failed = []
        for doc in Krita.instance().documents():
            if self.path_key(doc.fileName()) in keys and doc.modified() and not doc.save():
                failed.append(Path(doc.fileName()).name)
        self.persist()
        self.refresh()
        if failed:
            raise OSError("保存できなかった原稿：" + "、".join(failed))
        self.info.setText("作品を保存しました")
