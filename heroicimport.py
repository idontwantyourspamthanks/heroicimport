#!/usr/bin/env python3
"""Fetch SteamGridDB artwork for Heroic Games Launcher shortcuts in Steam.

Reads Steam's shortcuts.vdf, finds entries launched through Heroic, and
downloads grid/portrait/hero/logo artwork into Steam's grid folder.

Requires a SteamGridDB API key (https://www.steamgriddb.com/profile/preferences/api)
via SGDB_API_KEY env var or ~/.config/heroicimport/api_key.

Usage:
    heroicimport.py --dry-run          # list Heroic shortcuts + artwork status
    heroicimport.py                    # fetch missing artwork
    heroicimport.py --force            # re-fetch everything
"""

import argparse
import json
import os
import struct
import sys
import urllib.parse
import urllib.request

SGDB_API = "https://www.steamgriddb.com/api/v2"

STEAM_USERDATA_CANDIDATES = [
    "~/.steam/steam/userdata",
    "~/.local/share/Steam/userdata",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata",
]

# Artwork kinds: (filename suffix, SGDB endpoint, query params)
ART_TYPES = [
    ("p", "grids", {"dimensions": "600x900", "types": "static"}),
    ("", "grids", {"dimensions": "460x215,920x430", "types": "static"}),
    ("_hero", "heroes", {"types": "static"}),
    ("_logo", "logos", {"types": "static"}),
]


# --- shortcuts.vdf (binary VDF) parsing -------------------------------------

def _parse_map(data, i):
    obj = {}
    while True:
        rtype = data[i]
        i += 1
        if rtype == 0x08:  # end of map
            return obj, i
        end = data.index(b"\x00", i)
        key = data[i:end].decode("utf-8", "replace")
        i = end + 1
        if rtype == 0x00:  # nested map
            obj[key], i = _parse_map(data, i)
        elif rtype == 0x01:  # string
            end = data.index(b"\x00", i)
            obj[key] = data[i:end].decode("utf-8", "replace")
            i = end + 1
        elif rtype == 0x02:  # int32
            obj[key] = struct.unpack_from("<i", data, i)[0]
            i += 4
        else:
            raise ValueError(f"unknown VDF record type {rtype:#x} at {i}")


def load_shortcuts(path):
    with open(path, "rb") as f:
        data = f.read()
    root, _ = _parse_map(data, 0)
    shortcuts = root.get("shortcuts", {})
    return [shortcuts[k] for k in sorted(shortcuts, key=int)]


# --- Steam / Heroic discovery ------------------------------------------------

def find_shortcut_files():
    found = []
    for base in STEAM_USERDATA_CANDIDATES:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        for user in os.listdir(base):
            path = os.path.join(base, user, "config", "shortcuts.vdf")
            if os.path.isfile(path):
                found.append(path)
    return found


def is_heroic(shortcut):
    exe = shortcut.get("exe", "")
    opts = shortcut.get("LaunchOptions", "")
    return "heroic://launch" in opts or "heroic" in exe.lower()


def grid_dir(shortcuts_path):
    return os.path.join(os.path.dirname(shortcuts_path), "grid")


# --- SteamGridDB API ----------------------------------------------------------

def load_api_key():
    key = os.environ.get("SGDB_API_KEY", "").strip()
    if key:
        return key
    keyfile = os.path.expanduser("~/.config/heroicimport/api_key")
    if os.path.isfile(keyfile):
        with open(keyfile) as f:
            return f.read().strip()
    return None


def sgdb_get(path, key, params=None):
    url = SGDB_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": "heroicimport/1.0",
    })
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def search_game(name, key):
    term = urllib.parse.quote(name, safe="")
    data = sgdb_get(f"/search/autocomplete/{term}", key)
    results = data.get("data", [])
    return results[0] if results else None


def best_image(endpoint, game_id, key, params):
    data = sgdb_get(f"/{endpoint}/game/{game_id}", key, params)
    images = data.get("data", [])
    if not images:
        return None
    images.sort(key=lambda im: im.get("score", 0), reverse=True)
    return images[0]["url"]


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "heroicimport/1.0"})
    tmp = dest + ".part"
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
        f.write(resp.read())
    os.replace(tmp, dest)


# --- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="list Heroic shortcuts and artwork status; download nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download artwork that already exists")
    args = ap.parse_args()

    shortcut_files = find_shortcut_files()
    if not shortcut_files:
        sys.exit("error: no Steam shortcuts.vdf found")

    key = None if args.dry_run else load_api_key()
    if not args.dry_run and not key:
        sys.exit("error: no SteamGridDB API key. Set SGDB_API_KEY or write it to "
                 "~/.config/heroicimport/api_key")

    for sc_path in shortcut_files:
        shortcuts = [s for s in load_shortcuts(sc_path) if is_heroic(s)]
        if not shortcuts:
            continue
        gdir = grid_dir(sc_path)
        print(f"{sc_path}: {len(shortcuts)} Heroic shortcut(s)")
        os.makedirs(gdir, exist_ok=True)

        for sc in shortcuts:
            name = sc.get("AppName", "?")
            appid = sc.get("appid", 0) & 0xFFFFFFFF
            existing = {suf for suf, _, _ in ART_TYPES
                        if any(os.path.isfile(os.path.join(gdir, f"{appid}{suf}{ext}"))
                               for ext in (".png", ".jpg", ".webp"))}
            missing = [t for t in ART_TYPES if t[0] not in existing]

            if args.dry_run:
                status = "complete" if not missing else \
                         "missing: " + ",".join(suf or "grid" for suf, _, _ in missing)
                print(f"  {appid:>12}  {name}  [{status}]")
                continue

            if not missing and not args.force:
                print(f"  {name}: artwork complete, skipping")
                continue

            try:
                game = search_game(name, key)
            except urllib.error.HTTPError as e:
                print(f"  {name}: search failed (HTTP {e.code}), skipping")
                continue
            if not game:
                print(f"  {name}: no SteamGridDB match, skipping")
                continue
            print(f"  {name} -> {game['name']} (sgdb id {game['id']})")

            targets = ART_TYPES if args.force else missing
            for suf, endpoint, params in targets:
                try:
                    url = best_image(endpoint, game["id"], key, params)
                except urllib.error.HTTPError as e:
                    print(f"    {endpoint}{suf}: API error {e.code}")
                    continue
                if not url:
                    print(f"    {endpoint}{suf}: none available")
                    continue
                ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
                dest = os.path.join(gdir, f"{appid}{suf}{ext}")
                try:
                    download(url, dest)
                except Exception as e:
                    print(f"    {endpoint}{suf}: download failed ({e})")
                    try:
                        os.remove(dest + ".part")
                    except OSError:
                        pass
                    continue
                print(f"    {endpoint}{suf}: saved {os.path.basename(dest)}")

    if not args.dry_run:
        print("\nRestart Steam to pick up new artwork.")


if __name__ == "__main__":
    main()
