"""Enumerate installed libretro cores and the systems they emulate.

Every core shipped through RetroArch's Core Updater comes with a sibling
`.info` file. The field we care about most is `database`, because its value is
the *exact* libretro playlist name -- which is also the exact directory name on
thumbnails.libretro.com. That makes it the reliable bridge from "the core the
user picked" to "where this game's boxart lives".
"""

import glob
import os
import re
import zipfile

import decky

# RetroArch transparently decompresses these for most cores, but no core's
# `supported_extensions` lists them -- so matching on the archive extension
# alone would offer the user no cores at all.
ARCHIVE_EXTENSIONS = {"zip", "7z"}

# Cores are sometimes installed without their .info sibling (hand-copied, or a
# trimmed install). This covers the common ones so core selection and artwork
# lookup still work.
_FALLBACK_DATABASES = {
    "snes9x": "Nintendo - Super Nintendo Entertainment System",
    "snes9x2010": "Nintendo - Super Nintendo Entertainment System",
    "bsnes": "Nintendo - Super Nintendo Entertainment System",
    "bsnes_hd_beta": "Nintendo - Super Nintendo Entertainment System",
    "mesen": "Nintendo - Nintendo Entertainment System",
    "nestopia": "Nintendo - Nintendo Entertainment System",
    "fceumm": "Nintendo - Nintendo Entertainment System",
    "gambatte": "Nintendo - Game Boy Color",
    "sameboy": "Nintendo - Game Boy Color",
    "mgba": "Nintendo - Game Boy Advance",
    "vbam": "Nintendo - Game Boy Advance",
    "vba_next": "Nintendo - Game Boy Advance",
    "melonds": "Nintendo - Nintendo DS",
    "desmume": "Nintendo - Nintendo DS",
    "mupen64plus_next": "Nintendo - Nintendo 64",
    "parallel_n64": "Nintendo - Nintendo 64",
    "dolphin": "Nintendo - GameCube",
    "genesis_plus_gx": "Sega - Mega Drive - Genesis",
    "picodrive": "Sega - Mega Drive - Genesis",
    "flycast": "Sega - Dreamcast",
    "beetle_saturn": "Sega - Saturn",
    "mednafen_saturn": "Sega - Saturn",
    "swanstation": "Sony - PlayStation",
    "duckstation": "Sony - PlayStation",
    "beetle_psx": "Sony - PlayStation",
    "beetle_psx_hw": "Sony - PlayStation",
    "mednafen_psx": "Sony - PlayStation",
    "pcsx_rearmed": "Sony - PlayStation",
    "ppsspp": "Sony - PlayStation Portable",
    "pcsx2": "Sony - PlayStation 2",
    "mednafen_pce": "NEC - PC Engine - TurboGrafx 16",
    "mednafen_wswan": "Bandai - WonderSwan Color",
    "mame": "MAME",
    "fbneo": "FBNeo - Arcade Games",
    "fbalpha2012": "FBNeo - Arcade Games",
    "stella": "Atari - 2600",
    "prosystem": "Atari - 7800",
    "opera": "The 3DO Company - 3DO",
    "citra": "Nintendo - Nintendo 3DS",
    "kronos": "Sega - Saturn",
    "puae": "Commodore - Amiga",
    "vice_x64": "Commodore - 64",
    "dosbox_pure": "DOS",
}


def _parse_info(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                values[key.strip()] = raw.strip().strip('"')
    except OSError:
        pass
    return values


def _core_id(so_path):
    """`snes9x_libretro.so` -> `snes9x`."""
    name = os.path.basename(so_path)
    for suffix in ("_libretro.so", "_libretro.dylib", ".so"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _find_info_file(so_path, info_dirs):
    stem = os.path.basename(so_path)
    for suffix in (".so", ".dylib"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    candidates = [os.path.splitext(so_path)[0] + ".info"]
    for directory in info_dirs:
        candidates.append(os.path.join(directory, stem + ".info"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _cheevos_support(info):
    """"yes" / "no" / "unknown" from a core's declared memory descriptors.

    `memory_descriptors` is how a core says whether it publishes a memory map,
    which is what RetroAchievements reads. Absent means the .info file predates
    the field or omits it -- unknown, not a refusal.
    """
    declared = (info.get("memory_descriptors") or "").strip().lower()
    if declared == "false":
        return "no"
    if declared == "true":
        return "yes"
    return "unknown"


def list_cores(install):
    """[{id, path, display_name, system_name, databases, extensions}] sorted by label."""
    if not install:
        return []

    info_dirs = install.get("info_dirs", [])
    cores = {}

    for core_dir in install.get("core_dirs", []):
        for so_path in glob.glob(os.path.join(core_dir, "*.so")):
            core_id = _core_id(so_path)
            # First core dir wins: user-downloaded cores shadow bundled ones.
            if core_id in cores:
                continue

            info_path = _find_info_file(so_path, info_dirs)
            info = _parse_info(info_path) if info_path else {}

            databases = [
                part.strip()
                for part in info.get("database", "").split("|")
                if part.strip()
            ]
            if not databases and core_id in _FALLBACK_DATABASES:
                databases = [_FALLBACK_DATABASES[core_id]]

            extensions = [
                ext.strip().lower()
                for ext in info.get("supported_extensions", "").split("|")
                if ext.strip()
            ]

            display_name = info.get("display_name") or info.get("corename") or core_id
            # The core's own name, without the system prefix `display_name`
            # carries. `display_name` is right for a picker, where "Sega - Mega
            # Drive - Genesis (BlastEm)" says which system you are choosing, and
            # wrong for a list of what is installed, where six of those separated
            # by commas is unreadable -- the names contain both hyphens and
            # slashes of their own.
            short_name = info.get("corename") or display_name
            system_name = info.get("systemname") or (
                databases[0].split(" - ")[-1] if databases else ""
            )

            cores[core_id] = {
                "id": core_id,
                "path": so_path,
                "display_name": display_name,
                "short_name": short_name,
                "system_name": system_name,
                "databases": databases,
                "extensions": extensions,
                "has_info": bool(info),
                # Whether achievements are possible with this core: "yes", "no",
                # or "unknown".
                #
                # RetroAchievements reads emulated memory, so a core publishing
                # no memory map cannot support it -- RetroArch says so at launch
                # and nothing here can change that. BlastEm declares
                # `memory_descriptors = "false"` and is exactly this case, while
                # Genesis Plus GX on the same system declares "true".
                #
                # Three values rather than a boolean because the three cases are
                # genuinely different: a core that says nothing has not said no,
                # and lumping it in with either answer would state something the
                # .info file does not. Note that "yes" means the core can take
                # part, not that RetroAchievements has a set for a given game.
                "cheevos": _cheevos_support(info),
            }

    result = sorted(cores.values(), key=lambda core: core["display_name"].lower())
    decky.logger.info("Found %d libretro cores", len(result))
    return result


def cores_for_extension(cores, extension):
    """Cores that declare support for `extension`, e.g. 'sfc'."""
    ext = (extension or "").lower().lstrip(".")
    if not ext:
        return []
    return [core for core in cores if ext in core["extensions"]]


# The extension a chip dump carries inside an arcade ROM set: a bare number, or
# `icN` for the socket it came out of. Not invented -- read off Supermodel's own
# Games.xml, which names every file of all 63 Model 3 sets. Across those 1211
# files the only extensions are `.1` to `.60`, `.01` to `.09`, `.ic2` to `.ic24`,
# `.bin`, and none at all.
#
# `bin` and the empty extension are not evidence and are not in here. `bin` is
# the one extension a ROM set shares with real console formats -- a raw Mega
# Drive cartridge, a PlayStation track -- so on its own it says nothing.
_CHIP_DUMP_RE = re.compile(r"^(?:\d{1,2}|ic\d{1,2})$")

# What may sit beside the chip dumps and still leave the archive a ROM set.
_ROMSET_MEMBER_RE = re.compile(r"^(?:\d{1,2}|ic\d{1,2}|bin|)$")


def _zip_members(rom_path):
    """Every non-directory member's lowercase extension, or None if unreadable."""
    try:
        with zipfile.ZipFile(rom_path) as archive:
            return [
                os.path.splitext(entry.filename)[1].lower().lstrip(".")
                for entry in archive.infolist()
                if not entry.is_dir()
            ]
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        decky.logger.warning("Could not inspect archive %s: %s", rom_path, error)
        return None


def is_romset(rom_path):
    """Whether a `.zip` is an arcade ROM set rather than one game in a wrapper.

    The distinction matters because the two are opened from opposite ends. A
    zipped console ROM is a container -- RetroArch unpacks it and loads the one
    file inside, so the file inside is what decides which cores can run it. An
    arcade ROM set is not a container at all: it is the cartridge, forty chip
    dumps that mean nothing apart, and every emulator that reads one -- MAME,
    FBNeo, Supermodel -- takes the `.zip` itself and says so by declaring `zip`
    among its extensions.

    Told apart from the outside they are the same file, and the plugin used to
    treat them the same way: `scud.zip` reported `bin`, matched the PlayStation
    and Mega Drive cores that claim it, and suggested SwanStation for Scud Race
    while no arcade emulator was offered at all.

    Three conditions, and each one is load-bearing:

      * more than one member, or a lone `game.bin` would qualify;
      * at least one member is a chip dump, or a multi-track `.bin` rip with no
        cue sheet would qualify;
      * every member is a chip dump, a `.bin`, or extensionless, or a zip
        holding `game.sfc` beside a stray `patch.1` would qualify.

    Checked against all 63 sets Supermodel knows: every one satisfies all three,
    including `fvipers2`, whose four `mpr-*` members carry no extension.
    """
    extensions = _zip_members(rom_path) if _is_zip(rom_path) else None
    if not extensions or len(extensions) < 2:
        return False
    return (all(_ROMSET_MEMBER_RE.match(ext) for ext in extensions)
            and any(_CHIP_DUMP_RE.match(ext) for ext in extensions))


def _is_zip(rom_path):
    return os.path.splitext(rom_path)[1].lower() == ".zip"


def archive_inner_extension(rom_path):
    """The content extension inside an archive, e.g. 'n64' for a zipped ROM.

    Zipped ROMs are common, and a core that supports `.n64` will happily load
    `game.zip` -- RetroArch unpacks it first. Only zip can be inspected with the
    standard library; 7z returns nothing and the caller falls back to offering
    every core.

    Empty for a ROM set, which has no single file inside it to name. The caller
    then falls back to `zip`, which is the extension the emulators that read one
    actually declare.
    """
    if not _is_zip(rom_path) or is_romset(rom_path):
        return ""

    for ext in _zip_members(rom_path) or ():
        if ext and ext not in ARCHIVE_EXTENSIONS:
            return ext

    return ""


def content_extension(rom_path):
    """The extension to match cores against, looking inside archives."""
    extension = os.path.splitext(rom_path)[1].lower().lstrip(".")
    if extension in ARCHIVE_EXTENSIONS:
        return archive_inner_extension(rom_path) or extension
    return extension
