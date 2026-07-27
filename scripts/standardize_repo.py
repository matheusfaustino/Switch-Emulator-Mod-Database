#!/usr/bin/env python3
"""
Normalizes this repo's game folders into the <Game>/<TitleID>/<files> layout.

Codifies the mechanical, non-judgment-call steps from the folder-standardization
effort so they can be re-run whenever new mods are dropped at repo root, instead
of redoing them by hand:

  1. integrate loose root-level .zip/.rar files (title ID read from a
     [<16-hex-id>] tag in the filename) into <Game>/<TitleID>/
  2. replace ':' with '_' in top-level game folder names (Windows path safety)
  3. strip trailing (USA)/(EUR)/(JPN) region tags from game folder names,
     merging into an existing plain-named folder if one exists
  4. wrap loose title-ID-named files sitting directly in a game folder
     (bare "<id>.txt" or "<name> [<id>]...zip") into <Game>/<TitleID>/
  5. delete literal "..." placeholder files

Does NOT attempt fuzzy/nickname duplicate-folder merging (e.g. "mk8" ->
"Mario Kart 8 Deluxe"), title-ID lookups for folders with no ID anywhere
locally, or moving non-title-ID subfolders sitting directly under a game
folder (e.g. a stray "exefs_patches/") -- those are judgment calls, left for
a human. The subfolder case is flagged under "needs manual review" below;
the rest show up as validate_repo_rules.py warnings (see that script to find
everything left unresolved).

Never touches NX-60FPS-RES-GFX-Cheats/, Titles/, Mods/, Saves/ -- these are
vendored/aggregate data trees, not per-game folders, and README.md has relative
links into some of their paths.

Defaults to a dry run. Pass --apply to actually perform the changes.
"""
import argparse
import filecmp
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

EXCLUDED_TOP_LEVEL = {
    "NX-60FPS-RES-GFX-Cheats", "Titles", "Mods", "Saves",
    ".git", ".github", ".venv", "scripts",
    "README.md", "LICENSE", "Cheats.md", "Mods.md", "Saves.md",
    "remove_ds_store.sh", ".gitignore",
    "pyproject.toml", "uv.lock", ".python-version",
}

TITLE_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
BRACKET_ID_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
REGION_TAG_RE = re.compile(r"\s*\((USA|EUR|JPN)\)\s*$", re.IGNORECASE)
MOD_ARCHIVE_EXTS = {".zip", ".rar", ".7z"}
# Game-level doc/metadata files that apply to the whole game, not one title ID
# revision -- leave these where they are instead of flagging them.
IGNORED_LOOSE_FILENAMES = {"readme.md", ".ds_store"}


def normalize_name(name):
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


class Action:
    def __init__(self, description, apply_fn):
        self.description = description
        self.apply_fn = apply_fn


def top_level_game_dirs(root):
    return [
        p for p in sorted(root.iterdir())
        if p.is_dir() and p.name not in EXCLUDED_TOP_LEVEL
    ]


def find_existing_match(root, cleaned_name):
    target = normalize_name(cleaned_name)
    for p in top_level_game_dirs(root):
        if normalize_name(p.name) == target:
            return p
    return None


def clean_archive_game_name(stem):
    name = BRACKET_ID_RE.sub("", stem)
    name = re.sub(r"\[[^\]]*\]", "", name)
    return re.sub(r"\s+", " ", name).strip(" -_")


def plan_integrate_loose_archives(root, actions, warnings):
    for entry in sorted(root.iterdir()):
        if entry.is_dir() or entry.name in EXCLUDED_TOP_LEVEL:
            continue
        if entry.suffix.lower() not in MOD_ARCHIVE_EXTS:
            continue

        ids = BRACKET_ID_RE.findall(entry.name)
        if not ids:
            warnings.append(f"[skip] {entry.name}: no [<16-hex-id>] tag found, needs manual ID")
            continue
        title_id = ids[0].upper()

        game_name = clean_archive_game_name(entry.stem)
        if not game_name:
            warnings.append(f"[skip] {entry.name}: could not derive a game name")
            continue

        dest_game_dir = find_existing_match(root, game_name) or (root / game_name)

        if dest_game_dir.is_dir():
            existing_ids = [d.name for d in dest_game_dir.iterdir() if d.is_dir()]
            conflicting = [
                eid for eid in existing_ids
                if eid.upper() != title_id and eid.upper()[:12] == title_id[:12]
            ]
            if conflicting:
                warnings.append(
                    f"[conflict] {entry.name}: id {title_id} looks like a near-miss of "
                    f"existing {conflicting} under '{dest_game_dir.name}' -- left at root for manual review"
                )
                continue

        dest_id_dir = dest_game_dir / title_id
        dest_file = dest_id_dir / entry.name

        def do_move(entry=entry, dest_id_dir=dest_id_dir, dest_file=dest_file):
            dest_id_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest_file))

        actions.append(Action(
            f"move '{entry.name}' -> '{dest_file.relative_to(root)}'", do_move
        ))


def plan_replace_colons(root, actions, warnings):
    for d in top_level_game_dirs(root):
        if ":" not in d.name:
            continue
        new_name = d.name.replace(":", "_")
        dest = root / new_name
        if dest.exists():
            warnings.append(f"[conflict] cannot rename '{d.name}' -> '{new_name}': target already exists")
            continue

        def do_rename(d=d, dest=dest):
            d.rename(dest)

        actions.append(Action(f"rename '{d.name}' -> '{new_name}'", do_rename))


def remove_empty_dirs(path):
    for child in list(path.iterdir()):
        if child.is_dir():
            remove_empty_dirs(child)
    if not any(path.iterdir()):
        path.rmdir()


def merge_dirs(src, dst, warnings, rel_root):
    for item in list(src.iterdir()):
        target = dst / item.name
        if not target.exists():
            shutil.move(str(item), str(target))
        elif item.is_dir() and target.is_dir():
            merge_dirs(item, target, warnings, rel_root)
        elif item.is_file() and target.is_file():
            if filecmp.cmp(item, target, shallow=False):
                item.unlink()
            else:
                warnings.append(
                    f"[conflict] '{item.relative_to(rel_root)}' differs from "
                    f"'{target.relative_to(rel_root)}' -- left both, needs manual review"
                )
        else:
            warnings.append(
                f"[conflict] '{item.relative_to(rel_root)}' vs '{target.relative_to(rel_root)}': "
                f"file/dir type mismatch -- left both, needs manual review"
            )
    if src.exists() and not any(src.iterdir()):
        src.rmdir()


def plan_strip_region_tags(root, actions, warnings):
    for d in top_level_game_dirs(root):
        m = REGION_TAG_RE.search(d.name)
        if not m:
            continue
        base_name = d.name[: m.start()].strip()
        existing = find_existing_match(root, base_name)

        if existing is None:
            dest = root / base_name
            if dest.exists():
                warnings.append(f"[conflict] cannot strip region tag from '{d.name}': '{base_name}' already exists")
                continue

            def do_rename(d=d, dest=dest):
                d.rename(dest)

            actions.append(Action(f"rename '{d.name}' -> '{base_name}' (strip region tag)", do_rename))
        else:
            def do_merge(d=d, existing=existing, root=root):
                merge_dirs(d, existing, warnings, root)

            actions.append(Action(
                f"merge '{d.name}' into '{existing.name}' (strip region tag, dedupe identical content)",
                do_merge,
            ))


def plan_wrap_loose_id_files(root, actions, warnings):
    for game_dir in top_level_game_dirs(root):
        for entry in sorted(game_dir.iterdir()):
            if entry.is_dir():
                continue
            if entry.name.lower() in IGNORED_LOOSE_FILENAMES:
                continue

            stem_upper = entry.stem.upper()
            if TITLE_ID_RE.match(stem_upper):
                title_id = stem_upper
            else:
                ids = BRACKET_ID_RE.findall(entry.name)
                title_id = ids[0].upper() if ids else None

            if title_id is None:
                warnings.append(f"[skip] {game_dir.name}/{entry.name}: no title ID found, needs manual pass")
                continue

            dest_dir = game_dir / title_id
            dest_file = dest_dir / entry.name

            def do_move(entry=entry, dest_dir=dest_dir, dest_file=dest_file):
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry), str(dest_file))

            actions.append(Action(
                f"wrap '{game_dir.name}/{entry.name}' -> '{game_dir.name}/{title_id}/{entry.name}'", do_move
            ))


def plan_flag_non_id_subfolders(root, actions, warnings):
    for game_dir in top_level_game_dirs(root):
        for child in sorted(game_dir.iterdir()):
            if child.is_dir() and not TITLE_ID_RE.match(child.name):
                warnings.append(
                    f"[needs manual pass] {child.relative_to(root)}: non-title-ID subfolder directly "
                    f"under a game folder -- which <TitleID>/ it belongs to must be decided by hand"
                )


def plan_delete_placeholders(root, actions, warnings):
    for top in top_level_game_dirs(root):
        for dirpath, _dirnames, filenames in os.walk(top):
            for fname in filenames:
                if fname == "...":
                    fpath = Path(dirpath) / fname

                    def do_delete(fpath=fpath):
                        fpath.unlink()

                    actions.append(Action(f"delete placeholder '{fpath.relative_to(root)}'", do_delete))


STEPS = [
    ("archives", "integrate loose root-level mod archives", plan_integrate_loose_archives),
    ("colons", "replace ':' in folder names", plan_replace_colons),
    ("regions", "strip (USA)/(EUR)/(JPN) region tags", plan_strip_region_tags),
    ("wrap", "wrap loose title-ID files into <TitleID>/ folders", plan_wrap_loose_id_files),
    ("subfolders", "flag non-title-ID subfolders for manual review", plan_flag_non_id_subfolders),
    ("placeholders", "delete '...' placeholder files", plan_delete_placeholders),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root (default: current directory)")
    parser.add_argument("--apply", action="store_true", help="actually perform the changes (default: dry run)")
    parser.add_argument(
        "--skip", action="append", default=[], choices=[s[0] for s in STEPS],
        help="skip a step, may be passed multiple times",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    warnings = []

    for key, label, plan_fn in STEPS:
        if key in args.skip:
            continue

        actions = []
        plan_fn(root, actions, warnings)

        if not actions:
            continue

        print(f"\n== {label} ({len(actions)}) ==")
        for action in actions:
            print(f"  {action.description}")
            if args.apply:
                action.apply_fn()

    if warnings:
        print(f"\n== needs manual review ({len(warnings)}) ==")
        for w in warnings:
            print(f"  {w}")

    if not args.apply:
        print("\nDry run only -- no changes made. Re-run with --apply to perform them.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
