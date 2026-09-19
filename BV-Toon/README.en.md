[中文](README.md) ｜ **English** ｜ [日本語](README.ja.md)

# BV-Toon

> One-click toon shading for MMD models · native material reading · toon-ramp driven lighting ·
> edge preview · eye shadow · blush · bloom · enforced credit watermark · integrity check

**An independently written Blender add-on**: all code, node graphs and assets are original;
it contains no code or assets from any third-party add-on.

* Add-on manual: [`BV-Toon/README.md`](BV-Toon/README.en.md) ( [中文](BV-Toon/README.md) ｜ [日本語](BV-Toon/README.ja.md) ) ｜ Changelog: [`CHANGELOG.md`](CHANGELOG.md)
* Latest release: [`RELEASE-1.8.0.en.md`](RELEASE-1.8.0.en.md) ｜ MMD etiquette: [`MMD-NOTICE.md`](MMD-NOTICE.md)
* License: [`LICENSE`](LICENSE) (Chinese / English / Japanese)

## Quick start

1. Download `BV-Toon-1.8.0.zip` (release asset)
2. Blender: `Edit > Preferences > Add-ons > v > Install from Disk`
3. Enable **BV-Toon** → select your MMD model → `N` → the **Toon** tab → **One-click toon**

Requires Blender 4.5+ and the open-source add-on
[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/).

## What it does

* **One-click toon**: card-shading preset + MMD edge preview in a single click
* **Native MMD materials**: sphere layers follow MMD semantics (add = spangles/gems/metal,
  multiply = cloth sheen)
* **Toon-ramp driven lighting**: sampled the MMD way (U = 0.5, V = light level)
* **Enforced credit watermark**: `渲染 BVToon / @BVan` is burned in on one-click and
  **before every render** (85% transparent)
* **Integrity check (hash anti-tamper)**: the packaging manifest records the SHA-256 of 6 `.py`
  files plus the `.blend` asset, checked on load and before every render — edited = `未授权修改版`,
  no manifest = `未验证副本` (red and opaque + panel alert, **rendering is never blocked**)
* Eye shadow / blush / bloom / adjustable outline width / view transform switched to Standard

## Layout

| Path | Contents |
|---|---|
| `BV-Toon/` | the add-on (`__init__.py`, `bv_*.py`, `BVToonData/BVToonShading.blend`, LICENSE) |
| `tools/` | development & verification scripts (asset build, A/B renders, probes, `audit_bv_toon.py`) |

## License (summary)

✅ Free to use and redistribute (incl. commercial) ｜ ✅ Modification allowed ｜ ✅ Copies and modified versions must stay GPL v3
｜ ✅ Attribution must be preserved. Full text in [`LICENSE`](LICENSE).

### Glow performance (1.8.0)

At 4K the extra cost of enabling the glow dropped from **+2.3 s to +0.5 s**
(measured at 3840x2160 on one machine):

* adding the glow now switches the compositor to **GPU** (4.5 defaults to CPU - this is
  the big one), and **your original setting is restored when the glow is removed**;
* Glare quality `HIGH -> MEDIUM` (max luminance difference 0.016 - invisible);
* the blur/tint stage can run on a half-resolution canvas (`bv_glow.GLOW_CANVAS`,
  **off by default** - it saves nothing on a GPU compositor and only helps when you
  are stuck with CPU compositing).
