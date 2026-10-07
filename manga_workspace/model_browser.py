from pathlib import Path
from krita import Krita
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QStandardPaths, QUrl
from PyQt5.QtGui import QIcon, QPixmap, QDesktopServices
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                             QLabel, QPushButton, QComboBox, QLineEdit, QInputDialog,
                             QApplication, QScrollArea)
from .model_previews import read_preview, fetch_preview, guessed_version, version_id, catalog_entry


class PreviewWorker(QThread):
    result = pyqtSignal(str, object, str)

    def __init__(self, cache, checkpoint, version, manual):
        super().__init__(QApplication.instance())
        self.args = cache, checkpoint, version, manual

    def run(self):
        try:
            data = fetch_preview(*self.args)
            self.result.emit(self.args[1], data, '')
        except Exception as error:
            self.result.emit(self.args[1], {}, str(error))


class ModelBrowser(QDialog):
    def __init__(self, window):
        super().__init__(window.qwindow())
        self.krita_window = window
        self.setWindowTitle('生成モデル · 選択と参考画像')
        self.resize(850, 660)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.cache = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / 'manga_model_previews'
        self.rows, self.busy, self.metadata = [], False, {}
        layout = QVBoxLayout(self)
        self.target = QComboBox()
        self.target.addItems(['RT生成（Krita AI Diffusion）', 'AI作画（漫画ワークスペース）'])
        self.target.currentIndexChanged.connect(self.reload)
        layout.addWidget(self.target)
        self.current = QLabel()
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.search = QLineEdit()
        self.search.setPlaceholderText('モデル名・チェックポイント名で検索')
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.models = QListWidget()
        self.models.setIconSize(QSize(76, 76))
        self.models.currentItemChanged.connect(self.selected)
        layout.addWidget(self.models, 1)
        self.details = QLabel()
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.usage = QLabel()
        self.usage.setWordWrap(True)
        self.usage.setTextFormat(Qt.PlainText)
        usage_scroll = QScrollArea()
        usage_scroll.setWidgetResizable(True)
        usage_scroll.setWidget(self.usage)
        usage_scroll.setMaximumHeight(125)
        layout.addWidget(usage_scroll)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setIconSize(QSize(128, 128))
        self.gallery.setFixedHeight(166)
        self.gallery.itemDoubleClicked.connect(self.enlarge)
        layout.addWidget(self.gallery)
        row = QHBoxLayout()
        self.fetch = QPushButton('参考画像を取得')
        self.fetch.clicked.connect(self.fetch_images)
        row.addWidget(self.fetch)
        specify = QPushButton('配布URLを指定…')
        specify.clicked.connect(lambda: self.fetch_images(True))
        row.addWidget(specify)
        self.source = QPushButton('配布元を開く')
        self.source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.metadata.get('url', ''))))
        row.addWidget(self.source)
        configure = QPushButton('モデル設定…')
        configure.clicked.connect(self.configure)
        row.addWidget(configure)
        refresh = QPushButton('一覧を更新')
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.status = QLabel('参考画像は配布元の作例です。LoRAやプロンプトによって実際の結果は変わります。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.apply = QPushButton('このモデルを使う')
        self.apply.clicked.connect(self.apply_model)
        layout.addWidget(self.apply)
        self.reload()

    def ai_dock(self):
        return next((d for d in self.krita_window.dockers() if d.objectName() == 'manga_workspace'), None)

    def reload(self, *_):
        self.rows = []
        try:
            if self.target.currentIndex() == 0:
                from ai_diffusion.model.root import root
                from ai_diffusion.style import Styles
                from ai_diffusion.backend.client import filter_supported_styles
                client = root.connection.client_if_connected
                supported = filter_supported_styles(list(Styles.list()), client) if client else []
                model = root.model_for_active_document()
                self.current.setText('使用中：' + (model.style.name if model else '原稿を開いてください'))
                for style in Styles.list():
                    checkpoint = style.preferred_checkpoint(client.models.checkpoints) if client else next(iter(style.checkpoints), '')
                    if checkpoint == 'not-found':
                        checkpoint = next(iter(style.checkpoints), '')
                    self.rows.append(dict(name=style.name, checkpoint=checkpoint, key=style.filename,
                                          enabled=style in supported, reason='RT設定あり · 速度はモデルとステップ数によります'
                                          if style in supported else '未接続、または必要なモデルが未導入'))
            else:
                dock = self.ai_dock()
                if dock is None:
                    raise RuntimeError('AI作画パネルがありません')
                self.current.setText('使用中：' + dock.model.currentText())
                for i in range(dock.model.count()):
                    key = dock.model.itemData(i) or dock.model.itemText(i)
                    self.rows.append(dict(name=dock.model.itemText(i), checkpoint=key.split(':', 1)[-1],
                                          key=key, enabled=True, reason='AI作画に登録されたモデル（接続・生成可否は生成時に確認）'))
            self.filter()
        except Exception as error:
            self.status.setText(str(error))
            self.filter()

    def filter(self, *_):
        self.models.clear()
        query = self.search.text().casefold()
        for row in self.rows:
            if query not in (row['name'] + ' ' + row['checkpoint']).casefold():
                continue
            item = QListWidgetItem(row['name'] + '\n' + row['checkpoint'])
            item.setData(Qt.UserRole, row)
            metadata = read_preview(self.cache, row['checkpoint'])
            if metadata.get('images'):
                item.setIcon(QIcon(str(self.cache / metadata['images'][0])))
            self.models.addItem(item)
        if self.models.count():
            self.models.setCurrentRow(0)

    def selected(self, item, previous=None):
        self.gallery.clear()
        self.metadata = {}
        self.usage.clear()
        self.apply.setEnabled(bool(item and item.data(Qt.UserRole)['enabled']))
        self.fetch.setEnabled(bool(item) and not self.busy)
        self.source.setEnabled(False)
        if item is None:
            self.details.setText('モデルがありません')
            return
        row = item.data(Qt.UserRole)
        entry = catalog_entry(row['checkpoint'])
        if entry:
            self.usage.setText(entry['purpose'] + '\n' + entry['description'] + '\n評価：作者情報に基づく用途案。実機の使用感は未検証。')
        self.details.setText(row['reason'] + '\nCheckpoint: ' + row['checkpoint'])
        self.metadata = read_preview(self.cache, row['checkpoint'])
        self.source.setEnabled(bool(self.metadata.get('url')))
        for filename in self.metadata.get('images', []):
            path = self.cache / filename
            if path.is_file():
                card = QListWidgetItem(QIcon(str(path)), '拡大')
                card.setData(Qt.UserRole, str(path))
                self.gallery.addItem(card)
        if not self.gallery.count():
            self.gallery.addItem('参考画像なし：「参考画像を取得」で配布元から取得')

    def fetch_images(self, force_manual=False):
        item = self.models.currentItem()
        if item is None or self.busy:
            return
        checkpoint = item.data(Qt.UserRole)['checkpoint']
        version = None if force_manual else guessed_version(checkpoint)
        manual = not bool(version)
        if manual:
            text, ok = QInputDialog.getText(self, '配布バージョンを指定',
                                          'CivitaiのURL（modelVersionId付き）またはバージョンID')
            if not ok:
                return
            version = version_id(text)
        if not version:
            self.status.setText('バージョンを特定できません。modelVersionId付きの配布URLを指定してください')
            return
        self.busy = True
        self.fetch.setEnabled(False)
        self.status.setText('配布元の参考画像を取得中…')
        worker = PreviewWorker(str(self.cache), checkpoint, version, manual)
        worker.result.connect(self.fetched)
        worker.finished.connect(worker.deleteLater)
        self.worker = worker
        worker.start()

    def fetched(self, checkpoint, data, error):
        self.busy = False
        self.selected(self.models.currentItem())
        self.status.setText('取得できませんでした: ' + error if error else
                            f"参考画像 {len(data.get('images', []))}枚を保存しました。ダブルクリックで拡大できます。")
        for i in range(self.models.count()):
            item = self.models.item(i)
            if item.data(Qt.UserRole)['checkpoint'] == checkpoint and data.get('images'):
                item.setIcon(QIcon(str(self.cache / data['images'][0])))

    def enlarge(self, item):
        path = item.data(Qt.UserRole)
        if not path:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('配布元の参考画像')
        dialog.resize(850, 850)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        label = QLabel()
        label.setPixmap(QPixmap(path))
        scroll.setWidget(label)
        layout.addWidget(scroll)
        dialog.exec_()

    def configure(self):
        if self.target.currentIndex() == 0:
            from ai_diffusion.ui.settings import SettingsDialog
            SettingsDialog.instance().show()
        else:
            dock = self.ai_dock()
            if dock:
                dock.show()

    def apply_model(self):
        item = self.models.currentItem()
        if item is None:
            return
        row = item.data(Qt.UserRole)
        try:
            if self.target.currentIndex() == 0:
                from ai_diffusion.model.root import root
                from ai_diffusion.style import Styles
                from ai_diffusion.backend.client import filter_supported_styles
                model = root.model_for_active_document()
                if model is None:
                    raise RuntimeError('原稿を開いてください')
                if model.live.is_active:
                    raise RuntimeError('RT生成を停止してからモデルを変更してください')
                style = Styles.list().find(row['key'])
                client = root.connection.client_if_connected
                if not client or style not in filter_supported_styles([style], client):
                    raise RuntimeError('未接続、または必要なモデルが未導入です')
                model.style = style
                # Persist for the selected layer, even when RT is not open yet.
                from .live_layer_state import read_states, owner_id, KEY
                from PyQt5.QtCore import QByteArray
                import json
                doc = Krita.instance().activeDocument()
                node = doc.activeNode() if doc else None
                if node:
                    states = read_states(doc)
                    owner = owner_id(states, node.uniqueId().toString())
                    states.setdefault(owner, {})['style'] = style.filename
                    doc.setAnnotation(KEY, 'レイヤー別RT設定', QByteArray(json.dumps(states).encode('utf-8')))
                    doc.setModified(True)
            else:
                dock = self.ai_dock()
                if dock is None or dock._state is None:
                    raise RuntimeError('AI作画の対象原稿を開いてください')
                index = dock.model.findData(row['key'])
                if index < 0:
                    raise RuntimeError('モデル一覧を更新してください')
                dock.model.setCurrentIndex(index)
            self.current.setText('使用中：' + row['name'])
            self.status.setText('選択した生成先へ適用しました')
        except Exception as error:
            self.status.setText(str(error))
