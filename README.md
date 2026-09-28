# Manga Workspace for Krita

Kritaへページ管理、漫画原稿設定、コマ割り、レイヤー連動、範囲別プロンプトと任意のローカルAI作画を追加する、無料公開の試作プラグインです。

> **0.1.1-alpha**：重要な原稿はバックアップを取ってから使用してください。

## 主な機能

- 単ページから使えるページ管理
- B5・A4などの漫画原稿設定、裁ち落とし、基本枠
- 初期大ゴマ、コマ分割、縦横のコマ一覧
- CanvasクリックとKrita標準レイヤー選択の連動
- 選択範囲・人物・物体ごとのPrompt
- 日本語入力とDanbooru TagComplete
- ローカルComfyUIによる任意のAIプレビュー
- 人物・文字・コマの任意のローカル自動検出（Windows x64）

## インストール

1. [Releases](https://github.com/dr1610/krita-manga-workspace/releases)から `manga-workspace-0.1.1-alpha.zip` を取得します。
2. Kritaの「ツール → スクリプト → Pythonプラグインをインポート」でZIPを選択します。
3. Kritaを再起動します。
4. 「設定 → Kritaを設定 → Pythonプラグインマネージャー」で「漫画ワークスペース（試作版）」を有効にします。
5. Kritaをもう一度再起動します。

Krita公式の導入説明：https://docs.krita.org/en/user_manual/python_scripting/install_custom_python_plugin.html

## AIと自動検出

漫画制作の基本機能はKritaだけで動作します。ComfyUI、生成モデル、自動検出モデルはプラグインZIPへ含めていません。

- AI生成：利用者が用意したローカルComfyUIへ接続します。
- 自動検出：利用者が画面上で導入を選んだ場合だけ、専用Pythonと約250 MBの検出モデルを取得します。
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
