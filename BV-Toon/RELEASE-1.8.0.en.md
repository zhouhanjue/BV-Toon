[中文](RELEASE-1.8.0.md) ｜ **English** ｜ [日本語](RELEASE-1.8.0.ja.md)

# BV-Toon 1.8.0

> Blush removed on request · **Glow performance overhaul** (the cost of enabling the glow at 4K:
> +2.7 s -> +0.99 s) · integrity check / tri-state watermark / damage layer / forced credit are
> exactly the same as 1.7.2

## Install

1. Download `BV-Toon-1.8.0.zip` (release asset)
2. Blender: `Edit > Preferences > Add-ons > v (top right) > Install from Disk`
3. Enable **BV-Toon** -> select your MMD model -> `N` -> the "**Toon**" tab -> **One-click toon**

Requires Blender 4.5+ and the open-source add-on
[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/).

## What changed

### 1. The blush feature is **gone** (author's request)

No blush buttons in the panel (all three rows - add blush / face = current material / clear -
plus the hint lines were deleted), and no blush node chain in the shading pipeline:

* `__init__.py`: the three operators and their registration removed; the word "blush" removed
  from the `bl_info` description;
* `bv_shading.py`: the blush chain, its **10 input sockets** and `cheek_mask` deleted; the main
  colour chain now takes the rim-light result directly (the rim stage and the output stage are untouched);
* `bv_materials.py`: blush constants, `blush_*` / `place_blush` / `blush_region`, and the face
  detection helpers that only served blush (`face_materials` / `_material_zone` /
  `_face_zone_scores` / `_neck_z`) all deleted;
* the shading asset `BVToonShading.blend` was rebuilt from **78 nodes / 34 sockets** down to
  **50 nodes / 22 sockets** (20 inputs, no blush sockets);
* measured: **the render is pixel-identical to before the removal** (blush was off by default;
  Hutao: 36910 character pixels, mean 0.413).

### 2. Glow performance: enabling the glow now costs about a third (measured at 4K)

Protocol: 3840x2160, Hutao, one machine, warm-up frame, then alternating off/on, 3 rounds, median.

| Build | Glow off | Glow on | Extra cost |
| --- | --- | --- | --- |
| old 1.7.2 (4.5, compositor defaults to CPU) | 2.83 s | 5.17 s | **+2.34 s** |
| **1.8.0** (total, Emit pass included) | 2.14 s | 3.12 s | **+0.99 s** |

Three changes, biggest first:

* **Adding the glow now switches the compositor to GPU.** In 4.5
  `scene.render.compositor_device` **defaults to CPU** and the whole glow lives in the compositor:
  same 4K scene, **+3.01 s** on CPU vs **+1.04 s** on GPU, with a **pixel-identical** result
  (max luminance difference 0.004). **Your previous setting is remembered and restored when the
  glow is removed.** 5.2 already defaults to GPU, so nothing is touched there.
* **Glare quality HIGH -> MEDIUM.** The two Glare nodes are the most expensive part of the glow.
  On 4.5's CPU compositor this saves **0.6 s** (HIGH->LOW saves 0.8 s) for a maximum luminance
  difference of just **0.016**: the glow is a large-radius, low-frequency effect, so one pyramid
  level less is invisible.
* **New `GLOW_CANVAS` (default 1.0 = no reduction).** It can compute the front of the glow on a
  1/N canvas and scale back up before the final add (the picture itself is never downsampled).
  Measured: it only pays off on the **CPU compositor** (there 0.5 takes the 4.5 increment from
  +3.38 s down to **+1.13 s**); on a GPU compositor it saves nothing (+0.47 vs +0.49) while
  pushing the bloom slightly outwards (glow on the character **-16%**). So it is **off by default** -
  not a single pixel changes - and only worth flipping when you are stuck with CPU compositing.

**Could it be squeezed further? No - we measured it.** About two thirds of the remaining ~1 s is structural:

| Part | 4.5 | 5.2 | Can it go? |
| --- | --- | --- | --- |
| Emit pass (one extra AOV render - the glow's light source) | +0.33 s | +0.34 s | No - without it the glow is no longer driven by the model's own emission |
| The compositor framework (even an empty `RLayers->Composite` tree costs this) | +0.33 s | +0.35 s | No - it is the price of using a compositor at all |
| The glow maths (two Glares + blur + 15 per-pixel nodes) | +0.33 s | +0.33 s | Measured piece by piece: ~0.001-0.009 s per node, 0.00 s for Glare quality on GPU, and **dropping one Glare layer saves 0.02 s while changing the image by 0.081** |

So this release deliberately did **not** trade image quality for noise-level gains.

### 3. Three stale assertions in the audit tool fixed

`tools/audit_bv_toon.py` expected **9** panel buttons (from the blush era; it is **8** now) and
treated the second `remove_glow` (nothing left to remove) and `set_eye_shadow` on a model without
a "目影" material (returns `CANCELLED`) as failures. All three also failed on the old build (false
positives). Only the **first** call is now required to return `FINISHED`; the audit reports
**0 FAIL** in both real Blender configurations.

## Did the picture change?

* Glow: at 4K, per-pixel mean difference **0.0021**, max 0.0196; **the halo outside the silhouette
  is unchanged (0.0669 -> 0.0668)**; 5.2 mean difference 0.0015. The only measurable difference is
  that the glow landing **on the character** is about 9% lower (with MEDIUM the light concentrates
  more in the outer ring). Want the old tightness back? Set `bv_glow.GLOW_QUALITY` back to `"HIGH"`.
* Cross-model uniformity (`tools\check_glow_uniform.py`, four models) **failures=0**, spread
  **1.14x** (1.7.2 was 1.09x).
* After the blush removal: **pixel-identical render**.

## Upgrade / compatibility (1.7.2 -> 1.8.0)

* Blush **no longer exists** (panel, operators and node chain are gone); scenes that used it simply
  stop showing blush.
* The glow group still has the same sockets as 1.7.2 (22), so old scenes keep working. **But to get
  the new speed on 4.5, press "Add glow" once again** - the GPU switch happens at that step, and an
  old `.blend` still stores CPU (you can also flip the compositor device manually in Render Properties).
* The zip is `dist\BV-Toon-1.8.0.zip`; install via `Edit > Preferences > Add-ons > Install from Disk`.
  Requires Blender 4.5+ and mmd_tools.
* The integrity manifest ships **inside the zip**; a copy installed by hand from the sources will
  show the "UNVERIFIED COPY" watermark. The only official fix is `python tools\install_bv_toon.py`.

## Known gaps

* The glow's auto-strength target **0.16** was calibrated on one reference model (Odette) with
  default settings; another setup can shift it.
* The aura gate (`emission > 0.60`) **never fires for dark models** (the `gain` socket has always
  been 1.0): on Hutao, deleting the whole aura branch leaves the image pixel-identical - that branch
  only really works on models whose skin and clothes are bright.
* The items listed since 1.7.1 (special material-name rules, secondary-texture highlights, wider
  face detection) are unrelated to this release and still open.

## Licence (summary)

* Licence: **GNU GPL v3** (with a §7 attribution addendum) - allowed to use, modify and redistribute
  (including commercially) | redistributions and forks must stay GPL v3 | the credit `BVToon / @BVan`
  must be kept, and public works must show `渲染 BVToon / @BVan`. Full text in [`LICENSE`](LICENSE)
  (Chinese / English / Japanese).
* When using MMD assets, follow [`MMD-NOTICE.md`](MMD-NOTICE.md).
