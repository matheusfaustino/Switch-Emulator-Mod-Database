#!/usr/bin/env python3
"""
Checks this repo's game folders against the <Game>/<TitleID>/<files> convention.

ERRORS (exit code 1) are unambiguous rule violations that standardize_repo.py
can fix: colons in folder names, region tags, loose title-ID files not
wrapped in a <TitleID>/ folder, "..." placeholder files, and non-ID immediate
subfolders of a game folder. Un-integrated root-level mod archives (.zip/
.rar/.7z) are ignored by default -- there's currently a backlog of them --
pass --check-archives to include that check.

WARNINGS are informational / judgment calls that need a human (mirrors the
"open flags" from the standardization effort): folders with no title ID
found anywhere, and title-ID folders that are valid hex but not uppercase.

Never inspects NX-60FPS-RES-GFX-Cheats/, Titles/, Mods/, Saves/ -- those are
vendored/aggregate data trees, not per-game folders.
"""
import argparse
import re
import sys
from pathlib import Path

EXCLUDED_TOP_LEVEL = {
    "NX-60FPS-RES-GFX-Cheats", "Titles", "Mods", "Saves",
    ".git", ".github", ".venv", "scripts",
    "README.md", "LICENSE", "Cheats.md", "Mods.md", "Saves.md",
    "remove_ds_store.sh", ".gitignore",
    "pyproject.toml", "uv.lock", ".python-version",
}
IGNORED_LOOSE_FILENAMES = {"readme.md", ".ds_store"}

# Known unresolved game folders that still need a human to sort out (missing
# title ID, ambiguous demo/base-game split, etc.) -- ignored by default so CI
# stays green; drop an entry here once its folder is standardized.
DEFAULT_IGNORED_GAME_FOLDERS = {
    "Dragon Quest XI S Demo",
}

TITLE_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
BRACKET_ID_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
REGION_TAG_RE = re.compile(r"\s*\((USA|EUR|JPN)\)\s*$", re.IGNORECASE)
MOD_ARCHIVE_EXTS = {".zip", ".rar", ".7z"}


def top_level_game_dirs(root):
    return [
        p for p in sorted(root.iterdir())
        if p.is_dir() and p.name not in EXCLUDED_TOP_LEVEL
    ]


def check_root_archives(root, errors):
    for entry in sorted(root.iterdir()):
        if entry.is_dir() or entry.name in EXCLUDED_TOP_LEVEL:
            continue
        if entry.suffix.lower() in MOD_ARCHIVE_EXTS:
            errors.append(f"un-integrated archive at repo root: '{entry.name}'")


def check_folder_name_rules(root, errors):
    for d in top_level_game_dirs(root):
        if ":" in d.name:
            errors.append(f"'{d.name}': colon in folder name (use '_' instead)")
        if REGION_TAG_RE.search(d.name):
            errors.append(f"'{d.name}': trailing region tag should be stripped")


def check_subfolder_and_loose_files(root, errors, warnings):
    for game_dir in top_level_game_dirs(root):
        has_id_subfolder = False

        for child in sorted(game_dir.iterdir()):
            if child.is_dir():
                if TITLE_ID_RE.match(child.name):
                    has_id_subfolder = True
                    if child.name != child.name.upper():
                        warnings.append(f"'{child}': title-ID folder is not uppercase")
                else:
                    errors.append(f"'{child}': non-title-ID subfolder directly under a game folder")
                continue

            if child.name.lower() in IGNORED_LOOSE_FILENAMES:
                continue

            stem_upper = child.stem.upper()
            if TITLE_ID_RE.match(stem_upper) or BRACKET_ID_RE.search(child.name):
                errors.append(f"'{child}': loose title-ID file not wrapped in a <TitleID>/ folder")
            else:
                warnings.append(f"'{child}': loose file directly under a game folder, unclear if it needs wrapping")

        if not has_id_subfolder:
            warnings.append(f"'{game_dir.name}': no title-ID subfolder found -- unresolved ID")


def check_placeholder_files(root, errors):
    for top in top_level_game_dirs(root):
        for path in top.rglob("..."):
            if path.is_file():
                errors.append(f"'{path}': literal '...' placeholder file")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root (default: current directory)")
    parser.add_argument("--quiet", action="store_true", help="only print the summary line and errors, no warnings")
    parser.add_argument(
        "--ignore", action="append", default=[], metavar="FOLDER",
        help="additional top-level game folder name to skip entirely, on top of "
             "DEFAULT_IGNORED_GAME_FOLDERS, may be passed multiple times",
    )
    parser.add_argument(
        "--check-archives", action="store_true",
        help="also flag un-integrated .zip/.rar/.7z archives sitting loose at repo root "
             "(off by default while the existing backlog gets cleared)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()

    print("== configuration ==")
    print(f"  root: {root}")
    print(f"  excluded top-level entries (default): {', '.join(sorted(EXCLUDED_TOP_LEVEL))}")
    print(f"  ignored loose filenames: {', '.join(sorted(IGNORED_LOOSE_FILENAMES))}")
    print(f"  archive check (--check-archives): {'on' if args.check_archives else 'off'}")
    print(f"  known unresolved game folders (ignored by default): {', '.join(sorted(DEFAULT_IGNORED_GAME_FOLDERS))}")
    if args.ignore:
        print(f"  extra folders ignored (--ignore): {', '.join(sorted(args.ignore))}")
    print()

    EXCLUDED_TOP_LEVEL.update(DEFAULT_IGNORED_GAME_FOLDERS)
    EXCLUDED_TOP_LEVEL.update(args.ignore)
    errors, warnings = [], []

    if args.check_archives:
        check_root_archives(root, errors)
    check_folder_name_rules(root, errors)
    check_subfolder_and_loose_files(root, errors, warnings)
    check_placeholder_files(root, errors)

    if errors:
        print(f"== errors ({len(errors)}) ==")
        for e in sorted(errors):
            print(f"  {e}")

    if warnings and not args.quiet:
        print(f"\n== warnings ({len(warnings)}) ==")
        for w in sorted(warnings):
            print(f"  {w}")

    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
