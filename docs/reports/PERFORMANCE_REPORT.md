# Performance Report

Measurements taken on the target machine with real `/proc` samples. No values
are estimated.

## Machine

- Toshiba Satellite Pro C850-1ER, i5-3210M (2C/4T), Intel HD Graphics 4000
  (Ivy Bridge GT2, i915), 15,359 MB usable RAM, 1366×768, SSD.
- Ubuntu 26.04.1, GNOME Shell 50.1, Wayland.

## Live session (pre-login after installation)

The live session was measured while the **previous** GNOME Shell was still
running. GTK/dock settings are already applied, but the new Shell extensions
(Blur my Shell, MacOSDock, TPCT shell theme) only load at the next login. These
numbers therefore describe the transition state, not the final shell.

| Metric | Before repair (baseline sample) | After install (live) |
|---|---|---|
| RAM used | 2,837 MB | 3,098 MB |
| gnome-shell RSS | 330.3 MB | 390.6 MB |
| gnome-shell CPU (3 s idle) | 4.6 % | 7.6 % |
| Process count | 242 | 266 |
| gjs processes | 4 | 4 |

The increase includes GTK theme loading, appearance daemon, Rofi runtime, and
normal user activity; the extension stack was not loaded yet.

## Isolated nested Shell — glass stack cost (software rendering, worst case)

Both runs use a private D-Bus/dconf session, the same 2560² wallpaper, a
1366×768 virtual monitor, 6-second /proc samples of the nested `gnome-shell`
process. The production run enables all 11 extensions plus Blur my Shell panel +
popup blur and MacOSDock with the pointer held over a magnified icon. The
minimal run enables only User Themes + TPCT + the test helper.

| Metric | Minimal shell | Full glass/motion stack | Delta |
|---|---|---|---|
| gnome-shell RSS | 245.9 MB | 278.8 MB | +32.9 MB |
| gnome-shell CPU (idle) | 6.5 % | 9.0 % | +2.5 pp |

Software rendering (no GPU acceleration in the nested compositor) overstates the
GPU-side cost. On the live compositor, backdrop blur is GPU work; the CPU
magnification poll is event-free but runs at 60 Hz while the dock is visible.

## Optimisations applied

- Blur my Shell `static-blur=true` for panel and popups: blur is cached and only
  recomputed when the backdrop changes, not every frame.
- Dock blur is a single `Shell.BlurEffect` limited to the dock rectangle
  (σ18 lightweight / σ22 full), not a full-screen effect.
- Popup blur exists only while a popup is open (Control Center, menus).
- No Electron apps, no duplicate dock, no extra daemon loop; the appearance
  coordinator blocks on `gsettings monitor` and reacts to events.
- Wallpapers downscaled 6016² → 2560² to avoid excessive texture memory on the
  HD 4000 and a rendering failure observed with the originals in a nested shell.
- Lightweight profile automatically selected for this GPU; full profile available
  with `--profile full`.
- Magnification spring is one integrator per icon, 60 Hz only while the dock is
  visible; no continuous animation when idle.

## Disk usage

| Path | Size |
|---|---|
| `~/.local/share/themes` | 0.3 MB |
| `~/.local/share/icons` | 15.0 MB |
| `~/.local/share/fonts` | 0.8 MB |
| `~/.local/share/backgrounds` | 3.8 MB |
| project (bundled assets, tests, releases) | 68.8 MB |

## How to reproduce

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,".")
from engine import performance, utilities as u
print(performance.snapshot(3.0))
PY
```

`reports/baseline-performance.json`, `reports/final-performance.json` and
`reports/headless-performance.json` hold the raw samples.

## Limitation

The final post-login live measurement could not be taken automatically because
the installer must not terminate the running desktop session. After logging out
and back in, run the snippet above to record the final GPU-accelerated state.
