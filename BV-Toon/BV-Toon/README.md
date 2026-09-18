# BV-Toon

> MMD 模型一键卡渲 · 原生读取材质 · 渐变贴图驱动明暗 · 边缘预览 · 目影 · 腮红 · 泛光

**独立编写的 Blender 插件**：代码、节点图、资产全部自写，不含任何第三方插件的代码或资源。

* 插件源码与用法见 **[`BV-Toon/README.md`](BV-Toon/README.md)**
* 许可：**自定义使用许可**（允许使用 / 禁止再分发 / 禁止发布修改版 / 必须署名，中英日三语，见 [`LICENSE`](LICENSE)）
* 依赖：[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/)（开源 MMD 导入器）+ Blender 4.5 或更新

## 发版文案

* 最新版本说明：[`RELEASE-1.5.0.md`](RELEASE-1.5.0.md)（可直接粘进 GitHub Release）
* 逐版改动：[`CHANGELOG.md`](CHANGELOG.md)

## MMD 使用规范

用本插件出图并发布时，请遵守素材作者的使用规范并署名，格式见 [`MMD-NOTICE.md`](MMD-NOTICE.md)：

```text
模型：<模型作者名>（<配布页面链接>）
渲染：BVan
使用工具：BV-Toon
```

## 快速开始

1. 下载 `BV-Toon/` 整个文件夹，或从 Release 页面取打包好的 zip
2. Blender：`编辑 > 偏好设置 > 附加组件 > v > 从磁盘安装`
3. 在列表里勾上 **BV-Toon**，选中 MMD 模型 → `N` → 「**Toon**」标签 → **一键卡渲**

## 目录

| 路径 | 说明 |
|---|---|
| `BV-Toon/` | 插件本体（`__init__.py`、`bv_*.py`、`BVToonData/BVToonShading.blend`、README、LICENSE） |
| `tools/` | 开发/验证脚本：资产生成、A/B 渲图、遮罩与渐变图探针、各项检查 |

## tools 里的脚本

| 脚本 | 作用 |
|---|---|
| `build_assets.py` | 由代码生成 `BVToonData/BVToonShading.blend`（卡渲节点组资产） |
| `render_toon_ab.py` | 同机位渲 A/B 并逐像素对比（透明背景，只统计模型像素） |
| `probe_mask.py` | 把分界/遮罩接到输出渲出来，看它到底是什么值 |
| `probe_toon_math.py` / `probe_toon_axis.py` | 数值检查 MMD 渐变贴图（渐变的轴向、对比度、V 坐标范围） |
| `check_toon_ramp.py` / `check_ambient.py` / `check_oneclick.py` | 接线与行为的验收脚本 |

用法：`blender -b --python tools/<脚本> -- [--pmx <模型.pmx>]`

## 致谢与说明

设计上参考了 MMD 卡渲的通行做法（渐变贴图查表、球面层的加算/乘算语义、目影与描边），
并受同类 Blender 插件的公开行为启发。本项目与任何第三方插件不存在代码或资源上的关系。
运行需要开源插件 mmd_tools。