# Final Report — macOS Tahoe Liquid Glass for Ubuntu

Completed: 2026-11-06. Project version `1.1.2`.

This report records the finished desktop, the measured design system, the
automation framework, verification results and the honest remaining limits.

---

## 1. Original operating system

- Ubuntu 26.04.1 LTS (*resolute*), kernel 7.0.0-38-generic, x86_64.
- GNOME Shell 50.1, Wayland (`ubuntu:GNOME`), 1366×768.
- Toshiba Satellite Pro C850-1ER; Intel Core i5-3210M (2C/4T); Intel HD
  Graphics 4000 (Ivy Bridge GT2, i915); 15,359 MB usable RAM; SSD.

## 2. Original GNOME configuration (audited before changes)

- GTK/icon theme `Yaru-dark`; cursor `Yaru`; font `Ubuntu Sans 11`;
  color scheme `prefer-dark`; accent `orange`.
- Ubuntu Dock: left, fixed, extend-height, autohide+intellihide, icon size 48,
  80 % background opacity.
- Window buttons right (`:minimize,maximize,close`).
- Enabled extensions: ding, ubuntu-dock, tiling-assistant,
  snapd-search-provider, web-search-provider, gsconnect. Installed but disabled:
  Ubuntu AppIndicators, snapd-prompting.
- The full pre-install state (dconf, package list, fonts, extension list,
  wallpaper paths, copied user files) is preserved in
  `backups/20261105T184936Z_pre-install/`.

## 3. Final visual configuration

- **Panel**: 30 px translucent Tahoe-blue/navy glass, inset top highlight,
  bottom light border, static backdrop blur (σ20), white adaptive text, Apple
  menu, focused-app global menus, Finder menus, right-aligned clock, no
  Activities pill.
- **Dock**: floating, centered, 26 px-radius glass pill with configurable
  MacOSDock blur (σ18 lightweight), spring magnification, bounce, running dots,
  app-launcher grid, Trash, autohide/intellihide.
- **Window controls**: red/yellow/green on the left; verified in GTK3, GTK4 and
  libadwaita (GNOME Text Editor).
- **Control Center**: tinted glass (50–56 % opacity over real blur), 28 px
  radius, grouped glass tiles, vivid measured accent, functional Wi-Fi,
  Bluetooth, sound, brightness, battery, power mode, dark style, DND, GSConnect.
- **Popovers/menus/notifications**: distinct lighter glass materials with
  highlights/shadows; notifications are frosted cards.
- **GTK**: TPCT Mac light/dark plus generated Liquid Glass layers with a
  `prefers-color-scheme` dark media query. Windows get large radii, layered
  headerbar/sidebar tones, edge highlights and shadows. GTK cannot blur the
  desktop behind a window; this is stated rather than faked.
- **Nautilus**: Finder-style rounded window, sidebar, toolbar, icon view,
  WhiteSur icons.
- **Spotlight**: `Super+Space`, Rofi 2.0 glass theme, palette-derived accents,
  keyboard navigation, XWayland backend.
- **Wallpapers**: real Tahoe light/dark originals (downscaled to 2560²),
  auto-selected by mode; generated originals as offline fallback.
- **Typography**: Inter Variable (UI/documents/titlebar), Ubuntu Sans Mono.
- **Icons/cursors**: WhiteSur dark/light + WhiteSur cursors.
- **Widgets**: clock, calendar, world clock, battery (curated default layout).

## 4. Selected upstream projects

TPCT Mac Theme (GPL-3.0), WhiteSur icons/cursors (GPL-3.0), Inter (OFL),
User Themes, Blur my Shell (GPL-3.0), MacOSDock (MIT, vendored/patched),
Rofi (MIT), Ubuntu extension stack. Exact commits/versions and checksums are
pinned in `manifests/components.lock.json`; rationale in
`docs/reports/COMPATIBILITY_REPORT.md` and `config/extension-manifest.json`.

## 5. Installed themes

`TPCT-Mac-Dark`, `TPCT-Mac-Light` with generated Liquid Glass shell layers;
GTK4/libadwaita override with light/dark media query; GTK3 managed override.

## 6. Installed icons

`WhiteSur-dark`, `WhiteSur-light` (built tarballs + source for offline rebuild).

## 7. Installed cursor

`WhiteSur-cursors` (24 px).

## 8. Installed extensions

Enabled and verified active in the isolated shell:

- `user-theme@…` (Shell theme)
- `tpct-mac-shell@tpct` (global menu/widgets)
- `blur-my-shell@aunetx` (real blur)
- `macos-dock@vinnytherobot.github.io` (dock, vendored)

Preserved: Desktop Icons NG, Tiling Assistant, GSConnect, AppIndicator support,
snapd prompting/search, web search, Ubuntu Dock (installed, disabled).

## 9. Disabled or replaced extensions and reasons

- **Ubuntu Dock** disabled and blacklisted in `disabled-extensions` (Ubuntu's
  session mode force-enables it, so removing it from enabled-extensions alone is
  not enough). Replaced by MacOSDock because Dash to Dock cannot do
  magnification/spring physics. The extension remains installed for instant
  fallback; MacOSDock covers launching, running indicators, autohide,
  click-to-minimize, previews (optional) and keyboard shortcuts.
- Dash2Dock Animated rejected after it failed to render in the isolated shell.
- No existing functionality was silently disabled.

## 10. Application customisations

macOS display names for 13 stock apps (Finder, System Settings, App Store,
TextEdit, Preview, Terminal, Activity Monitor, Disk Utility, Storage, Clock,
Font Book, Character Viewer, QuickTime Player); Finder-style Nautilus; Ptyxis
macOS palette and system font; Safari-style Firefox userChrome only in the full
profile; Rofi Spotlight; Terminal/Text Editor inherit the GTK glass.

## 11. Global menu

TPCT `tpct-mac-shell` provides the Apple menu, focused GTK app menus over
GMenuModel/D-Bus, dbusmenu for XWayland apps through a built-in
`com.canonical.AppMenu.Registrar`, Finder menus on the desktop and macOS
fallback menus. Native Wayland Qt apps cannot export menus (no protocol);
they receive the standard macOS menu set. Verified in screenshots with Finder
and Text Editor focused.

## 12. Spotlight

Rofi 2.0 draun mode, `Super+Space` custom keybinding, palette-derived glass
theme, icons, keyboard navigation, row selection. Rofi uses XWayland because
GNOME/Mutter does not implement wlr-layer-shell; the wrapper sets
`WAYLAND_DISPLAY` off and `GDK_BACKEND=x11`. Input-source switching moved to
Alt+Shift. Verified interactively on the live desktop.

## 13. Dock implementation

Vendored MacOSDock v18 (MIT), patched:

- damped spring: `m = 1.0`, `k = 320`, `c = 26` (underdamped, ~0.4 s settle,
  subtle overshoot), integrated per icon at 60 Hz;
- adjustable falloff (125 px) and max scale (1.45);
- configurable `dock-blur-sigma` (18 lightweight / 22 full);
- custom Liquid Glass stylesheet applied through the extension’s own
  `custom-css` mechanism;
- macOS Trash launcher appended to favourites; app-grid launcher; running dots;
  bounce; autohide; drag reorder; previews disabled for performance.

## 14. Performance

Real measurements in `docs/reports/PERFORMANCE_REPORT.md`:

- Nested software-rendered shell: minimal 245.9 MB / 6.5 % CPU; full glass stack
  278.8 MB / 9.0 % CPU (6 s idle samples).
- Live transition state: 3,098 MB RAM used, shell 390.6 MB / 7.6 % CPU.
- Blur static-cached; popup blur only while open; dock blur limited to the dock;
  no duplicate dock/daemon.

## 15–16. Errors encountered and fixes

- Rollback used typed instead of raw GVariant text → added `gsettings_set_raw`.
- EGO extension schemas are shipped uncompiled → compile them on every extension
  install path.
- Multi-schema extensions (Blur my Shell) were not found by schema-dir lookup →
  probe schema candidates instead of filename matching.
- `dpkg-deb` does not create missing parent directories → create runtime dir and
  check every extraction.
- Rofi Wayland layer-shell failure on GNOME → XWayland wrapper.
- Rofi theme parser: `border: 1px solid rgba()` invalid; split border/border-color
  and remove spaces in rgba values.
- GTK3 managed markers nested on repeat installs → distinct wrapper markers and
  strip upstream markers; idempotency tests added.
- GTK4 dark headerbar stayed white → combined media-query stylesheet.
- 6016² Apple wallpapers rendered black / too heavy → downscale to 2560² with
  ImageMagick; added fallback JPEGs.
- DING’s desktop window painted over the wallpaper in the *nested test shell* →
  excluded from visual captures (live rendering is unaffected).
- Live dconf was briefly modified by an early nested test → private-bus settings
  enforced; restored immediately. Recorded as a testing lesson.
- Panel text contrast was wrong with pale generated wallpapers → panel text is
  derived from the measured wallpaper luminance; real Tahoe wallpaper uses white
  text.
- Spring settings were hard-coded → exposed as schema/`motion.json` parameters.
- Ubuntu's session mode kept force-enabling `ubuntu-dock`, producing a second
  static taskbar alongside MacOSDock. Added the `disabled-extensions` blacklist
  to the installer and appearance daemon; verification now checks the live state.
- GTK rejects `!important`; the popover reset was silently discarded, leaving a
  double frame around context menus. Removed `!important` from the GTK layer and
  validated with a `Gtk.PopoverMenu` reproduction; regression test added.
- Dock auto-hide waited for Shell motion events; Wayland sends pointer events
  over app windows to the client, so the dock stayed visible. Added a 100 ms
  pointer poll while shown and a configurable `auto-hide-delay` (550 ms).
- MacOSDock deleted its cached custom stylesheet while GNOME Shell still held a
  reference, making User Themes fail with a missing-file error. Cache files are
  now retained.

## 17. Automation architecture

`install.sh` → Python engine phases: preflight/compatibility, backup, assets,
extensions, spotlight, desktop, apps, verify, report. JSON state records phases,
component status, applied-settings journal, installed extensions/packages and
asset checksums. Pristine backup is reused by repairs. Rollback restores only
journaled values and owned files. Downloads use HTTPS, retries, atomic temp files
and SHA-256. Offline mode uses bundled assets; no unverified substitution.

Supporting commands: `uninstall.sh`, `verify.sh [--headless]`, `repair.sh`,
`export.sh`, `scripts/{bootstrap,configure,restore,diagnostics}.sh`.

## 18. Installer test results

- **90 unit/integration tests pass** (`python3 -m unittest discover -s tests -t tests`),
  covering detection, compatibility, manifests/checksums, backup, rollback,
  idempotency, archive safety, offline bundles, export, uninstall safety.
- **Fresh-install simulation passes** (`tests/fresh_sim.sh`): exports the release,
  extracts it, runs the offline installer twice in a private HOME/XDG/D-Bus
  environment, checks all artefacts, dconf state, extension uniqueness and machine
  isolation. No live configuration is touched.
- **Live verification: 91 checks passed, 0 failed**, 2 expected warnings
  (Blur my Shell and MacOSDock activate at next login).
- **Headless production captures**: all four managed extensions ACTIVE; dark,
  light, both Control Centers and a GTK4 window captured with no JS errors.

## 19. Portable export

`./export.sh` produces `releases/macos-tahoe-ubuntu-v1.1.2.tar.gz`,
`.sha256` and `-manifest.json` (SHA-256 `91942eee4f1ac1e1c08546c1a251ea17a63687671473009c7589f1d4fd68c8a8`). Apple-proprietary wallpapers/references are
excluded by default and re-downloaded/verified online at install; if absent,
the generated fallback wallpapers are installed. Copy the release **off the
machine** before reinstalling Ubuntu.

## 20. Fresh-install execution

```bash
tar xzf macos-tahoe-ubuntu-v1.1.2.tar.gz
cd macos-tahoe-ubuntu-v1.1.2
sha256sum -c ../macos-tahoe-ubuntu-v1.1.2.sha256
./install.sh
# log out and back in
```

## 21. Recovery

`./uninstall.sh` → restores the pristine dconf snapshot and saved user files,
removes only project-owned assets/extensions/launchers, re-enables nothing
without evidence. `./install.sh --restore` performs the same restore.
`./repair.sh` diagnoses and re-applies managed components without duplicating
anything. `./install.sh --resume` continues an interrupted transaction.

## 22. Manual activation

One logout/login (or reboot) is required for GNOME Shell to load the new Shell
theme and the two newly enabled Shell extensions. No other manual step exists.
The Light/Dark daemon starts automatically at login.

## 23. Remaining limitations (honest)

- Apple’s proprietary Liquid Glass renderer is not reproduced. The closest
  supportable approximation is used: real compositor blur, measured tints,
  edge highlights, layered shadows and distinct material alphas.
- GNOME/St CSS has no backdrop-filter or refraction shader; gradients in St CSS
  are ignored by GNOME 50, so solid translucent tints plus blur are used.
- GTK applications cannot blur the desktop behind their windows.
- Native Wayland Qt apps cannot export menus; standard macOS menus are shown.
- Snap/Flatpak sandboxing may prevent some apps from reading user themes.
- GDM/login screen theming is intentionally not applied system-wide (requires
  root and modifies system files); the lock screen follows the Shell theme.
- The final post-login GPU performance sample could not be taken without
  terminating the running session; instructions to record it are provided.
- Apple wallpapers are personal-use only and excluded from default releases.
