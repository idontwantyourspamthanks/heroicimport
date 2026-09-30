# heroicimport

Fetch [SteamGridDB](https://www.steamgriddb.com/) artwork for Heroic Games
Launcher shortcuts in Steam.

Heroic can add its games to Steam as non-Steam shortcuts, but it doesn't
supply the grid/hero/logo artwork. This tool reads Steam's `shortcuts.vdf`
directly, finds the entries launched through Heroic, and downloads the
missing artwork into Steam's `grid/` folder — no re-importing, no
dependencies beyond Python 3.

## Requirements

- Python 3.8+ (standard library only)
- A SteamGridDB API key: create one at
  <https://www.steamgriddb.com/profile/preferences/api>

Provide the key either as an environment variable:

```bash
export SGDB_API_KEY=your_key_here
```

or in a file:

```bash
mkdir -p ~/.config/heroicimport
echo "your_key_here" > ~/.config/heroicimport/api_key
```

## Usage

```bash
# List Heroic shortcuts and their artwork status (no downloads)
python3 heroicimport.py --dry-run

# Download missing artwork
python3 heroicimport.py

# Re-download all artwork, even where complete
python3 heroicimport.py --force
```

Restart Steam afterwards so it picks up the new artwork.

## How it works

1. Locates `shortcuts.vdf` under the usual Steam userdata paths
   (native and Flatpak).
2. Parses the binary VDF format with a built-in parser and keeps shortcuts
   whose launch options reference `heroic://launch`.
3. Uses the `appid` stored in the VDF to name artwork files
   (`<appid>p.jpg`, `<appid>.jpg`, `<appid>_hero.jpg`, `<appid>_logo.jpg`)
   in the user's `grid/` folder, matching Steam's conventions.
4. Searches SteamGridDB by game name and downloads the highest-scored
   static image for each missing artwork type. Downloads are atomic
   (temp file + rename) and per-game failures are skipped, not fatal.
