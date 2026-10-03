"""NovelAI-inspired prompt planning UI with a local ComfyUI preview path."""
import random
import threading
import time
from krita import Krita, DockWidget, Selection
from PyQt5.QtCore import QByteArray, QBuffer, QIODevice, Qt, QPointF, QEvent, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QImage, QPixmap, QPolygonF
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit, QMessageBox, QComboBox,
    QSpinBox, QDoubleSpinBox, QTabWidget, QGroupBox, QApplication, QCheckBox,
    QToolButton, QProgressBar, QAbstractButton, QFileDialog
)
from . import state as metadata
from . import comfy_backend
from . import bfs_backend
from .compact import scroll_content
from .prompt_edit import TagPromptEdit
from .detection_ui import DetectionController
from .onomatopoeia import OnomatopoeiaMaterialDialog
from .theme import apply_panel_theme, section, muted


REGION_KIND_COLORS = {
    "character": "#e83e78", "object": "#2688e8",
    "background": "#26a69a", "free": "#8a5bd6",
    "text": "#f39c2b", "frame": "#16a085",
}
REGION_KIND_LABELS = {
    "character": "人物", "object": "物体", "background": "背景",
    "free": "自由領域", "text": "文字（自動）", "frame": "コマ（自動）",
}


def region_color(region):
    return REGION_KIND_COLORS.get(region.get("kind"), "#8a5bd6")
AI_DEFAULTS = {
    "server": "http://127.0.0.1:8188",
    "maximum": 768,
    "timeout": 300,
    "positive": metadata.DEFAULT_SCENE_PROMPT,
    "negative": metadata.DEFAULT_NEGATIVE_PROMPT,
    "tag_completion": True,
    "tag_completion_rows": 10,
}


class GenerationSignals(QObject):
    finished = pyqtSignal(bytes, object, object, object)
    failed = pyqtSignal(str, object)
    progress = pyqtSignal(str, object)


class CollapsibleSection(QWidget):
    """Compact section that keeps its current state visible when folded."""
    def __init__(self, title, expanded=True, changed=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.changed = changed
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        header = QWidget(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.toggle = QToolButton(header)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(bool(expanded))
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title + "の開閉")
        self.summary = muted(QLabel("未入力", header))
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.toggle, 1)
        row.addWidget(self.summary)
        outer.addWidget(header)
        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(10, 0, 0, 2)
        self.content_layout.setSpacing(4)
        outer.addWidget(self.content)
        self.content.setVisible(bool(expanded))
        self.toggle.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded):
        self.content.setVisible(bool(expanded))
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setToolTip("折り畳む" if expanded else "展開する")
        if self.changed:
            self.changed(bool(expanded))

    def set_summary(self, text):
        self.summary.setText(text)


class PromptOverlay(QWidget):
    """Paint prompt markers; intercept one click only while placement is active."""
    def __init__(self, canvas, owner, view, placing=False):
        super().__init__(canvas)
        self.owner, self.view, self.placing = owner, view, placing
        interactive = placing or owner.selecting_region
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not interactive)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(canvas.rect())
        self.setCursor(Qt.CrossCursor if interactive else Qt.ArrowCursor)
        canvas.installEventFilter(self)
        self.show()
        self.raise_()
        if placing:
            self.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def to_doc(self, point):
        inverse, ok = self.view.flakeToCanvasTransform().inverted()
        if not ok:
            raise ValueError("Canvas座標を変換できません")
        image_point = self.view.flakeToImageTransform().map(inverse.map(point))
        return [image_point.x(), image_point.y()]

    def to_canvas(self, point):
        inverse, ok = self.view.flakeToImageTransform().inverted()
        if not ok:
            return QPointF()
        return self.view.flakeToCanvasTransform().map(inverse.map(QPointF(*point)))

    def mousePressEvent(self, event):
        if self.placing and event.button() == Qt.LeftButton:
            self.owner.add_at_point(self.to_doc(event.localPos()))
            event.accept()
        elif self.owner.selecting_region and event.button() == Qt.LeftButton:
            marker = self.marker_at(event.localPos())
            if marker is not None:
                self.owner.select_region_index(marker)
            else:
                self.owner.select_region_at(self.to_doc(event.localPos()))
            event.accept()
        elif (self.placing or self.owner.selecting_region) and event.button() == Qt.RightButton:
            self.owner.stop_canvas_modes()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.owner.stop_canvas_modes()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        if not self.owner._state:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        selected_index = self.owner.regions.currentRow()
        if self.owner.selecting_region:
            visible_indices = range(len(self.owner._state["regions"]))
        elif 0 <= selected_index < len(self.owner._state["regions"]):
            visible_indices = (selected_index,)
        else:
            visible_indices = ()
        for index in visible_indices:
            region = self.owner._state["regions"][index]
            point = region.get("point")
            if point is None:
                x, y, w, h = region["bbox"]
                point = [x + w / 2, y + h / 2]
            position = self.to_canvas(point)
            color = QColor(region_color(region))
            selected = index == self.owner.regions.currentRow()
            x, y, w, h = region["bbox"]
            painter.setPen(QPen(color, 3 if selected else 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([self.to_canvas(p) for p in
                ([x,y], [x+w,y], [x+w,y+h], [x,y+h])]))
            radius = 15 if selected else 12
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(position, radius, radius)
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawText(int(position.x() - radius), int(position.y() - radius),
                             radius * 2, radius * 2, Qt.AlignCenter, str(index + 1))
        painter.end()

    def marker_at(self, canvas_point):
        """Hit the visible numbered circle before overlapping region boxes."""
        matches = []
        for index, region in enumerate(self.owner._state.get("regions", [])):
            point = region.get("point")
            if point is None:
                x, y, width, height = region["bbox"]
                point = [x + width / 2, y + height / 2]
            marker = self.to_canvas(point)
            distance = ((marker.x() - canvas_point.x()) ** 2 +
                        (marker.y() - canvas_point.y()) ** 2) ** 0.5
            if distance <= 20:
                matches.append((distance, index))
        return min(matches)[1] if matches else None


class MangaDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI作画")
        self._document = None
        self._state = None
        self._loading = False
        self.overlay = None
        self.placing = False
        self.selecting_region = False
        self.buttons = []
        self._busy = False
        self._generation_token = None
        self._generation_started_at = None
        self._generation_message = ""
        self._generation_clock = QTimer(self)
        self._generation_clock.setInterval(1000)
        self._generation_clock.timeout.connect(self.update_generation_elapsed)
        self.generation_signals = GenerationSignals()
        self.generation_signals.finished.connect(self.generation_finished)
        self.generation_signals.failed.connect(self.generation_failed)
        self.generation_signals.progress.connect(self.generation_progress)
        self.ai_config = self.read_ai_config()
        QApplication.instance().installEventFilter(self)

        body = QWidget(self)
        apply_panel_theme(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)

        self.tabs = QTabWidget()
        self.generate_tab = QWidget()
        self.history_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.generate_tab, "生成")
        self.tabs.addTab(self.history_tab, "履歴")
        self.tabs.addTab(self.settings_tab, "設定")
        root.addWidget(self.tabs)

        self.build_generate_tab()
        self.build_history_tab()
        self.build_settings_tab()
        scroll_content(self, body)

        self.regions.currentRowChanged.connect(self.select_region)
        self.name.textEdited.connect(self.edit_region)
        self.kind.currentIndexChanged.connect(self.edit_region)
        self.prompt.textChanged.connect(self.edit_region)
        self.region_negative.textChanged.connect(self.edit_region)
        self.text_type.currentIndexChanged.connect(self.edit_region)
        self.text_render.currentIndexChanged.connect(self.edit_region)
        self.text_content.textChanged.connect(self.edit_region)
        self.panel_owner.currentIndexChanged.connect(self.edit_region)
        self.scene.textChanged.connect(self.edit_scene)
        self.negative.textChanged.connect(self.edit_scene)
        self.scene.textChanged.connect(self.update_prompt_summaries)
        self.negative.textChanged.connect(self.update_prompt_summaries)
        self.prompt.textChanged.connect(self.update_prompt_summaries)
        self.region_negative.textChanged.connect(self.update_prompt_summaries)
        self.target_mode.currentIndexChanged.connect(self.change_target_mode)
        self.model.currentTextChanged.connect(self.edit_generation)
        self.generation_mode.currentIndexChanged.connect(self.edit_bfs_settings)
        self.bfs_reference_path.textChanged.connect(self.edit_bfs_settings)
        self.seed.valueChanged.connect(self.edit_generation)
        self.steps.valueChanged.connect(self.edit_generation)
        self.guidance.valueChanged.connect(self.edit_generation)
        self.visibilityChanged.connect(lambda visible: self.refresh_overlay() if visible else self.clear_overlay())
        self.load_document(None)

    @staticmethod
    def read_section_state(name, default):
        value = Krita.instance().readSetting(
            "manga_workspace", "ai_section_" + name,
            "open" if default else "closed")
        return str(value).lower() not in ("closed", "false", "0")

    @staticmethod
    def save_section_state(name, expanded):
        Krita.instance().writeSetting(
            "manga_workspace", "ai_section_" + name,
            "open" if expanded else "closed")

    def update_prompt_summaries(self):
        scene = bool(self.scene.toPlainText().strip())
        negative = bool(self.negative.toPlainText().strip())
        if scene and negative:
            common = "全体・除外 入力済み"
        elif scene:
            common = "全体 入力済み"
        elif negative:
            common = "全体 未入力"
        else:
            common = "未入力"
        self.common_prompt_section.set_summary(common)

        region = self.current()
        if region is None:
            local = "領域未選択"
        else:
            positive = bool(self.prompt.toPlainText().strip())
            excluded = bool(self.region_negative.toPlainText().strip())
            if positive and excluded:
                local = "内容・除外 入力済み"
            elif positive:
                local = "内容 入力済み"
            else:
                local = "未入力"
        self.region_prompt_section.set_summary(local)

    def build_generate_tab(self):
        layout = QVBoxLayout(self.generate_tab)
        layout.setContentsMargins(5, 6, 5, 6)
        layout.setSpacing(5)
        self.status = muted(QLabel("原稿を開いてください"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.target_mode = QComboBox()
        self.target_mode.addItem("現在のコマ", "current_panel")
        self.target_mode.addItem("選択範囲", "selection")
        self.target_mode.addItem("ページ全体", "full_page")
        form.addRow("対象", self.target_mode)
        self.generation_mode = QComboBox()
        self.generation_mode.addItem("通常", "standard")
        self.generation_mode.addItem("BFS 頭部", "head")
        self.generation_mode.addItem("BFS 全身", "body")
        self.generation_mode.setToolTip("BFSは参照画像の人物を原稿の対象範囲へ反映します")
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.generation_mode, 1)
        settings_button = QPushButton("⚙")
        settings_button.setToolTip("AI作画の接続・生成・Tag補完設定を開く")
        settings_button.clicked.connect(self.open_settings)
        mode_layout.addWidget(settings_button)
        form.addRow("方式", mode_row)
        self.model = QComboBox()
        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self.model, 1)
        refresh_models = QPushButton("更新")
        refresh_models.setToolTip("ComfyUIに登録されたCheckpointを再読込")
        refresh_models.clicked.connect(self.reload_models)
        model_layout.addWidget(refresh_models)
        form.addRow("モデル", model_row)
        self.model_row = model_row
        self.model_label = form.labelForField(model_row)
        self.reload_models()
        reference_row = QWidget()
        reference_layout = QHBoxLayout(reference_row)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        self.bfs_reference_path = QLineEdit()
        self.bfs_reference_path.setReadOnly(True)
        self.bfs_reference_path.setPlaceholderText("キャラの参照画像を選択")
        self.bfs_reference_path.setToolTip("PNG・JPG。設定中のComfyUIへ生成時に送信します")
        reference_layout.addWidget(self.bfs_reference_path, 1)
        choose_reference = QPushButton("選ぶ…")
        choose_reference.clicked.connect(self.choose_bfs_reference)
        reference_layout.addWidget(choose_reference)
        self.bfs_reference_button = choose_reference
        form.addRow("参照画像", reference_row)
        self.bfs_reference_row = reference_row
        self.bfs_reference_label = form.labelForField(reference_row)
        layout.addLayout(form)
        self.bfs_help_section = CollapsibleSection(
            "BFSの説明", self.read_section_state("bfs_help", False),
            lambda expanded: self.save_section_state("bfs_help", expanded))
        self.bfs_help_section.summary.hide()
        self.bfs_hint = muted(QLabel(
            "編集対象は上の『対象』で指定し、参照画像の人物を合わせます。"
            "Qwen Image 2.1と対応BFS LoRAが必要です。"
            "CFGは1固定。個別領域プロンプトは使用しません。"))
        self.bfs_hint.setWordWrap(True)
        self.bfs_help_section.content_layout.addWidget(self.bfs_hint)
        layout.addWidget(self.bfs_help_section)
        self.update_bfs_ui()

        common_expanded = self.read_section_state("common_prompt", True)
        self.common_prompt_section = CollapsibleSection(
            "全体・除外プロンプト", common_expanded,
            lambda expanded: self.save_section_state("common_prompt", expanded))
        common = self.common_prompt_section.content_layout
        self.common_prompt_label = section(QLabel("全体プロンプト（必須・日本語入力可）"))
        common.addWidget(self.common_prompt_label)
        self.scene = TagPromptEdit()
        self.scene.setMinimumHeight(92)
        self.scene.setMaximumHeight(132)
        self.scene.setPlaceholderText("ページ／現在のコマ全体の場面・画風・構図")
        self.scene.setToolTip("対象全体に共通する人物、背景、構図、画風を入力します。日本語入力とTag補完に対応しています。")
        self.scene.setAccessibleName("全体プロンプト")
        common.addWidget(self.scene)
        self.common_prompt_hint = muted(QLabel("人物・背景・構図・画風など、対象全体に必ず反映したい内容"))
        common.addWidget(self.common_prompt_hint)
        common.addWidget(section(QLabel("除外プロンプト（描かないもの）")))
        self.negative = TagPromptEdit()
        self.negative.setMinimumHeight(68)
        self.negative.setMaximumHeight(104)
        self.negative.setPlaceholderText("除外プロンプト")
        self.negative.setToolTip("崩れ、不要な文字、描いてほしくない要素を入力します。")
        self.negative.setAccessibleName("除外プロンプト")
        common.addWidget(self.negative)
        layout.addWidget(self.common_prompt_section)

        placement_row = QHBoxLayout()
        self.selection_action = QComboBox()
        self.selection_action.setAccessibleName("選択範囲の用途")
        self.selection_action.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.selection_action.setMinimumContentsLength(8)
        for label, kind in (("生成対象にする", "target"),
                            ("人物範囲を追加", "character"),
                            ("物体範囲を追加", "object"),
                            ("背景範囲を追加", "background"),
                            ("文字・オノマトペ範囲を追加", "text")):
            self.selection_action.addItem(label, kind)
        self.selection_action.setToolTip("キャンバスで選択した範囲の用途を選び、適用を押します")
        placement_row.addWidget(self.selection_action, 1)
        self.buttons.append(self.selection_action)
        self.button(placement_row, "適用", self.apply_selection_action)
        layout.addLayout(placement_row)

        layout.addWidget(section(QLabel("自動検出（任意）")))
        self.detector = DetectionController(self)
        detection_row = QHBoxLayout()
        self.button(detection_row, "ページを自動検出", self.detector.guarded(self.detector.run))
        self.button(detection_row, "検出停止", self.detector.cancel)
        layout.addLayout(detection_row)
        self.detector_status = muted(QLabel(""))
        self.detector_status.setWordWrap(True)
        layout.addWidget(self.detector_status)
        detection_setup = QHBoxLayout()
        self.detector_setup_button = self.button(
            detection_setup, "自動判定機能を追加導入…",
            self.detector.guarded(self.detector.setup))
        self.detector_setup_button.setToolTip(
            "任意機能。専用Python、ライブラリ、約250MBの検出モデルをダウンロードします")
        layout.addLayout(detection_setup)
        self.detector_note = muted(QLabel(
            "任意機能：初回のみ専用環境と約250MBのモデルを取得します。"
            "未導入でも手動の範囲指定を使用できます。"))
        self.detector_note.setWordWrap(True)
        layout.addWidget(self.detector_note)
        self.regions = QListWidget()
        self.regions.setMaximumHeight(116)
        self.regions.setAccessibleName("人物・オブジェクトのプロンプト一覧")
        layout.addWidget(self.regions)
        legend = QLabel(
            '<span style="color:#e83e78">● 人物</span>　'
            '<span style="color:#2688e8">● 物体</span>　'
            '<span style="color:#f39c2b">● 文字</span>　'
            '<span style="color:#16a085">● コマ</span>')
        legend.setWordWrap(True)
        legend.setToolTip("番号は一覧の行番号と一致します。通常時は選択中の範囲だけを表示します。")
        layout.addWidget(legend)
        row = QHBoxLayout()
        self.place_button = self.button(row, "Canvasで位置指定", self.toggle_placing)
        self.place_button.setCheckable(True)
        self.region_select_button = self.button(row, "配置範囲を確認・選択", self.toggle_region_selecting)
        self.region_select_button.setCheckable(True)
        self.button(row, "削除", self.remove)
        layout.addLayout(row)

        region_expanded = self.read_section_state("region_prompt", True)
        self.region_prompt_section = CollapsibleSection(
            "選択した領域の設定", region_expanded,
            lambda expanded: self.save_section_state("region_prompt", expanded))
        self.editor = QGroupBox()
        editor = QVBoxLayout(self.editor)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("表示名")
        self.kind = QComboBox()
        self.kind.addItem("人物", "character")
        self.kind.addItem("物体", "object")
        self.kind.addItem("背景", "background")
        self.kind.addItem("自由領域", "free")
        self.kind.addItem("コマ全体（検出）", "frame")
        self.kind.addItem("テキスト（検出）", "text")
        row.addWidget(self.name, 2)
        row.addWidget(self.kind, 1)
        editor.addLayout(row)
        self.prompt = TagPromptEdit()
        self.prompt.setMaximumHeight(68)
        self.prompt.setPlaceholderText("この人物・物体に描きたい内容")
        editor.addWidget(self.prompt)
        self.region_negative = TagPromptEdit()
        self.region_negative.setMaximumHeight(48)
        self.region_negative.setPlaceholderText("この人物・物体だけの除外プロンプト")
        editor.addWidget(self.region_negative)

        self.text_options = QGroupBox("MANGA BRIDGE v2 文字領域")
        text_options_layout = QVBoxLayout(self.text_options)
        text_form = QFormLayout()
        self.text_type = QComboBox()
        self.text_type.addItems(("未分類", "台詞", "オノマトペ", "効果音", "モノローグ", "ナレーター"))
        self.text_render = QComboBox()
        self.text_render.addItems(("文字を描かず空間を確保", "吹き出しを残し文字は描かない", "指定した文字を描く"))
        self.panel_owner = QComboBox()
        text_form.addRow("テキストの種類", self.text_type)
        text_form.addRow("描画方法", self.text_render)
        text_form.addRow("所属コマ", self.panel_owner)
        text_options_layout.addLayout(text_form)
        self.text_content = QPlainTextEdit()
        self.text_content.setMaximumHeight(58)
        self.text_content.setPlaceholderText("文字の内容（例：ドン、ザワザワ、台詞本文）")
        text_options_layout.addWidget(self.text_content)
        self.create_lettering = QPushButton("この領域へ漫画表現素材を作成…")
        self.create_lettering.clicked.connect(self.create_text_material)
        text_options_layout.addWidget(self.create_lettering)
        editor.addWidget(self.text_options)
        row = QHBoxLayout()
        self.position_update = self.button(row, "選択範囲で位置更新", self.move_region)
        self.button(row, "この範囲を選択", self.detector.guarded(self.detector.select))
        self.reference = QPushButton("参照")
        self.reference.setEnabled(False)
        self.reference.setToolTip("参照画像接続はAI-4で実装")
        row.addWidget(self.reference)
        self.pose = QPushButton("Pose")
        self.pose.setEnabled(False)
        self.pose.setToolTip("Pose接続はAI-4で実装")
        row.addWidget(self.pose)
        editor.addLayout(row)
        self.bounds = muted(QLabel(""))
        self.bounds.setWordWrap(True)
        editor.addWidget(self.bounds)
        self.region_prompt_section.content_layout.addWidget(self.editor)
        layout.addWidget(self.region_prompt_section)

        settings = QHBoxLayout()
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2147483647)
        self.seed.setSpecialValueText("ランダム")
        self.steps = QSpinBox()
        self.steps.setRange(1, 150)
        self.guidance = QDoubleSpinBox()
        self.guidance.setRange(0, 30)
        self.guidance.setDecimals(1)
        for title, control in (("Seed", self.seed), ("Steps", self.steps), ("Guidance", self.guidance)):
            box = QVBoxLayout()
            box.addWidget(muted(QLabel(title)))
            box.addWidget(control)
            settings.addLayout(box, 1)
        layout.addLayout(settings)

        for title in ("Image2Image / Inpaint", "参照画像", "LoRA", "Control"):
            button = QPushButton("▸  " + title)
            button.setEnabled(False)
            button.setToolTip("生成Backend接続時に有効になります")
            layout.addWidget(button)

        self.generate = QPushButton("▶  AIプレビュー生成")
        self.generate.setProperty("primary", True)
        self.generate.setEnabled(False)
        self.generate.setToolTip("設定したComfyUIでプレビューを生成します")
        self.generate.clicked.connect(self.generate_preview)
        layout.addWidget(self.generate)

        self.generation_activity = QGroupBox("AI生成を実行しています")
        activity = QVBoxLayout(self.generation_activity)
        activity.setContentsMargins(8, 6, 8, 7)
        self.generation_activity_title = QLabel("● 生成中 0:00")
        font = self.generation_activity_title.font()
        font.setBold(True)
        self.generation_activity_title.setFont(font)
        activity.addWidget(self.generation_activity_title)
        self.generation_activity_detail = QLabel("ComfyUIへ送信中…")
        self.generation_activity_detail.setWordWrap(True)
        activity.addWidget(self.generation_activity_detail)
        self.generation_progress_bar = QProgressBar()
        self.generation_progress_bar.setRange(0, 0)
        self.generation_progress_bar.setTextVisible(False)
        self.generation_progress_bar.setAccessibleName("AI画像生成中")
        activity.addWidget(self.generation_progress_bar)
        self.generation_activity.setVisible(False)
        layout.addWidget(self.generation_activity)

        previews = QHBoxLayout()
        self.source_preview = QLabel("元の絵")
        self.ai_preview = QLabel("AIプレビュー")
        for label in (self.source_preview, self.ai_preview):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(44)
            previews.addWidget(label)
        layout.addLayout(previews)
        row = QHBoxLayout()
        self.apply = QPushButton("適用")
        self.apply_new = QPushButton("新規レイヤーに追加")
        self.apply.setEnabled(False)
        self.apply_new.setEnabled(False)
        row.addWidget(self.apply)
        row.addWidget(self.apply_new)
        layout.addLayout(row)
        layout.addStretch()

    def build_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        title = section(QLabel("生成履歴"))
        layout.addWidget(title)
        text = muted(QLabel("履歴は生成Backend接続後に、Prompt・配置・Seed・設定と一緒に保存します。"))
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()

    def build_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        title = section(QLabel("AI作画の設定"))
        layout.addWidget(title)
        form = QFormLayout()
        self.setting_server = QLineEdit(self.ai_config["server"])
        self.setting_server.setPlaceholderText("http://127.0.0.1:8188")
        form.addRow("ComfyUI URL", self.setting_server)
        self.setting_maximum = QSpinBox()
        self.setting_maximum.setRange(256, 2048)
        self.setting_maximum.setSingleStep(32)
        self.setting_maximum.setSuffix(" px")
        self.setting_maximum.setValue(self.ai_config["maximum"])
        form.addRow("Preview長辺上限", self.setting_maximum)
        self.setting_timeout = QSpinBox()
        self.setting_timeout.setRange(30, 1800)
        self.setting_timeout.setSuffix(" 秒")
        self.setting_timeout.setValue(self.ai_config["timeout"])
        form.addRow("生成待機上限", self.setting_timeout)
        layout.addLayout(form)
        layout.addWidget(section(QLabel("新規原稿の初期Prompt")))
        self.setting_positive = TagPromptEdit()
        self.setting_positive.setMaximumHeight(70)
        self.setting_positive.setPlainText(self.ai_config["positive"])
        layout.addWidget(self.setting_positive)
        self.setting_negative = TagPromptEdit()
        self.setting_negative.setMaximumHeight(60)
        self.setting_negative.setPlainText(self.ai_config["negative"])
        layout.addWidget(self.setting_negative)
        self.setting_tag_completion = QCheckBox("Tag補完を有効にする")
        self.setting_tag_completion.setChecked(self.ai_config["tag_completion"])
        layout.addWidget(self.setting_tag_completion)
        completion_row = QFormLayout()
        self.setting_tag_completion_rows = QSpinBox()
        self.setting_tag_completion_rows.setRange(3, 30)
        self.setting_tag_completion_rows.setSuffix(" 件")
        self.setting_tag_completion_rows.setValue(self.ai_config["tag_completion_rows"])
        self.setting_tag_completion_rows.setToolTip(
            "候補ポップアップに一度に表示する件数です。全候補はスクロールできます。")
        completion_row.addRow("TagComplete表示件数", self.setting_tag_completion_rows)
        layout.addLayout(completion_row)
        layout.addWidget(section(QLabel("自動判定の環境")))
        self.setting_detector_status = muted(QLabel(""))
        self.setting_detector_status.setWordWrap(True)
        layout.addWidget(self.setting_detector_status)
        detector_row = QHBoxLayout()
        self.button(detector_row, "導入済み環境を選択…", self.detector.guarded(self.detector.choose))
        self.button(detector_row, "状態を再確認", self.refresh_detector_ui)
        layout.addLayout(detector_row)
        row = QHBoxLayout()
        for title, function in (("保存", self.save_ai_settings), ("接続確認", self.test_ai_connection),
                                ("初期値", self.reset_ai_settings)):
            button = QPushButton(title)
            button.clicked.connect(function)
            row.addWidget(button)
        layout.addLayout(row)
        self.setting_status = muted(QLabel("設定はKrita全体の漫画ワークスペースで共有します"))
        self.setting_status.setWordWrap(True)
        layout.addWidget(self.setting_status)
        layout.addStretch()
        self.refresh_detector_ui()

    def refresh_detector_ui(self):
        if not hasattr(self, "detector"):
            return
        available = self.detector.available()
        if hasattr(self, "detector_status"):
            self.detector_status.setText(
                "● 自動判定：利用可能" if available
                else "自動判定：未導入（手動の範囲指定は使用可能）")
        if hasattr(self, "detector_setup_button"):
            self.detector_setup_button.setVisible(not available)
        if hasattr(self, "detector_note"):
            self.detector_note.setVisible(not available)
        if hasattr(self, "setting_detector_status"):
            path = str(self.detector.root())
            self.setting_detector_status.setText(
                ("利用可能\n" if available else "未導入\n") + "保存先：" + path)

    def button(self, layout, title, function):
        button = QPushButton(title)
        button.clicked.connect(function)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def reload_models(self):
        selected = self.model.currentData() or self.model.currentText()
        options = comfy_backend.model_options(self.ai_config["server"])
        self.model.blockSignals(True)
        self.model.clear()
        for label, identity in options:
            self.model.addItem(label, identity)
        index = self.model.findData(selected)
        self.model.setCurrentIndex(max(0, index))
        self.model.blockSignals(False)
        if self._state is not None:
            self.edit_generation()

    def choose_bfs_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "キャラの参照画像を選択", self.bfs_reference_path.text(),
            "画像 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.bfs_reference_path.setText(path)

    def update_bfs_ui(self):
        bfs = self.generation_mode.currentData() in ("head", "body")
        if hasattr(self, "common_prompt_label"):
            self.common_prompt_label.setText("追加指示（任意・日本語可）" if bfs else "全体プロンプト（必須・日本語入力可）")
            self.common_prompt_hint.setText("参照画像との合わせ方などを追加できます" if bfs else
                                            "人物・背景・構図・画風など、対象全体に必ず反映したい内容")
        for widget in (self.bfs_reference_row, self.bfs_reference_label, self.bfs_help_section):
            widget.setVisible(bfs)
        self.model_row.setVisible(not bfs)
        self.model_label.setVisible(not bfs)
        if hasattr(self, "guidance"):
            self.guidance.setEnabled(not bfs and self._state is not None)
            self.guidance.setToolTip("BFSではCFG 1.0を使用します" if bfs else "")

    def edit_bfs_settings(self, *args):
        self.update_bfs_ui()
        if not self._loading and self._state is not None:
            self._state["bfs_mode"] = self.generation_mode.currentData()
            self._state["bfs_reference"] = self.bfs_reference_path.text()
            self.persist()

    @staticmethod
    def read_ai_config():
        app = Krita.instance()
        def value(name, default):
            return app.readSetting("manga_workspace", "ai_" + name, str(default))
        return {
            "server": value("server", AI_DEFAULTS["server"]),
            "maximum": max(256, min(2048, int(value("maximum", AI_DEFAULTS["maximum"])))),
            "timeout": max(30, min(1800, int(value("timeout", AI_DEFAULTS["timeout"])))),
            "positive": value("positive", AI_DEFAULTS["positive"]),
            "negative": value("negative", AI_DEFAULTS["negative"]),
            "tag_completion": value("tag_completion", "true").lower() == "true",
            "tag_completion_rows": max(3, min(30, int(value(
                "tag_completion_rows", AI_DEFAULTS["tag_completion_rows"])))),
        }

    def apply_completion_setting(self):
        for editor in (self.scene, self.negative, self.prompt, self.region_negative,
                       self.setting_positive, self.setting_negative):
            editor.set_completion_enabled(self.ai_config["tag_completion"])
            editor.set_completion_visible_count(self.ai_config["tag_completion_rows"])

    def save_ai_settings(self):
        server = self.setting_server.text().strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            self.setting_status.setText("ComfyUI URLは http:// または https:// から入力してください")
            return
        self.ai_config = {
            "server": server,
            "maximum": self.setting_maximum.value(),
            "timeout": self.setting_timeout.value(),
            "positive": self.setting_positive.toPlainText().strip(),
            "negative": self.setting_negative.toPlainText().strip(),
            "tag_completion": self.setting_tag_completion.isChecked(),
            "tag_completion_rows": self.setting_tag_completion_rows.value(),
        }
        app = Krita.instance()
        for name, value in self.ai_config.items():
            app.writeSetting("manga_workspace", "ai_" + name,
                             "true" if value is True else "false" if value is False else str(value))
        self.apply_completion_setting()
        self.reload_models()
        self.setting_status.setText("AI作画設定を保存しました")

    def reset_ai_settings(self):
        self.setting_server.setText(AI_DEFAULTS["server"])
        self.setting_maximum.setValue(AI_DEFAULTS["maximum"])
        self.setting_timeout.setValue(AI_DEFAULTS["timeout"])
        self.setting_positive.setPlainText(AI_DEFAULTS["positive"])
        self.setting_negative.setPlainText(AI_DEFAULTS["negative"])
        self.setting_tag_completion.setChecked(AI_DEFAULTS["tag_completion"])
        self.setting_tag_completion_rows.setValue(AI_DEFAULTS["tag_completion_rows"])
        self.setting_status.setText("初期値を表示しました。「保存」で確定します")

    def test_ai_connection(self):
        server = self.setting_server.text().strip().rstrip("/")
        if comfy_backend.server_available(server):
            self.setting_status.setText("ComfyUIへ接続できました")
        else:
            self.setting_status.setText("ComfyUIへ接続できません。URLと起動状態を確認してください")

    def canvasChanged(self, canvas):
        self.stop_canvas_modes()
        view = canvas.view() if canvas else None
        self.load_document(view.document() if view else None)

    def canvas_widget(self):
        window = Krita.instance().activeWindow()
        if not window:
            return None, None
        view = window.activeView()
        canvases = [w for w in QApplication.allWidgets() if w.isVisible()
                    and w.window() == window.qwindow() and not w.visibleRegion().isEmpty()
                    and w.metaObject().className() in ("KisOpenGLCanvas2", "KisQPainterCanvas")]
        return (canvases[0], view) if len(canvases) == 1 else (None, view)

    def clear_overlay(self):
        if self.overlay:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def refresh_overlay(self):
        self.clear_overlay()
        if not self.isVisible() or not self._document or not self._state:
            return
        canvas, view = self.canvas_widget()
        if canvas and view and view.document() == self._document:
            self.overlay = PromptOverlay(canvas, self, view, self.placing)

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.MouseButtonPress and isinstance(obj, QAbstractButton)
                and obj.metaObject().className() == "KoToolBoxButton"
                and (self.placing or self.selecting_region)):
            QTimer.singleShot(0, self.stop_canvas_modes)
        return False

    def toggle_placing(self, checked=False):
        if not self._document:
            self.place_button.setChecked(False)
            return
        self.placing = self.place_button.isChecked()
        if self.placing:
            self.selecting_region = False
            self.region_select_button.setChecked(False)
        self.place_button.setText("Canvasをクリック…" if self.placing else "Canvasで位置指定")
        self.refresh_overlay()

    def toggle_region_selecting(self, checked=False):
        if not self._document or not self._state or not self._state.get("regions"):
            self.region_select_button.setChecked(False)
            self.status.setText("確認できる人物・物体の配置範囲がありません")
            return
        self.selecting_region = self.region_select_button.isChecked()
        if self.selecting_region:
            self.placing = False
            self.place_button.setChecked(False)
            self.place_button.setText("Canvasで位置指定")
            self.region_select_button.setText("Canvas上の範囲をクリック…")
            self.status.setText("確認する配置範囲をCanvas上でクリックしてください。Esc／右クリックで終了します。")
        else:
            self.region_select_button.setText("配置範囲を確認・選択")
        self.refresh_overlay()

    def select_region_at(self, point):
        if not self._state:
            return
        matches = []
        for index, region in enumerate(self._state.get("regions", [])):
            x, y, width, height = region["bbox"]
            if x <= point[0] <= x + width and y <= point[1] <= y + height:
                matches.append((width * height, index, region))
        if not matches:
            self.status.setText("この位置に人物・物体の配置範囲はありません")
            return
        _, index, _ = min(matches, key=lambda item: item[0])
        self.select_region_index(index)

    def select_region_index(self, index):
        if not self._state or not 0 <= index < len(self._state.get("regions", [])):
            return
        region = self._state["regions"][index]
        self.regions.setCurrentRow(index)
        x, y, width, height = [int(round(value)) for value in region["bbox"]]
        selection = Selection()
        selection.select(x, y, width, height, 255)
        self._document.setSelection(selection)
        self.region_prompt_section.toggle.setChecked(True)
        self.status.setText("%s の配置範囲を選択しました" % region.get("name", "配置"))
        self.stop_canvas_modes(keep_status=True)

    def open_settings(self):
        self.tabs.setCurrentWidget(self.settings_tab)
        self.show()
        self.raise_()

    def stop_placing(self):
        self.placing = False
        if hasattr(self, "place_button"):
            self.place_button.setChecked(False)
            self.place_button.setText("Canvasで位置指定")
        self.refresh_overlay()

    def stop_canvas_modes(self, keep_status=False):
        self.placing = False
        self.selecting_region = False
        if hasattr(self, "place_button"):
            self.place_button.setChecked(False)
            self.place_button.setText("Canvasで位置指定")
        if hasattr(self, "region_select_button"):
            self.region_select_button.setChecked(False)
            self.region_select_button.setText("配置範囲を確認・選択")
        self.refresh_overlay()
        if not keep_status and self._document:
            self.status.setText(self._document.name())

    def add_at_point(self, point):
        if not self._document or not self._state:
            return
        x = max(0.0, min(float(self._document.width() - 1), point[0]))
        y = max(0.0, min(float(self._document.height() - 1), point[1]))
        size = max(32.0, min(self._document.width(), self._document.height()) * 0.12)
        left = max(0.0, min(self._document.width() - size, x - size / 2))
        top = max(0.0, min(self._document.height() - size, y - size / 2))
        region = metadata.add_region(self._state, [left, top, size, size])
        region["point"] = [x, y]
        region["name"] = "人物 %d" % len(self._state["regions"])
        self.refresh_region_items(len(self._state["regions"]) - 1)
        self.persist()
        self.stop_placing()

    def load_document(self, document):
        if document is not self._document and self._busy:
            self._generation_token = None
            self._busy = False
            self.end_generation_ui()
        self._loading = True
        self._document = document
        self._state = None
        self.regions.clear()
        self.name.clear()
        self.prompt.clear()
        self.region_negative.clear()
        self.scene.clear()
        self.negative.clear()
        self.bfs_reference_path.clear()
        self.bounds.clear()
        try:
            if document:
                raw = bytes(document.annotation(metadata.ANNOTATION))
                self._state = metadata.decode(raw)
                if not raw:
                    self._state["scene_prompt"] = self.ai_config["positive"]
                    self._state["negative_prompt"] = self.ai_config["negative"]
                self.scene.setPlainText(self._state["scene_prompt"])
                self.negative.setPlainText(self._state["negative_prompt"])
                self.refresh_region_items(-1)
                index = self.target_mode.findData(self._state["target_mode"])
                self.target_mode.setCurrentIndex(max(0, index))
                index = self.model.findData(self._state["model"])
                if index < 0:
                    index = self.model.findText(self._state["model"])
                if index < 0:
                    self.model.addItem(self._state["model"], self._state["model"])
                    index = self.model.count() - 1
                self.model.setCurrentIndex(index)
                self.seed.setValue(self._state["seed"])
                self.steps.setValue(self._state["steps"])
                self.guidance.setValue(self._state["guidance"])
                index = self.generation_mode.findData(self._state.get("bfs_mode", "standard"))
                self.generation_mode.setCurrentIndex(max(0, index))
                self.bfs_reference_path.setText(self._state.get("bfs_reference", ""))
                self.status.setText(document.name())
            else:
                self.generation_mode.setCurrentIndex(0)
                self.status.setText("原稿を開いてください")
        except Exception as error:
            self.status.setText("配置データを読み込めません。元データは保持します：" + str(error))
        enabled = self._state is not None
        for widget in self.buttons + [self.scene, self.negative, self.regions, self.target_mode,
                                      self.model, self.seed, self.steps, self.guidance,
                                      self.generation_mode, self.bfs_reference_button]:
            widget.setEnabled(enabled)
        self.update_bfs_ui()
        self.generate.setEnabled(enabled and not self._busy)
        self._loading = False
        self.apply_completion_setting()
        self.select_region(-1)
        QTimer.singleShot(0, self.refresh_overlay)

    def current(self):
        row = self.regions.currentRow()
        return (self._state["regions"][row]
                if self._state and 0 <= row < len(self._state["regions"]) else None)

    def region_display_name(self, index, region):
        kind = REGION_KIND_LABELS.get(region.get("kind"), "領域")
        if region.get("kind") == "text" and region.get("text_type", "未分類") != "未分類":
            kind = region["text_type"]
        name = (region.get("name") or "").strip()
        return "%02d  %s%s" % (index + 1, kind, ("｜" + name) if name else "")

    def refresh_region_items(self, selected=None):
        if selected is None:
            selected = self.regions.currentRow()
        self.regions.blockSignals(True)
        self.regions.clear()
        for index, region in enumerate(self._state.get("regions", []) if self._state else []):
            item = QListWidgetItem(self.region_display_name(index, region))
            item.setForeground(QBrush(QColor(region_color(region))))
            item.setToolTip("Canvas番号 %d：%s" % (index + 1, region.get("name", "")))
            self.regions.addItem(item)
        self.regions.blockSignals(False)
        if self.regions.count():
            self.regions.setCurrentRow(max(-1, min(int(selected), self.regions.count() - 1)))

    def select_region(self, row):
        self._loading = True
        region = self.current()
        self.name.setText(region["name"] if region else "")
        self.prompt.setPlainText(region["prompt"] if region else "")
        self.region_negative.setPlainText(region["negative_prompt"] if region else "")
        self.text_type.setCurrentText(region.get("text_type", "未分類") if region else "未分類")
        self.text_render.setCurrentText(
            region.get("text_render", "文字を描かず空間を確保") if region else "文字を描かず空間を確保")
        self.text_content.setPlainText(region.get("text_content", "") if region else "")
        self.refresh_panel_owners(region)
        is_text = bool(region and region.get("kind") == "text")
        self.text_options.setVisible(is_text)
        self.create_lettering.setEnabled(is_text)
        self.prompt.setPlaceholderText(
            "この文字領域へのAI描画指示" if is_text else "この人物・物体に描きたい内容")
        self.region_negative.setPlaceholderText(
            "この文字領域だけの除外プロンプト" if is_text else "この人物・物体だけの除外プロンプト")
        if region:
            index = self.kind.findData(region["kind"])
            self.kind.setCurrentIndex(max(0, index))
            self.bounds.setText("位置：%s  範囲：%s" % (region.get("point"), region["bbox"]))
        else:
            self.bounds.clear()
        for widget in (self.name, self.kind, self.prompt, self.region_negative, self.position_update,
                       self.text_type, self.text_render, self.text_content, self.panel_owner):
            widget.setEnabled(region is not None)
        self._loading = False
        self.update_prompt_summaries()
        if self.overlay:
            self.overlay.update()

    def persist(self):
        if self._loading or self._state is None:
            return
        try:
            self._document.setAnnotation(metadata.ANNOTATION, "漫画AI作画",
                                         QByteArray(metadata.encode(self._state)))
            self._document.setModified(True)
            self.status.setText(self._document.name() + " · AI設定を記録")
        except Exception as error:
            self.status.setText("AI設定の記録に失敗しました：" + str(error))

    def edit_scene(self):
        if not self._loading and self._state is not None:
            self._state["scene_prompt"] = self.scene.toPlainText()
            self._state["negative_prompt"] = self.negative.toPlainText()
            self.persist()

    def edit_generation(self, *args):
        if not self._loading and self._state is not None:
            self._state["model"] = self.model.currentData() or self.model.currentText()
            self._state["seed"] = self.seed.value()
            self._state["steps"] = self.steps.value()
            self._state["guidance"] = self.guidance.value()
            self.persist()

    def edit_region(self, *args):
        if self._loading:
            return
        region = self.current()
        if region:
            region["name"] = self.name.text()
            region["kind"] = self.kind.currentData()
            region["prompt"] = self.prompt.toPlainText()
            region["negative_prompt"] = self.region_negative.toPlainText()
            region["text_type"] = self.text_type.currentText()
            region["text_render"] = self.text_render.currentText()
            region["text_content"] = self.text_content.toPlainText()
            region["parent_panel_id"] = self.panel_owner.currentData()
            self.text_options.setVisible(region["kind"] == "text")
            item = self.regions.currentItem()
            item.setText(self.region_display_name(self.regions.currentRow(), region))
            item.setForeground(QBrush(QColor(region_color(region))))
            self.persist()

    def selection_bounds(self):
        selection = self._document.selection() if self._document else None
        if selection is None:
            QMessageBox.information(self, "範囲を指定", "Kritaの矩形選択ツールで範囲を指定してください。")
            return None
        x, y = max(0, selection.x()), max(0, selection.y())
        right = min(self._document.width(), selection.x() + selection.width())
        bottom = min(self._document.height(), selection.y() + selection.height())
        if right <= x or bottom <= y:
            return None
        return [x, y, right - x, bottom - y]

    def current_panel_bounds(self):
        window = Krita.instance().activeWindow()
        panel_dock = next((d for d in window.dockers() if d.objectName() == "manga_panels"), None) if window else None
        panel = panel_dock.current() if panel_dock and panel_dock.document == self._document else None
        if not panel:
            return None
        xs = [p[0] for p in panel["polygon"]]
        ys = [p[1] for p in panel["polygon"]]
        return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]

    def change_target_mode(self, index):
        if self._loading or self._state is None:
            return
        mode = self.target_mode.currentData()
        bounds = None
        if mode == "selection":
            bounds = self.selection_bounds()
        elif mode == "current_panel":
            bounds = self.current_panel_bounds()
            if bounds is None:
                self.status.setText("コマ一覧で対象コマを選択してください")
                return
        elif mode == "full_page":
            bounds = [0, 0, self._document.width(), self._document.height()]
        if bounds:
            self._state["target_mode"] = mode
            self._state["target"] = bounds
            self.persist()

    def apply_selection_action(self):
        kind = self.selection_action.currentData()
        if kind == "target":
            self.use_selection_as_target()
        else:
            self.add_from_selection(kind)

    def use_selection_as_target(self):
        bounds = self.selection_bounds()
        if not bounds or self._state is None:
            return
        self._state["target_mode"] = "selection"
        self._state["target"] = bounds
        index = self.target_mode.findData("selection")
        self.target_mode.blockSignals(True)
        self.target_mode.setCurrentIndex(index)
        self.target_mode.blockSignals(False)
        self.common_prompt_section.toggle.setChecked(True)
        self.persist()
        self.status.setText("選択範囲を生成対象にしました。描きたい人物・背景を全体プロンプトへ入力してください。")
        QTimer.singleShot(0, self.scene.setFocus)

    def add_from_selection(self, kind="character"):
        bounds = self.selection_bounds()
        if bounds:
            region = metadata.add_region(self._state, bounds)
            region["kind"] = kind if kind in ("character", "object", "background", "text") else "character"
            label = {"character": "人物", "object": "物体", "background": "背景", "text": "文字"}[region["kind"]]
            count = sum(1 for item in self._state["regions"] if item.get("kind") == region["kind"])
            region["name"] = "%s %d" % (label, count)
            if region["kind"] == "text":
                region["text_type"] = "オノマトペ"
                region["text_render"] = "指定した文字を描く"
                panel = self.current_panel()
                region["parent_panel_id"] = panel.get("id") if panel else None
            self.refresh_region_items(len(self._state["regions"]) - 1)
            self.region_prompt_section.toggle.setChecked(True)
            self.persist()
            self.refresh_overlay()
            self.status.setText(
                "選択範囲を%sの配置領域に追加しました。この領域に描きたい内容を入力してください。" % label)
            QTimer.singleShot(0, self.text_content.setFocus if region["kind"] == "text" else self.prompt.setFocus)

    def current_panel(self):
        window = Krita.instance().activeWindow()
        dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        return dock.current() if dock and getattr(dock, "document", None) == self._document else None

    def refresh_panel_owners(self, region=None):
        selected = region.get("parent_panel_id") if region else None
        self.panel_owner.blockSignals(True)
        self.panel_owner.clear()
        self.panel_owner.addItem("所属なし", None)
        window = Krita.instance().activeWindow()
        dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        panels = dock.active_panels() if dock and getattr(dock, "document", None) == self._document else []
        for index, panel in enumerate(panels):
            self.panel_owner.addItem("コマ %02d" % (index + 1), panel.get("id"))
        owner_index = self.panel_owner.findData(selected)
        self.panel_owner.setCurrentIndex(max(0, owner_index))
        self.panel_owner.blockSignals(False)

    def create_text_material(self):
        region = self.current()
        if not region or region.get("kind") != "text":
            QMessageBox.information(self, "文字領域", "文字・オノマトペ領域を選択してください。")
            return
        text = region.get("text_content", "").strip()
        parent_node = None
        owner_id = region.get("parent_panel_id")
        window = Krita.instance().activeWindow()
        panel_dock = next((item for item in window.dockers() if item.objectName() == "manga_panels"), None) if window else None
        if panel_dock and getattr(panel_dock, "document", None) == self._document:
            owner = next((panel for panel in panel_dock.active_panels() if panel.get("id") == owner_id), None)
            parent_node = owner.get("node") if owner else None
        dialog = OnomatopoeiaMaterialDialog(
            self.window(), initial_text=text, fixed_bounds=list(region["bbox"]),
            fixed_parent_node=parent_node)
        if dialog.exec_():
            region["text_content"] = dialog.text.text().strip()
            region["text_type"] = "オノマトペ"
            region["text_render"] = "指定した文字を描く"
            self.select_region(self.regions.currentRow())
            self.persist()

    def move_region(self):
        region = self.current()
        if region:
            bounds = self.selection_bounds()
            if bounds:
                region["bbox"] = bounds
                region["point"] = [bounds[0] + bounds[2] / 2, bounds[1] + bounds[3] / 2]
                self.bounds.setText("位置：%s  範囲：%s" % (region["point"], bounds))
                self.persist()
                self.refresh_overlay()

    def remove(self):
        row = self.regions.currentRow()
        if row >= 0:
            self._loading = True
            self._state["regions"].pop(row)
            self.refresh_region_items(min(row, len(self._state["regions"]) - 1))
            self._loading = False
            self.select_region(self.regions.currentRow())
            self.persist()
            self.refresh_overlay()

    def generation_bounds(self):
        mode = self.target_mode.currentData()
        if mode == "current_panel":
            bounds = self.current_panel_bounds()
            if bounds is None:
                raise ValueError("コマ一覧で生成対象のコマを選択してください")
            return bounds
        if mode == "selection":
            bounds = self.selection_bounds()
            if bounds is None:
                raise ValueError("矩形選択で生成範囲を指定してください")
            return bounds
        return [0, 0, self._document.width(), self._document.height()]

    def generation_prompts(self, bounds):
        prompt = self.scene.toPlainText().strip()
        negative = self.negative.toPlainText().strip()
        x, y, width, height = bounds
        background, exclusions, regions = [], [], []
        for region in self._state.get("regions", []):
            rx, ry, rw, rh = region["bbox"]
            intersects = min(x + width, rx + rw) > max(x, rx) and min(y + height, ry + rh) > max(y, ry)
            text = region.get("prompt", "").strip()
            if region.get("kind") == "text":
                instruction = "%s。%s" % (
                    region.get("text_type", "未分類"),
                    region.get("text_render", "文字を描かず空間を確保"))
                content = region.get("text_content", "").strip()
                if content and region.get("text_render") == "指定した文字を描く":
                    instruction += "。文字内容：" + content
                text = "、".join(part for part in (instruction, text) if part)
            if not intersects or not text:
                continue
            named = "%s: %s" % (region.get("name") or region.get("kind"), text)
            if region.get("kind") == "background":
                background.append(named)
            else:
                regions.append({"name": region.get("name", ""), "kind": region.get("kind", "character"),
                                "prompt": named, "bbox": list(region["bbox"])})
            if region.get("negative_prompt", "").strip():
                exclusions.append(region["negative_prompt"].strip())
        return (", ".join(part for part in [prompt] + background if part),
                ", ".join(part for part in [negative] + exclusions if part), regions)

    @staticmethod
    def bfs_png(image, width, height):
        if image.isNull():
            raise ValueError("BFSへ送る画像を読み込めませんでした")
        canvas = QImage(width, height, QImage.Format_RGB32)
        canvas.fill(Qt.white)
        scaled = image.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawImage((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
        painter.end()
        buffer = QBuffer()
        if not buffer.open(QIODevice.WriteOnly) or not canvas.save(buffer, "PNG"):
            raise ValueError("BFS用PNGを作成できませんでした")
        result = bytes(buffer.data())
        buffer.close()
        return result

    def generate_preview(self):
        if self._busy or not self._document or self._state is None:
            return
        try:
            self.stop_canvas_modes()
            bounds = self.generation_bounds()
            prompt, negative, regions = self.generation_prompts(bounds)
            bfs_mode = self.generation_mode.currentData()
            if bfs_mode in ("head", "body"):
                prompt = self.scene.toPlainText().strip()
                negative = self.negative.toPlainText().strip()
            if not prompt and bfs_mode not in ("head", "body"):
                raise ValueError("全体プロンプトを入力してください")
            seed = self.seed.value()
            if seed < 0:
                seed = random.randrange(0, 2147483648)
            token = object()
            document = self._document
            steps = self.steps.value()
            guidance = self.guidance.value()
            model_id = self.model.currentData() or self.model.currentText()
            base_png = reference_png = None
            if bfs_mode in ("head", "body"):
                reference = QImage(self.bfs_reference_path.text())
                if reference.isNull():
                    raise ValueError("BFSの参照画像を選択してください（PNG・JPGなど）")
                x, y, target_width, target_height = [int(round(value)) for value in bounds]
                base = document.projection(x, y, target_width, target_height)
                width, height = comfy_backend.generation_size(bounds, maximum=self.ai_config["maximum"])
                base_png = self.bfs_png(base, width, height)
                scale = min(1.0, 768 / max(reference.width(), reference.height()))
                reference_png = self.bfs_png(reference, max(32, int(reference.width() * scale)),
                                             max(32, int(reference.height() * scale)))
                self.source_preview.setPixmap(QPixmap.fromImage(base).scaled(
                    150, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            parent_id = None
            if self.target_mode.currentData() == "current_panel":
                window = Krita.instance().activeWindow()
                panel_dock = next((d for d in window.dockers() if d.objectName() == "manga_panels"), None) if window else None
                panel = panel_dock.current() if panel_dock and panel_dock.document == document else None
                parent_id = panel["node"] if panel else None
            self._generation_token = token
            self._busy = True
            self.begin_generation_ui("ComfyUIへ送信中…")

            def work():
                try:
                    progress = lambda message: self.generation_signals.progress.emit(message, token)
                    if bfs_mode in ("head", "body"):
                        image, info = bfs_backend.generate(
                            bfs_mode, base_png, reference_png, prompt, negative, seed, steps,
                            server=self.ai_config["server"], timeout=self.ai_config["timeout"],
                            progress=progress)
                        info["size"] = [width, height]
                    else:
                        image, info = comfy_backend.generate(
                            prompt, negative, seed, steps, guidance, bounds, regions,
                            progress, server=self.ai_config["server"], timeout=self.ai_config["timeout"],
                            model_id=model_id, maximum=self.ai_config["maximum"])
                    info["parent_node"] = parent_id
                    self.generation_signals.finished.emit(image, info,
                                                          [int(round(v)) for v in bounds], token)
                except Exception as error:
                    self.generation_signals.failed.emit(str(error), token)
            threading.Thread(target=work, name="KritaMangaComfyPreview", daemon=True).start()
        except Exception as error:
            self.status.setText(str(error))

    def generation_progress(self, message, token):
        if token is self._generation_token:
            self._generation_message = message
            self.generation_activity_detail.setText(message)
            self.status.setText(message)

    def begin_generation_ui(self, message):
        self._generation_started_at = time.monotonic()
        self._generation_message = message
        self.generate.setEnabled(False)
        self.generate.setText("●  AI生成中…")
        self.generation_activity_title.setText("● 生成中 0:00")
        self.generation_activity_detail.setText(message)
        self.generation_activity.setVisible(True)
        self.tabs.setTabText(0, "生成 ●")
        self.setWindowTitle("AI作画 ● 生成中")
        self.status.setText(message)
        self._generation_clock.start()

    def update_generation_elapsed(self):
        if not self._busy or self._generation_started_at is None:
            return
        elapsed = max(0, int(time.monotonic() - self._generation_started_at))
        self.generation_activity_title.setText(
            "● 生成中 %d:%02d" % divmod(elapsed, 60))

    def end_generation_ui(self):
        self._generation_clock.stop()
        self._generation_started_at = None
        self._generation_message = ""
        self.generate.setText("▶  AIプレビュー生成")
        self.generate.setEnabled(self._document is not None and self._state is not None)
        self.generation_activity.setVisible(False)
        self.tabs.setTabText(0, "生成")
        self.setWindowTitle("AI作画")

    def generation_failed(self, message, token):
        if token is not self._generation_token:
            return
        self._busy = False
        self._generation_token = None
        self.end_generation_ui()
        self.status.setText("生成に失敗しました：" + message)

    @staticmethod
    def find_node(document, identity):
        def walk(node):
            if node.uniqueId().toString() == identity:
                return node
            for child in node.childNodes():
                found = walk(child)
                if found:
                    return found
        return walk(document.rootNode())

    def generation_finished(self, image_data, info, bounds, token):
        if token is not self._generation_token:
            return
        self._busy = False
        self._generation_token = None
        self.end_generation_ui()
        image = QImage.fromData(image_data)
        if image.isNull():
            self.status.setText("生成画像を読み込めませんでした")
            return
        x, y, width, height = bounds
        scaled = image.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        left = max(0, (scaled.width() - width) // 2)
        top = max(0, (scaled.height() - height) // 2)
        placed = scaled.copy(left, top, width, height).convertToFormat(QImage.Format_ARGB32)
        parent = (self.find_node(self._document, info.get("parent_node"))
                  if info.get("parent_node") else self._document.rootNode())
        parent = parent or self._document.rootNode()
        bfs = info.get("mode", "").startswith("bfs_")
        if bfs:
            for node in parent.childNodes():
                if node.name().startswith("BFS Preview"):
                    node.setVisible(False)
            layer_name = "BFS Preview %s · Seed %s" % (
                "頭部" if info["mode"] == "bfs_head" else "全身", info["seed"])
        else:
            for node in list(parent.childNodes()):
                if node.name() == "AI Preview":
                    node.remove()
            layer_name = "AI Preview"
        layer = self._document.createNode(layer_name, "paintlayer")
        parent.addChildNode(layer, None)
        ptr = placed.constBits()
        ptr.setsize(placed.byteCount())
        layer.setPixelData(QByteArray(bytes(ptr)), x, y, width, height)
        self._document.setActiveNode(layer)
        self._document.setModified(True)
        self._document.refreshProjection()
        self.ai_preview.setPixmap(QPixmap.fromImage(image).scaled(150, 110, Qt.KeepAspectRatio,
                                                                  Qt.SmoothTransformation))
        self.status.setText("%sを追加 · Seed %s · %s" % (layer_name, info["seed"], info["size"]))
