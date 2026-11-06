# Changelog

## 1.1.2 — 2026-11-06 — Reliable idle auto-hide

- **Auto-hide no longer depends on pointer movement.** On Wayland, motion
  events over application windows do not reach the Shell stage, so the dock
  could stay visible until the pointer touched a shell surface. The dock now
  polls the pointer while shown and hides after a configurable delay even when
  the pointer is stationary.
- Added `auto-hide-delay` (default 550 ms) to the MacOSDock schema, driven by
  `config/motion.json` (`dock.auto_hide_delay_ms`), and verified live.
- MacOSDock now keeps its cached custom stylesheets instead of deleting them;
  deleting a stylesheet still referenced by GNOME Shell made User Themes enter
  an ERROR state after theme/dock reloads.
- Tests: 90 (auto-hide polling and configuration regressions added).
- Rebuilt portable release.

## 1.1.1 — 2026-11-06 — Field-test fixes (dock + menus)

- **Duplicate dock fixed.** Ubuntu's session mode (`/usr/share/gnome-shell/modes/ubuntu.json`)
  force-enables `ubuntu-dock` regardless of the enabled-extensions list. The
  installer and appearance daemon now also add it to `disabled-extensions`
  (the correct session-mode blacklist) and verify the live extension state, not
  just the preference list. Only MacOSDock remains; the static Ubuntu taskbar no
  longer appears.
- **Context-menu double frame fixed.** GTK's CSS parser rejects `!important`;
  the generated GTK layer used it on the popover reset, so the rule was silently
  discarded and the outer popover actor painted a second box around menus. The
  GTK layer no longer uses `!important`; a regression test enforces this.
- Verification now distinguishes "blacklisted but still loaded until logout"
  from a genuine second-dock failure.
- Rebuilt portable release; tests now 88.

## 1.1.0 — 2026-11-06 — Liquid Glass and motion

### Desktop
- Downloaded and validated the real macOS Tahoe light/dark wallpapers and Apple
  UI references; added original wallpapers as offline fallbacks.
- Added measured colour pipelines: `tools/analyze_references.py`,
  `config/palette-light.json`, `config/palette-dark.json`,
  `docs/reports/REFERENCE_ANALYSIS.md`, swatch strips.
- Added generated Liquid Glass layers for GNOME Shell, GTK3/GTK4/libadwaita,
  the dock and Spotlight (`tools/generate_glass.py`).
- Replaced the static Ubuntu Dock with vendored MacOSDock and a damped-spring
  magnification integrator; configurable stiffness/damping/mass, falloff,
  framerate, bounce.
- Added real backdrop blur: Blur my Shell for the panel and popovers, and
  Shell.BlurEffect for the dock (σ configurable, reduced on HD 4000).
- Added a Light/Dark appearance daemon that coordinates GTK, icons, Shell theme,
  dock glass and blur; installed as an autostart service.
- Added macOS Trash launcher (MacOSDock has no built-in trash).
- Added material-specific glass treatments for panel, dock, Control Center,
  popovers, notifications, OSD, toolbars and sidebars.
- Fixed light-panel contrast, GTK4 dark-mode headerbar, and GNOME 50 St CSS
  gradient incompatibility (solid tints + real blur instead).
- Downscaled 6016² Apple wallpapers to 2560² for the Intel HD 4000.

### Engineering
- New config: `config/motion.json`, palette files, `manifests/assets.json`
  entries for Apple/fallback wallpapers and the vendored dock.
- `extension_manager` now compiles extension GSettings schemas on all install
  paths; fixes multi-schema extensions (Blur my Shell).
- `utilities` supports XDG_DATA_HOME/XDG_CONFIG_HOME throughout.
- Pristine pre-install backup is recorded once and reused by repairs.
- Exporter excludes proprietary Apple assets by default
  (`--include-proprietary` opt-in).
- Verification grew to 91 live checks (glass layers, GTK media query,
  appearance runtime, dock spring, dock glass, BLUR settings, dock uniqueness).
- Headless harness mirrors the live dconf, queries all managed extensions,
  reports errors, captures screenshots and measures CPU/RSS.
- Fixed `install_dir` schema compilation, Rofi extraction parent creation,
  Rofi Wayland fallback, GTK3 marker idempotency and font detection.
- Test suite expanded to 86 tests, all passing; fresh-install simulation passes
  offline with fallback wallpapers.

## 1.0.0 — 2026-11-05 — Initial transformation and automation

- Ubuntu 26.04 / GNOME 50 audit and compatibility gate.
- TPCT Mac theme (GTK3/GTK4/libadwaita/Shell) + global menu + widgets.
- WhiteSur icons and cursors, Inter font, generated Tahoe wallpapers.
- Bottom floating translucent dock, traffic lights, Spotlight (Rofi),
  Control Center, Finder-style Files, macOS display names.
- Backup, transactional state, rollback, repair, verify, offline mode,
  portable export and fresh-install simulation.
- Reports, tests, documentation.
