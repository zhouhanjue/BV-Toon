[中文](RELEASE-1.7.2.md) ｜ **English** ｜ [日本語](RELEASE-1.7.2.ja.md)

# BV-Toon 1.7.2

> One-click toon shading for MMD · the bloom is finally uniform across models · "add glow" now
> **measures instead of guessing** · and it says so when it cannot measure
> (integrity check / three-state watermark / damaged picture / enforced credit: unchanged)

## Install

1. Download `BV-Toon-1.7.2.zip` (release asset)
2. Blender: `Edit > Preferences > Add-ons > v > Install from Disk`
3. Enable **BV-Toon** → select your MMD model → `N` → the **Toon** tab → **One-click toon**

Requires Blender 4.5+ and the open-source add-on
[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/).

> **This release touches the glow only.** 1.7.1's integrity check, three-state watermark, damaged
> picture, enforced credit — and the whole face-only blush path — are **unchanged down to the line**;
> a normal copy still renders with the `渲染 BVToon / @BVan` credit. The manifest is in the zip, so a
> copy installed by **hand-copying the source directory** still reads "unverified copy", and the only
> way back is `python tools\install_bv_toon.py`.

## The symptom: the bloom is inconsistent — dark characters have almost none

* The author's report: "the bloom is inconsistent — 胡桃 and other characters are clearly weaker than 奥黛塔; raise all characters to Odette's level"
* In its most extreme phrasing: **Hu Tao has no bloom at all**, while Odette has a full ring of light
* It is not a matter of taste — it **measures**: same camera, same settings, their brightness outside the silhouette differed by **7×**

## Root cause: the whole glow chain runs on absolute brightness (measured at 640×853, identical camera, EEVEE)

The glow source is the render's **Emit pass** (the toon shader is all-emission), plus **image parts over the 0.95 threshold**, plus an "**outer glow**" that only fires where `max(RGB)` of the emit **exceeds 0.60**. Darker clothes therefore simply produce less light — every term is an absolute quantity:

| Model | Character mean brightness (no glow) | Added on the character | Added in the ring just outside the silhouette |
|---|---|---|---|
| 奥黛塔 (Odette, white skin/clothes) | 0.735 | +0.0497 | +0.160 |
| 芙宁娜 (Furina) | 0.586 | +0.0075 | +0.029 |
| 胡桃 (Hu Tao, dark clothes) | 0.421 | +0.0060 | +0.017 |
| 初音ミク (Miku) | 0.964 | +0.0099 | +0.271 |

Odette glowed **7×** more than Hu Tao — so "Hu Tao has no bloom at all" is no exaggeration.

* **Tried and rejected**: the first attempt guessed a per-model gain from the materials' average base colour × `brightness`. It does not work — the material average **cannot predict how much of the screen is bright**: for Hu Tao it implied a **1.44×** boost, while the measurement showed she needed about **9×**.

## Highlights: clicking "add glow" measures the model instead of guessing

* 「添加泛光」 now **renders two 192×192 frames** (glow strength 0 and the current strength) and then looks only at the **ring just outside the silhouette**: pixels that are black with the glow off, lit with the glow on, and **within 2 px of the silhouette**
* Then it **closes the loop**: if the ring is dimmer than the target it multiplies the strength and **measures again, up to 3 iterations** (the "glow off" frame is reused, so the cost is **1 + N tiny renders**)
* Target value: **0.16** — exactly what Odette measured at the settings everyone liked
* The auto value is clamped to **[0.03, 2.50]** and is **raise-only**: a character that already glows more than the target (Miku, 0.271) is **left exactly as it was** — the request was "don't let dark characters be dimmer", not "dim the bright ones"

| Step | What it is |
|---|---|
| **Measuring frames** | 192×192 × 2 (strength 0 / current strength); the "glow off" frame is reused in the loop |
| **Pixels measured** | black with the glow off, lit with the glow on, and within **2 px** of the silhouette (the "ring just outside the silhouette") |
| **Target** | **0.16** |
| **Closed loop** | dimmer than the target ⇒ multiply the strength and measure again, up to **3 iterations** |
| **Value** | clamped to **[0.03, 2.50]**, **raise-only** |

## Highlights: why the calibration is what it is

* The measuring band must be a fixed **fraction** of the frame (2 px at 192 ≈ **1 %** of the width), because the glare radius is itself a percentage of the image — the two have to scale together
* The counter-example: measuring at **96 px** with a **3-px** band samples the **bright core** right next to the silhouette and over-estimates the response — Hu Tao read **0.265** there, while the true full-resolution value was **0.166**
* A single measurement is also not enough on its own: the glow **clips at 1.0** (Odette's response per unit strength is **1.49** at strength 0.10 but only **0.43** at 1.2), hence the closed loop instead of a one-shot linear extrapolation

## Other changes (1.7.2)

* **The measurement protects the scene while it runs**: it temporarily sets the resolution to **192 px** on the long side (keeping the aspect), turns off the render stamp, and **temporarily unmounts the forced-credit `render_pre` handler** (white stamp text would pollute the measurement) — and always puts it back; the audit now asserts that the handler is **still mounted** afterwards
* All render settings are restored and the temporary PNGs are **deleted** (temp dir)
* **When it cannot measure, it says so**: with no camera in the scene, nothing framed, or fewer than **12 ring pixels** found, the add-on **says so in the operator report** (stored in the scene as `bv_glow_note`) and keeps the old default strength **0.10** instead of pretending it measured something
* New glow-group input **`增益`** (gain, default **1.0**): a manual multiplier on the emit-based glow source, applied **before the outer-glow gate**, so the gate becomes relative to the model as well. It is a **hand knob, not auto-set**
* New verification tooling: `tools\check_glow_uniform.py` (per model: import → one-click toon → add glow → render off/on, then assert the ring is **≥ 0.10 and ≤ 0.45**, that the forced-credit handler survived the measurement, and that the normalized models are **within 1.6× of each other**; currently `failures=0`), the probe `_scratch\probe_glow_models.py`, and **6 new glow checks** in `tools\audit_bv_toon.py` (now **70 pass / 2 known false failures** — `remove_glow` and `set_eye_shadow` returning CANCELLED is normal)
* Example images: `_glow_demo\`, per-model pairs `<name>-0-noglow.png` / `<name>-1-glow.png`

## Measured, and how to reproduce it

Method: **identical camera**, both versions rendered **at the auto strength**.

| Model | Ring before | Ring after | On the character (before → after) |
|---|---|---|---|
| 奥黛塔 | 0.160 | **0.152** | — |
| 胡桃 | 0.017 | **0.144** | **+0.0060 → +0.083** |
| 芙宁娜 | 0.029 | **0.142** | **+0.0075 → +0.061** |
| 初音ミク | 0.271 | **0.271** (raise-only, left untouched) | — |

* Odette / Hu Tao / Furina now sit **within 1.07× of each other** (it was **7×**) — and Miku stays untouched at **0.271**, per the raise-only rule

```
& 'C:\Program Files\XF Blender 4.5\blender.exe' -b --factory-startup --python tools\check_glow_uniform.py -- dist\BV-Toon-1.7.2.zip _glow_demo <模型.pmx 或 .pmd …>
python tools\package_bv_toon.py --verify
```

The first runs the full per-model measurement (the paired screenshots and the assertions land in `_glow_demo\`); the second checks the manifest in the zip.

## Tooling pitfall: the measurement unmounts the forced-credit handler

* The measurement needs a frame with **no stamp text**, so it **temporarily unmounts** the forced-credit `render_pre` handler
* The risk is real: had it been forgotten, **every later render would silently lose the `渲染 BVToon / @BVan` credit**, with no error raised anywhere
* It is therefore **always put back**, and `tools\audit_bv_toon.py` **asserts that the handler is still mounted** after the measurement

## Upgrading and compatibility (1.7.1 → 1.7.2)

* The glow node group **gained an input** ⇒ after upgrading **remove the glow and add it again** (or just click 添加泛光 once more — it removes and re-adds)
* The strength is **measured from the current camera/pose** ⇒ after changing the camera or the model, **re-click 添加泛光** if you want it re-measured
* The zip is `dist\BV-Toon-1.7.2.zip`; install via `Edit > Preferences > Add-ons > Install from Disk`; requires Blender 4.5+ and mmd_tools
* The manifest is packed in the zip, so a copy installed **by hand** from source shows "unverified copy", and the only official way back is `python tools\install_bv_toon.py`

## Known gaps

* The target **0.16** is calibrated on **one reference model** (奥黛塔) at its **default settings**, so another setup can still miss it
* The auto strength is a **scene-level** value (it lives on the glow group node in the compositor): with several characters of very different brightness in one scene, it measures **the camera view as a whole** — **split them into separate scenes** if you need per-character values
* The gaps listed in 1.7.1 (material-name special cases, sub-texture highlight, face-detection coverage) are untouched by this release and remain open

## License (summary)

* License: **GNU GPL v3** (plus Section 7 attribution terms) — ✅ use, modify and redistribute freely (incl. commercial) ｜ ✅ copies and modified versions must stay GPL v3 ｜ ✅ the credit `BVToon / @BVan` must be preserved, and published works carry the credit `渲染 BVToon / @BVan`; full text in [`LICENSE`](LICENSE).
When publishing MMD works, follow [`MMD-NOTICE.md`](MMD-NOTICE.md).
