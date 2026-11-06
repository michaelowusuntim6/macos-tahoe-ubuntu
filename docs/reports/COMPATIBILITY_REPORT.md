# Compatibility Report

Target machine audited on 2026-11-05/06; values are re-detected on every run.

## Detected system

- Ubuntu 26.04.1 LTS (*resolute*), GNOME Shell 50.1, Wayland.
- Toshiba Satellite Pro C850-1ER, Intel Core i5-3210M, Intel HD Graphics 4000
  (i915), 15,359 MB RAM, 1366×768, ~44 GB free.
- Result: **validated** — profile `ubuntu-26.04-gnome50`.
- Recommended install profile: **lightweight** (Ivy Bridge GPU rule).

## Support policy

- Validated: Ubuntu 26.04.x, GNOME 50, Wayland/X11.
- Untested: another Ubuntu point release with GNOME 50 → refused unless
  `--allow-untested` after review.
- Unsupported: other GNOME majors or distributions → refused unless the
  explicit `--force-unsupported` flag is given.
- Extensions must declare the detected GNOME major in `metadata.json`; metadata
  is never edited to force compatibility.

## Selected components

| Component | Version | Why |
|---|---|---|
| TPCT Mac theme + `tpct-mac-shell` | commit `4407330…` | Coherent GTK3/GTK4/libadwaita/Shell theme; global menu, Apple menu, Finder menus, widgets; GNOME 50 metadata. |
| WhiteSur icons | commit `73d8040…` | Broad application/folder coverage. |
| WhiteSur cursors | commit `e190baf…` | Matching cursor set. |
| Inter variable font | 4.1 (OFL) | Closest freely distributable UI font to SF Pro. |
| User Themes (EGO v79) | GNOME 50 | Loads the Shell theme. |
| Blur my Shell (EGO v77) | GNOME 50 | Real backdrop blur; panel/popup static caching. |
| MacOSDock v18 (MIT) | GNOME 45–50 | Floating dock with magnification; vendored and patched with damped-spring physics and configurable blur sigma. |
| Rofi 2.0 | Ubuntu | Spotlight backend; XWayland fallback (GNOME lacks wlr-layer-shell). |
| Ubuntu Dock | system | Kept installed but disabled; replaced by MacOSDock. |

## Rejected candidates

- **Dash2Dock Animated (dash2dock-lite)** — GNOME 50 metadata present, but it did
  not render a dock in the isolated GNOME 50 nested shell. MacOSDock rendered,
  magnified and exposed a clean custom-CSS hook, so it was selected after
  re-evaluation.
- **Search Light** — published metadata stops at GNOME 49; forcing metadata is
  forbidden. Spotlight uses Rofi.
- **fildem / X11 global-menu implementations** — X11-only; the session is Wayland.
- **Blur my Shell dash component** — not used with MacOSDock (own
  `Shell.BlurEffect`), avoiding double blur.
- **Forcing extension metadata** — never done.

## Security review

- Upstream install scripts are not executed. TPCT install logic is reimplemented;
  only theme CSS/source and the extension directory are used.
- MacOSDock is MIT, vendored and diffable; `metadata.json` untouched.
- EGO extension zips are pinned by `version_tag` and SHA-256 verified.
- HTTPS only, retries/timeouts, temporary files, checksum validation; no
  unverified substitutions.
- No PPAs, repository replacement, `apt upgrade`, or sudo bypass. Per-user
  assets throughout; Rofi is unpacked from signed Ubuntu `.deb`s when APT is
  unavailable.
