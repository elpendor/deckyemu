"""BIOS files for libretro cores, as rows in the same firmware panel.

Every core says what it reads in its `.info` file -- `firmware0_path =
"scph5501.bin"`, relative to RetroArch's system folder -- so nothing here is a
table somebody has to keep up to date. This turns those declarations into an
entry shaped exactly like a catalog emulator's, so matching, installing,
removing, sharing a file with DuckStation and the add-game warning all go
through `emu_firmware` unchanged. One entry for RetroArch rather than one per
core: every core reads the same folder, so `gb_bios.bin` is one file however
many cores want it.

**Which rows are shown is decided by the library, and optional files are
folded away.** Measured on a Deck with EmuDeck's 94 cores: they declare 269
files, and the six cores its games ran on still declared 27 -- every one
optional, from a Game Genie ROM to eight arcade BIOS sets for one core. As rows,
that was 27 amber triangles saying something was missing when nothing was. So a
row appears for a file somebody has just sent, or, for a core a game runs on,
when the file is required, in place, or held by another emulator. The rest are
counted into one "optional files" line with a Send button, which is all that
optional files need: the transfer dialog recognises an arrival by its name.
`visible` is that rule.
"""

import os
import posixpath
import re

import ra_detect
import sysenv

#: The entry id every RetroArch row is filed under, in the panel, the transfer
#: dialog and `firmware_installed.json`.
ENTRY_ID = "retroarch"


def _label(desc, path):
    """`"scph5501.bin (PS1 US BIOS)"` -> `PS1 US BIOS`.

    Cut after the filename rather than matched on the last brackets: a
    description can hold brackets of its own, as a region tag inside a title.
    """
    desc = (desc or "").strip()
    for prefix in (path, posixpath.basename(path)):
        if desc.startswith(prefix + " (") and desc.endswith(")"):
            return desc[len(prefix) + 2:-1].strip()
    return desc or posixpath.basename(path)


def _relative_system_dir(install):
    """The system folder relative to the home, or '' when it is not under it.

    `emu_firmware` refuses any destination outside the home, which is right for
    a path read from a table and then written to and deleted from.
    """
    system = os.path.normpath(ra_detect.system_dir((install or {}).get("config_dir", "")))
    home = os.path.normpath(sysenv.user_home())
    if not system.startswith(home + os.sep):
        return ""
    return os.path.relpath(system, home).replace(os.sep, "/")


def entry(install, cores):
    """The firmware every core in `cores` declares, as a catalog-shaped entry.

    None when there is nothing to show: no RetroArch, a system folder outside
    the home, or no core that declares a file. Each requirement carries
    `core_ids` so `visible` can tell which games it matters to.
    """
    if not install or not cores:
        return None
    base = _relative_system_dir(install)
    if not base:
        return None

    rows = {}
    for core in cores:
        for item in core.get("firmware") or ():
            path = posixpath.normpath(item["path"].replace("\\", "/"))
            name = posixpath.basename(path)
            # A folder rather than a file (`pcsx2/bios`) is a layout this has no
            # way to fill from one sent file, and a path climbing out of the
            # system folder is not something to write to.
            if path.startswith(("/", "..")) or "." not in name:
                continue
            row = rows.get(path)
            if row is None:
                folder = posixpath.dirname(path)
                row = rows[path] = {
                    "name": path,
                    "label": _label(item.get("desc", ""), item["path"]),
                    "match": r"(?i)^%s$" % re.escape(name),
                    "as": name,
                    "expects": "Named %s. Capital letters do not matter." % name,
                    "dest": base + ("/" + folder if folder else ""),
                    "optional": True,
                    "core_ids": [],
                    "core_names": [],
                }
            # Required if any core that reads it cannot start without it.
            row["optional"] = row["optional"] and item.get("optional", True)
            if core["id"] not in row["core_ids"]:
                row["core_ids"].append(core["id"])
                row["core_names"].append(core.get("short_name") or core["id"])

    if not rows:
        return None

    firmware = []
    for path in sorted(rows, key=str.lower):
        row = rows[path]
        # `label` and `core_names` stay on the spec: the optional-files list
        # shows them apart, where a row shows them joined into the note.
        row["note"] = "%s. %s by %s." % (
            row["label"],
            "Optional, used" if row["optional"] else "Needed",
            ", ".join(row["core_names"]),
        )
        firmware.append(row)
    return {"id": ENTRY_ID, "name": "RetroArch", "firmware": firmware}


def for_core(install, cores, core_id):
    """The entry narrowed to one core, for the warning while a game is added."""
    return entry(install, [core for core in cores if core["id"] == core_id])


def library_core_ids(library):
    """The libretro cores games in the library run on."""
    return {
        str(game.get("core_id") or "")
        for game in (library or {}).values()
        if isinstance(game, dict)
        and game.get("core_id")
        and not str(game["core_id"]).startswith("emu:")
    }


def visible(entry_, report, used):
    """Split `report` into the rows to show and the optional files folded away.

    Returns `(rows, optional)`, where `optional` lists the files a core in use
    could read and nobody has supplied, each as `{name, label, cores}` so the
    panel can say what each one is for. A core nothing in the library runs on
    contributes neither: on a Deck set up by EmuDeck the system folder holds
    files for dozens of those.
    """
    by_name = {spec["name"]: spec for spec in (entry_ or {}).get("firmware") or ()}
    rows = []
    optional = []
    for row in report:
        in_use = set(by_name.get(row["name"], {}).get("core_ids") or ()) & set(used)
        if row["waiting"]:
            rows.append(row)
        elif not in_use:
            continue
        elif not row["optional"] or row["installed"] or row["elsewhere"]:
            rows.append(row)
        else:
            spec = by_name[row["name"]]
            optional.append({
                "name": row["name"],
                "label": spec.get("label", ""),
                "cores": list(spec.get("core_names") or ()),
            })
    return rows, optional
