"""Persistent personal materials, independent of the installation directory."""
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from krita import Krita
from PyQt5.QtCore import Qt, QSize, QStandardPaths, QTimer, QEventLoop
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QListWidget, QListWidgetItem, QListView,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QDialogButtonBox, QLabel)

CATEGORIES = ('描き文字', '吹き出し', '効果線', 'その他')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.svg', '.kra'}


class MaterialStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate(item):
        if not isinstance(item, dict):
            raise ValueError('素材情報が不正です')
        name, filename = item.get('name'), item.get('file')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('素材名が不正です')
        if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix.lower() not in EXTENSIONS:
            raise ValueError('素材ファイル名が不正です')
        if item.get('category') not in CATEGORIES or not isinstance(item.get('tags', ''), str):
            raise ValueError('素材の分類・タグが不正です')
        return item

    def entries(self):
        result = []
        for path in self.root.glob('*/material.json'):
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                self.validate(item)
                item['id'] = path.parent.name
                if Path(item['file']).name != item['file']:
                    continue
                if (path.parent / item['file']).is_file():
                    result.append(item)
            except (ValueError, KeyError, TypeError, OSError):
                continue
        return sorted(result, key=lambda item: item['name'])

    def save(self, item):
        self.validate(item)
        directory = self.store_path(item)
        temp = directory / 'material.tmp'
        temp.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(directory / 'material.json')

    def add(self, source, name, category, tags, thumbnail=None):
        source = Path(source)
        if source.suffix.lower() not in EXTENSIONS:
            raise ValueError('対応していない素材形式です')
        identity = uuid.uuid4().hex
        directory = self.root / identity
        directory.mkdir()
        try:
            filename = 'source' + source.suffix.lower()
            shutil.copyfile(str(source), str(directory / filename))
            item = dict(id=identity, file=filename, name=name, category=category,
                        tags=tags, favorite=False)
            if thumbnail is not None and not thumbnail.save(str(directory / 'preview.png')):
                raise ValueError('サムネイルを保存できません')
            self.save(item)
            return item
        except Exception:
            shutil.rmtree(directory)
            raise

    def export_set(self, destination):
        destination = Path(destination).resolve()
        if self.root.resolve() in destination.parents:
            raise ValueError('素材保存フォルダの外へ書き出してください')
        temp = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
                for item in self.entries():
                    directory = self.root / item['id']
                    for name in ('material.json', item['file'], 'preview.png'):
                        path = directory / name
                        if path.is_file():
                            archive.write(path, item['id'] + '/' + name)
            temp.replace(destination)
        finally:
            if temp.exists(): temp.unlink()

    def import_set(self, source):
        import tempfile
        staged = []
        with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory() as temp:
            if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
                raise ValueError('素材セットが大きすぎます（上限512MB）')
            for info in archive.infolist():
                if not info.filename.endswith('/material.json'):
                    continue
                item = self.validate(json.loads(archive.read(info).decode('utf-8')))
                name = item['file']
                if Path(name).name != name or Path(name).suffix.lower() not in EXTENSIONS:
                    raise ValueError('素材セットのファイル名が不正です')
                prefix = info.filename.rsplit('/', 1)[0]
                local = Path(temp) / (str(len(staged)) + Path(name).suffix.lower())
                local.write_bytes(archive.read(prefix + '/' + name))
                preview = prefix + '/preview.png'
                thumbnail = archive.read(preview) if preview in archive.namelist() else None
                staged.append((local, item, thumbnail))
            if not staged: raise ValueError('素材セットに素材がありません')
            added_items = []
            try:
                for local, item, thumbnail in staged:
                    added = self.add(local, item['name'], item['category'], item.get('tags', ''))
                    added_items.append(added)
                    added['favorite'] = bool(item.get('favorite')); self.save(added)
                    if thumbnail is not None:
                        (self.root / added['id'] / 'preview.png').write_bytes(thumbnail)
            except Exception:
                for added in added_items: shutil.rmtree(self.store_path(added))
                raise
        return len(staged)

    def store_path(self, item):
        path = (self.root / item['id']).resolve()
        if path.parent != self.root.resolve(): raise ValueError('素材IDが不正です')
        return path


def transfer_node(source, document, parent, offset_x=0, offset_y=0, above=None):
    # Cross-document vector clones can lose their rendering association.
    if source.type() == 'grouplayer':
        target = document.createGroupLayer(source.name())
    elif source.type() == 'vectorlayer':
        target = document.createVectorLayer(source.name())
    else:
        target = source.clone()
    if not parent.addChildNode(target, above):
        raise ValueError('素材レイヤーを追加できません')
    if source.type() == 'vectorlayer':
        import xml.etree.ElementTree as ET
        from .onomatopoeia import _svg_document
        exported = ET.fromstring(source.toSvg())
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        content = ''.join(ET.tostring(child, encoding='unicode') for child in exported)
        # toSvg uses points. Rewrap in target pixels, without the source viewport clip.
        content = '<g transform="translate(%s %s) scale(%s)">%s</g>' % (offset_x, offset_y, document.resolution()/72.0, content)
        shapes = target.addShapesFromSvg(_svg_document(document, content))
        for shape in shapes:
            shape.setSelectable(True)
    elif source.type() != 'grouplayer':
        position = target.position()
        target.move(position.x() + offset_x, position.y() + offset_y)
    if source.type() in ('grouplayer', 'vectorlayer'):
        target.setOpacity(source.opacity()); target.setBlendingMode(source.blendingMode())
        target.setVisible(source.visible()); target.setLocked(source.locked())
        target.setInheritAlpha(source.inheritAlpha()); target.setColorLabel(source.colorLabel())
        previous_child = None
        for child in source.childNodes():
            previous_child = transfer_node(child, document, target, offset_x, offset_y, previous_child)
    return target


class UserMaterials(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        root = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'MangaWorkspace' / 'materials'
        self.store = MaterialStore(root)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        for label, callback in [('＋ファイルから登録', self.register_file), ('レイヤーから登録', self.register_layer)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.search = QLineEdit(); self.search.setPlaceholderText('素材名・タグで検索')
        layout.addWidget(self.search)
        row = QHBoxLayout()
        self.category = QComboBox(); self.category.addItems(('すべて',) + CATEGORIES)
        self.favorite = QCheckBox('お気に入り')
        row.addWidget(self.category); row.addWidget(self.favorite); layout.addLayout(row)
        self.list = QListWidget(); self.list.setViewMode(QListView.IconMode)
        self.list.setResizeMode(QListView.Adjust); self.list.setIconSize(QSize(96, 80))
        self.list.setWordWrap(True); self.list.setMinimumHeight(180)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        for label, callback in [('名前・分類', self.edit), ('☆切替', self.toggle_favorite), ('削除', self.remove)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        button = QPushButton('選んだ素材を原稿へ配置'); button.clicked.connect(self.place)
        layout.addWidget(button)
        hint = QLabel('「配置」の配置先に合わせて追加します。元ファイルのコピーを保存します。')
        hint.setWordWrap(True); layout.addWidget(hint)
        row = QHBoxLayout()
        for label, callback in [('セットを書き出す', self.export_set), ('セットを取り込む', self.import_set)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.search.textChanged.connect(self.refresh)
        self.category.currentTextChanged.connect(self.refresh)
        self.favorite.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self, *_, select_id=None):
        selected = self.list.currentItem()
        wanted = select_id or (selected.data(Qt.UserRole)['id'] if selected else None)
        self.list.clear()
        for entry in self.store.entries():
            if self.favorite.isChecked() and not entry.get('favorite'): continue
            if self.category.currentText() != 'すべて' and entry.get('category') != self.category.currentText(): continue
            if self.search.text().casefold() not in (entry['name'] + ' ' + entry.get('tags', '')).casefold(): continue
            path = self.store.root / entry['id'] / 'preview.png'
            item = QListWidgetItem(QIcon(str(path)), ('★ ' if entry.get('favorite') else '') + entry['name'])
            item.setData(Qt.UserRole, entry); item.setToolTip(entry.get('category', '') + '\n' + entry.get('tags', ''))
            self.list.addItem(item)
            if entry['id'] == wanted: self.list.setCurrentItem(item)

    def selected(self):
        item = self.list.currentItem()
        if not item: raise ValueError('サムネイルから素材を選んでください')
        return item.data(Qt.UserRole)

    def details(self, name, category='その他', tags=''):
        dialog = QDialog(self); dialog.setWindowTitle('マイ素材に登録')
        form = QFormLayout(dialog)
        title = QLineEdit(name); group = QComboBox(); group.addItems(CATEGORIES); group.setCurrentText(category)
        tag = QLineEdit(tags)
        form.addRow('名前', title); form.addRow('分類', group); form.addRow('タグ', tag)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec_() != QDialog.Accepted: return None
        if not title.text().strip(): raise ValueError('素材名を入力してください')
        return title.text().strip(), group.currentText(), tag.text().strip()

    def error(self, error):
        QMessageBox.warning(self, 'マイ素材', str(error))

    def register_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '登録する素材', '', '素材 (*.png *.jpg *.jpeg *.svg *.kra)')
        if not path: return
        try:
            from .onomatopoeia import load_external_material
            details = self.details(Path(path).stem, self.owner.current_kind)
            if not details: return
            if Path(path).suffix.lower() == '.kra':
                with zipfile.ZipFile(path) as archive:
                    thumbnail = QPixmap(); thumbnail.loadFromData(archive.read('mergedimage.png'))
            else:
                thumbnail = QPixmap.fromImage(load_external_material(path))
            added = self.store.add(path, *details, thumbnail=thumbnail.scaled(160, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.search.clear(); self.category.setCurrentIndex(0); self.favorite.setChecked(False)
            self.refresh(select_id=added['id'])
        except Exception as error: self.error(error)

    def register_layer(self):
        import tempfile
        document = Krita.instance().activeDocument()
        if not document or not document.activeNode(): return self.error('登録するレイヤー／グループを選んでください')
        tempdoc = None
        try:
            node = document.activeNode(); details = self.details(node.name(), self.owner.current_kind)
            if not details: return
            bounds = node.bounds()
            if bounds.isEmpty(): raise ValueError('選択レイヤーに描画がありません')
            app = Krita.instance()
            tempdoc = app.createDocument(document.width(), document.height(), '素材登録', document.colorModel(), document.colorDepth(), document.colorProfile(), document.resolution())
            tempdoc.setBatchmode(True)
            for default_node in tempdoc.rootNode().childNodes():
                default_node.remove()
            transfer_node(node, tempdoc, tempdoc.rootNode())
            tempdoc.refreshProjection(); tempdoc.waitForDone()
            tempdoc.crop(bounds.x(), bounds.y(), bounds.width(), bounds.height()); tempdoc.waitForDone()
            tempdoc.setModified(True)
            # Vector repaint is queued by a timer, outside the document's worker barrier.
            self.setEnabled(False)
            repaint = QEventLoop(); QTimer.singleShot(250, repaint.quit); repaint.exec_()
            tempdoc.refreshProjection(); tempdoc.waitForDone()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'source.kra'
                if not tempdoc.saveAs(str(path)): raise ValueError('レイヤー素材を保存できません')
                added = self.store.add(path, *details, thumbnail=tempdoc.thumbnail(160, 120))
            self.search.clear(); self.category.setCurrentIndex(0); self.favorite.setChecked(False)
            self.refresh(select_id=added['id'])
        except Exception as error: self.error(error)
        finally:
            if tempdoc: tempdoc.setModified(False); tempdoc.close()
            self.setEnabled(True)

    def edit(self):
        try:
            entry = self.selected(); details = self.details(entry['name'], entry.get('category','その他'), entry.get('tags',''))
            if details:
                entry['name'], entry['category'], entry['tags'] = details
                self.store.save(entry); self.refresh()
        except Exception as error: self.error(error)

    def toggle_favorite(self):
        try:
            entry = self.selected(); entry['favorite'] = not entry.get('favorite')
            self.store.save(entry); self.refresh()
        except Exception as error: self.error(error)

    def remove(self):
        try:
            entry = self.selected()
            if QMessageBox.question(self, '登録解除', '「%s」をマイ素材から削除しますか？原稿と元ファイルは残ります。' % entry['name']) == QMessageBox.Yes:
                shutil.rmtree(self.store.store_path(entry)); self.refresh()
        except Exception as error: self.error(error)

    def export_set(self):
        path, _ = QFileDialog.getSaveFileName(self, '素材セットを書き出す', 'マイ素材.zip', '素材セット (*.zip)')
        if path:
            try: self.store.export_set(path)
            except Exception as error: self.error(error)

    def import_set(self):
        path, _ = QFileDialog.getOpenFileName(self, '素材セットを取り込む', '', '素材セット (*.zip)')
        if path:
            try:
                count = self.store.import_set(path); self.refresh()
                QMessageBox.information(self, 'マイ素材', '%d件取り込みました' % count)
            except Exception as error: self.error(error)

    def place(self):
        temporary = None
        document = Krita.instance().activeDocument()
        group = None
        try:
            from .onomatopoeia import load_external_material, fit_external_material, apply_polygon_mask
            if not document: raise ValueError('原稿を開いてください')
            entry = self.selected(); path = self.store.root / entry['id'] / entry['file']
            bounds, polygon = self.owner.target_geometry(document)
            x, y, width, height = bounds
            if path.suffix.lower() not in ('.svg', '.kra'):
                image = fit_external_material(load_external_material(str(path)), width, height)
                apply_polygon_mask(image, polygon, x, y)
                self.owner.place_image(document, image, bounds, entry['name']); return
            if path.suffix.lower() == '.svg':
                import xml.etree.ElementTree as ET
                from PyQt5.QtSvg import QSvgRenderer
                from PyQt5.QtCore import QByteArray
                from .onomatopoeia import _svg_document
                data = path.read_bytes()
                svg = ET.fromstring(data)
                ET.register_namespace('', 'http://www.w3.org/2000/svg')
                if not svg.get('viewBox'):
                    renderer = QSvgRenderer(QByteArray(data)); box = renderer.viewBoxF()
                    if not renderer.isValid() or box.isEmpty(): raise ValueError('SVGの寸法が不正です')
                    svg.set('viewBox', '%s %s %s %s' % (box.x(), box.y(), box.width(), box.height()))
                for element in svg.iter():
                    for key, value in element.attrib.items():
                        if key.split('}')[-1] == 'href' and not value.startswith(('#', 'data:')):
                            raise ValueError('外部ファイル参照を埋め込んだSVGを登録してください')
                svg.set('x', str(x)); svg.set('y', str(y))
                svg.set('width', str(width)); svg.set('height', str(height))
                svg.set('preserveAspectRatio', 'xMidYMid meet')
                group = document.createGroupLayer(entry['name'])
                self.owner.destination_parent(document).addChildNode(group, None)
                vector = document.createVectorLayer(entry['name']); group.addChildNode(vector, None)
                shapes = vector.addShapesFromSvg(_svg_document(document, ET.tostring(svg, encoding='unicode')))
                if not shapes: raise ValueError('SVGをベクターとして配置できません')
                for shape in shapes: shape.setSelectable(True)
                if polygon: self.owner.add_polygon_mask(document, group, polygon)
                document.setActiveNode(vector); document.setModified(True); document.refreshProjection()
                return
            temporary = Krita.instance().openDocument(str(path))
            if not temporary: raise ValueError('素材を開けません')
            temporary.setBatchmode(True)
            scale = min(width / temporary.width(), height / temporary.height())
            new_w, new_h = max(1, round(temporary.width()*scale)), max(1, round(temporary.height()*scale))
            temporary.scaleImage(new_w, new_h, document.resolution(), document.resolution(), 'Bicubic')
            temporary.waitForDone()
            group = document.createGroupLayer(entry['name'])
            self.owner.destination_parent(document).addChildNode(group, None)
            offset_x, offset_y = int(x + (width-new_w)/2), int(y + (height-new_h)/2)
            previous = None
            for node in temporary.rootNode().childNodes():
                previous = transfer_node(node, document, group, offset_x, offset_y, previous)
            if polygon: self.owner.add_polygon_mask(document, group, polygon)
            document.setActiveNode(group); document.setModified(True); document.refreshProjection()
        except Exception as error:
            if group: group.remove()
            self.error(error)
        finally:
            if temporary: temporary.setModified(False); temporary.close()
