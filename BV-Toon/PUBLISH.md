**中文** ｜ [English](PUBLISH.en.md) ｜ [日本語](PUBLISH.ja.md)

# 上架步骤

## 1. 建仓库并推上去

```bat
cd github\BV-Toon
git init
git add .
git commit -m "BV-Toon 1.5.0：MMD 一键卡渲 + 强制署名水印"
git branch -M main
git remote add origin https://github.com/<你的用户名>/BV-Toon.git
git push -u origin main
```

## 2. 建 Release

**Releases → Draft a new release → tag `v1.5.0`** → 说明区粘 [`RELEASE-1.5.0.md`](RELEASE-1.5.0.md)
的内容 → 附件传 `dist\BV-Toon-1.5.0.zip`（顶层就是 `BV-Toon/`，别人能直接「从磁盘安装」）。

## 3. 仓库设置建议

* **About**：`MMD 模型一键卡渲：原生读取材质 · 渐变贴图驱动明暗 · 边缘预览 · 目影 · 腮红 · 泛光`
* **Topics**：`blender-addon` `mmd` `toon-shading` `cel-shading` `mmd-tools` `eevee`
* **License**：自定义使用许可（GitHub 会显示 Unknown license，属正常；条款在 `LICENSE`）

## 4. 文档是三语的

每份文档都有 `中文（.md）` / `English（.en.md）` / `日本語（.ja.md）` 三个版本，
顶部有语言切换条：

| 文档 | 中文 | English | 日本語 |
|---|---|---|---|
| 首页 | `README.md` | `README.en.md` | `README.ja.md` |
| 版本说明 | `RELEASE-1.5.0.md` | `RELEASE-1.5.0.en.md` | `RELEASE-1.5.0.ja.md` |
| MMD 规范 | `MMD-NOTICE.md` | `MMD-NOTICE.en.md` | `MMD-NOTICE.ja.md` |
| 上架步骤 | `PUBLISH.md` | `PUBLISH.en.md` | `PUBLISH.ja.md` |
| 使用条款 | `LICENSE`（三语在同一份里） | | |

## 5. 不要放进去的东西

* 任何第三方插件的内容（**付费插件的代码与资产 —— 本机自用可以，不能上架**）
* 本地过程产物（`dist/`、`_scratch/`、`tests/_out/`、`.blend1`、`__pycache__`）
* 用第三方 MMD 模型渲的测试图（模型有独立授权）