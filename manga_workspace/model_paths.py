"""User-owned ComfyUI model paths; no machine-specific defaults."""
import json
from pathlib import Path

BEGIN = '# BEGIN manga-workspace model folders'
END = '# END manga-workspace model folders'

def update_config(text, folders):
    if (BEGIN in text) != (END in text) or text.count(BEGIN)>1 or text.count(END)>1:
        raise ValueError('設定ファイルの専用区間が不正です。変更していません。')
    if BEGIN in text:
        a=text.index(BEGIN); b=text.index(END)+len(END)
        if b<a: raise ValueError('設定区間の順序が不正です')
        text=text[:a]+text[b:].lstrip('\r\n')
    data={}
    for kind, path in folders:
        if kind not in ('checkpoints','loras'):raise ValueError('未対応のモデル種別')
        if any(c in path for c in ('\n','\r')):raise ValueError('改行を含むパスは使えません')
        entries=data.setdefault(kind,[])
        if path not in entries:entries.append(path)
    if not data:return text
    if 'manga_workspace_user_models:' in text:raise ValueError('同名の設定が既にあります')
    block='manga_workspace_user_models: '+json.dumps({k:'\n'.join(v) for k,v in data.items()},ensure_ascii=False)
    return text.rstrip()+'\n\n'+BEGIN+'\n'+block+'\n'+END+'\n'

def open_model_paths(parent=None):
    from PyQt5.QtCore import QSettings, Qt
    from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,
        QPushButton,QFileDialog,QListWidget,QListWidgetItem,QComboBox,QMessageBox)
    prefs=QSettings('MangaWorkspace','ModelFolders')
    dialog=QDialog(parent);dialog.setWindowTitle('モデルフォルダ設定');dialog.resize(650,420)
    layout=QVBoxLayout(dialog)
    label=QLabel('このPCで動くComfyUIのフォルダとモデルの場所を指定します。\n設定後は生成サーバーを再起動してください。外部サーバーはサーバー側で設定してください。')
    label.setWordWrap(True);layout.addWidget(label)
    row=QHBoxLayout();server=QLineEdit(prefs.value('comfyui',''));server.setPlaceholderText('ComfyUIフォルダ（main.pyがある場所）');row.addWidget(server)
    browse=QPushButton('選ぶ…');row.addWidget(browse);layout.addLayout(row)
    def choose_server():
        path=QFileDialog.getExistingDirectory(dialog,'ComfyUIフォルダ',server.text())
        if path:server.setText(path)
    browse.clicked.connect(choose_server)
    listing=QListWidget();layout.addWidget(listing)
    def add_item(kind,path):
        item=QListWidgetItem(('Checkpoint' if kind=='checkpoints' else 'LoRA')+' · '+path)
        item.setData(Qt.UserRole,(kind,path));listing.addItem(item)
    for kind,path in json.loads(prefs.value('folders','[]')):add_item(kind,path)
    row=QHBoxLayout();kind=QComboBox();kind.addItem('Checkpoint','checkpoints');kind.addItem('LoRA','loras');row.addWidget(kind)
    def choose_folder(change=False):
        item=listing.currentItem() if change else None
        if change and item is None:return
        old=item.data(Qt.UserRole) if item else (kind.currentData(),'')
        path=QFileDialog.getExistingDirectory(dialog,'モデルフォルダ',old[1])
        if not path:return
        if item:listing.takeItem(listing.row(item))
        add_item(old[0],path)
    add=QPushButton('追加');add.clicked.connect(lambda:choose_folder());row.addWidget(add)
    change=QPushButton('変更');change.clicked.connect(lambda:choose_folder(True));row.addWidget(change)
    remove=QPushButton('登録を解除');remove.clicked.connect(lambda:listing.takeItem(listing.currentRow()) if listing.currentRow()>=0 else None);row.addWidget(remove)
    layout.addLayout(row);layout.addWidget(QLabel('登録解除ではモデルファイルを削除しません。個人のパスはこのPCだけに保存します。'))
    save=QPushButton('保存');layout.addWidget(save)
    def commit():
        try:
            base=Path(server.text())
            if not (base/'main.py').is_file():raise ValueError('ComfyUIのmain.pyがあるフォルダを選んでください')
            folders=[listing.item(i).data(Qt.UserRole) for i in range(listing.count())]
            if any(not Path(p).is_dir() for _,p in folders):raise ValueError('存在しないモデルフォルダがあります')
            path=base/'extra_model_paths.yaml'
            text=path.read_text(encoding='utf-8-sig') if path.exists() else ''
            updated=update_config(text,folders)
            if path.exists():
                import shutil,datetime
                shutil.copy2(path,path.with_name(path.name+'.manga-backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            temp=path.with_name(path.name+'.manga-tmp');temp.write_text(updated,encoding='utf-8');temp.replace(path)
            prefs.setValue('comfyui',str(base));prefs.setValue('folders',json.dumps(folders,ensure_ascii=False))
            QMessageBox.information(dialog,'保存しました','生成を停止してからサーバーを再起動してください。');dialog.accept()
        except Exception as error:QMessageBox.warning(dialog,'保存できません',str(error))
    save.clicked.connect(commit)
    dialog.exec_()
