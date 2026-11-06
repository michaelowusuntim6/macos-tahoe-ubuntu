# Vendored extensions

| Directory | Upstream | License | Local changes |
|---|---|---|---|
| `tpct-mac-shell@tpct/` | https://github.com/TPCT/tpct-mac-theme | GPL-3.0-or-later | None. Used for the global menu, Apple menu, Finder menus and desktop widgets. |
| `macos-dock@vinnytherobot.github.io/` | https://github.com/vinnytherobot/MacOSDock | MIT (see `extensions/macos-dock@vinnytherobot.github.io/LICENSE`) | Spring magnification integrator (`lib/magnification.js`), configurable spring settings in the schema, configurable dock blur sigma (`lib/dockManager.js`). |

Nothing here modifies `metadata.json` `shell-version` lists. Every bundled
extension declares GNOME 50 support upstream and is validated in an isolated
nested GNOME Shell before installation.
