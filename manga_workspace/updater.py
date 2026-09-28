"""GitHub release notification and verified in-place plugin updater."""
import hashlib
import io
import json
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from krita import Krita
from PyQt5.QtCore import QObject, QUrl, pyqtSignal, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout,
)

from .update_utils import is_newer, safe_archive_names
from .version import __version__


RELEASES_API = "https://api.github.com/repos/dr1610/krita-manga-workspace/releases?per_page=10"
RELEASES_PAGE = "https://github.com/dr1610/krita-manga-workspace/releases"
MAX_PACKAGE_BYTES = 50 * 1024 * 1024


class UpdateManager(QObject):
    checked = pyqtSignal(object, str)
    available = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.release = None
        self.busy = False

    def check(self):
        if self.busy:
            return
        self.busy = True
        request = QNetworkRequest(QUrl(RELEASES_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", b"krita-manga-workspace-updater")
        reply = self.network.get(request)
        reply.finished.connect(lambda r=reply: self._finished(r))

    def _finished(self, reply):
        self.busy = False
        try:
            if reply.error() != QNetworkReply.NoError:
                raise OSError(reply.errorString())
            releases = json.loads(bytes(reply.readAll()).decode("utf-8"))
            release = next((item for item in releases if not item.get("draft")), None)
            if not release:
                raise ValueError("公開Releaseが見つかりません")
            self.release = release
            self.checked.emit(release, "")
            if is_newer(release.get("tag_name"), __version__):
                self.available.emit(release)
        except Exception as error:
            self.checked.emit(None, str(error))
        finally:
            reply.deleteLater()


class InstallSignals(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)


def package_asset(release):
    assets = release.get("assets") or []
    return next((item for item in assets if item.get("name", "").startswith("manga-workspace-")
                 and item.get("name", "").endswith(".zip")), None)


def install_release(release):
    asset = package_asset(release)
    if not asset:
        raise ValueError("更新用ZIPがReleaseにありません")
    url = asset.get("browser_download_url", "")
    if not url.startswith("https://github.com/dr1610/krita-manga-workspace/"):
        raise ValueError("更新ファイルの配布元が正しくありません")
    request = urllib.request.Request(url, headers={"User-Agent": "krita-manga-workspace-updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_PACKAGE_BYTES + 1)
    if len(data) > MAX_PACKAGE_BYTES:
        raise ValueError("更新ファイルが上限サイズを超えています")
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        raise ValueError("GitHubのSHA-256情報がないため自動更新を中止しました")
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != digest.split(":", 1)[1].lower():
        raise ValueError("更新ファイルのSHA-256が一致しません")

    plugin_dir = Path(__file__).resolve().parent
    pykrita_dir = plugin_dir.parent
    desktop = pykrita_dir / "manga_workspace.desktop"
    backup_root = pykrita_dir.parent / "manga_workspace_backups"
    backup = backup_root / ("%s-%s" % (__version__, datetime.now().strftime("%Y%m%d-%H%M%S")))
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copytree(plugin_dir, backup / "manga_workspace")
    if desktop.is_file():
        shutil.copy2(desktop, backup / "manga_workspace.desktop")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if not safe_archive_names(names):
                raise ValueError("更新ZIPに安全でないパスが含まれています")
            if "manga_workspace/__init__.py" not in names or "manga_workspace.desktop" not in names:
                raise ValueError("更新ZIPのプラグイン構成が不完全です")
            with tempfile.TemporaryDirectory(prefix="manga-workspace-update-") as temp:
                stage = Path(temp)
                archive.extractall(stage)
                shutil.copytree(stage / "manga_workspace", plugin_dir, dirs_exist_ok=True)
                shutil.copy2(stage / "manga_workspace.desktop", desktop)
    except Exception:
        shutil.copytree(backup / "manga_workspace", plugin_dir, dirs_exist_ok=True)
        if (backup / "manga_workspace.desktop").is_file():
            shutil.copy2(backup / "manga_workspace.desktop", desktop)
        raise
    return str(backup)


class UpdateDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.release = manager.release
        self.install_signals = InstallSignals(self)
        self.install_signals.finished.connect(self.install_finished)
        self.install_signals.failed.connect(self.install_failed)
        self.setWindowTitle("漫画ワークスペースの更新")
        self.setMinimumSize(540, 380)
        layout = QVBoxLayout(self)
        self.current = QLabel("現在のバージョン：" + __version__)
        self.latest = QLabel("最新バージョン：確認中")
        layout.addWidget(self.current); layout.addWidget(self.latest)
        self.notes = QPlainTextEdit(); self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("Release情報を確認しています…")
        layout.addWidget(self.notes, 1)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("GitHub Releaseを確認します")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        row = QHBoxLayout()
        self.check_button = QPushButton("更新を確認")
        self.web_button = QPushButton("GitHubで開く")
        self.install_button = QPushButton("更新を適用")
        self.install_button.setEnabled(False)
        row.addWidget(self.check_button); row.addWidget(self.web_button); row.addStretch(1); row.addWidget(self.install_button)
        layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(self.reject); layout.addWidget(close)
        self.check_button.clicked.connect(self.check)
        self.web_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            self.release.get("html_url", RELEASES_PAGE) if self.release else RELEASES_PAGE)))
        self.install_button.clicked.connect(self.install)
        self.manager.checked.connect(self.checked)
        if self.release:
            self.checked(self.release, "")
        else:
            self.check()

    def check(self):
        self.check_button.setEnabled(False)
        self.status.setText("GitHub Releaseを確認中…")
        self.manager.check()

    def checked(self, release, error):
        self.check_button.setEnabled(True)
        if error:
            self.status.setText("更新確認に失敗しました：" + error)
            return
        self.release = release
        tag = str(release.get("tag_name", ""))
        self.latest.setText("最新バージョン：" + tag.lstrip("v"))
        self.notes.setPlainText(release.get("body") or "Release説明はありません")
        newer = is_newer(tag, __version__)
        self.install_button.setEnabled(newer and package_asset(release) is not None)
        self.status.setText("更新できます。" if newer else "現在のバージョンは最新です。")

    def install(self):
        if not self.release:
            return
        answer = QMessageBox.question(
            self, "更新を適用", "GitHubから更新ZIPを取得し、現在版をバックアップして配置します。\n"
            "反映にはKritaの再起動が必要です。続けますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.install_button.setEnabled(False); self.check_button.setEnabled(False)
        self.progress.show(); self.status.setText("更新をダウンロード・検証・配置しています…")

        def work():
            try:
                backup = install_release(self.release)
                self.install_signals.finished.emit(backup)
            except Exception as error:
                self.install_signals.failed.emit(str(error))
        threading.Thread(target=work, name="MangaWorkspaceUpdater", daemon=True).start()

    def install_finished(self, backup):
        self.progress.hide(); self.check_button.setEnabled(True)
        self.status.setText("更新を配置しました。Kritaを再起動してください。")
        QMessageBox.information(self, "更新完了", "更新を配置しました。\nKritaを再起動すると反映されます。\n\nバックアップ：" + backup)

    def install_failed(self, error):
        self.progress.hide(); self.check_button.setEnabled(True); self.install_button.setEnabled(True)
        self.status.setText("更新に失敗しました：" + error)
        QMessageBox.warning(self, "更新失敗", error)
