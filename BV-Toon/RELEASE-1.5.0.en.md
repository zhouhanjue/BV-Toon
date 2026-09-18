[中文](RELEASE-1.5.0.md) ｜ **English** ｜ [日本語](RELEASE-1.5.0.ja.md)

# BV-Toon 1.5.0

> One-click toon shading for MMD · native material reading · toon-ramp lighting ·
> edge preview · eye shadow · blush · bloom · enforced credit watermark

## Install

1. Download `BV-Toon-1.5.0.zip` (release asset)
2. Blender: `Edit > Preferences > Add-ons > v > Install from Disk`
3. Enable **BV-Toon** → select your MMD model → `N` → the **Toon** tab → **One-click toon**

Requires Blender 4.5+ and the open-source add-on
[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/).

## Highlights: enforced credit watermark

* One-click burns **`渲染 BVToon / @BVan`** into the image (**85% transparent**, no background box)
* **It is forced again the instant you hit Render** (a `render_pre` handler) — turning the panel
  switch off or editing the text does not bypass it
* Every other Blender stamp field (`file / date / render time / timecode / scene / frame /
  camera / labels` …) is turned **off**, so only the credit appears
* Panel: `烧录署名` (toggle), `署名文字` (text), `不透明度` (default 0.15 = 85% transparent)

## Highlights: trilingual license

* A **custom use license (Chinese / English / Japanese)**: ✅ free to use (incl. commercial) ｜
  ❌ no redistribution ｜ ❌ no publishing modified versions ｜ ✅ attribution required
* The panel gains a `使用条款` row with **中文 / EN / 日本語** buttons, each opening a popup
* Full text ships as `LICENSE` inside the add-on package (all three languages)

## Other improvements (cumulative 1.4.x → 1.5.0)

* **Toon-ramp driven lighting** — sampled the MMD way (U = 0.5, V = light level), shared
  `toon01–10` supported
* **Sphere layers follow MMD semantics** — add (spangles/gems/metal/eyes) = 1.0,
  multiply (cloth) = 0.30
* **Clean material trees** — after conversion only `bv_*` nodes and the output remain
* **View transform switched to Standard automatically** — AgX/Filmic washes out and flattens
* **Adjustable outline** — coloured from the material's own `edge_color`, panel slider
  (default 0.08)
* **Fixed the green ghost bloom** (Glare options became sockets in 4.5/5.x, enum capitalised)

## Known gaps

* Material-name special cases (`发+` additive highlight, `目光/目影`, `肌` subsurface red, `スフィア`)
* Sub-texture (specular map) wired into the highlight path

## License (summary)

✅ Free to use (incl. commercial) ｜ ❌ No redistribution ｜ ❌ No publishing modified versions ｜
✅ Attribution required. Full text in [`LICENSE`](LICENSE). When publishing MMD works, follow
[`MMD-NOTICE.md`](MMD-NOTICE.md).