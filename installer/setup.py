import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import check_comfy, default_paths, install, krita_running, krita_version, verify_payload


def payload_path():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload'


class Setup(tk.Tk):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.title('Krita 漫画拡張セットアップ')
        self.geometry('800x690')
        self.minsize(690, 590)
        self.option_add('*Font', ('Yu Gothic UI', 10))
        style = ttk.Style(self)
        style.theme_use('vista')
        style.configure('Title.TLabel', font=('Yu Gothic UI', 19, 'bold'))
        self.events = queue.Queue()
        self.busy = False
        self.finished = False
        exe, root, config = default_paths()
        self.exe = tk.StringVar(value=exe)
        self.root_dir = tk.StringVar(value=str(root))
        self.config = tk.StringVar(value=str(config))
        self.mode = tk.StringVar(value='manga')
        self.url = tk.StringVar(value='http://127.0.0.1:8188')
        self.status = tk.StringVar(value='原稿を保存してKritaを終了してから、導入してください。')
        self.checked_url = None
        self.checked_config = None
        manifest = verify_payload(payload)
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        frame = ttk.Frame(canvas, padding=22)
        content = canvas.create_window((0, 0), window=frame, anchor='nw')
        frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(content, width=event.width))
        self.bind_all('<MouseWheel>', lambda event: canvas.yview_scroll(-int(event.delta / 120), 'units'))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='漫画制作を、Kritaで。', style='Title.TLabel').grid(sticky='w')
        ttk.Label(frame, text=f'Manga Workspace {manifest["version"]} ／ Windows用・無料試作版').grid(sticky='w', pady=(4, 12))
        ttk.Label(frame, text='コマ割り・描き文字・吹き出し・効果線・素材登録を導入します。\n既存の拡張と設定はバックアップし、原稿や登録素材は変更しません。').grid(sticky='w')
        paths = ttk.LabelFrame(frame, text='1. Kritaと導入先', padding=10)
        paths.grid(sticky='ew', pady=12)
        paths.columnconfigure(1, weight=1)
        for row, (label, variable, folder) in enumerate([
                ('Krita本体', self.exe, False), ('リソースフォルダ', self.root_dir, True),
                ('Krita設定ファイル', self.config, False)]):
            ttk.Label(paths, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=3)
            ttk.Entry(paths, textvariable=variable).grid(row=row, column=1, sticky='ew')
            ttk.Button(paths, text='参照', width=6, command=lambda v=variable, f=folder: self.browse(v, f)).grid(row=row, column=2, padx=(6, 0))
        ttk.Label(paths, text='通常は自動検出された場所を使用。ポータブル版は実際の保存先を選択。').grid(row=3, column=0, columnspan=3, sticky='w', pady=(6, 0))
        mode = ttk.LabelFrame(frame, text='2. 使う機能', padding=10)
        mode.grid(sticky='ew')
        ttk.Radiobutton(mode, text='漫画制作のみ（AIの準備なしで利用できます）', variable=self.mode, value='manga').pack(anchor='w')
        ttk.Radiobutton(mode, text='AI作画も使う（起動済みのComfyUIへ接続）', variable=self.mode, value='ai').pack(anchor='w', pady=4)
        connect = ttk.Frame(mode)
        connect.pack(fill='x', pady=(4, 0))
        ttk.Label(connect, text='ComfyUI URL').pack(side='left', padx=(0, 8))
        self.url_entry = ttk.Entry(connect, textvariable=self.url)
        self.url_entry.pack(side='left', fill='x', expand=True)
        self.check_button = ttk.Button(connect, text='接続確認', command=self.test_connection)
        self.check_button.pack(side='left', padx=(6, 0))
        ttk.Label(mode, text='ComfyUI・生成モデルの新規導入や取得は、この版では行いません。\nモデルの対応・画像生成の成否は、導入後にAI作画画面で確認してください。').pack(anchor='w', pady=(8, 0))
        links = ttk.Frame(frame)
        links.grid(sticky='ew', pady=10)
        ttk.Button(links, text='使い方', command=lambda: os.startfile(str(payload / 'manga_workspace/manual.html'))).pack(side='left')
        ttk.Button(links, text='ライセンス', command=lambda: os.startfile(str(payload / 'LICENSE'))).pack(side='left', padx=8)
        ttk.Button(links, text='配布物の利用条件', command=lambda: os.startfile(str(payload / 'THIRD_PARTY_NOTICES.md'))).pack(side='left')
        self.message = ttk.Label(frame, textvariable=self.status, wraplength=610, justify='left')
        self.message.grid(row=6, sticky='new', pady=5)
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.grid(row=7, sticky='ew', pady=8)
        buttons = ttk.Frame(frame)
        buttons.grid(row=8, sticky='ew')
        self.install_button = ttk.Button(buttons, text='導入・更新する', command=self.begin_install)
        self.install_button.pack(side='right', padx=(8, 0))
        self.launch_button = ttk.Button(buttons, text='Kritaを起動', command=self.launch, state='disabled')
        self.launch_button.pack(side='right')
        self.close_button = ttk.Button(buttons, text='閉じる', command=self.close)
        self.close_button.pack(side='left')
        self.mode.trace_add('write', lambda *_: self.refresh())
        self.config.trace_add('write', self.config_changed)
        self.url.trace_add('write', self.reset_connection)
        self.refresh()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def config_changed(self, *_):
        # A different Krita installation must use its own resource location.
        from core import read_text, setting
        try:
            path = Path(self.config.get())
            value = setting(read_text(path), '', 'ResourceDirectory') if path.is_file() else None
        except OSError:
            return
        if value:
            self.root_dir.set(value)

    def reset_connection(self, *_):
        self.checked_url = None

    def refresh(self):
        enabled = self.mode.get() == 'ai' and not self.busy and not self.finished
        self.url_entry.configure(state='normal' if enabled else 'disabled')
        self.check_button.configure(state='normal' if enabled else 'disabled')
        self.install_button.configure(state='disabled' if self.busy or self.finished else 'normal')
        self.close_button.configure(state='disabled' if self.busy else 'normal')

    def browse(self, variable, folder):
        if self.busy or self.finished:
            return
        if folder:
            value = filedialog.askdirectory(parent=self, title='Kritaのリソースフォルダ')
        else:
            value = filedialog.askopenfilename(parent=self, title='Krita本体' if variable is self.exe else 'Kritaのkritarc設定ファイル',
                filetypes=[('Krita', 'krita.exe' if variable is self.exe else '*kritarc*'), ('すべて', '*')])
        if value:
            variable.set(value)

    def work(self, function, done):
        self.busy = True
        self.refresh()
        self.progress.start()
        def run():
            try:
                result = function()
                self.events.put((done, result, None))
            except Exception as error:
                self.events.put((done, None, str(error)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            done, value, error = self.events.get_nowait()
            self.busy = False
            self.progress.stop()
            if error:
                self.status.set('完了していません：' + error)
            else:
                done(value)
            self.refresh()
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def test_connection(self):
        url = self.url.get()
        self.status.set('ComfyUIの接続とモデル一覧を確認しています…')
        def done(value):
            server, count = value
            if self.url.get().strip().rstrip('/') == server:
                self.checked_url = server
            self.status.set(f'接続成功。モデル一覧：{count}件。画像生成の成功を確認したものではありません。')
        self.work(lambda: check_comfy(url), done)

    def begin_install(self):
        try:
            exe = self.exe.get().strip()
            version = krita_version(exe)
            if not (Path(exe).parent.parent / 'lib/krita-python-libs').is_dir():
                raise ValueError('このKritaのPythonプラグイン環境を確認できません。通常のWindows版を指定してください。')
            if krita_running():
                raise ValueError('原稿を保存してKritaを終了してください。終了後、再び「導入・更新する」を押してください。')
            root, config = self.root_dir.get().strip(), self.config.get().strip()
            if not root or not config or not Path(root).is_absolute() or not Path(config).is_absolute():
                raise ValueError('導入先と設定ファイルを絶対パスで指定してください。')
            server = self.checked_url if self.mode.get() == 'ai' else None
            if self.mode.get() == 'ai' and not server:
                raise ValueError('先にComfyUIの「接続確認」を押してください。未準備なら「漫画制作のみ」で導入できます。')
            # Snapshot all fields before starting the worker.
            self.installed_exe = exe
            self.status.set(f'Krita {version}：バックアップを作成して導入しています…')
            def job():
                if krita_running():
                    raise ValueError('Kritaが起動されています。終了してから再実行してください。')
                return install(self.payload, root, config, server)
            def done(backup):
                self.finished = True
                self.launch_button.configure(state='normal')
                self.status.set('導入完了。Kritaを起動すると拡張が有効になります。\n'
                    '左の「描・吹・線」から素材を開けます。AI作画はページ管理から開きます。\n'
                    'バックアップ：' + str(backup))
            self.work(job, done)
        except Exception as error:
            self.status.set(str(error))

    def launch(self):
        try:
            subprocess.Popen([self.installed_exe])
        except OSError as error:
            self.status.set('起動できませんでした：' + str(error))

    def close(self):
        if not self.busy:
            self.destroy()


def self_test(payload):
    from core import setting
    manifest = verify_payload(payload)
    with tempfile.TemporaryDirectory(prefix='manga-setup-test-') as temp:
        root = Path(temp) / 'resources'
        config = Path(temp) / 'kritarc'
        config.write_text('ResourceDirectory=unchanged\n[python]\nenable_other=true\n[manga_workspace]\nai_positive=keep me\n', encoding='utf-8')
        old = root / 'pykrita/manga_workspace'
        old.mkdir(parents=True)
        (old / 'old.txt').write_text('old')
        asset = root / 'my-material.png'
        asset.write_bytes(b'keep-material')
        backup = install(payload, root, config, 'http://127.0.0.1:8188')
        assert (backup / 'manga_workspace/old.txt').read_text() == 'old'
        assert asset.read_bytes() == b'keep-material'
        assert setting(config.read_text(), 'python', 'enable_other') == 'true'
        assert setting(config.read_text(), 'python', 'enable_manga_workspace') == 'true'
        assert setting(config.read_text(), 'manga_workspace', 'ai_positive') == 'keep me'
        assert (old / 'material_placement.py').is_file()
    ui = Setup(payload)
    ui.withdraw()
    ui.update_idletasks()
    assert ui.install_button.winfo_exists()
    ui.destroy()
    return {'ok': True, 'version': manifest['version'], 'payload_verified': True, 'install_backup_preservation': True, 'tk_ui_created': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test(payload_path())
            if args.report:
                Path(args.report).write_text(json.dumps(result, indent=2), encoding='utf-8')
        else:
            Setup(payload_path()).mainloop()
    except Exception as error:
        if args.self_test:
            if args.report:
                Path(args.report).write_text(json.dumps({'ok': False, 'error': repr(error)}), encoding='utf-8')
            sys.exit(1)
        messagebox.showerror('セットアップを開始できません', str(error))
