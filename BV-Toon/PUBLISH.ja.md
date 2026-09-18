[中文](PUBLISH.md) ｜ [English](PUBLISH.en.md) ｜ **日本語**

# 公開手順

## 1. リポジトリを作成して push

```bat
cd github\BV-Toon
git init
git add .
git commit -m "BV-Toon 1.5.0：MMD ワンクリック・トゥーン + 署名の強制"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/BV-Toon.git
git push -u origin main
```

## 2. リリースを作成

**Releases → Draft a new release → タグ `v1.5.0`** → 説明欄に
[`RELEASE-1.5.0.md`](RELEASE-1.5.0.ja.md) の内容を貼り付け → 添付に
`dist\BV-Toon-1.5.0.zip` をアップロード（最上位が `BV-Toon/` なので、そのまま
「ディスクからインストール」できます）。

## 3. リポジトリ設定の推奨

* **About**：`MMD のワンクリック・トゥーン：マテリアルのネイティブ読み込み・トゥーンランプ・エッジプレビュー・目影・チーク・ブルーム`
* **Topics**：`blender-addon` `mmd` `toon-shading` `cel-shading` `mmd-tools` `eevee`
* **License**：カスタム使用許諾（GitHub では "Unknown license" と表示されますが正常です。条項は `LICENSE`）

## 4. ドキュメントは三か国語

各ドキュメントに 中国語（`.md`）／英語（`.en.md`）／日本語（`.ja.md`）があり、上部に言語切替があります：

| ドキュメント | 中国語 | 英語 | 日本語 |
|---|---|---|---|
| トップ | `README.md` | `README.en.md` | `README.ja.md` |
| リリースノート | `RELEASE-1.5.0.md` | `RELEASE-1.5.0.en.md` | `RELEASE-1.5.0.ja.md` |
| MMD のマナー | `MMD-NOTICE.md` | `MMD-NOTICE.en.md` | `MMD-NOTICE.ja.md` |
| 公開手順 | `PUBLISH.md` | `PUBLISH.en.md` | `PUBLISH.ja.md` |
| 利用規約 | `LICENSE`（三か国語を 1 ファイルに） | | |

## 5. 入れてはいけないもの

* サードパーティ製アドオンの内容（**有料アドオンのコードとアセット —— 私的利用は可、公開は不可**）
* ローカルの作業生成物（`dist/`、`_scratch/`、`tests/_out/`、`.blend1`、`__pycache__`）
* サードパーティ製 MMD モデルでレンダリングしたテスト画像（モデルには独自のライセンスがあります）