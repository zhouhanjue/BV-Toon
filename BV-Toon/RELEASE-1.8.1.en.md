[中文](RELEASE-1.8.1.md) ｜ **English** ｜ [日本語](RELEASE-1.8.1.ja.md)

# BV-Toon 1.8.1

> **Adjustable outline colour** (new "Uniform outline colour" toggle) · outlines follow MMD's
> `edge_flag` and the names **瞳 / 目 / 眉** · **models converted from other games are no longer
> dark** (pure-grey diffuse colours are skipped) · the panel no longer "loses options"
> (`draw()` is read-only) · glow performance · integrity check / tri-state watermark / damage layer /
> forced credit unchanged

## Install

1. Download `BV-Toon-1.8.1.zip` (release asset)
2. Blender: `Edit > Preferences > Add-ons > v (top right) > Install from Disk`
3. Enable **BV-Toon** -> select your MMD model -> `N` -> the "**Toon**" tab -> **One-click toon**

Requires Blender 4.5+ and the open-source add-on
[mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/).

> **Restart Blender after installing**: a running Blender does not reload add-on code, so the panel
> would still show the old version.

## What is in this release

### 1. Adjustable outline colour (new)

In "Other settings": a "**Uniform outline colour**" toggle plus a colour picker.

* Off (default): every material keeps the MMD `edge_color` the model author painted
* On: the whole model uses the colour you pick; "Apply" re-applies **thickness and colour** at once

The `mmd_edge.*` materials run their colour through a `Gamma 2.2` node, so the uniform colour is
pre-compensated - **what you pick is what you see**. Materials marked "no outline" (eyes, mouth, eye
shadow) are never tinted - they have no shell at all.

### 2. Outlines follow MMD's "draw or not" flag

* `edge_flag = 0` materials no longer hide their shell behind a transparent material - the shell is
  simply not built;
* any material whose name contains **瞳 / 目 / 眉** never gets an outline, even if the model says
  otherwise (on `Vesna.pmx` the shell weight went 0.01083 -> 0.00000).

### 3. Converted models are no longer dark (important)

Packages converted from other games (Arknights: Endfield, Genshin, Star Rail ...) often write **the
same `0.8` grey into every material's diffuse colour**. MMD renders
``texture x (diffuse x light + ambient)`` - **a pure-grey diffuse is a lighting level, not a
colour**; this add-on is fully self-emissive, so multiplying by it just darkens everything by 20%.
Pure-grey diffuse colours are now **skipped**:

* tinted -> still applied (this is what the classic Miku colour-only materials need)
* pure grey and not dark (>= 0.6) -> skipped
* pure grey but clearly dark (< 0.6) -> kept (deliberately dark parts)

Measured on `D:\da\Liino` (Endfield's Liino): skin value **0.654 -> 0.718** (the texture itself is
0.737, i.e. 97%), close to the package's official key art (0.775). **19-model batch check**:
no errors, no blackening, no lost geometry; every model has 6-29 grey-diffuse materials affected,
so this was a systemic issue rather than an Endfield-only one.

### 4. The panel no longer "loses options" (bug fix)

`draw()` used to create missing scene properties on the fly - but some Blender contexts **forbid
writing to IDs**, raising `AttributeError: Writing to ID classes in this context is not allowed`,
and **every widget after that exception silently disappeared** (which looked like "the panel is
missing that option"). All panel properties are now **registered properties** (they always exist)
and `draw()` only reads. The audit gained two checks (static + a real draw with a "writing raises"
fake scene), so this cannot come back unnoticed.

### 5. Glow performance

The total cost of enabling the glow went from **+2.72 s to +0.99 s** (measured at 4K): the
compositor switches to GPU when you press "Add glow" (4.5 defaults to CPU; your old setting is
restored on removal), Glare quality HIGH -> MEDIUM, plus an optional `GLOW_CANVAS` (off by default).
The halo outside the silhouette is unchanged.

### 6. The credit watermark is now mandatory (option removed)

The three panel controls (the **stamp credit** checkbox, the **credit text** field and the **opacity**
slider) are gone; a single locked line states `Credit: always burned in, cannot be disabled`:

* it is always stamped - neither one-click nor the pre-render handler checks a switch any more;
* the text is fixed - `渲染 BVToon / @BVan` in the normal state; modified/unverified copies get the
  warning text from the integrity check (`UNAUTHORIZED MODIFIED COPY` / `UNVERIFIED COPY`);
* opacity is fixed at 0.15 (85% transparent);
* four audit checks pin it down: flip the old switches off, set a custom text, set opacity 0 - the
  forced watermark still comes out as the default credit.

### 7. Per-game glow presets (collapsible, three games)

Inside the "Glow" block there is a collapsed "**Per-game glow presets**" line that sets the glow to
that game's look in one click (**it appears after you press "Add glow" and disappears when you remove
the glow**):

| Button | Strength | Threshold | Size | Aura | Gain |
|---|---|---|---|---|---|
| Endfield | 1.10 | 0.55 | 9 | 0.24 | 1 |
| Genshin | 0.08 | 1.20 | 9 | 0.24 | 1 |
| Zenless Zone Zero | 0.10 | 1.30 | 9 | 0.24 | 1 |

Measured (Hu Tao, dark backdrop, whole-frame mean): auto strength 0.277 | Endfield **0.336** (very
strong, highlights blow out) | Genshin 0.277 | ZZZ 0.277. Tune "Strength / Threshold" on the node if
you want it stronger or softer.

### 8. Panel rearranged into four blocks

```
[BV-Toon One-click]  mode / one-click / hint
[Glow]               add & remove + (when a glow exists) the collapsible per-game presets
Settings             outline width + Apply / Set eye shadow / Uniform outline colour + picker
About                credit (mandatory) / terms of use (3 languages) / damage (single tier, no option)
```

## Notes

* Scenes toon-shaded before this release should be re-shaded (one-click again, or "Apply") to pick up
  the new outline handling.
* If a model package is missing a texture, that part falls back to the material colour instead of
  turning magenta/white.
* Blender 5.2's blur node has no `size_x`/`size_y` properties (the size moved to a socket), so the
  outer-glow blur radius is not applied - 5.2's glow has one layer less than 4.5's (known, unfixed).

## Licence (summary)

* Licence: **GNU GPL v3** (with a §7 attribution addendum) - allowed to use, modify and redistribute
  (including commercially) | redistributions and forks must stay GPL v3 | the credit `BVToon / @BVan`
  must be kept, and public works must show `渲染 BVToon / @BVan`. Full text in [`LICENSE`](LICENSE).
* When using MMD assets, follow [`MMD-NOTICE.md`](MMD-NOTICE.md).
