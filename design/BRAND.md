# Content Digest brand

The mark is called **Stack to Line**. Three stacked bars on the left collapse into a single bar on the right: many things saved, one summary returned. It states the function, reduction, not the medium, which is why it is not a page or a folder.

Everything here inherits `design/tokens.json` and the account palette. Content Digest shares crimson with ledge by design; the symbol, not the colour, carries identity.

---

## Construction

The symbol is drawn on a **96 unit grid**, stroke 10, round caps.

| Element | Geometry |
|---|---|
| Input bars | (16,30) to (38,30); (16,48) to (46,48); (16,66) to (38,66) |
| Output bar | (58,48) to (80,48) |
| Optical centre | 48, 48 |

The outer input bars are shorter than the middle one, so the stack's right edge points at the output. The output bar is the only accent element.

---

## Colour

Tokens only.

| Context | Ground | Input bars | Output bar |
|---|---|---|---|
| Light | `bg` `#F7F5F2` | `text` `#1C1B1D` | `accent` `#BD4753` |
| Dark | `bg` `#1C1B1D` | `text` `#F7F5F2` | `accent` `#E78892` |

---

## Clear space and minimum sizes

Clear space on all four sides equals the stroke width (10 grid units).

| Asset | Minimum |
|---|---|
| Symbol, colour | 16 px |
| Symbol, monochrome | 20 px. Below that the middle bar and the output bar fuse |
| Horizontal lockup | 200 px wide |

The extension icons ship at 16, 48, and 128 on the paper tile, which keeps the mark legible on both light and dark toolbars.

---

## Files

```
design/
  logo/       symbol light, dark, mono black, mono white; tiles; wordmark; lockups
  github/     readme banners 1400x400, social preview 1280x640, avatar 400x400
  web/        og 1200x630, favicon set, apple touch icon, PWA icons
extension/
  icon16.png, icon48.png, icon128.png   regenerated from the same geometry
```

Filenames carry pixel dimensions for raster deliverables.

---

## Do not

1. Do not stretch, rotate, or shear the mark.
2. Do not recolour outside the tokens above.
3. Do not add shadows, gradients, glows, or strokes.
4. Do not equalize the input bars; equal bars read as a menu icon.
5. Do not drop the output bar. Without it the mark is a hamburger menu.
6. Do not rebuild the wordmark in live type; it is outlined geometry.

---

## Rebuilding the assets

Every file is generated from the same 96 unit geometry. If the mark changes, regenerate rather than hand-editing individual sizes.

*Mark designed 2026-07-28. Built by Claude (Anthropic), directed by Shashank Karpal.*
