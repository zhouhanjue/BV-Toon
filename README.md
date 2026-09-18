**中文** ｜ [English](README.en.md) ｜ [日本語](README.ja.md)
# BV-Toon

> MMD 模型一键卡渲 · 原生读取材质 · 渐变贴图驱动明暗 · 边缘预览 · 目影 · 腮红 · 泛光 · 强制署名

**独立编写的 Blender 插件**：代码、节点图、资产全部自写，不含任何第三方插件的代码或资源。

* 插件用法见 [`BV-Toon/README.md`](BV-Toon/README.md) ｜ 逐版改动见 [`CHANGELOG.md`](CHANGELOG.md)
* 最新版说明：[`RELEASE-1.5.0.md`](RELEASE-1.5.0.md) ｜ 使用规范：[`MMD-NOTICE.md`](MMD-NOTICE.md)
* 许可：[`LICENSE`](LICENSE)（中 / 英 / 日三语）

## 快速开始

1. 下载 `BV-Toon-1.5.0.zip`（Release 附件）
2. Blender：`编辑 > 偏好设置 > 附加组件 > v > 从磁盘安装`
3. 勾上 **BV-Toon** → 选中 MMD 模型 → `N` → 「**Toon**」标签 → **一键卡渲**

需要 Blender 4.5+ 与开源插件 [mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/)。

## 它做什么

* **一键卡渲**：套卡渲预设 + MMD 边缘预览，一次点完
* **原生读取 MMD 材质**：球面层按 MMD 语义分层（加算 = 闪片/宝石/金属，乘算 = 布料光泽）
* **渐变贴图（toon ramp）驱动明暗**：按 MMD 的查表方式（U=0.5、V=受光程度）
* **强制署名水印**：一键卡渲与**每次渲染前**都会烧上 `渲染 BVToon / @BVan`（85% 透明）
* 目影 / 腮红 / 泛光 / 可调描边粗细 / 自动把视图变换切到「标准」

## 目录

| 路径 | 说明 |
|---|---|
| `BV-Toon/` | 插件本体（`__init__.py`、`bv_*.py`、`BVToonData/BVToonShading.blend`、LICENSE） |
| `tools/` | 开发与验证脚本（资产生成、A/B 渲图、探针、体检 `audit_bv_toon.py`） |

## 许可（摘要）

✅ 允许免费使用（含商业项目）｜❌ 禁止再分发｜❌ 禁止发布修改版｜✅ 必须标明原作者
完整条款见 [`LICENSE`](LICENSE)。
