"""Short platform names for collection titles.

libretro's database names are precise but unwieldy on a shelf header: "Nintendo -
Super Nintendo Entertainment System" is 46 characters for what everyone calls the
SNES. These are the names people actually use.

Keyed on the libretro database name, which is what cores report and what the
plugin already stores per game, so existing entries benefit without re-adding
anything.
"""

import re

SHORT_NAMES = {
    # Nintendo
    "Nintendo - Nintendo Entertainment System": "NES",
    "Nintendo - Family Computer Disk System": "FDS",
    "Nintendo - Super Nintendo Entertainment System": "SNES",
    "Nintendo - Nintendo 64": "N64",
    "Nintendo - Nintendo 64DD": "N64DD",
    "Nintendo - Game Boy": "Game Boy",
    "Nintendo - Game Boy Color": "GBC",
    "Nintendo - Game Boy Advance": "GBA",
    "Nintendo - Nintendo DS": "NDS",
    "Nintendo - Nintendo DSi": "DSi",
    "Nintendo - Nintendo 3DS": "3DS",
    "Nintendo - GameCube": "GameCube",
    "Nintendo - Wii": "Wii",
    "Nintendo - Virtual Boy": "Virtual Boy",
    "Nintendo - Pokemon Mini": "Pokemon mini",
    "Nintendo - Satellaview": "Satellaview",
    "Nintendo - Sufami Turbo": "Sufami Turbo",
    # Sega
    "Sega - Master System - Mark III": "Master System",
    "Sega - Mega Drive - Genesis": "Genesis",
    "Sega - Mega-CD - Sega CD": "Sega CD",
    "Sega - 32X": "32X",
    "Sega - Game Gear": "Game Gear",
    "Sega - Saturn": "Saturn",
    "Sega - Dreamcast": "Dreamcast",
    "Sega - SG-1000": "SG-1000",
    "Sega - Naomi": "Naomi",
    # Sony
    "Sony - PlayStation": "PS1",
    "Sony - PlayStation 2": "PS2",
    "Sony - PlayStation Portable": "PSP",
    "Sony - PlayStation Vita": "Vita",
    # NEC
    "NEC - PC Engine - TurboGrafx 16": "TurboGrafx-16",
    "NEC - PC Engine CD - TurboGrafx-CD": "TurboGrafx-CD",
    "NEC - PC Engine SuperGrafx": "SuperGrafx",
    "NEC - PC-98": "PC-98",
    # Atari
    "Atari - 2600": "Atari 2600",
    "Atari - 5200": "Atari 5200",
    "Atari - 7800": "Atari 7800",
    "Atari - Jaguar": "Jaguar",
    "Atari - Lynx": "Lynx",
    "Atari - ST": "Atari ST",
    # SNK
    "SNK - Neo Geo": "Neo Geo",
    "SNK - Neo Geo CD": "Neo Geo CD",
    "SNK - Neo Geo Pocket": "NGP",
    "SNK - Neo Geo Pocket Color": "NGPC",
    # Others
    "Bandai - WonderSwan": "WonderSwan",
    "Bandai - WonderSwan Color": "WonderSwan Color",
    "Commodore - Amiga": "Amiga",
    "Commodore - 64": "C64",
    "Commodore - VIC-20": "VIC-20",
    "Microsoft - MSX": "MSX",
    "Microsoft - MSX2": "MSX2",
    "The 3DO Company - 3DO": "3DO",
    "Coleco - ColecoVision": "ColecoVision",
    "Mattel - Intellivision": "Intellivision",
    "GCE - Vectrex": "Vectrex",
    "Magnavox - Odyssey2": "Odyssey 2",
    "Sharp - X68000": "X68000",
    "Sharp - X1": "Sharp X1",
    "Sinclair - ZX Spectrum": "ZX Spectrum",
    "Sinclair - ZX 81": "ZX81",
    "Amstrad - CPC": "Amstrad CPC",
    "Fairchild - Channel F": "Channel F",
    "Watara - Supervision": "Supervision",
    # Arcade and computer targets, which have no manufacturer prefix to strip.
    "MAME": "Arcade",
    "FBNeo - Arcade Games": "Arcade",
    "DOS": "DOS",
    "ScummVM": "ScummVM",
    "Cannonball": "Cannonball",
    "Dinothawr": "Dinothawr",
    "Doom": "Doom",
    "Quake": "Quake",
}


# Systems libretro has no database for, and therefore no thumbnails either.
# They still need a platform label for collection naming, and their artwork comes
# from SteamGridDB -- which covers modern titles well, so this is not much of a
# loss.
#
# The first field deliberately follows libretro's "Manufacturer - System"
# convention. These sit in the same picker as the libretro databases, and mixing
# conventions scatters a manufacturer's systems across the alphabet.
#
#   (picker label, display name, short name)
NO_LIBRETRO_PLATFORMS = (
    ("Nintendo - Switch", "Nintendo Switch", "Switch"),
    ("Nintendo - Wii U", "Nintendo Wii U", "Wii U"),
    ("Sony - PlayStation 3", "PlayStation 3", "PS3"),
    ("Sony - PlayStation 4", "PlayStation 4", "PS4"),
    ("Sony - PlayStation Vita", "PlayStation Vita", "Vita"),
    ("Microsoft - Xbox", "Xbox", "Xbox"),
    ("Microsoft - Xbox 360", "Xbox 360", "Xbox 360"),
    ("Microsoft - Windows", "Windows", "Windows"),
    ("Google - Android", "Android", "Android"),
)


def folder_name(database, fallback=""):
    """A directory name for a system: "Sony - PlayStation 3" -> playstation-3.

    Built from the display short name rather than invented separately, so the
    folder a game is filed into is recognisably the label shown for it
    everywhere else. Lowercase and hyphenated because these are typed by nobody
    and read on a Deck's file picker by everybody.
    """
    text = short_name(database, fallback) or fallback or ""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    # Bounded and non-empty: this becomes a path segment, and a name that
    # cannot be a directory should not get as far as being tried.
    return slug[:32]


def short_name(database, fallback=""):
    """A short label for a libretro database name.

    Falls back to trimming the manufacturer prefix ("Nintendo - Wii" -> "Wii"),
    which is a reasonable answer for systems not listed above.
    """
    if database:
        if database in SHORT_NAMES:
            return SHORT_NAMES[database]
        return database.split(" - ")[-1]
    return fallback


# Extensions that name a system on their own.
#
# Only useful for a core covering more than one, which is most of them: of the
# seven cores with an info file on the device this was written against, six
# declare between two and six databases. Genesis Plus GX declares Game Gear,
# Master System, Mega-CD, Mega Drive, PICO and SG-1000, and libretro lists them
# alphabetically -- so "the core's system" is Game Gear, and every Mega Drive
# ROM run on it was filed under Game Gear unless something else spoke up.
#
# What speaks up is the file. `.md` is a Mega Drive cartridge and nothing else,
# and that is true of every entry here: a mapping is only listed when the
# extension names one system across every core that reads it.
#
# Deliberately no disc images. `.cue`, `.chd`, `.iso` and `.m3u` name a *medium*
# -- Mega-CD, Saturn, PlayStation, GameCube and PSP all arrive as one -- so an
# entry for them would be a guess wearing a fact's clothes. Those keep the
# behaviour they had, which is the core's first database.
EXTENSION_SYSTEMS = {
    # Sega
    "md": "Sega - Mega Drive - Genesis",
    "smd": "Sega - Mega Drive - Genesis",
    "gen": "Sega - Mega Drive - Genesis",
    "mdx": "Sega - Mega Drive - Genesis",
    "68k": "Sega - Mega Drive - Genesis",
    "sgd": "Sega - Mega Drive - Genesis",
    "bin": "Sega - Mega Drive - Genesis",
    "gg": "Sega - Game Gear",
    "sms": "Sega - Master System - Mark III",
    "bms": "Sega - Master System - Mark III",
    "sg": "Sega - SG-1000",
    "32x": "Sega - 32X",
    # Nintendo
    "gb": "Nintendo - Game Boy",
    "gbc": "Nintendo - Game Boy Color",
    "gba": "Nintendo - Game Boy Advance",
    "nes": "Nintendo - Nintendo Entertainment System",
    "unf": "Nintendo - Nintendo Entertainment System",
    "unif": "Nintendo - Nintendo Entertainment System",
    "fds": "Nintendo - Family Computer Disk System",
    "sfc": "Nintendo - Super Nintendo Entertainment System",
    "smc": "Nintendo - Super Nintendo Entertainment System",
    "swc": "Nintendo - Super Nintendo Entertainment System",
    "fig": "Nintendo - Super Nintendo Entertainment System",
    "bs": "Nintendo - Satellaview",
    "st": "Nintendo - Sufami Turbo",
    "n64": "Nintendo - Nintendo 64",
    "z64": "Nintendo - Nintendo 64",
    "v64": "Nintendo - Nintendo 64",
    "ndd": "Nintendo - Nintendo 64DD",
    "gcm": "Nintendo - GameCube",
    "gcz": "Nintendo - GameCube",
    "wbfs": "Nintendo - Wii",
    "wad": "Nintendo - Wii",
    # Handhelds whose two generations share a core
    "ws": "Bandai - WonderSwan",
    "wsc": "Bandai - WonderSwan Color",
    "ngp": "SNK - Neo Geo Pocket",
    "ngc": "SNK - Neo Geo Pocket Color",
    "pce": "NEC - PC Engine - TurboGrafx 16",
    "sgx": "NEC - PC Engine SuperGrafx",
    "lnx": "Atari - Lynx",
    "a78": "Atari - 7800",
}


def system_for_extension(databases, extension):
    """Which of `databases` a file extension names, or "".

    Answered only when the core itself claims the system. The table above is
    keyed on the extension alone, so `.md` maps to Mega Drive even when asked
    about DuckStation -- and DuckStation does not declare Mega Drive, so the
    answer is "" and nothing downstream changes. That guard is what lets the
    table stay a plain dict instead of a per-core one.
    """
    wanted = EXTENSION_SYSTEMS.get((extension or "").lower().lstrip("."))
    if wanted and wanted in (databases or []):
        return wanted
    return ""
