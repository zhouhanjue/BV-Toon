# BV-Toon

[中文](README.md) ｜ **English** ｜ [日本語](README.ja.md)

> One-click toon shading for MMD models · native material reading · edge preview · eye shadow · bloom · enforced credit watermark

**Current version: 1.8.0**

**BV-Toon is an independently written Blender add-on**: the code, the node graphs and the assets are all written from scratch, and it contains no code or assets from any third-party add-on.
The shading nodes are assembled inside the bundled `BVToonData/BVToonShading.blend`, which you can open in Blender and edit by hand; if that asset is missing, it automatically falls back to generating the nodes on the spot.

> The design follows the common practice of MMD toon shading and was inspired by the publicly documented behaviour of similar Blender add-ons. Running it requires the open-source add-on [mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/). This project has no code or asset relationship with any third-party add-on.

## What it does

| Feature | Description |
|---|---|
| **One-click toon (一键卡渲)** | One button: apply a toon preset → generate the MMD edge preview |
| **Native material reading (原生读取材质)** | Reads mmd_tools' `mmd_material` directly (base colour / sphere / sub-texture / transparency) with **no destructive conversion**, so the spangles and the sheen of the sphere layer are not lost |
| **Toon presets (卡渲预设)** | One-click toon (一键卡渲) / Cool (冷调) / Warm night (夜色暖); the parameters are exactly that table in `bv_shading.py`, change them however you like |
| **Bloom (泛光)** | A compositor effect: **driven by the Emit pass + glow outside the silhouette**; it works even with no lighting, and a bright background does not get smeared along with it; **the strength is measured per model and set automatically** (a dark-coloured character does not come out dimmer than the others); removable in one click |
| **Eye shadow (目影)** | Sets the "目影" material to semi-transparent black. **The blush feature has been removed on request** (see the "1.8.0" entry in the CHANGELOG) |
| **Enforced credit watermark (强制署名水印)** | Before rendering it forcibly burns in `渲染 BVToon / @BVan` (85% transparent, no backing plate); an edited copy turns into "未授权修改版". The handler carries the `persistent` flag and is re-attached on every enable / every panel draw — so it is **still enforced** after creating or opening a file |
| **The material tree stays clean (材质树保持干净)** | Once toon shading takes over, the non-toon nodes in the material tree are cleaned up and only `bv_*` and the output are kept (so that the two node setups do not fight each other). The mmd_tools `mmd_material` data itself is not rewritten, but there is **no "restore to basic material in one click" button** |

## Panel

`3D viewport → N → the "Toon" tab`

``
▼ BV-Toon 一键卡渲        [模式：替换【模型】材质 ▾]
                          [ ▶  一 键 卡 渲 ]        ← toon shading + edge preview
  其他设置                [添加泛光][🗑] / [设置目影]
                          脸材质：颜 ／ 损毁：被改或未验证都损毁（唯一档位，无选项）
                          [烧录署名] [署名文字] [不透明度]
                          [使用条款 中文 | EN | 日本語] / [描边粗细] [应用]
  BV-Toon · 维护：BVan / DEEPSEEK · 1.8.0
``

If the copy has been edited, or the integrity manifest is missing, an extra red warning block appears at the **very top** of the panel.

## Integrity check (hash anti-tamper)

At packaging time `BVToonData/integrity.json` is generated (SHA-256 of the 7 top-level `.py` files + the toon asset) and shipped out with the zip.
The add-on checks it **on load**, **every time the panel is drawn** and **before every render**:

| State | When | Watermark |
|---|---|---|
| Normal | The manifest is there and every file matches | `渲染 BVToon / @BVan` (85% transparent white text, editable in the panel) |
| Unauthorised modified copy (未授权修改版) | The manifest is there, but a file was edited / is missing / is extra | `未授权修改版 / UNAUTHORIZED MODIFIED COPY` (opaque red text + black background) |
| Unverified copy (未验证副本) | There is no manifest, or the manifest cannot be read | `未验证副本 / UNVERIFIED COPY` (opaque red text + black background) |

### Verification fails: the picture is always damaged (no setting to choose)

**There is no switch and no dropdown** — the panel shows only one line of text: `损毁：被改或未验证都损毁（唯一档位，无选项）`.
There is only one rule:

* Verification **passes** → the picture is as usual
* Verification **fails** (modified / unverified) → the picture is **pixelated + level-crushed + desaturated and darkened**, obviously a ruined image at a glance

The damage goes through the compositor (`bv_damage.py`), so stills, animations and viewport renders are **all** affected; once things are back to normal (the manifest recomputed)
the nodes are removed and the wiring is restored, leaving no junk behind.

* **Why there is no option**: an edited copy should not be able to produce usable pictures at all — no room is left to loosen that
* **The cost (stated honestly)**: because "unverified" also counts as a failure, a **copy dragged straight from the source directory
  into `addons` (with no manifest) is damaged as well**; there is only one proper way back to normal: run `tools/install_bv_toon.py` once to recompute the manifest
* **This is not encryption, and is not meant to be**: someone who knows what they are doing can recompute the manifest along with it, or simply disable the add-on.
  What it stops is "change a few names and claim you wrote it", and it makes an edited copy **unable to produce usable pictures by itself**.
* **How this relates to the licence**: GPL v3 allows modification and redistribution — all that is touched here is **the picture this copy renders itself**,
  and nobody is restricted from changing the code, redistributing it or using it commercially; §7 additional term 2 of the LICENSE already requires that "a modified version must be marked in a
  reasonable way as different from the original", and both the watermark and the damage are implementations of that requirement.
* The manifest covers the top-level `*.py` files and `BVToonData/BVToonShading.blend`; documentation and `LICENSE` are not covered.

## 腮红：已移除

1.8.0**去掉了腮红功能**（作者要求）：面板上没有相关按钮，
卡渲组里也没有腮红插座。目影不受影响。

## Bloom (strength measured per model, not by how dark the character is)

The whole bloom chain works on **absolute brightness** (the source is the render's Emit pass + the part of the picture above the threshold, and the outer glow has an extra
"emission > threshold" gate), so a dark-coloured character naturally gets less than a light-coloured one — measured with the same set of parameters,
the ring of light outside the silhouette of 奥黛塔 (Odette) is **+0.160**, while 胡桃 (Hu Tao) gets only **+0.017** (a 7× difference; what you see is "Hu Tao has no bloom").

Now, when you click "add bloom" (添加泛光), it **measures first and decides after**:

1. It renders two **192×192** thumbnails (strength 0 / current value) and looks at how much **the ring of light outside the silhouette** was brightened
   (averaging the pixels that are "black when off, bright only when on, and within 2 pixels of the silhouette")
2. If it is not bright enough it scales up proportionally, **closing the loop** at most 3 times, approaching the target **0.16** (= the value measured on 奥黛塔 at
   settings everyone accepts); the automatic value is clamped to `[0.03, 2.50]`
3. **It only adjusts upwards**: characters already brighter than 0.16 are left as they are (bright ones are never dimmed)
4. If it cannot measure (no camera / the camera does not frame it / fewer than 12 pixels outside the silhouette) that is **written honestly in the report**,
   the strength stays at the default `0.10`, and it does not pretend to have measured

Measured results: the ring of light outside the silhouette — 奥黛塔 **0.152** / 胡桃 **0.144** / 芙宁娜 **0.142** (a 1.07× spread).

The `BVToon_Glow` group node in the compositor can be tuned by hand at any time: **strength / threshold / size / outer glow / gain**.
`增益` (gain) is a multiplier for manual fine-tuning (it multiplies the emission branch, and sits before the outer-glow gate — so it also turns
"how bright counts as a bright area" into something relative to this model).

> What it measures is **the picture the current camera sees**: if you change the camera position or swap the model, click "add bloom" (添加泛光) again to re-measure.

## Dependencies

- **Blender 4.5 or newer** (bloom uses Eevee Next's Emit pass; 3.6+ works but bloom is limited)
- **[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/)** (open-source MMD importer) —
  reading MMD materials, importing models and the edge preview all need it

No other add-on is required.

## Installation

1. `Edit > Preferences > Add-ons > v (top right) > Install from Disk` → choose `BV-Toon-1.8.0.zip`
2. Tick **BV-Toon** in the list
3. Select your MMD model → `N` → the "Toon" tab → **One-click toon (一键卡渲)**

Installing by hand from the source directory is possible too, but then there is no integrity manifest and the watermark will read "unverified copy" (未验证副本) —
if you want the normal credit, use the zip from the Release, or run
`python tools/install_bv_toon.py --target <that directory>` yourself inside the copy's directory.

## Directory structure

| File | Purpose |
|---|---|
| `__init__.py` | bl_info, the panel, the operators, the enforced watermark before rendering |
| `bv_util.py` | reads mmd_tools' MMD material data, builds its own UV groups, sphere / sub-texture layers |
| `bv_shading.py` | the toon node group (generated on the spot in Python) + the preset table |
| `bv_materials.py` | applying / cleaning up nodes / eye shadow / outline / ambient colour |
| `bv_glow.py` | bloom (emission-driven + glow outside the silhouette + strength measured per model automatically) |
| `bv_integrity.py` | integrity check (generating and verifying the hash manifest, three-state judgement) |
| `BVToonData/BVToonShading.blend` | the toon node group asset (75 nodes / 31 interfaces, editable by hand) |
| `BVToonData/integrity.json` | the hash manifest generated at packaging / install time (not written by hand) |

## MMD etiquette

This add-on contains no MMD model / texture / motion data; when you publish a work, follow the material author's rules and give credit:

```text
Model: <model author name> (<distribution page link>)
渲染 BVToon / @BVan
Tools used: BV-Toon
```

See [`MMD-NOTICE.md`](MMD-NOTICE.md) in the add-on directory for details.

## Licence

**GNU GPL v3 + §7 attribution additional term** (in Chinese / English / Japanese; full text in `LICENSE`):
✅ Use, modification and redistribution allowed (including commercial) ｜ ✅ Redistributions and modified versions must be open-sourced under GPL v3 as well ｜ ✅ The credit `BVToon / @BVan` must be preserved, and published works must state `渲染 BVToon / @BVan` ｜ ✅ A modified version must be marked in a reasonable way as different from the original (the add-on's own "未授权修改版" watermark is the technical implementation of that term) ｜ ✅ No warranty.

## Glow performance (1.8.0)

At 4K the extra cost of enabling the glow dropped from **+2.3 s to +0.5 s**
(3840x2160, measured on one machine).

* Adding the glow switches the compositor to **GPU** (4.5 defaults to CPU - the big win),
  and **your original setting is restored when the glow is removed**;
* Glare quality `HIGH -> MEDIUM` (max luminance difference 0.016 - invisible);
* The glow front-end can run on a half-resolution canvas (`bv_glow.GLOW_CANVAS`,
  **off by default**: it saves nothing on a GPU compositor and only helps when you are
  stuck with CPU compositing).
