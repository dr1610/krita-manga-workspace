"""Independent reference slots backed by official KAD controls."""
from pathlib import Path
from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QImage, QImageReader, QPainter
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QPushButton, QLabel


class ReferenceDocument:
    def __init__(self, document, image):
        self.document, self.image = document, image

    def __getattr__(self, name):
        return getattr(self.document, name)

    def get_image(self, *args, **kwargs):
        from ai_diffusion.image import Image
        return Image(self.image)

    def create_mask_from_selection(self, *args):
        return None, None


class ReferenceSlot(QWidget):
    def __init__(self, dialog, title, mode, drop_class):
        super().__init__(dialog)
        self.dialog, self.title, self.mode = dialog, title, mode
        self.image = self.node = self.control = None
        self.pending = None
        self.closed = False
        dialog.model.jobs.job_finished.connect(self.job_finished)
        dialog.model.style_changed.connect(self.sync)
        dialog.connection.state_changed.connect(self.sync)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(6)
        self.drop = drop_class(self)
        self.drop.description.setText(title + '画像をここへドロップ\nPNG・JPG・WebP')
        self.drop.image_dropped.connect(self.load)
        layout.addWidget(self.drop)
        row = QHBoxLayout()
        self.enabled = QCheckBox('使用')
        self.enabled.setChecked(mode != 'pose')
        if mode == 'pose':
            self.enabled.setText('RTでも常時使用（重くなります）')
        self.enabled.toggled.connect(self.sync)
        row.addWidget(self.enabled)
        row.addWidget(QLabel('効き具合'))
        self.strength = QSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setValue(100)
        self.strength.setSuffix('%')
        self.strength.valueChanged.connect(self.sync)
        self.strength.setFixedWidth(76)
        row.addWidget(self.strength)
        remove = QPushButton('削除')
        remove.clicked.connect(self.clear)
        remove.setFixedWidth(54)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)
        self.pose_ready = QCheckBox('骨格画像をそのまま使う（OpenPose形式）')
        self.pose_ready.setVisible(mode == 'pose')
        self.pose_ready.toggled.connect(self.reload)
        layout.addWidget(self.pose_ready)
        self.status = QLabel('画像未選択')
        self.drop.setToolTip('人物写真は骨格抽出後に使用します' if mode == 'pose'
                             else '構図の参考に使用します。背景の完全な複製ではありません')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def load(self, image, path):
        if self.pending:
            self.status.setText('骨格を抽出中です。完了後に画像を変更できます')
            return
        if path:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
        if image is None or image.isNull():
            self.status.setText('画像を読み込めませんでした')
            return
        self.clear()
        self.image = image.scaled(1536, 1536, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.drop.show_image(self.image, Path(path).name if path else '貼り付けた画像')
        self.sync()

    def reload(self, *_):
        if not self.pending:
            self.detach()
            self.sync()

    def sync(self, *_):
        if self.closed or self.pending or self.image is None:
            return
        if not self.enabled.isChecked():
            self.detach()
            self.status.setText('参照はオフです')
            return
        if self.dialog.connection.state.name != 'connected':
            self.status.setText('未使用: サーバー未接続')
            return
        try:
            if self.control is None:
                self.install()
            if self.control:
                self.control.use_custom_strength = True
                self.control.strength = round(self.strength.value() / 2)
                self.update_status()
        except Exception as error:
            if self.pending:
                self.pending.layer_id_changed.disconnect(self.pose_finished)
                self.pending = None
            self.detach()
            self.status.setText('参照を設定できません: ' + str(error))

    def install(self):
        from ai_diffusion.backend.resources import ControlMode
        from ai_diffusion.model.control import ControlLayer
        from .live_panel import image_bytes
        d = self.dialog
        image = self.image.convertToFormat(QImage.Format_ARGB32)
        x, y = 0, 0
        if self.mode == 'pose':
            x, y, w, h = d.bounds
            fitted = QImage(w, h, QImage.Format_ARGB32)
            fitted.fill(Qt.black if self.pose_ready.isChecked() else Qt.white)
            scaled = image.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p = QPainter(fitted)
            p.drawImage((w-scaled.width())//2, (h-scaled.height())//2, scaled)
            p.end()
            image = fitted
        node = d.document.createNode('Live' + self.title + '参照（非表示）', 'paintlayer')
        self.node = node
        d.document.rootNode().addChildNode(node, None)
        node.setVisible(False)
        node.setPixelData(QByteArray(image_bytes(image)), x, y, image.width(), image.height())
        d.model.layers.updated()
        mode = getattr(ControlMode, self.mode)
        if self.mode == 'pose' and not self.pose_ready.isChecked():
            probe = ControlLayer(d.model, mode, node.uniqueId(), 0)
            if not probe.is_supported:
                self.status.setText('参照は未使用（詳細）')
                self.status.setToolTip(probe.error_text)
                self.detach()
                return
            # Official preprocessing normally reads the whole visible drawing.
            # Substitute only the dropped image, without changing the canvas.
            full = QImage(d.document.width(), d.document.height(), QImage.Format_ARGB32)
            full.fill(Qt.white)
            p = QPainter(full)
            p.drawImage(x, y, image)
            p.end()
            original = d.model._doc
            self.pending = probe
            probe.layer_id_changed.connect(self.pose_finished)
            try:
                d.model._doc = ReferenceDocument(original, full)
                job = d.model.generate_control_layer(probe)
            finally:
                d.model._doc = original
            if job is None:
                self.pending = None
                probe.layer_id_changed.disconnect(self.pose_finished)
                raise RuntimeError('骨格抽出を開始できません。接続・モデル設定を確認してください')
            self.status.setText('骨格を抽出中…')
            return
        self.attach(node)

    def attach(self, node):
        from ai_diffusion.backend.resources import ControlMode
        c = self.dialog.model.regions.control.emplace()
        self.control = c
        c.layer_id = node.uniqueId()
        c.mode = getattr(ControlMode, self.mode)
        c.is_supported_changed.connect(self.update_status)
        c.error_text_changed.connect(self.update_status)

    def pose_finished(self, layer_id):
        from .panels import node_by_id
        probe, self.pending = self.pending, None
        probe.layer_id_changed.disconnect(self.pose_finished)
        node = node_by_id(self.dialog.document, layer_id.toString())
        if node is None:
            return
        node.setVisible(False)
        if self.closed:
            node.remove()
            return
        self.detach()
        self.node = node
        # The processed vector remains editable via Krita's shape tools.
        node.setName('Liveポーズ骨格（非表示）')
        self.dialog.document.waitForDone()
        self.dialog.model.layers.updated()
        x, y, w, h = self.dialog.bounds
        pixels = node.projectionPixelData(x, y, w, h)
        preview = QImage(bytes(pixels), w, h, QImage.Format_ARGB32).copy()
        self.drop.show_image(preview, '抽出した骨格')
        self.attach(node)
        self.sync()

    def job_finished(self, job):
        if self.pending is not None and job.control is self.pending:
            self.pending.layer_id_changed.disconnect(self.pose_finished)
            self.pending = None
            self.detach()
            self.status.setText('骨格抽出に失敗、または中断しました。画像を入れ直してください')

    def update_status(self, *_):
        if self.control and not self.closed:
            self.status.setText('未使用: サーバー未接続' if self.dialog.connection.state.name != 'connected'
                                else '参照を設定済み' if self.control.is_supported
                                else '参照は未使用（詳細）')
            self.status.setToolTip(self.control.error_text if not self.control.is_supported else '')

    def detach(self):
        if self.control:
            c, self.control = self.control, None
            c.is_supported_changed.disconnect(self.update_status)
            c.error_text_changed.disconnect(self.update_status)
            if c in list(self.dialog.model.regions.control):
                self.dialog.model.regions.control.remove(c)
        if self.node:
            self.node.remove()
            self.node = None
        self.dialog.model.layers.updated()

    def clear(self):
        if self.pending:
            self.status.setText('骨格抽出の完了後に削除できます')
            return
        self.detach()
        self.image = None
        self.drop.thumbnail.clear()
        self.drop.description.setText(self.title + '画像をここへドロップ')
        self.status.setText('画像未選択')

    def cleanup(self):
        self.closed = True
        self.dialog.model.jobs.job_finished.disconnect(self.job_finished)
        self.dialog.model.style_changed.disconnect(self.sync)
        self.dialog.connection.state_changed.disconnect(self.sync)
        if self.pending:
            # The queued job can finish after the dialog is destroyed. A plain
            # callback removes only its own output without accessing widgets.
            probe, self.pending = self.pending, None
            probe.layer_id_changed.disconnect(self.pose_finished)
            document = self.dialog.document
            def discard_output(layer_id):
                from .panels import node_by_id
                node = node_by_id(document, layer_id.toString())
                if node is not None:
                    node.remove()
                probe.layer_id_changed.disconnect(discard_output)
            probe.layer_id_changed.connect(discard_output)
        self.detach()
