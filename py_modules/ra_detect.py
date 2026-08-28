"""Locate the user's RetroArch install and work out where its cores live.

RetroArch on a Deck shows up in one of three shapes: the Flathub flatpak (what
Discover and most emulation setups install), a distro/native binary, or a loose
AppImage in ~/Applications. Each keeps its cores somewhere different, and the
flatpak additionally needs its sandbox opened up to reach ROMs on an SD card.
"""

import glob
import os
import posixpath
import shutil
import subprocess

import decky

import fileserver
import sysenv

FLATPAK_ID = "org.libretro.RetroArch"

def user_home():
    """See sysenv.user_home -- kept here because most callers of it live here."""
    return sysenv.user_home()


def _flatpak_system_roots():
    """Where flatpak keeps installed applications, system-wide and per-user.

    Shared with the emulator side rather than kept here: both ask the same
    question of the same two directories, and a copy was how the per-user root
    came to be frozen at import time in the first place -- see `sysenv`.
    """
    return sysenv.flatpak_roots()


def _flatpak_data_dir():
    return os.path.join(user_home(), ".var", "app", FLATPAK_ID)


def flatpak_scope():
    """Whether the RetroArch flatpak belongs to this user or to the system.

    This decides whether it can be removed at all. A user install lives under the
    user's home and needs no privileges; a system one -- which is what Discover
    and the usual setup scripts produce -- is owned by root, and the plugin has no
    way to answer a password prompt, so offering to remove it would only ever fail.

    Returns "user", "system", or "" when RetroArch is not installed as a flatpak.
    """
    system_root, user_root = _flatpak_system_roots()
    if sysenv.flatpak_deployed(user_root, FLATPAK_ID):
        return "user"
    if sysenv.flatpak_deployed(system_root, FLATPAK_ID):
        return "system"
    return ""


def _flatpak_installed():
    """Whether the RetroArch flatpak is actually installed.

    A leftover `~/.var/app/org.libretro.RetroArch` is deliberately not accepted as
    evidence. `flatpak uninstall` keeps user data unless `--delete-data` is given,
    so that directory routinely outlives the application -- treating it as proof
    would report RetroArch as present after it had been removed, and every launch
    would then fail.
    """
    for root in _flatpak_system_roots():
        if sysenv.flatpak_deployed(root, FLATPAK_ID):
            return True
    if shutil.which("flatpak"):
        try:
            done = subprocess.run(
                ["flatpak", "info", FLATPAK_ID],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                # Without this, flatpak dies on Steam's libcrypto and the check
                # silently reports RetroArch as absent.
                env=sysenv.clean_env(),
            )
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return False


def _flatpak_bundled_core_dirs():
    dirs = []
    for root in _flatpak_system_roots():
        base = os.path.join(root, "app", FLATPAK_ID, "current", "active", "files")
        dirs.append(os.path.join(base, "lib", "retroarch", "cores"))
        dirs.append(os.path.join(base, "share", "libretro", "info"))
    return [d for d in dirs if os.path.isdir(d)]


def parse_cfg(path):
    """RetroArch's config is a flat `key = "value"` file."""
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


def _resolve_ra_path(value, config_dir):
    """RetroArch writes `:` as a stand-in for its own config/install root."""
    if not value:
        return ""
    if value.startswith(":"):
        return os.path.normpath(os.path.join(config_dir, value[1:].lstrip("/")))
    # Not expanduser: that reads the *process* home, which is not necessarily the
    # user's. A `~/cores` in retroarch.cfg means the user's cores.
    if value.startswith("~"):
        return os.path.normpath(user_home() + value[1:])
    return value


def save_dirs(config_dir):
    """Where this RetroArch writes saves and states, as {label: absolute path}.

    **Read out of `retroarch.cfg`, never assumed from the config directory.** On
    the development Deck those keys point at `~/Emulation/saves/retroarch`, which
    EmuDeck set, while `<config>/saves` still holds an older set of files. Both
    exist; only one of them is where the next save lands. Anything that assumed
    the default would have backed up the wrong directory and said it had worked.

    Falls back to RetroArch's own defaults where a key is unset, which is what a
    RetroArch nobody has reconfigured actually uses.
    """
    cfg = parse_cfg(os.path.join(config_dir, "retroarch.cfg"))
    return {
        "saves": _resolve_ra_path(cfg.get("savefile_directory", ""), config_dir)
        or os.path.join(config_dir, "saves"),
        "states": _resolve_ra_path(cfg.get("savestate_directory", ""), config_dir)
        or os.path.join(config_dir, "states"),
    }


def _build_install(kind, config_dir, exe=None, extra_core_dirs=()):
    cfg = parse_cfg(os.path.join(config_dir, "retroarch.cfg"))

    core_dirs = []
    from_cfg = _resolve_ra_path(cfg.get("libretro_directory", ""), config_dir)
    if from_cfg:
        core_dirs.append(from_cfg)
    core_dirs.append(os.path.join(config_dir, "cores"))

    info_dirs = []
    info_cfg = _resolve_ra_path(cfg.get("libretro_info_path", ""), config_dir)
    if info_cfg:
        info_dirs.append(info_cfg)
    info_dirs.append(os.path.join(config_dir, "info"))

    core_dirs.extend(extra_core_dirs)
    info_dirs.extend(extra_core_dirs)

    if kind == "native":
        core_dirs.extend(["/usr/lib/libretro", "/usr/lib64/libretro"])
        info_dirs.append("/usr/share/libretro/info")

    # Where this plugin puts cores, whether or not it exists yet.
    #
    # Every other candidate is dropped unless it is a real directory, which is
    # right for guesses at somebody else's layout and wrong for this one: on a
    # RetroArch that has never had a core, `<config>/cores` does not exist at
    # detection, so it was dropped -- and the installer then created it, wrote
    # the core into it, and the scan that followed looked everywhere except
    # there. Installing the first core on a fresh RetroArch reported "0 core(s)
    # now available" and the core stayed invisible until a re-detect.
    #
    # Kept in step with installer.target_core_dir() by a test rather than an
    # import: installer imports this module.
    destination = os.path.normpath(os.path.join(config_dir, "cores"))

    seen = set()
    def _dedupe(paths):
        out = []
        for path in paths:
            norm = os.path.normpath(path)
            if norm and norm not in seen and (os.path.isdir(norm) or norm == destination):
                seen.add(norm)
                out.append(norm)
        return out

    return {
        "kind": kind,
        "exe": exe or "",
        "config_dir": config_dir,
        "core_dirs": _dedupe(core_dirs),
        # info dirs are deduped against a fresh set so a shared cores/info dir
        # is still reported for both roles
        "info_dirs": [
            os.path.normpath(p)
            for p in dict.fromkeys(info_dirs)
            if os.path.isdir(p)
        ],
    }


def detect_all():
    """All RetroArch installs we can find, most-likely-intended first."""
    installs = []

    if _flatpak_installed():
        installs.append(
            _build_install(
                "flatpak",
                os.path.join(_flatpak_data_dir(), "config", "retroarch"),
                exe=shutil.which("flatpak") or "/usr/bin/flatpak",
                extra_core_dirs=_flatpak_bundled_core_dirs(),
            )
        )

    native = shutil.which("retroarch")
    if native:
        installs.append(
            _build_install(
                "native",
                os.path.join(user_home(), ".config", "retroarch"),
                exe=native,
            )
        )

    for pattern in ("RetroArch*.AppImage", "retroarch*.AppImage"):
        for appimage in sorted(glob.glob(os.path.join(user_home(), "Applications", pattern))):
            installs.append(
                _build_install(
                    "appimage",
                    os.path.join(user_home(), ".config", "retroarch"),
                    exe=appimage,
                )
            )

    return installs


def detect():
    installs = detect_all()
    if not installs:
        decky.logger.warning("No RetroArch install found")
        return None
    return installs[0]


def default_rom_dir():
    """Where the ROM picker opens when nothing better is known: the transfer folder.

    This used to guess -- RetroArch's remembered browse directory, then the ROM
    folders the common emulation setups lay down, then SD-card variants of those.
    Every guess that missed dropped the user somewhere unexpected with no way to
    tell why, and none of them can be right for a library spread across several of
    those places at once. That guessing is not coming back.

    Home replaced it, on the grounds that it sits above all of them and always
    exists. What that missed is the install this answer is actually for. On a
    brand new device home holds no ROMs either, so "somewhere empty" was never
    the thing separating the two -- and of the two empty folders, one is where
    this plugin's own flow puts every file it receives. Sending a game from
    another device and then being dropped in `/home/deck` to find it is the
    friction the transfer feature exists to remove.

    Two things still win over this, and between them they cover the case home was
    kept for: `last_rom_dir` in settings, so anyone whose library is on an SD card
    goes back to it after one visit, and `waiting_dir()`, which overrides even
    that when something new has just arrived.
    """
    # Created, unlike most reads of a plugin folder: this is a path handed to a
    # file picker, and a picker opened at a directory that is not there has no
    # good behaviour. It is one folder the plugin owns outright, not one per
    # emulator, so there is no litter to leave.
    return fileserver.default_dir()


def launch_argv(install, core_path, rom_path, appendconfig=""):
    """Argv that starts `rom_path` in `core_path` for this install shape."""
    kind = install["kind"]
    if kind == "flatpak":
        argv = [install["exe"] or "flatpak", "run"]
        # The flatpak cannot see /run/media (SD card) or arbitrary folders by
        # default. Granting just the ROM's directory keeps the sandbox useful.
        for directory in _dirs_to_share(core_path, rom_path):
            argv.append("--filesystem=%s" % directory)
        if appendconfig:
            # Read-only: RetroArch only needs to read this, and it lives in the
            # plugin's own runtime directory.
            argv.append("--filesystem=%s:ro" % posixpath.dirname(appendconfig))
        argv.append(FLATPAK_ID)
    else:
        argv = [install["exe"]]

    if appendconfig:
        argv.append("--appendconfig=%s" % appendconfig)
    # **The only lever that makes RetroArch say why a game did not start.**
    #
    # Measured on a Deck against a ROM renamed out from under a game: launched
    # as the plugin launches it, RetroArch printed *nothing at all* -- one line
    # about a flatpak sandbox path and no mention of the missing file. With
    # `--verbose` it printed exactly the sentence somebody needs:
    #
    #   [ERROR] [Content] Could not read content file: "....sfc".
    #
    # `log_verbosity` in the appended config does not do it. Tried at three
    # `frontend_log_level` values, all of which produced zero lines: the config
    # key governs RetroArch's own log file, and the flag is what opens stderr.
    #
    # It costs almost nothing and nothing on screen. That whole failing run was
    # 1,923 bytes, and `hide_osd` is about on-screen notifications, which this
    # does not touch -- what it feeds is `launchers.LAUNCH_LOG_DIR`, which
    # exists because `hide_osd` took the visible channel away.
    argv.append("--verbose")
    argv.extend(["-L", core_path, rom_path])
    return argv


def _dirs_to_share(core_path, rom_path):
    # These are always absolute paths on the target system, so use posixpath
    # rather than os.path -- os.path would rewrite them if this ever runs on a
    # non-POSIX host (which is exactly what the tests do).
    shared = []
    for path in (rom_path, core_path):
        directory = posixpath.dirname(path)
        if directory and directory not in shared:
            shared.append(directory)
    return shared
