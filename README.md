# Manga Workspace for Krita

Kritaへページ管理、漫画原稿設定、コマ割り、レイヤー連動、範囲別プロンプトと任意のローカルAI作画を追加する、無料公開の試作プラグインです。

> **0.7.1-alpha**：重要な原稿はバックアップを取ってから使用してください。

## 主な機能

- 単ページから使えるページ管理
- B5・A4などの漫画原稿設定、裁ち落とし、基本枠
- 初期大ゴマ、コマ分割、縦横のコマ一覧
- CanvasクリックとKrita標準レイヤー選択の連動、番号付きコマグループ
- 選択範囲・人物・物体ごとのPrompt
- 日本語入力とDanbooru TagComplete
- ローカルComfyUIによる任意のAIプレビュー
- Qwen Image 2.1とBFS LoRAによる頭部・全身の参照画像編集（試験機能、モデルは別途必要）
- 人物・文字・コマの任意のローカル自動検出（Windows x64）
- 用途別素材パレット、描き文字15種類、空の吹き出し14種類、効果線12種類、オノマトペ12カテゴリ144語
- 左側の「描」「吹」「線」から直接開け、Canvasを操作したまま使えるドッキング式の漫画表現素材パネル
- オノマトペ検索・最近使った言葉、縁取り・変形・縦書き、編集可能なベクター吹き出し、種類別の尻尾・思考点・フラッシュ、効果線の色・密度・太さ調整
- MANGA BRIDGE v2形式の文字領域、分類、描画方法、所属コマ、AI指示連携
- 外部サイトへの素材導線と、取得済みPNG・JPG・SVGの安全な手動読み込み
- マイ素材：PNG・JPG・SVG・KRAや現在のレイヤーを登録、サムネイル検索・お気に入り・範囲へ配置・ZIP移行
- 起動後の更新通知、手動確認、検証付き更新ボタン

## インストール

Windows x64では、[Releases](https://github.com/dr1610/krita-manga-workspace/releases)の **`MangaWorkspace-Setup-0.7.1-alpha-Windows.zip`** を展開し、同梱の「最初にお読みください・導入方法.txt」を読んでEXEを実行できます。Kritaを終了してから「導入・更新する」を押してください。Pythonの別途導入は不要です。バックアップ・有効化・既存ComfyUIへの接続確認に対応します。ComfyUIやモデルの新規導入は行いません。EXEはコード署名なしです。

従来のKritaインポート用ZIPも利用できます。セットアップ用ZIPとは別です。

1. [Releases](https://github.com/dr1610/krita-manga-workspace/releases)から `manga-workspace-0.7.1-alpha.zip` を取得します。
2. Kritaの「ツール → スクリプト → Pythonプラグインをインポート」でZIPを選択します。
3. Kritaを再起動します。
4. 「設定 → Kritaを設定 → Pythonプラグインマネージャー」で「漫画ワークスペース（試作版）」を有効にします。
5. Kritaをもう一度再起動します。

## 更新

`0.2.0-alpha` 以降は、起動後にGitHub Releaseを確認します。新しい版があると「ページ管理」メニューの「拡張機能の更新…」へ印が付きます。同じ画面の「更新を適用」でZIPを取得し、GitHubが公開するSHA-256を検証してから配置します。反映にはKritaの再起動が必要です。更新前の版はKrita設定フォルダ内の `manga_workspace_backups` へ保存します。

`0.1.1-alpha` 以前には更新機能がないため、`0.2.0-alpha` だけは上記の手順で手動導入してください。

Krita公式の導入説明：https://docs.krita.org/en/user_manual/python_scripting/install_custom_python_plugin.html

## AIと自動検出

漫画制作の基本機能はKritaだけで動作します。ComfyUI、生成モデル、自動検出モデルはプラグインZIPへ含めていません。

- AI生成：利用者が用意したローカルComfyUIへ接続します。
- 自動検出：利用者が画面上で導入を選んだ場合だけ、専用Pythonと約250 MBの検出モデルを取得します。
- 更新確認：起動後にGitHubの公開Release情報だけを取得します。原稿画像やPromptは送信しません。
- 原稿画像やPromptを、このプラグイン独自の外部サービスへ送信する処理はありません。

## 既知の制約

- 試作版であり、Krita・OS・画面構成の全組み合わせでは未検証です。
- 自動検出は現在Windows x64向けです。
- 検出結果は矩形であり、人物輪郭Maskや背景分離ではありません。
- Qwen Image Edit、Inpaint、参照画像、LoRA、Control、Poseは未接続または開発途中です。
- AI生成はリアルタイムではありません。

詳しい操作はプラグイン同梱の `manga_workspace/manual.html`、変更内容は[CHANGELOG.md](CHANGELOG.md)を参照してください。

## ライセンス

GNU General Public License v3.0。第三者コンポーネントは[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。
