"""Opt-in page layerization, isolated from Krita's layer/shape creation loop."""
import json
import os
from pathlib import Path
from uuid import uuid4

from krita import Krita
from PyQt5.QtCore import QObject, QProcess, QTimer, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QProgressBar, QCheckBox, QMessageBox, QFileDialog)


class LayerizeController(QObject):
    def __init__(self, owner, button):
        super().__init__(owner)
        self.owner, self.button = owner, button
        self.process = None
        self.dialog = None
        self.cancelled = False

    def runtime(self):
        path = Krita.instance().readSetting('manga_workspace', 'layerize_runtime', '')
        if path:
            return Path(path)
        config = Path(__file__).with_name('layerize-local.json')
        if config.is_file():
            return Path(json.loads(config.read_text(encoding='utf-8'))['runtime'])
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MangaWorkspaceLayerize/runtime-v1'

    def choose_runtime(self):
        folder = QFileDialog.getExistingDirectory(self.owner, 'レイヤー化の専用環境（venv・model.onnx・bubble.h5）')
        if folder:
            Krita.instance().writeSetting('manga_workspace', 'layerize_runtime', folder)

    def start(self):
        if self.process is not None:
            return
        if self.dialog and self.dialog.isVisible():
            self.dialog.raise_()
            return
        doc = self.owner.document
        window = Krita.instance().activeWindow()
        if doc is None or not window or not window.activeView() or window.activeView().document() != doc:
            QMessageBox.information(self.owner, 'レイヤー化', '対象のページを開いてください')
            return
        try:
            root = self.runtime()
            python = root / 'venv/Scripts/python.exe'
            if not all(p.is_file() for p in (python, root/'model.onnx', root/'bubble.h5')):
                QMessageBox.information(self.owner, 'レイヤー化', '専用環境が見つかりません。ボタンの右クリックから環境を選択してください。')
                return
            if doc.width()*doc.height() > 12000000:
                QMessageBox.information(self.owner, 'レイヤー化', '試験版は1200万画素までです。複製した画像を縮小して実行してください。')
                return
            self.source_document, self.source_window = doc, window
            self.dpi = doc.resolution()
            self.folder = root.parent / 'results' / uuid4().hex
            self.folder.mkdir(parents=True)
            if not doc.projection(0, 0, doc.width(), doc.height()).save(str(self.folder/'source.png'), 'PNG'):
                raise ValueError('解析用の画像を保存できませんでした')
            self.root, self.python = root, python
            dialog = QDialog(self.owner)
            self.dialog = dialog
            dialog.setWindowTitle('レイヤー化 — ' + (doc.name() or '現在のページ'))
            dialog.resize(620, 760)
            layout = QVBoxLayout(dialog)
            note = QLabel('表示中の画像を解析します。元ページは保持し、結果は新しいタブで開きます。\n'
                          '文字・コマ枠は画像です。人物輪郭は要確認。隠れた背景の補完は行いません。')
            note.setWordWrap(True)
            layout.addWidget(note)
            self.rectangles = QCheckBox('人物は矩形で保持（輪郭分離で欠ける場合）')
            self.rectangles.setToolTip('背景を含む矩形で保持します。人物の輪郭分離は行いません。')
            layout.addWidget(self.rectangles)
            self.status = QLabel('準備中…')
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            self.bar = QProgressBar()
            layout.addWidget(self.bar)
            self.preview = QLabel('解析結果をここに表示します')
            self.preview.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.preview, 1)
            row = QHBoxLayout()
            self.retry = QPushButton('この設定で再解析')
            self.retry.clicked.connect(self.launch)
            row.addWidget(self.retry)
            self.open_button = QPushButton('確認してレイヤー原稿を開く')
            self.open_button.setEnabled(False)
            self.open_button.clicked.connect(self.open_result)
            row.addWidget(self.open_button)
            self.stop = QPushButton('停止')
            self.stop.clicked.connect(self.cancel_or_close)
            row.addWidget(self.stop)
            layout.addLayout(row)
            dialog.finished.connect(self.cancel)
            dialog.show()
            self.launch()
        except Exception as error:
            QMessageBox.warning(self.owner, 'レイヤー化', str(error))

    def launch(self):
        if self.process is not None:
            return
        self.cancelled = False
        self.button.setEnabled(False)
        self.rectangles.setEnabled(False)
        self.retry.setEnabled(False)
        self.open_button.setEnabled(False)
        self.stop.setText('停止')
        self.bar.setValue(0)
        self.status.setText('解析を開始しています…')
        self.log, self.pending = '', ''
        process = QProcess(self)
        self.process = process
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(lambda error: self.failed_start(process) if error == QProcess.FailedToStart else None)
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(self.cancel)
        timer.start(15*60*1000)
        args = ['-u', str(Path(__file__).with_name('layerize_worker.py')),
                '--image', str(self.folder/'source.png'), '--output', str(self.folder),
                '--detector', str(self.root/'model.onnx'), '--bubble', str(self.root/'bubble.h5')]
        if self.rectangles.isChecked():
            args.append('--rectangles')
        process.start(str(self.python), args)

    def read_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self.log = (self.log + text)[-16000:]
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            try:
                item = json.loads(line)
                self.bar.setValue(int(item['progress']))
                self.status.setText(item['message'])
            except (ValueError, KeyError, TypeError):
                pass

    def failed_start(self, process):
        if self.process is process:
            self.log = process.errorString()
            self.finished(-1, QProcess.CrashExit)

    def finished(self, code, status):
        if self.process is None:
            return
        self.read_output()
        process, self.process = self.process, None
        process.deleteLater()
        self.button.setEnabled(True)
        self.rectangles.setEnabled(True)
        self.retry.setEnabled(True)
        self.stop.setText('閉じる')
        if self.cancelled:
            self.status.setText('停止しました。元ページは変更していません。')
            return
        if code != 0 or status != QProcess.NormalExit:
            self.status.setText('解析に失敗しました。元ページは変更していません。\n' + self.log[-1200:])
            return
        try:
            result = json.loads((self.folder/'result.json').read_text(encoding='utf-8'))
            if not result.get('verified_composite'):
                raise ValueError('再合成の検証結果がありません')
            self.preview.setPixmap(QPixmap(str(self.folder/'preview.png')).scaled(560, 510, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.status.setText(f"{result['panels']}コマ・人物{result['characters']}領域・吹き出し{result['bubbles']}個\n"
                                '橙：人物／緑：吹き出し。髪・顔の欠けや背景混入を確認してください。')
            self.open_button.setEnabled(True)
        except Exception as error:
            self.status.setText('結果を確認できません：' + str(error))

    def cancel(self, *_):
        if self.process:
            self.cancelled = True
            self.process.kill()

    def cancel_or_close(self):
        if self.process:
            self.cancel()
        else:
            self.dialog.close()

    def open_result(self):
        if self.process or not self.open_button.isEnabled():
            return
        window = Krita.instance().activeWindow()
        if window is None:
            return
        self.open_button.setEnabled(False)
        result = Krita.instance().openDocument(str(self.folder/'layerized.ora'))
        if result is None:
            self.status.setText('原稿を開けませんでした：' + str(self.folder/'layerized.ora'))
            self.open_button.setEnabled(True)
            return
        result.setResolution(self.dpi)
        result.setModified(True)
        window.addView(result)
        self.dialog.close()
