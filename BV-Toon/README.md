**中文** ｜ [English](README.en.md) ｜ [日本語](README.ja.md)
# BV-Toon

> MMD 模型一键卡渲 · 原生读取材质 · 渐变贴图驱动明暗 · 边缘预览 · 目影 · 腮红 · 泛光 · 强制署名 · 完整性校验

**独立编写的 Blender 插件**：代码、节点图、资产全部自写，不含任何第三方插件的代码或资源。

* 插件用法见 [`BV-Toon/README.md`](BV-Toon/README.md)（[EN](BV-Toon/README.en.md) ｜ [日本語](BV-Toon/README.ja.md)）｜ 逐版改动见 [`CHANGELOG.md`](CHANGELOG.md)
* 最新版说明：[`RELEASE-1.8.0.md`](RELEASE-1.8.0.md) ｜ 使用规范：[`MMD-NOTICE.md`](MMD-NOTICE.md)
* 许可：[`LICENSE`](LICENSE)（中 / 英 / 日三语）

## 快速开始

1. 下载 `BV-Toon-1.8.0.zip`（Release 附件）
2. Blender：`编辑 > 偏好设置 > 附加组件 > v > 从磁盘安装`
3. 勾上 **BV-Toon** → 选中 MMD 模型 → `N` → 「**Toon**」标签 → **一键卡渲**

需要 Blender 4.5+ 与开源插件 [mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/)。

## 它做什么

* **一键卡渲**：套卡渲预设 + MMD 边缘预览，一次点完
* **原生读取 MMD 材质**：球面层按 MMD 语义分层（加算 = 闪片/宝石/金属，乘算 = 布料光泽）
* **渐变贴图（toon ramp）驱动明暗**：按 MMD 的查表方式（U=0.5、V=受光程度）
* **强制署名水印**：一键卡渲与**每次渲染前**都会烧上 `渲染 BVToon / @BVan`（85% 透明）
* **完整性校验（哈希防盗）**：打包清单记下 6 个 `.py` ＋ 资产 `.blend` 的 SHA-256，加载与每次渲染前
  各核对一遍 —— 改过 = `未授权修改版`、没清单 = `未验证副本`（红字不透明 + 面板红框，**不阻止渲染**）
* 目影 / 腮红 / 泛光 / 可调描边粗细 / 自动把视图变换切到「标准」

## 目录

| 路径 | 说明 |
|---|---|
| `BV-Toon/` | 插件本体（`__init__.py`、`bv_*.py`、`BVToonData/BVToonShading.blend`、LICENSE） |
| `tools/` | 开发与验证脚本（资产生成、A/B 渲图、探针、体检 `audit_bv_toon.py`） |

## 许可（摘要）

✅ 允许使用与再分发（含商用）｜✅ 允许修改｜✅ 改版必须同样以 GPL v3 开源｜✅ 必须保留署名
完整条款见 [`LICENSE`](LICENSE)。

### 泛光性能（1.8.0）

开泛光的额外开销在 4K 下从 **+2.3 秒降到 +0.5 秒**（3840×2160、同一台机器实测）：

* 点「添加泛光」时把合成器切到 **GPU**（4.5 默认是 CPU，这是最大的一笔），
  并且**记住你原来的设置，摘掉泛光时还回去**；
* Glare 质量 `HIGH → MEDIUM`（画面最大亮度差 0.016，看不出来）；
* 渐变/模糊那一段可以在半分辨率上算（`bv_glow.GLOW_CANVAS`，**默认关闭** ——
  GPU 合成器上并不省时间，只在显卡用不了、必须用 CPU 合成时才值得打开）。
