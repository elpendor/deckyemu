import emu_config

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
        "repo": "Vita3K/Vita3K",
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
    #   2  the fullscreen flag, which was missing entirely
    #   3  installed titles launch by id rather than by path
    "recipe": 3,
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
