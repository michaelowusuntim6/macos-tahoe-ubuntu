# Licences and attribution

This project combines original code and generated artwork with third-party
components. Each component keeps its own licence.

## Project code and generated artwork

- Engine, installer, verifier, tests, tools, configuration and the generated
  glass CSS: **GPL-3.0-or-later** (see `LICENSE`). GPL is required because the
  distributed bundle includes the GPL-licensed theme and icon assets below.
- Generated wallpapers (`assets/wallpapers/tahoe-*.png`,
  `assets/wallpapers/fallback/*.jpg`) are produced by
  `tools/make_wallpapers.py` and released under **CC0-1.0**.
- Measured palettes (`config/palette-*.json`) and the analysis report are
  original data produced from the references; they are released under
  **CC0-1.0**. The reference images themselves are not covered by that licence.

## Theme, icons and cursors

| Component | Upstream | Licence | Notes |
|---|---|---|---|
| TPCT Mac Theme | https://github.com/TPCT/tpct-mac-theme | **GPL-3.0-or-later** | Theme SCSS/CSS and the `tpct-mac-shell` extension, vendored. |
| WhiteSur GTK Theme | https://github.com/vinceliuice/WhiteSur-gtk-theme | **MIT** | Evaluated; the project uses TPCT for GTK/Shell, not WhiteSur GTK. |
| WhiteSur Icon Theme | https://github.com/vinceliuice/WhiteSur-icon-theme | **GPL-3.0** | Built icon themes bundled as tarballs; source tarball included. |
| WhiteSur Cursors | https://github.com/vinceliuice/WhiteSur-cursors | **GPL-3.0** | Pre-built cursor set bundled. |
| Inter font | https://github.com/rsms/inter (via google/fonts) | **OFL-1.1** | Variable font bundled. |

Full licence texts are distributed by the upstream projects; the GPL-3.0 text is
included in this repository as `LICENSE`. The MIT licence for MacOSDock is in
`extensions/macos-dock@vinnytherobot.github.io/LICENSE`.

## GNOME extensions

| Extension | Upstream | Licence | Use |
|---|---|---|---|
| User Themes | GNOME / extensions.gnome.org | GPL-2.0-or-later | Loads the Shell theme. |
| Blur my Shell | https://github.com/aunetx/blur-my-shell | GPL-3.0 | Real backdrop blur for the panel and popovers. |
| MacOS Dock | https://github.com/vinnytherobot/MacOSDock | **MIT** | Floating dock with magnification; vendored and patched (spring physics, configurable blur sigma). |
| TPCT Mac Shell | https://github.com/TPCT/tpct-mac-theme | **GPL-3.0-or-later** | Global menu, Apple menu, Finder menus, widgets. |
| Ubuntu Dock | Canonical / Ubuntu | GPL-3.0 | Installed but disabled; kept as a fallback. |

Other Ubuntu extensions (Desktop Icons NG, GSConnect, AppIndicator support,
Tiling Assistant, Snap providers, Web Search) are used unmodified under their
respective upstream licences.

## Applications and libraries

| Component | Licence | Notes |
|---|---|---|
| Rofi 2.0 | **MIT** | Spotlight backend; installed via APT when available, otherwise unpacked from the signed Ubuntu `.deb` set into `runtime/rofi/` without root. |
| libxcb / xcb-util / xkbcommon families | MIT / X11 | Runtime libraries required by the private Rofi copy; bundled `.deb`s from the Ubuntu archive. |

## Apple wallpapers and reference images — proprietary

The following files are **not** part of the project's open-source licence and are
**excluded from portable releases by default**:

- `assets/wallpapers/apple/tahoe-light.jpg`
- `assets/wallpapers/apple/tahoe-dark.jpg`
- `assets/references/wallpaper-light.jpg`
- `assets/references/wallpaper-dark.jpg`
- `assets/references/control-center.jpg`
- `assets/references/app-dock.jpg`
- `assets/references/finder-dark.jpg`

They are Apple Inc. marketing/wallpaper material, downloaded from the user-provided
URLs for **personal, local use only**. The reference screenshots are used solely
to measure colours and luminance; they are never rendered by the installed
desktop. The wallpapers can be downloaded and verified at install time in online
mode. The project claims no affiliation with Apple and does not reproduce
Apple's proprietary Liquid Glass rendering engine.

If you redistribute this project, remove these files or obtain permission from
the rights holder. `./export.sh` excludes them unless
`--include-proprietary` is explicitly passed, and the maintainer accepts no
responsibility for such redistribution.

## Trademarks

macOS, Mac, Finder, Spotlight, Control Center and related names are trademarks
of Apple Inc. This is an independent, unaffiliated customization project.
