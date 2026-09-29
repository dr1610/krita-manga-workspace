# Windows導入EXE

対象：Windows x64、Pythonプラグインを含むKrita 5.2以降。
利用者側のPython導入・管理者権限は不要です。Krita本体は事前に導入してください。

1. 原稿を保存してKritaを終了します。
2. `MangaWorkspace-Setup-0.7.1-alpha.exe`を起動します。
3. Krita本体・リソースフォルダ・設定ファイルを確認します。通常は自動検出値を使用できます。
4. 「漫画制作のみ」、または「AI作画も使う」を選びます。AIを選ぶ場合は、既存ComfyUIを起動してURLを入力し「接続確認」を押します。
5. 「導入・更新する」を押し、完了後に「Kritaを起動」を押します。

標準の保存先は `%APPDATA%/krita/pykrita`、設定は `%LOCALAPPDATA%/kritarc` です。
既存設定の `ResourceDirectory` があれば、その場所を優先します。ポータブル版やカスタム設定の利用者は実際の保存先を指定してください。
既存の拡張・設定は、選択したリソースフォルダ内の `manga-workspace-backups` に保存されます。
バックアップ内の `restore.txt` に復元先を記録します。原稿や登録素材のフォルダは変更しません。

ComfyUIとモデルの新規導入・ダウンロードは行いません。接続確認はサーバーとモデル一覧の読み取りのみで、画像生成の成功や全モデルへの対応を保証するものではありません。
EXEはコード署名なしです。GitHub公開と署名は別の作業です。

## 再ビルド

WindowsのPython 3.12とPyInstaller 6.20.0を使用しています。

```
python -m pip install pyinstaller==6.20.0
python installer/build.py
```

出力は `release/` に作成されます。利用者の設定・原稿や開発用診断コードは同梱しません。
生成したEXEに `--self-test --report <結果JSON>` を指定すると、一時フォルダだけを使った導入・設定保持・バックアップ・GUI生成の確認を実行します。
