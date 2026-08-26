import emu_config
import steam_layouts

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
        # **Not upstream, and deliberately so.** Upstream builds since roughly
        # 3830 have no working motion on a Deck, and the cause is two projects
        # disagreeing about a unit: SDL's Steam Deck driver reports sensor
        # timings in microseconds through a parameter SDL documents as
        # nanoseconds, and `motion.cpp` converts ns -> us on top of that, so the
        # elapsed time driving `UpdateOrientation`/`UpdateRotation` comes out
        # 1000x too small and the integrated orientation never moves. SDL fixed
        # its side in `e1af6236` (2025-11-12, shipped in release-3.4.x); Vita3K
        # pins a 3.2.x commit from January that predates it.
        #
        # This repository is upstream `496939b6` (build 4074) plus one commit
        # that takes the elapsed time from a monotonic clock instead, built by
        # GitHub Actions from public source. Measured on the Deck: 3829 has
        # working gyro, 3996/3998/4074 do not, this build does.
        #
        # **It is a pin, not a channel.** Upstream publishes a rolling
        # `continuous` release and this one does not, so Vita3K stops following
        # upstream while this is here -- which is the cost of the trade and the
        # reason to go back the day the fix lands upstream.
        #
        # The commit is offered upstream as Vita3K/Vita3K#4100. **When that is
        # merged, put `Vita3K/Vita3K` back here and drop the fork** -- and check
        # the merged build first, since a maintainer may take the other route
        # discussed there (bumping `external/sdl`), which fixes the same thing a
        # different way.
        "repo": "elpendor/Vita3K",
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
    # Gyro. The Vita had one and Gravity Rush is unplayable without it, and
    # every part of this was measured on the Deck with the game running --
    # nothing here is read off a wiki.
    #
    # Vita3K takes motion from SDL *gamepad* sensors only: `ctrl.cpp` calls
    # `SDL_GamepadHasSensor` and `motion.cpp` handles
    # `SDL_EVENT_GAMEPAD_SENSOR_UPDATE`. There is no DSU/cemuhook client, so
    # SteamDeckGyroDSU -- the usual answer on this hardware -- cannot reach it.
    # `disable-motion` is already false in the shipped config, so nothing in
    # the setup block above is missing; what was missing is a pad with sensors.
    #
    # Steam hides the Deck's own controller (`28de:1205`) from a launched game
    # behind `SDL_GAMECONTROLLER_IGNORE_DEVICES` and publishes its virtual pad
    # instead, and that pad has no sensors: probed inside a running Gravity
    # Rush, `gyro=False accel=False`. Overriding the list hands the real
    # controller back, sensors included.
    #
    # The second variable is not optional. Steam's virtual pad reports the
    # *physical* pad's `28de:1205` -- `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD`
    # is what makes SDL mirror the identity -- so no ignore list can separate
    # them, and both would be visible at once. Outside PSTV mode `ctrl.cpp`
    # merges every connected pad into port 1 with `axes[0] += ...`, so two pads
    # means every stick reads double and half deflection is full deflection.
    # With this at `0` exactly one pad is left, which is the real one.
    #
    # What this costs: Steam Input no longer shapes the pad for Vita games.
    # Layouts, stick curves and the back buttons stop applying, and `GUIDE`
    # reaches the game as the PS button. Trackpad-as-mouse is unaffected -- it
    # is the X11 pointer, which no joystick hint touches -- so touch still
    # works, and `touch.cpp` only reports a touch while a mouse button is held,
    # so a drifting cursor cannot fire one.
    #
    # **The layout still has to bind gyro to something.** Steam leaves the IMU
    # powered down when nothing in the running game's layout uses it, and the
    # sensors then read exactly `(0,0,0)` -- not noise, nothing at all. That is
    # not this file's to fix; the `layout` below is what switches it on.
    "env": {
        "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD": "0",
        "SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x28de/0x11ff",
        # The Deck's own mapping with `guide:` removed, and it is not cosmetic:
        # `main_window.cpp` calls `on_ps_button()` -> `on_pause_triggered()` on
        # `SDL_GAMEPAD_BUTTON_GUIDE`, which *toggles* pause. Steam normally eats
        # the Steam button so no game sees it -- but reading the physical pad
        # (above) means Vita3K gets it, so pressing Steam opened the menu and
        # paused the emulator, and closing the menu left it paused because
        # nothing sent a second press. A long press happened to send one, which
        # is why it looked like an unreliable workaround rather than a toggle.
        #
        # Removing the binding is better than remapping it: SDL then reports no
        # guide button at all, so nothing downstream can act on it. The GUID is
        # the crc-free form, which is what SDL falls back to when the name-based
        # checksum in the runtime GUID does not match -- verified on the device,
        # with buttons and the gyro still present afterwards. The Vita's PS
        # button goes with it, which no game needs and the Deck cannot send
        # anyway.
        "SDL_GAMECONTROLLERCONFIG": (
            "03000000de2800000512000000036800,Steam Deck Controller,"
            "a:b0,b:b1,back:b4,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,dpup:h0.1,"
            "leftshoulder:b9,leftstick:b7,lefttrigger:a4,leftx:a0,lefty:a1,"
            "misc1:b11,paddle1:b12,paddle2:b13,paddle3:b14,paddle4:b15,"
            "rightshoulder:b10,rightstick:b8,righttrigger:a5,rightx:a2,"
            "righty:a3,start:b6,x:b2,y:b3,"
        ),
    },
    # The other half, and the one that is not obvious: **Steam powers the Deck's
    # IMU down unless the running game's layout binds gyro to something.** The
    # sensors then read exactly `(0, 0, 0)` -- not noise, zeros -- while buttons
    # and sticks work perfectly, so it presents as an emulator that ignores
    # motion. Measured both ways on the device: with Gyro Behavior at `None` a
    # probe inside the running game reads zeros; bind it to anything and the same
    # probe reads gravity within the second.
    #
    # Derived from "Gamepad with Gyro", the one stock Deck template that binds
    # gyro at all, with the binding moved from the mouse to a stick --
    # `steam_layouts.py` does the rewriting, on the device, from the user's own
    # Steam files. Stock would work just as well at switching the sensor on
    # (`ALLOW_STEAM_VIRTUAL_GAMEPAD=0` above means Steam's gyro output reaches
    # the emulator either way), but gyro-to-mouse drifts a pointer across the
    # screen, and Vita3K reads that pointer as the Vita's touchscreen.
    #
    # Left to the user this is a setting nobody would guess, three levels into a
    # Steam menu, that silently reverts when Steam Input is toggled -- which is
    # exactly how it was lost after being set by hand. Pinned at add time
    # instead, and only over a layout Steam guessed: an explicit choice is
    # somebody's and is never touched. `steam/layout.ts`.
    "layout": steam_layouts.DERIVED_URL,
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
    "recipe": 9,
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
