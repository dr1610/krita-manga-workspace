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
- 選択コマを拡大するLive作画ポップアップ（別途Krita AI Diffusionが必要）
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
- コマのLive作画：コマ割りでコマを選び「このコマでLive作画…」を押します。左に下描きし、右側のKrita AI Diffusion Liveを開始します。左の描画欄を右クリックするとペン・鉛筆・マーカー・消しゴム、太さ、色を変更できます。右のプロンプト欄は日本語TagCompleteに対応します。キャラ画像（PNG・JPG・WebP）をドロップまたは選択すると、非表示の参照レイヤーをLiveに接続できます。画像内に生成プロンプトが埋め込まれている場合は候補を編集して追加できます。画像だけから元のプロンプトを推測する機能ではありません。結果を確認して「このコマに反映」を押すと、選択コマのフォルダに新規レイヤーを作成します。Krita AI Diffusionと対応モデル・生成サーバーは別途用意してください。参照機能にはモデルに対応する参照用モデル（例：IP-Adapter）が必要です。
- 自動検出：利用者が画面上で導入を選んだ場合だけ、専用Pythonと約250 MBの検出モデルを取得します。
- 更新確認：起動後にGitHubの公開Release情報だけを取得します。原稿画像やPromptは送信しません。
- 原稿画像やPromptを、このプラグイン独自の外部サービスへ送信する処理はありません。

## 既知の制約

- 試作版であり、Krita・OS・画面構成の全組み合わせでは未検証です。
- 自動検出は現在Windows x64向けです。
- 検出結果は矩形であり、人物輪郭Maskや背景分離ではありません。
- Qwen Image Edit、Inpaint、参照画像、LoRA、Control、Poseは未接続または開発途中です。
- 通常のAI作画はリアルタイムではありません。Live作画はKrita AI Diffusionを有効にした環境のみ利用できます。

詳しい操作はプラグイン同梱の `manga_workspace/manual.html`、変更内容は[CHANGELOG.md](CHANGELOG.md)を参照してください。

## ライセンス

GNU General Public License v3.0。第三者コンポーネントは[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。


### ページ管理の「レイヤー化」（試験機能）

「AI作画パネルを開く」の直下にある「レイヤー化」を押すと、現在のページの表示画像を解析します。
画像を開いただけでは実行しません。解析結果を確認して「確認してレイヤー原稿を開く」を押すと、
元ページを保持したまま、コマごとのテキスト・吹き出し・キャラ・背景を持つOpenRaster原稿を別タブで開きます。
必要に応じてKRAとして名前を付けて保存してください。

- 別プロセスで解析し、停止できます。再解析は最初に取得した画像を対象にします。
- 人物の輪郭は試験的なGrabCutです。髪・顔の欠けや背景混入を確認してください。
  「人物は矩形で保持」で再解析すれば、人物領域を背景込みで保持できます。
- 文字とコマ枠は画像レイヤーです。OCR、編集可能な文字・ベクター枠への変換、隠れた背景の補完は行いません。
- 元の合成画像も非表示の保存用レイヤーとして残します。分離後の再合成一致を検証してから確認画面を出します。
- 試験版は1200万画素までです。色空間はKritaのprojectionによる表示用画像を使用します。
- 結果と取得時の画像は専用環境の親フォルダにあるresults以下へ保存されます。作品への自動登録は行いません。

専用環境はPython 3.12のvenvと`layerize-requirements.txt`の依存関係、既存検出器の`model.onnx`、
吹き出し候補モデルの`bubble.h5`が必要です。Krita/ComfyUIのPython環境に直接インストールしないでください。
専用フォルダの構成は`venv/Scripts/python.exe`、`model.onnx`、`bubble.h5`です。
「レイヤー化」ボタンの右クリックから専用環境を指定できます。

吹き出し候補モデル: [VincentQQu/manga_text_bubble_detect_translate](https://github.com/VincentQQu/manga_text_bubble_detect_translate)
コミット `ce8c2b4c05d3c0efa0625765664986fb2201b8d9` の `exds/ver_2/v4_13600.h5`を使用（配置名bubble.h5）。
MITライセンスは`manga_workspace/BUBBLE-DETECTOR-LICENSE.txt`に収録しています。
このモデルの文字領域予測を起点に白い吹き出しを抽出します。色付き・透明の吹き出しは精度未検証です。


### モデルフォルダを指定する
「生成モデル → モデルフォルダ設定…」で、このPCのComfyUIフォルダ（main.pyがある場所）を選び、Checkpoint・LoRAのフォルダを追加してください。複数登録、変更、登録解除ができます。保存後は生成サーバーを再起動してください。

登録解除は参照設定だけを外し、モデル本体を削除しません。既存のextra_model_paths.yamlはバックアップし、この機能専用の区間だけを更新します。設定パスは各利用者のQSettingsとComfyUIに保存し、リポジトリへ含めません。リモートサーバーの場合はサーバー側でモデル配置を設定してください。
