# 上架步骤

## 1. 建仓库并推上去

```bat
cd github\BV-Toon
git init
git add .
git commit -m "BV-Toon 1.1.5：MMD 一键卡渲插件（自研）"
git branch -M main
git remote add origin https://github.com/<你的用户名>/BV-Toon.git
git push -u origin main
```

## 2. 建 Release（可选，方便别人一键安装）

把 `dist\BV-Toon-1.1.5.zip` 传到 Release 附件即可（zip 里顶层就是 `BV-Toon/`，
Blender 的「从磁盘安装」能直接吃）。

## 3. 仓库设置里的建议

* **About**：`MMD 模型一键卡渲：原生读取材质 · 一键卡渲 · 边缘预览 · 目影 · 腮红 · 泛光`
* **Topics**：`blender-addon` `mmd` `toon-shading` `cel-shading` `mmd-tools` `eevee`
* **License**：GPL-3.0（`LICENSE` 已在仓库根目录）

## 这个文件夹里有什么 / 没有什么

**有**（都是自研内容）：
```
BV-Toon/                      插件本体（5 个 py + BVToonData/BVToonShading.blend + README + LICENSE）
tools/                        9 个开发/验证脚本
README.md  LICENSE  .gitignore  PUBLISH.md
```

**没有**（有意排除，请勿添加）：
* 其它插件的内容（尤其是付费插件的代码与资产 —— 本机自用没问题，**不能上架**）
* `_bvtoon_backup/`、`dist/_old/`、`_scratch/`、`tests/`（本地过程产物）
* 用第三方 MMD 模型渲出的测试图（模型本身有独立的授权，别一起发）

## 许可

本仓库按 **GPL-3.0** 发布：可自由使用、修改、分发；**改版再发布必须同样开源并保留署名**。