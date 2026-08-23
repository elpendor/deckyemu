import emu_config

# Read off the emulator rather than the manifest, because the manifest is
# misleading. `com.supermodel3.Supermodel.yaml` carries `--persist=.supermodel`,
# and Supermodel's `FileSystemPath::GetPath` prefers `$HOME/.supermodel` when
# that directory exists -- so the paths look like they should be there. They are
# not. A first run on a Deck put the config under the XDG branch instead, and
# said so itself:
#
#   -game-xml-file=<file>  [Default: /home/deck/.var/app/com.supermodel3.Supermodel
#                                    /config/supermodel/Config/Games.xml]
#   -log-output=<outputs>  [Default: /home/deck/.var/app/com.supermodel3.Supermodel
#                                    /data/supermodel/Log/Supermodel.log]
#
# Config under `config/supermodel/Config`, everything else -- NVRAM, save
# states, the log -- under `data/supermodel`. Both inside the flatpak's own
# directory, which the reset tab already covers, so there is no `data` field
# below.
_SUPERMODEL_CONFIG = (
    ".var/app/com.supermodel3.Supermodel/config/supermodel/Config/Supermodel.ini"
)

# Supermodel writes this file itself on its first run, fully commented, with
# every input already bound to both a keyboard and a pad. That is unusual --
# most entries here exist because an emulator ships keyboard-only defaults --
# and it means the job is not to write a profile but to correct the four places
# where its defaults and a Deck disagree.
#
# What the pad numbers mean is not guesswork. `SDLInputSystem.cpp` opens the pad
# with `SDL_GameControllerOpen` and maps JOY1_BUTTONn onto a *named* button, so
# the numbering is fixed whatever the hardware:
#
#   1 A   2 B   3 X   4 Y   5 LB   6 RB   7 Back   8 Start   9 L3   10 R3
#
# and JOY1_ZAXIS is the left trigger, JOY1_RZAXIS the right.
_SUPERMODEL_GLOBAL = {
    # The whole reason the numbering above is true. Supermodel has two SDL input
    # backends and `Main.cpp` picks between them on this string alone:
    #
    #   if (selectedInputSystem == "sdl")          CSDLInputSystem(config, false)
    #   else if (... == "sdlgamepad")              CSDLInputSystem(config, true)
    #
    # and the flag is `m_useGameController`. Only the second reads the pad
    # through `SDL_GameControllerGetButton`, where JOY1_BUTTONn means a *named*
    # button. The first -- which is the default, and what a Deck was running --
    # calls `SDL_JoystickGetButton` with the raw index, and raw indices are
    # whatever order the device happens to publish.
    #
    # For Steam's virtual pad that order is not the named one. SDL's own mapping
    # for it, read off the Deck, is:
    #
    #   a:b0 b:b1 x:b2 y:b3 leftshoulder:b4 rightshoulder:b5
    #   back:b6 start:b7 guide:b8 leftstick:b9 rightstick:b10
    #
    # so under `sdl` this entry's `JOY1_BUTTON9` was raw button 8 -- **guide**,
    # the Steam button, which Steam keeps and never passes to a game. Test could
    # not fire however hard it was pressed, and every other binding here was one
    # position out of true.
    #
    # `sdlgamepad` also makes the numbering independent of the device, which is
    # the greater part of why it is right: a pad that publishes its buttons in
    # another order still has A where A is.
    "InputSystem": '"sdlgamepad"',

    # The Deck's panel. Supermodel renders at whatever this says and asks SDL
    # for a real mode change (`SDL_WINDOW_FULLSCREEN`), so the default 496x384
    # is not a window size to be scaled up -- it is the resolution the game is
    # drawn at, and gamescope stretches the result across 1280x800. The Model 3
    # is a 1998 board and the fill cost of drawing it at panel resolution is
    # nothing next to the PowerPC emulation; what it buys is a picture that is
    # not blurred. Aspect ratio is preserved by Supermodel itself, which
    # pillarboxes the 4:3 image rather than stretching it.
    #
    # Neither key exists in the file Supermodel writes, so both are appended.
    "XResolution": "1280",
    "YResolution": "800",

    # Coin and Start, moved off the stick clicks. Supermodel's defaults are
    # Start1 on L3 and Coin1 on R3, which work but are wrong twice over: they
    # are the two buttons a thumb rests against while steering, so a race picks
    # up phantom credits, and they are not where anyone has learned to look.
    # Select-inserts-coin and Start-starts is what RetroArch's arcade cores
    # bind, what every arcade frontend binds, and what someone coming to this
    # from MAME already has in their hands.
    "InputStart1": {
        "value": '"KEY_1,JOY1_BUTTON8"', "default": '"KEY_1,JOY1_BUTTON9"',
    },
    "InputCoin1": {
        "value": '"KEY_3,JOY1_BUTTON7"', "default": '"KEY_3,JOY1_BUTTON10"',
    },

    # Which frees Back and Start, and they had to be freed: the 4-speed shifter
    # claims buttons 5 to 8 by default, so with the two lines above and nothing
    # else, starting a game would also drop it into fourth gear.
    #
    # The gears go back to the keyboard rather than somewhere else on the pad
    # because the sequential shifter can drive them. `Inputs.cpp` builds the
    # 4-speed box as `AddGearShift4Input(..., shift1, shift2, shift3, shift4,
    # shiftN, gearShiftUp, gearShiftDown)` -- up and down are inputs to the same
    # control, so two shoulder buttons cover every gear in Daytona USA 2, Sega
    # Rally 2 and Scud Race without spending four face buttons on them.
    "InputGearShift1": {"value": '"KEY_Q"', "default": '"KEY_Q,JOY1_BUTTON5"'},
    "InputGearShift2": {"value": '"KEY_W"', "default": '"KEY_W,JOY1_BUTTON6"'},
    "InputGearShift3": {"value": '"KEY_E"', "default": '"KEY_E,JOY1_BUTTON7"'},
    "InputGearShift4": {"value": '"KEY_R"', "default": '"KEY_R,JOY1_BUTTON8"'},
    "InputGearShiftUp": {"value": '"KEY_Y,JOY1_BUTTON6"', "default": '"KEY_Y"'},
    "InputGearShiftDown": {"value": '"KEY_H,JOY1_BUTTON5"', "default": '"KEY_H"'},

    # Test and Service, onto the stick clicks that moving Coin and Start freed.
    #
    # These are the two buttons inside a real cabinet's coin door, and every
    # other emulator here would leave them alone -- but on this board they are
    # not an operator's convenience, they are the only way into the game's own
    # settings, and some Model 3 games do not start without going there. Daytona
    # USA 2 is one: a fresh NVRAM has it configured as a linked cabinet, so it
    # stops at "CANCELLED / NETWORK BOARD NOT PRESENT" and stays there. Read off
    # the emulated framebuffer on a Deck, not guessed.
    #
    # The way out, confirmed by the user against the running game: open the test
    # menu, go to **Game System**, and change **Link ID** from Master to Single.
    # It is written to NVRAM, so it is done once. Test is `KEY_6` and Service is
    # `KEY_5` in Supermodel's own defaults, which is what every guide to this
    # says to press -- so the two pad bindings below are those two keys and
    # nothing new to learn.
    #
    # Supermodel binds them to the keyboard and nothing else, which in Game Mode
    # means they do not exist. That is §1a exactly: a feature that needs a
    # keyboard needs an in-panel alternative, and here the alternative is a pad
    # binding.
    #
    # L3 and R3 rather than a combination, because the operator menus are
    # *navigated* with these two and a combination that fires its own components
    # on the way in cannot work. They are the only pad buttons no Model 3 game
    # uses -- the face buttons are views and punches, the shoulders shift, the
    # triggers are the pedals -- and a stick click is a deliberate press rather
    # than something a resting thumb does.
    "InputTestA": {"value": '"KEY_6,JOY1_BUTTON9"', "default": '"KEY_6"'},
    "InputServiceA": {"value": '"KEY_5,JOY1_BUTTON10"', "default": '"KEY_5"'},

    # The pedals, onto the triggers. Both are `AddAnalogInput` in Inputs.cpp,
    # and the Deck's triggers are analog, while Supermodel's default binds them
    # to the D-pad -- so out of the box every racer on the board, which is most
    # of what the board is, has on-or-off throttle and no way to feather it.
    "InputAccelerator": {
        "value": '"KEY_UP,JOY1_RZAXIS_POS"', "default": '"KEY_UP,JOY1_UP"',
    },
    "InputBrake": {
        "value": '"KEY_DOWN,JOY1_ZAXIS_POS"', "default": '"KEY_DOWN,JOY1_DOWN"',
    },
}

_SUPERMODEL_SETUP = {
    "format": emu_config.PLAIN_INI,
    "label": "resolution and controller bindings",
    #   1  resolution, coin and start, the shifter, the pedals
    #   2  Test and Service on the stick clicks, without which the operator
    #      menus are unreachable from Game Mode and a linked game such as
    #      Daytona USA 2 cannot be made to start at all
    #   3  `sdlgamepad`, without which none of the button numbers above mean
    #      what they say and Test landed on the Steam button
    "version": 3,
    "path": _SUPERMODEL_CONFIG,
    # `Global` with no spaces, though Supermodel writes `[ Global ]`. Both are
    # the same section: its own `FromINIFile` trims the name before looking it
    # up, and `_split_sections` now does the same.
    "sections": {"Global": _SUPERMODEL_GLOBAL},
}

ENTRY = {
    "id": "supermodel",
    "name": "Supermodel",
    "summary": "Sega Model 3 arcade. Demanding, and 63 games exist.",
    "source": {"kind": "flatpak", "id": "com.supermodel3.Supermodel"},
    # No libretro database and no core: MAME has Model 3 drivers and they do not
    # play the games, so this is the only way any of these run. Hence a platform
    # label rather than `databases`, and `MANUAL_EXTENSIONS` carrying `zip`.
    "databases": [],
    "platform": "Sega - Model 3",
    # `-game-xml-file` is not a refinement. Without it this emulator installs
    # and cannot run anything, and it says so on a Deck:
    #
    #   Error: Failed to parse .../config/supermodel/Config/Games.xml
    #          (XML_ERROR_FILE_NOT_FOUND).
    #   Error: Game and ROM set definitions could not be loaded! ROMs will not
    #          be detected.
    #
    # Games.xml is what tells Supermodel which chip dump is which for each of
    # the 63 sets, and the flatpak puts its copy in `/app/bin/Config` while
    # `FileSystemPath::GetPath(Config)` looks under the app's own config
    # directory. Nothing bridges the two, so a stock install detects no ROM at
    # all. Pointing at the packaged copy fixes it and keeps fixing it: `/app` is
    # whatever version of the build is installed, where a copy taken at install
    # time would go stale the next time the flatpak updated.
    #
    # Then the ROM set, and the archive stays an archive. Supermodel's own usage
    # line says "ROM set must be a valid ZIP file containing a single game" --
    # it opens the zip and reads the chip dumps out of it by name, the way MAME
    # does, so unpacking one destroys it. `ra_cores.is_romset` is what keeps the
    # Unpack row out of the panel for these, and what stops the file being
    # matched on whatever the first chip dump inside happens to be called.
    "args": "-game-xml-file=/app/bin/Config/Games.xml {rom}",
    # The same packaging fault as Games.xml, one step worse, because there is no
    # flag for this one. `CCrosshair::Init` loads both crosshair bitmaps out of
    # `FileSystemPath::GetPath(Assets)` unconditionally -- whatever
    # `-crosshairs` and `-crosshair-style` say -- and `Main.cpp` treats a
    # failure as fatal:
    #
    #   Error: Unable to load bitmap crosshair texture
    #
    # The flatpak puts them in `/app/bin/Assets` and the emulator looks under
    # its own data directory, so out of the box every game on this build loads
    # its ROM set, opens a window, and quits before the emulator is built. On a
    # Deck that is a shortcut that flashes and returns to the library.
    "seed": {
        "bin/Assets":
            ".var/app/com.supermodel3.Supermodel/data/supermodel/Assets",
    },
    "fullscreen_args": "-fullscreen",
    # Steam's own on-screen keyboard, kept off the game.
    #
    # It opened over Daytona USA 2 and stayed there, and the chain is entirely
    # inside SDL2 rather than anything this plugin does. Steam sets `SteamDeck=1`
    # in every game's environment; `SDL_x11video.c` reads that into
    # `is_steam_deck`, which makes `X11_HasScreenKeyboardSupport` true and points
    # `ShowScreenKeyboard` at a deeplink:
    #
    #   steam://open/keyboard?XPosition=0&YPosition=0&Width=0&Height=0&Mode=1
    #
    # and `SDL_StartTextInput` calls it whenever
    # `SDL_GetHintBoolean(SDL_HINT_ENABLE_SCREEN_KEYBOARD, SDL_TRUE)` -- note the
    # default -- is on and a window has focus. Supermodel never asks for text
    # input itself; the call comes from the ImGui SDL2 backend it bundles.
    #
    # Confirmed rather than reasoned: that exact URL is in the Deck's own
    # `~/.steam/steam/logs/console_log.txt`, timestamped to each launch.
    #
    # Turning the hint off suppresses the keyboard and nothing else -- text
    # input still works for anything that reads it, which here is nothing.
    #
    # And the pad, which without the second line does nothing at all.
    #
    # SDL2 drops every joystick event while the window has no input focus:
    # `SDL_joystick_allows_background_events` in `SDL_joystick.c` defaults to
    # false and gates the lot. Supermodel never asks for focus -- `Main.cpp`
    # calls `CreateGLScreen(..., focusWindow=false, ...)`, so `SDL_RaiseWindow`
    # is never reached -- and under gamescope the window it opens does not have
    # it. The emulator then reads a pad it has open, from a binding that is
    # correct, and sees nothing move.
    #
    # Measured on the Deck end to end, because every step of it looks fine on
    # its own: Steam's virtual pad reports A, L3 and R3 to `/dev/input/event10`
    # (captured while the buttons were pressed), Supermodel has that same device
    # open, nothing holds an exclusive grab, and `-print-inputs` reports
    # `Test A = KEY_6,JOY1_BUTTON9`. The corroboration was in an earlier
    # session: injected keystrokes reached this emulator only after an explicit
    # `xdotool windowactivate`, which is the same fault wearing a keyboard.
    "env": {
        "SDL_ENABLE_SCREEN_KEYBOARD": "0",
        "SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS": "1",
    },
    #   1  the first recipe
    #   2  the environment above. `env` only reaches an installed emulator when
    #      the recipe moves, so without this the keyboard stays.
    #   3  and the pad, which needs the same environment to work at all
    "recipe": 3,
    "setup": _SUPERMODEL_SETUP,
    # No firmware. A Model 3 ROM set is self-contained -- the boot ROM is one of
    # the chip dumps inside it -- so unlike xemu or the PlayStation entries there
    # is nothing separate for the user to supply.
    #
    # Not verified: confirming a launch recipe means watching a game boot, and
    # that needs a ROM set this project will never hold. What has been checked
    # on a Deck is everything either side of it. The flatpak installs and writes
    # the config named above. Handed a path with a space in it and `-fullscreen`
    # after it, Supermodel parses both and fails only on the file itself
    # ("Could not open '/tmp/My Game.zip'"), so neither the argument order nor
    # the quoting is in question. And with `-game-xml-file` as set above,
    # `-print-games` lists all 63 sets instead of reporting that none can be
    # detected -- which is the difference between this entry working and not.
    "verified": False,
    "note": "Send the ROM set as a .zip and leave it zipped -- Supermodel reads "
            "the chip dumps out of the archive, so unpacking one makes it "
            "unplayable. Model 3 is a demanding board and the racers are the "
            "heaviest of it; expect some games to run below full speed. "
            "Arcade Test and Service are the stick buttons: push the LEFT "
            "STICK straight down until it clicks (L3) for Test, and the RIGHT "
            "STICK for Service. Not moving the stick -- pressing it in. "
            "Daytona USA 2 needs them: it stops at \"network board not "
            "present\" until you press Test, go to Game System, and change "
            "Link ID from Master to Single.",
}
