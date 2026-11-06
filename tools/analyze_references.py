#!/usr/bin/env python3
"""Derive the Tahoe colour system from the downloaded reference images.

This is a development tool: it reads the references in assets/references,
computes real dominant colours, luminance ranges, highlights and accent hues,
and writes config/palette-light.json, config/palette-dark.json plus a
human-readable report and swatch strips.  The installer itself only consumes
the generated JSON files; numpy/Pillow are not runtime dependencies.

Usage: python3 tools/analyze_references.py
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "assets/references"
OUT = ROOT / "config"
REPORT = ROOT / "docs/reports/REFERENCE_ANALYSIS.md"


def hexc(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c)) for c in rgb))


def load(path: Path, max_side: int = 1400) -> Image.Image:
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    return im


def arr(im: Image.Image) -> np.ndarray:
    return np.asarray(im, dtype=np.float32)


def region(im: Image.Image, box) -> np.ndarray:
    w, h = im.size
    x0, y0, x1, y1 = box
    crop = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    return arr(crop).reshape(-1, 3)


def lum(pixels: np.ndarray) -> np.ndarray:
    return 0.2126 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.0722 * pixels[:, 2]


def stats(pixels: np.ndarray) -> dict:
    l = lum(pixels)
    p = np.percentile(l, [2, 5, 25, 50, 75, 95, 98])
    mean = pixels.mean(axis=0)
    return {
        "mean": hexc(mean),
        "median": hexc(np.median(pixels, axis=0)),
        "luminance": {
            "p2": round(float(p[0])), "p5": round(float(p[1])),
            "p25": round(float(p[2])), "p50": round(float(p[3])),
            "p75": round(float(p[4])), "p95": round(float(p[5])),
            "p98": round(float(p[6])),
        },
        "darkest_2pct": hexc(pixels[l <= p[0]].mean(axis=0)) if np.any(l <= p[0]) else hexc(mean),
        "brightest_2pct": hexc(pixels[l >= p[6]].mean(axis=0)) if np.any(l >= p[6]) else hexc(mean),
    }


def dominant(pixels: np.ndarray, n: int = 8, sample: int = 120_000) -> list[dict]:
    if len(pixels) > sample:
        idx = np.random.default_rng(7).choice(len(pixels), sample, replace=False)
        pixels = pixels[idx]
    im = Image.fromarray(pixels.astype(np.uint8).reshape(1, -1, 3))
    q = im.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette()[: n * 3]
    counts = Counter(q.getdata())
    total = sum(counts.values())
    out = []
    for index, count in counts.most_common(n):
        rgb = palette[index * 3: index * 3 + 3]
        out.append({"hex": hexc(rgb), "share": round(count / total, 4),
                    "rgb": [int(c) for c in rgb]})
    return out


def vivid_accent(pixels: np.ndarray) -> str | None:
    """Median of the most vivid, bright pixels (real UI accent colour)."""
    rgb = pixels / 255.0
    mx = rgb.max(axis=1)
    mn = rgb.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / mx, 0)
    score = sat * 1.25 + mx
    mask = (sat > 0.40) & (mx > 0.40)
    if mask.sum() < 200:
        return None
    selected = pixels[mask]
    s2 = score[mask]
    cutoff = np.percentile(s2, 99.5)
    top = selected[s2 >= cutoff]
    return hexc(np.median(top, axis=0))


def accents(pixels: np.ndarray, n: int = 4) -> list[dict]:
    rgb = pixels / 255.0
    mx = rgb.max(axis=1)
    mn = rgb.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / mx, 0)
    mask = (sat > 0.55) & (mx > 0.32)
    if mask.sum() < 100:
        mask = (sat > 0.4) & (mx > 0.25)
    selected = pixels[mask]
    if len(selected) == 0:
        return []
    return dominant(selected, n=n, sample=60_000)


def material(base_hex: str, *, alpha: float, blur: int, brightness: float,
             saturation: float, border_hex: str, border_alpha: float,
             highlight_hex: str, highlight_alpha: float,
             shadow_hex: str, shadow_alpha: float, radius: int,
             inset: int = 0) -> dict:
    return {
        "base": base_hex, "alpha": alpha, "blur_sigma": blur,
        "brightness": brightness, "saturation": saturation,
        "border": border_hex, "border_alpha": border_alpha,
        "highlight": highlight_hex, "highlight_alpha": highlight_alpha,
        "shadow": shadow_hex, "shadow_alpha": shadow_alpha,
        "radius": radius, "inset": inset,
    }


def analyse_wallpaper(path: Path) -> dict:
    im = load(path)
    a = arr(im)
    h, w, _ = a.shape
    bands = {
        "top_band": a[: int(h * 0.075)].reshape(-1, 3),
        "upper": a[int(h * 0.075): int(h * 0.35)].reshape(-1, 3),
        "middle": a[int(h * 0.35): int(h * 0.70)].reshape(-1, 3),
        "lower": a[int(h * 0.70): int(h * 0.87)].reshape(-1, 3),
        "bottom_band": a[int(h * 0.87):].reshape(-1, 3),
    }
    return {
        "path": str(path.relative_to(ROOT)),
        "size": list(Image.open(path).size),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "dominant": dominant(a.reshape(-1, 3), n=10),
        "accents": accents(a.reshape(-1, 3)),
        "bands": {name: stats(p) for name, p in bands.items()},
    }


def analyse_regions(path: Path, boxes: dict[str, tuple]) -> dict:
    im = load(path)
    return {name: {"region": [round(v, 3) for v in box], **stats(region(im, box))}
            for name, box in boxes.items()}


def build_mode(mode: str, wall: dict, ui: dict, *, dark: bool) -> dict:
    top = wall["bands"]["top_band"]
    bottom = wall["bands"]["bottom_band"]
    # Prefer accents measured from the UI chrome itself (Control Center tiles,
    # Finder selection), falling back to the wallpaper's vivid pixels.
    accent = ui.get("ui_accent") or (wall["accents"][0]["hex"] if wall["accents"]
                                     else ("#0a84ff" if dark else "#007aff"))
    accent2 = (wall["accents"][1]["hex"] if len(wall["accents"]) > 1
               else accent)
    dom = wall["dominant"]
    highlight = wall["bands"]["middle"]["brightest_2pct"]
    shadow = wall["bands"]["lower"]["darkest_2pct"]

    if dark:
        surface = ui.get("window", {}).get("median", "#1c1c1e")
        toolbar = ui.get("toolbar", {}).get("median", "#161618")
        sidebar = ui.get("sidebar", {}).get("median", "#202024")
        cc = ui.get("control_center", {}).get("median", "#1b2a4a")
        panel = top["median"]
        dock = bottom["median"]
        text = "#f5f5f7"
        text2 = "rgba(235,235,245,0.62)"
        border = "#ffffff"
        tint = accent
        panel_alpha, dock_alpha, cc_alpha = 0.22, 0.26, 0.52
        blur_panel, blur_dock, blur_cc = 20, 22, 28
    else:
        sidebar = ui.get("sidebar", {}).get("median", "#eef3fa")
        surface = ui.get("surface") or sidebar
        toolbar = ui.get("toolbar", {}).get("median", "#ffffff")
        cc = ui.get("control_center", {}).get("median", "#3f9be8")
        panel = top["median"]
        dock = bottom["median"]
        text = "#1d1d1f"
        text2 = "rgba(60,60,67,0.62)"
        border = "#ffffff"
        tint = accent
        panel_alpha, dock_alpha, cc_alpha = 0.30, 0.30, 0.42
        blur_panel, blur_dock, blur_cc = 18, 20, 26

    palette = {
        "schema_version": 1,
        "mode": mode,
        "source_wallpaper": wall["path"],
        "source_wallpaper_sha256": wall["sha256"],
        "colors": {
            "background_top": top["median"],
            "background_bottom": bottom["median"],
            "background_deep": top["darkest_2pct"],
            "surface": surface,
            "surface_raised": sidebar,
            "toolbar": toolbar,
            "control_center": cc,
            "panel_sample": panel,
            "dock_sample": dock,
            "accent": accent,
            "accent_secondary": accent2,
            "accent_soft": _mix(accent, "#ffffff", 0.55 if dark else 0.35),
            "highlight": highlight,
            "shadow": shadow,
            "text_primary": text,
            "text_secondary": text2,
            "border": border,
            "dominant": [d["hex"] for d in dom[:6]],
        },
        "materials": {
            "panel": material(panel, alpha=panel_alpha, blur=blur_panel,
                              brightness=1.06 if dark else 1.02,
                              saturation=1.25, border_hex=border,
                              border_alpha=0.10 if dark else 0.55,
                              highlight_hex=highlight, highlight_alpha=0.16,
                              shadow_hex=shadow, shadow_alpha=0.28,
                              radius=14),
            "dock": material(dock, alpha=dock_alpha, blur=blur_dock,
                             brightness=1.10, saturation=1.35,
                             border_hex=border, border_alpha=0.14 if dark else 0.55,
                             highlight_hex=highlight, highlight_alpha=0.22,
                             shadow_hex="#000000", shadow_alpha=0.35,
                             radius=26, inset=8),
            "control_center": material(cc, alpha=cc_alpha, blur=blur_cc,
                                       brightness=1.04, saturation=1.30,
                                       border_hex=border,
                                       border_alpha=0.12 if dark else 0.45,
                                       highlight_hex=highlight, highlight_alpha=0.18,
                                       shadow_hex="#000000", shadow_alpha=0.42,
                                       radius=28),
            "popover": material(surface, alpha=0.72 if dark else 0.74,
                                blur=22, brightness=1.02, saturation=1.18,
                                border_hex=border, border_alpha=0.10 if dark else 0.5,
                                highlight_hex=highlight, highlight_alpha=0.12,
                                shadow_hex="#000000", shadow_alpha=0.38,
                                radius=16),
            "notification": material(surface, alpha=0.80 if dark else 0.82,
                                     blur=18, brightness=1.0, saturation=1.12,
                                     border_hex=border,
                                     border_alpha=0.10 if dark else 0.55,
                                     highlight_hex=highlight, highlight_alpha=0.10,
                                     shadow_hex="#000000", shadow_alpha=0.32,
                                     radius=20),
            "toolbar": material(toolbar, alpha=0.66 if dark else 0.72,
                                blur=16, brightness=1.02, saturation=1.10,
                                border_hex=border, border_alpha=0.08 if dark else 0.4,
                                highlight_hex=highlight, highlight_alpha=0.08,
                                shadow_hex="#000000", shadow_alpha=0.18,
                                radius=0),
            "sidebar": material(sidebar, alpha=0.55 if dark else 0.55,
                                blur=14, brightness=1.0, saturation=1.05,
                                border_hex=border, border_alpha=0.06 if dark else 0.3,
                                highlight_hex=highlight, highlight_alpha=0.05,
                                shadow_hex="#000000", shadow_alpha=0.10,
                                radius=0),
            "control_tile": material(cc, alpha=0.55 if dark else 0.58,
                                     blur=20, brightness=1.08, saturation=1.28,
                                     border_hex=border,
                                     border_alpha=0.10 if dark else 0.5,
                                     highlight_hex=highlight, highlight_alpha=0.14,
                                     shadow_hex="#000000", shadow_alpha=0.22,
                                     radius=22),
        },
        "text": {"primary": text, "secondary": text2,
                 "on_accent": "#ffffff"},
        "motion": {
            "dock_magnification": {
                "max_scale": 1.34, "falloff_px": 112, "spring_stiffness": 320.0,
                "spring_damping": 26.0, "spring_mass": 1.0,
                "framerate": 60, "duration_ms": 170,
            },
            "panel": {"duration_ms": 220, "easing": "cubic-bezier(0.22,1,0.36,1)"},
            "popover": {"duration_ms": 180, "easing": "cubic-bezier(0.16,1,0.3,1)"},
            "hover": {"duration_ms": 140, "scale": 1.04},
        },
        "luminance": {
            "wallpaper": wall["bands"],
            "ui": {name: {"median": data["median"],
                          "p5": data["luminance"]["p5"],
                          "p95": data["luminance"]["p95"]}
                   for name, data in ui.items()
                   if isinstance(data, dict) and "luminance" in data},
        },
    }
    return palette


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return hexc([ca[i] + (cb[i] - ca[i]) * t for i in range(3)])


def swatch_strip(colors: list[tuple[str, str]], path: Path) -> None:
    width, height, pad = 160, 96, 14
    im = Image.new("RGB", (pad + len(colors) * (width + pad),
                           height + 52 + pad), (28, 28, 30))
    d = ImageDraw.Draw(im)
    for i, (label, colour) in enumerate(colors):
        x = pad + i * (width + pad)
        rgb = tuple(int(colour[j:j + 2], 16) for j in (1, 3, 5))
        d.rounded_rectangle([x, pad, x + width, pad + height], radius=14, fill=rgb)
        d.text((x + 4, pad + height + 8), f"{label}\n{colour}", fill=(235, 235, 240))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    light_wall = analyse_wallpaper(REFS / "wallpaper-light.jpg")
    dark_wall = analyse_wallpaper(REFS / "wallpaper-dark.jpg")

    light_ui = analyse_regions(REFS / "control-center.jpg", {
        "control_center": (0.52, 0.16, 0.86, 0.86),
        "panel": (0.50, 0.12, 0.91, 0.18),
    })
    cc_im = load(REFS / "control-center.jpg")
    light_ui["ui_accent"] = vivid_accent(region(cc_im, (0.53, 0.18, 0.86, 0.62)))
    light_ui.update(analyse_regions(REFS / "app-dock.jpg", {
        "window": (0.14, 0.20, 0.86, 0.80),
        "toolbar": (0.14, 0.20, 0.86, 0.28),
        "sidebar": (0.14, 0.28, 0.27, 0.72),
        "dock": (0.13, 0.87, 0.87, 0.94),
    }))
    finder_im = load(REFS / "finder-dark.jpg")
    dark_ui = analyse_regions(REFS / "finder-dark.jpg", {
        "window": (0.20, 0.145, 0.80, 0.60),
        "toolbar": (0.20, 0.145, 0.80, 0.20),
        "sidebar": (0.20, 0.21, 0.305, 0.60),
        "dock": (0.045, 0.88, 0.955, 0.955),
        "panel": (0.0, 0.0, 1.0, 0.035),
        "selection": (0.205, 0.245, 0.30, 0.278),
    })
    dark_ui["ui_accent"] = vivid_accent(region(finder_im, (0.205, 0.245, 0.30, 0.278)))

    light = build_mode("light", light_wall, light_ui, dark=False)
    dark = build_mode("dark", dark_wall, dark_ui, dark=True)
    (OUT / "palette-light.json").write_text(json.dumps(light, indent=2) + "\n")
    (OUT / "palette-dark.json").write_text(json.dumps(dark, indent=2) + "\n")

    swatch_strip([("background", light["colors"]["background_top"]),
                  ("surface", light["colors"]["surface"]),
                  ("control", light["colors"]["control_center"]),
                  ("accent", light["colors"]["accent"]),
                  ("accent2", light["colors"]["accent_secondary"]),
                  ("highlight", light["colors"]["highlight"])],
                 REFS / "palette-light.png")
    swatch_strip([("background", dark["colors"]["background_top"]),
                  ("surface", dark["colors"]["surface"]),
                  ("control", dark["colors"]["control_center"]),
                  ("accent", dark["colors"]["accent"]),
                  ("accent2", dark["colors"]["accent_secondary"]),
                  ("highlight", dark["colors"]["highlight"])],
                 REFS / "palette-dark.png")

    lines = ["# Reference Analysis", "",
             "Generated from the downloaded Apple/wallpaper references. Colours are",
             "measured, not guessed: dominant colours come from a median-cut",
             "quantisation, bands and regions from real pixel statistics.", "",
             "## Wallpapers", ""]
    for name, data in (("Light", light_wall), ("Dark", dark_wall)):
        lines += [f"### {name} wallpaper", "",
                  f"- File: `{data['path']}`",
                  f"- Dimensions: {data['size'][0]}x{data['size'][1]}",
                  f"- SHA256: `{data['sha256']}`", "",
                  "Dominant colours:", ""]
        lines += [f"- `{d['hex']}` — {d['share'] * 100:.1f}%" for d in data["dominant"]]
        lines += ["", "Top / bottom bands:", "",
                  f"- top median `{data['bands']['top_band']['median']}`, "
                  f"bottom median `{data['bands']['bottom_band']['median']}`",
                  f"- brightest 2% `{data['bands']['middle']['brightest_2pct']}`, "
                  f"darkest 2% `{data['bands']['lower']['darkest_2pct']}`", ""]
    for name, pal in (("Light", light), ("Dark", dark)):
        lines += [f"## {name} material palette", "",
                  "| Role | Colour |", "|---|---|"]
        lines += [f"| {key} | `{value}` |" for key, value in pal["colors"].items()
                  if isinstance(value, str)]
        lines += ["", "| Material | Base | Alpha | Blur σ | Radius |",
                  "|---|---|---|---|---|"]
        for key, mat in pal["materials"].items():
            lines.append(f"| {key} | `{mat['base']}` | {mat['alpha']} | "
                         f"{mat['blur_sigma']} | {mat['radius']} |")
        lines += ["", f"Swatches: `assets/references/palette-{name.lower()}.png`", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT}/palette-light.json, {OUT}/palette-dark.json")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
