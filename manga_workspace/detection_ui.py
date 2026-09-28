"""QProcess boundary keeps inference and dependencies outside Krita Python."""
import json
import tempfile
from pathlib import Path
from krita import Krita, Selection
from PyQt5.QtCore import QObject, QProcess, QStandardPaths, QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from .detection_data import merge

class DetectionController(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.process = None
        self.temp = None
        self.document = None

    def guarded(self, method):
        def call():
            try:
                method()
            except Exception as error:
                if self.temp and not self.process:
                    self.temp.cleanup(); self.temp = None
                self.owner.status.setText(str(error))
        return call

    def root(self):
        fallback = str(Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'MangaWorkspaceDetector' / 'runtime-v1')
        return Path(Krita.instance().readSetting('manga_workspace', 'detector_runtime', fallback))

    def available(self):
        root = self.root()
        return ((root/'python/python.exe').is_file()
                and (root/'model.onnx').is_file()
                and (root/'runtime.json').is_file())

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self.owner, '検出専用環境のフォルダ（runtime.jsonがある場所）', str(self.root().parent))
        if folder:
            path = Path(folder)
            if not (path/'python/python.exe').is_file() or not (path/'model.onnx').is_file() or not (path/'runtime.json').is_file():
                raise ValueError('自動判定用の専用環境がありません。「自動判定機能を追加導入…」を実行してください。')
            Krita.instance().writeSetting('manga_workspace', 'detector_runtime', folder)
            self.owner.status.setText('検出環境：' + folder)
            self.owner.refresh_detector_ui()

    def setup(self):
        if self.process:
            raise ValueError('検出または導入が実行中です')
        root = self.root()
        if root.exists():
            self.owner.status.setText('導入先が既にあります。既存環境を選ぶか、新しい保存先を指定してください。')
            folder = QFileDialog.getExistingDirectory(self.owner, '新しい検出環境の親フォルダを選択')
            if not folder:
                return
            root = Path(folder)/'MangaWorkspaceDetector-runtime-v1'
        dialog = QMessageBox(self.owner)
        dialog.setIcon(QMessageBox.Question)
        dialog.setWindowTitle('自動判定機能を追加導入（任意）')
        dialog.setText('ページ内のコマ・人物・文字を自動判定する機能を追加します。')
        dialog.setInformativeText(
            '専用Pythonとライブラリ、約250MBの検出モデルをダウンロードします。\n'
            'ダウンロード元：Python公式・PyPI・Hugging Face\n\n'
            '画像やプロンプトは送信しません。既存Pythonは変更しません。\n'
            '導入しなくても、手動の範囲指定と漫画制作機能は使用できます。\n\n'
            '保存先：' + str(root))
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dialog.button(QMessageBox.Ok).setText('ダウンロードして導入')
        dialog.button(QMessageBox.Cancel).setText('キャンセル')
        dialog.setDefaultButton(QMessageBox.Cancel)
        if dialog.exec_() != QMessageBox.Ok:
            return
        self.owner.status.setText('検出専用環境を導入中…（初回ダウンロード）')
        def completed():
            Krita.instance().writeSetting('manga_workspace', 'detector_runtime', str(root))
            self.owner.status.setText('検出環境を導入しました。「ページを自動検出」で実行できます。')
            self.owner.refresh_detector_ui()
        self.launch('powershell.exe', ['-NoProfile','-ExecutionPolicy','Bypass','-File',
                    str(Path(__file__).with_name('Setup-Detector.ps1')), '-RuntimeRoot', str(root)], completed)

    def launch(self, program, args, completed):
        p = QProcess(self)
        self.process = p
        self.log = bytearray()
        p.setProcessChannelMode(QProcess.MergedChannels)
        def read():
            chunk = bytes(p.readAllStandardOutput())
            self.log.extend(chunk)
            if len(self.log) > 65536:
                del self.log[:-65536]
        p.readyReadStandardOutput.connect(read)
        # A timeout kills only our isolated worker, never Krita or ComfyUI.
        timer = QTimer(p)
        timer.setSingleShot(True)
        timer.timeout.connect(p.kill)
        timer.start(30 * 60 * 1000)
        def finish(code, status):
            read()
            self.process = None
            try:
                if code != 0 or status != QProcess.NormalExit:
                    raise ValueError('検出処理が停止・失敗しました。\n' + self.log.decode('utf-8', errors='replace')[-2000:])
                completed()
            except Exception as error:
                self.owner.status.setText(str(error))
            finally:
                if self.temp:
                    self.temp.cleanup()
                    self.temp = None
                p.deleteLater()
        p.finished.connect(finish)
        p.errorOccurred.connect(lambda error: self.owner.status.setText('検出プロセスを起動できません：'+p.errorString()))
        p.start(program, args)
        if not p.waitForStarted(1000):
            self.process = None
            p.deleteLater()
            raise ValueError('検出専用Pythonを起動できません。検出環境を確認してください。')

    def cancel(self):
        if self.process:
            self.process.kill()

    def run(self):
        o = self.owner
        if self.process:
            raise ValueError('検出または導入が実行中です')
        if not o._document or o._state is None:
            return
        root = self.root()
        if not (root/'python/python.exe').is_file() or not (root/'model.onnx').is_file():
            raise ValueError('自動判定機能は未導入です。「自動判定機能を追加導入…」から導入できます。手動の範囲指定はそのまま使えます。')
        self.document = o._document
        captured_state = o._state
        self.temp = tempfile.TemporaryDirectory(prefix='krita-detection-')
        image = Path(self.temp.name)/'page.png'
        output = Path(self.temp.name)/'result.json'
        doc = self.document
        # projection() converts document color space/depth to a QImage safely.
        projection = doc.projection(0, 0, doc.width(), doc.height())
        if not projection.save(str(image), 'PNG'):
            self.temp.cleanup(); self.temp = None
            raise ValueError('検出用ページ画像を保存できませんでした')
        o.status.setText('ページを自動検出中（ローカルCPU）…')
        def completed():
            if o._document is not doc or o._state is not captured_state:
                o.status.setText('ページが切り替わったため検出結果を適用しませんでした。元のページで再実行してください。')
                return
            result = json.loads(output.read_text(encoding='utf-8'))
            added = merge(o._state, result, doc.width(), doc.height())
            o._loading = True
            o.refresh_region_items(len(o._state['regions'])-len(added) if added else -1)
            o._loading = False
            o.persist()
            o.refresh_overlay()
            o.status.setText('%d領域を追加しました。選択してPromptを入力できます。矩形の検出で、輪郭マスクではありません。' % len(added))
        self.launch(str(root/'python/python.exe'), ['-I',str(Path(__file__).with_name('detector_worker.py')),
             '--image',str(image),'--model',str(root/'model.onnx'),'--output',str(output)], completed)

    def select(self):
        o = self.owner
        region = o.current()
        if not region:
            return
        x,y,w,h = [int(round(v)) for v in region['bbox']]
        selection = Selection()
        selection.select(x,y,w,h,255)
        o._document.setSelection(selection)
        o.target_mode.setCurrentIndex(o.target_mode.findData('selection'))
        o.change_target_mode(o.target_mode.currentIndex())
        o.status.setText('検出範囲をKritaの選択範囲・生成対象に設定しました。')
