[中文](PUBLISH.md) ｜ **English** ｜ [日本語](PUBLISH.ja.md)

# Publishing steps

## 1. Create the repo and push

```bat
cd github\BV-Toon
git init
git add .
git commit -m "BV-Toon 1.5.0: one-click MMD toon shading + enforced credit watermark"
git branch -M main
git remote add origin https://github.com/<your-name>/BV-Toon.git
git push -u origin main
```

## 2. Create the release

**Releases → Draft a new release → tag `v1.5.0`** → paste the contents of
[`RELEASE-1.5.0.md`](RELEASE-1.5.0.en.md) into the description → attach
`dist\BV-Toon-1.5.0.zip` (its top level is `BV-Toon/`, so users can install it directly).

## 3. Suggested repository settings

* **About**: `One-click toon shading for MMD: native materials, toon-ramp lighting, edge preview, eye shadow, blush, bloom`
* **Topics**: `blender-addon` `mmd` `toon-shading` `cel-shading` `mmd-tools` `eevee`
* **License**: custom use license (GitHub shows "Unknown license" — that is expected; terms are in `LICENSE`)

## 4. Docs are trilingual

Every document has a Chinese (`.md`), English (`.en.md`) and Japanese (`.ja.md`) version with a
language switcher at the top:

| Doc | Chinese | English | Japanese |
|---|---|---|---|
| Home | `README.md` | `README.en.md` | `README.ja.md` |
| Release notes | `RELEASE-1.5.0.md` | `RELEASE-1.5.0.en.md` | `RELEASE-1.5.0.ja.md` |
| MMD etiquette | `MMD-NOTICE.md` | `MMD-NOTICE.en.md` | `MMD-NOTICE.ja.md` |
| Publishing steps | `PUBLISH.md` | `PUBLISH.en.md` | `PUBLISH.ja.md` |
| Terms of use | `LICENSE` (all three languages in one file) | | |

## 5. What must NOT go in

* Any third-party add-on content (**paid add-ons' code and assets — fine for private use, never to publish**)
* Local build artefacts (`dist/`, `_scratch/`, `tests/_out/`, `.blend1`, `__pycache__`)
* Test renders made with third-party MMD models (those models have their own licenses)