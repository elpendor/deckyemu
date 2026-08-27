import emu_config
import steam_layouts
from . import deck_gyro

_VITA3K_CONFIG = ".config/Vita3K/config.yml"

_VITA3K_SETUP = {
    "format": emu_config.YAML_KEYS,
    "label": "startup settings",
    #   1  validation layers off and the first-run wizard answered
    #   2  the missing-firmware modal answered in advance
    #   3  reapplied, because 2 recorded itself against a config it had just
    #      broken: the write "succeeded" into a file Vita3K then refused, the
    #      version was stored, and needs_setup answered no forever afterwards
    #   4  show-welcome, the modal that was stopping every launch
    "version": 4,
    "path": _VITA3K_CONFIG,
    "sections": {
        # The dialog that cost an evening. `confirm_missing_firmware_warning`
        # in main_window.cpp pops "Firmware is not fully installed" whenever
        # vs0 or sa0 looks empty, with Cancel as the *default* button -- and
        # gamescope only composites windows Steam launched, so from a shortcut
        # it is invisible. Every launch that appeared to hang was waiting on an
        # answer to a question nobody could see.
        #
        # Answered rather than depended upon: the firmware rows below install
        # both halves, so by the time a game runs the warning has nothing to
        # warn about. This is for the gap in between, and for the case where
        # somebody installs a game before the firmware.
        "warn-missing-firmware": {"value": "false", "default": "true"},
        # Vita3K ships with Vulkan validation layers on. They exist to tell an
        # emulator's developers about API misuse and they cost real frames to
        # do it -- the same family of default as shadPS4 choosing a software
        # renderer, which cost every game on this Deck its framerate until it
        # was found.
        "validation-layer": {"value": "false", "default": "true"},
        # Vita3K shows a first-run wizard, which in Game Mode is a dialog in
        # front of the game with no keyboard to answer it. `false` means it has
        # not been done yet; saying it has is what skips it. The wizard's real
        # job -- installing firmware -- has its own row in the panel.
        "initial-setup": {"value": "true", "default": "false"},
        # The one that actually mattered, and the one I never found: a separate
        # welcome screen from the wizard above, sitting at line 126 of a config
        # I had only ever read the first seventy lines of.
        #
        # It is why `-r <TITLE_ID>` appeared to do nothing for an entire
        # evening. Vita3K parsed the argument, logged it, queued the boot on a
        # zero-delay timer -- and put a modal in front of it that gamescope
        # never composited, because gamescope only draws windows Steam
        # launched. With this false, the same command boots the game.
        "show-welcome": {"value": "false", "default": "true"},
    },
}

ENTRY = {
    "id": "vita3k",
    "name": "Vita3K",
    "summary": "PlayStation Vita. Experimental.",
    "source": {
        "kind": "github",
        # Upstream's own build repository, not `Vita3K/Vita3K`.
        #
        # Same project, same artifact -- release 4074 here is byte-identical to
        # the `continuous` asset on the main repo, checked by sha256. What it
        # adds is a *tag per build*: 4074, 4073, 4072, back past 3829. The main
        # repo publishes one rolling `continuous` release, and a build with no
        # number cannot be compared with anything.
        #
        # Three things follow. The build record stops saying `continuous` and
        # starts saying which build. The build picker works, so a user can drop
        # back to a known-good one -- 3829 has working motion with no fix at
        # all. And `fixed_in` becomes checkable, which is the whole reason the
        # panel can say a fix is no longer needed without guessing.
        #
        # This used to name a fork, because upstream builds since roughly 3830
        # have no working motion on a Deck. That is handled below now, as four
        # bytes applied to upstream's own build.
        "repo": "Vita3K/Vita3K-builds",
        # aarch64 builds are published beside the x86_64 one, and installing
        # the wrong architecture fails at exec time with nothing useful.
        "asset": r"^Vita3K-x86_64\.AppImage$",
    },
    # Two directories, and the small one is the misleading one: the config
    # is 24KB of yaml under .config, while the games, firmware, fonts and
    # saves are 215MB under .local/share.
    "data": [".config/Vita3K", ".local/share/Vita3K"],
    "databases": [],
    "platform": "Sony - PlayStation Vita",
    # The positional path is documented as "Path to the app with a .vpk/.zip
    # extension or folder of content to install & run", so one argument both
    # installs and starts a release. Read off the binary's own --help.
    "args": "{rom}",
    # `-F, --fullscreen`. This was empty, which is a plain omission rather
    # than an emulator without the flag -- every game opened windowed.
    "fullscreen_args": "--fullscreen",
    # How an installed title is started, which is not by path. `-r` takes
    # the title id; combined with --fullscreen this is the `-Fr` other
    # launchers use, arrived at independently. A title id never contains a space,
    # which matters because Vita3K's AppImage word-splits its arguments.
    "installed_args": "-r {title}",
    # And here is why it does, read off the AppImage rather than inferred: its
    # `AppRun.wrapped` ends in `"${APPDIR}/usr/bin/Vita3K" $@`, with `$@`
    # unquoted. Every path handed to it therefore has to be free of spaces --
    # the title id above is one answer, and `emulators.space_free` is the other,
    # for the package and firmware installs, which have no id to use instead.
    "splits_args": True,
    # Motion, and the only part of this entry a user can switch off.
    #
    # The Vita had a gyro and Gravity Rush is unplayable without one. Every part
    # of this was measured on the Deck with the game running -- nothing here is
    # read off a wiki.
    #
    # Vita3K takes motion from SDL *gamepad* sensors only: `ctrl.cpp` calls
    # `SDL_GamepadHasSensor` and `motion.cpp` handles
    # `SDL_EVENT_GAMEPAD_SENSOR_UPDATE`. There is no DSU/cemuhook client, so
    # SteamDeckGyroDSU -- the usual answer on this hardware -- cannot reach it.
    # `disable-motion` is already false in the shipped config, so nothing in the
    # setup block above is missing; what was missing is a pad with sensors.
    #
    # Why these variables and what they cost is in `deck_gyro`, because none of
    # it is Vita-specific. The two costs that are: Vita3K merges every connected
    # pad into port 1 outside PSTV mode, so the virtual pad left visible
    # alongside the real one doubles every stick; and `touch.cpp` only reports a
    # touch while a mouse button is held, so the trackpad still works as the
    # Vita's touchscreen and a drifting cursor cannot fire one.
    #
    # Vita3K needs no axis correction, unlike shadPS4: `motion.cpp` already
    # rotates SDL's gamepad frame into the console's in its `from_gamepad`
    # branch, which is the same rotation `shim/gyroshim.c` applies for PS4.
    #
    # What it does need is the third half, and the reason `apply.patch` exists.
    # Reaching the Deck's sensors is not enough, because upstream cannot
    # integrate what it reads: SDL's Steam Deck driver reports sensor timings in
    # microseconds through a parameter SDL documents as nanoseconds, and
    # `motion.cpp` converts ns -> us on top of that, so the elapsed time driving
    # `UpdateOrientation`/`UpdateRotation` comes out 1000x too small and the
    # orientation never moves. Measured on the Deck: 3829 works, 3996/3998/4074
    # do not. SDL fixed its side in `e1af6236` (2025-11-12, in release-3.4.x);
    # Vita3K bundles 3.2.30, and that branch never got the backport.
    #
    # shadPS4 takes its motion fix as an `LD_PRELOAD` because it links SDL
    # dynamically. Vita3K compiles SDL in -- `ldd` names none -- so no shim,
    # hint or variable can reach this, and the file is the only seam there is.
    "workarounds": [{
        "id": "vita-motion",
        "name": "Motion controls",
        # Both halves, because both are true and the second is the one that
        # explains why this fix has to touch the emulator's own files. Said in
        # what it looks like rather than what it is: a user does not need the
        # word microsecond to understand "reads it too slowly to notice".
        "because": "Steam hands a launched game a virtual pad with no sensors "
                   "on it, and leaves the Deck's own motion sensor powered "
                   "down unless the game's layout uses gyro -- and Vita3K then "
                   "reads that sensor a thousand times too slowly to see it "
                   "move at all.",
        "upstream": "https://github.com/Vita3K/Vita3K/pull/4100",
        "costs": "Steam Input stops shaping the pad for every Vita game -- "
                 "remapped buttons, stick curves and the back buttons stop "
                 "applying, including in games that have no motion at all.",
        # Off unless asked for, like shadPS4's. Vita games want motion more
        # often than PS4 games do, but the cost is the same and is paid by
        # every Vita game either way.
        "default": False,
        "apply": {
            # Four bytes, applied to upstream's own build at install and kept
            # beside it, so switching this off runs exactly what upstream
            # shipped. `motion.cpp` reads
            #   sensor.sensor_timestamp > 0 ? to_microseconds(...) : steady_clock
            # so a *zero* timestamp routes it onto the monotonic clock -- the
            # same behaviour the fork's commit reached from the other side.
            # `add (%r12),%ecx` becomes `xor %ecx,%ecx; nop; nop`, the next
            # instruction stores the zero back, and both `SDL_SendJoystickSensor`
            # calls in that function then pass 0.
            #
            # `within` is what makes it safe rather than lucky: those four bytes
            # occur nine times in the 54MB binary and exactly once inside this
            # function. Verified against two independent compiles, which placed
            # the function 0x400 apart and were otherwise byte-identical.
            "patch": {
                "file": "usr/bin/Vita3K",
                "within": "HIDAPI_DriverSteamDeck_UpdateDevice",
                "find": "41030c24",
                "replace": "31c99090",
            },
            "env": deck_gyro.motion_env(),
            # The other half, and the one that is not obvious: Steam powers the
            # Deck's IMU down unless the running game's layout binds gyro to
            # something, and the sensors then read exactly `(0, 0, 0)` -- not
            # noise, zeros -- while buttons and sticks work perfectly. Measured
            # both ways on the device: with Gyro Behavior at `None` a probe
            # inside the running game reads zeros; bind it to anything and the
            # same probe reads gravity within the second.
            #
            # Derived from "Gamepad with Gyro", the one stock Deck template that
            # binds gyro at all, with the binding moved from the mouse to a
            # stick -- `steam_layouts.py` does the rewriting, on the device,
            # from the user's own Steam files. Stock would switch the sensor on
            # just as well, but gyro-to-mouse drifts a pointer across the screen
            # and Vita3K reads that pointer as the Vita's touchscreen.
            "layout": steam_layouts.DERIVED_URL,
        },
    }],
    #   2  the fullscreen flag, which was missing entirely
    #   3  installed titles launch by id rather than by path
    #   4  splits_args, so an install already on the device stops handing this
    #      emulator paths it will re-split -- the field is refreshed only when
    #      this number moves, so adding one without the other reaches nobody
    #   5  and the same for the file extensions: dropping .vpk from the catalog
    #      left every installed copy still claiming it, so the picker went on
    #      offering to run one
    #   6  the environment above, which is how the Deck's gyro reaches a Vita
    #      game. `env` only travels to an installed emulator when this number
    #      moves, and until this release it never travelled to an AppImage at
    #      all -- `launch_argv` dropped it
    #   7  the layout above, which travels by the same rule the environment
    #      does: added without moving this number, it reached the catalog and
    #      no installed emulator, so a freshly added game came up on whatever
    #      Steam guessed and its gyro stayed powered down
    #   8  and that layout moved from Steam's stock gyro template to one derived
    #      from it, because the stock one aims the gyro at the mouse and the
    #      pointer it drags around is the Vita's touchscreen
    #   9  the controller mapping, without which pressing Steam paused the
    #      emulator and closing the menu left it paused
    #  10  back to upstream's own builds. The motion fix moved out of `source`
    #      and into the workaround as four bytes, so this stops being a pin --
    #      but only a recipe bump reaches an install still sitting on the fork
    "recipe": 10,
    "setup": _VITA3K_SETUP,
    # Booted on a Deck: firmware and font fetched and imported headlessly, a
    # .pkg installed with its zRIF, and the game started from its Steam
    # shortcut by title id. Nothing here is a reading of the documentation
    # any more.
    "verified": True,
    # An earlier version of this note said Vita3K ignores its command line.
    # It does not. Every test that said so was run against `show-welcome`,
    # a modal gamescope never composited because Steam had not launched the
    # window -- Vita3K parsed the argument, queued the boot, and waited on a
    # dialog nobody could see. With the setup block applied, `-Fr
    # <TITLE_ID>` boots the game.
    "note": (
        "Install games through Vita3K's own interface -- it decrypts them as "
        "it installs, so copying files in does not work. Once installed they "
        "can be added to Steam and launched directly."
    ),
    "firmware": [
        {
            "name": "PS Vita firmware",
            "note": "Sony publish it freely, so this one can be downloaded.",
            # PSVUPDAT.PUP only. An earlier version of this accepted
            # PSP2UPDAT.PUP as an alias, which was wrong twice over: they
            # are two different files, and the second one is the font
            # package below. Matching both here would have made each row
            # claim the other's download.
            "match": r"(?i)^PSVUPDAT\.PUP$",
            "expects": "PSVUPDAT.PUP -- or press download and it is "
            "fetched from Sony.",
            # Pinned rather than read from an index, unlike the PS3's: the
            # Vita's last firmware was 3.74 in February 2022 and there will
            # not be another, so the address Sony's own support page gives
            # is as permanent as an address gets.
            "fetch": {
                "kind": "url",
                "url": "http://dus01.psv.update.playstation.net/update/psv/image"
                       "/2022_0209/rel_f2c7b12fe85496ec88a0391b514d6e3b/PSVUPDAT.PUP",
                "name": "PSVUPDAT.PUP",
            },
            # The two module trees the firmware PUP writes. Neither exists
            # before it runs -- both appeared in the listing taken after a
            # real install, and the font package puts its files in sa0
            # rather than either of these. Nothing of the user's is in
            # them: games and saves are under ux0.
            "removes": [
                ".local/share/Vita3K/Vita3K/os0",
                ".local/share/Vita3K/Vita3K/vs0",
            ],
            # `--firmware <path>`, run on a Deck: six seconds, exit 0,
            # "Firmware installation progress: 100%", nothing to press.
            "import": {
                "args": ["--firmware", "{file}"],
                # What that run left behind, chosen by taking the directory
                # listing before and after. os0 does not exist at all until
                # firmware is installed, and this is the one plain file in
                # it -- the rest are directories.
                "installed": ".local/share/Vita3K/Vita3K/os0/psp2bootconfig.skprx",
                # Vita3K records the version nowhere on disk. It logs
                # "Firmware Version: 0x3740000" and keeps it to itself, so
                # the row says what is installed rather than which build.
                "seconds": 900,
                # Vita3K's Qt aborts with "could not connect to display"
                # before it has looked at its arguments, so even this --
                # which opens no window and draws nothing -- needs the
                # session's display handed to it.
                "needs_display": True,
            },
        },
        {
            # The second thing Vita3K needs and the reason its welcome
            # screen keeps coming back: without fonts it reports itself
            # unconfigured, and it says so nowhere except in that screen.
            # A separate PUP from the firmware, despite both being 2022_0209
            # and both installing through --firmware.
            "name": "PS Vita font package",
            "note": "Vita3K will not consider itself set up without it.",
            "match": r"(?i)^PSP2UPDAT\.PUP$",
            "expects": "PSP2UPDAT.PUP -- or press download and it is "
            "fetched from Sony.",
            # Vita3K's own downloader fails here with a certificate error,
            # because Sony serve this over plain http and it is requested
            # over https. Fetching it ourselves at the address Vita3K's own
            # quickstart gives sidesteps that entirely.
            "fetch": {
                "kind": "url",
                "url": "http://dus01.psp2.update.playstation.net/update/psp2/image"
                       "/2022_0209/sd_59dcf059d3328fb67be7e51f8aa33418"
                       "/PSP2UPDAT.PUP?dest=us",
                "name": "PSP2UPDAT.PUP",
            },
            # All 178 of them are under sa0, and sa0 holds nothing else.
            "removes": [".local/share/Vita3K/Vita3K/sa0"],
            "import": {
                "args": ["--firmware", "{file}"],
                # 178 files under sa0, all fonts and dictionaries. This is
                # the Latin font every game needs, taken from the listing
                # after a real install rather than from a guess.
                "installed": ".local/share/Vita3K/Vita3K/sa0/data/font/pvf/ltn0.pvf",
                "seconds": 900,
                "needs_display": True,
            },
        }
    ],
}
