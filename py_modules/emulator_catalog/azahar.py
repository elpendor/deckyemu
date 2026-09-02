import emu_config

from . import deck_gyro
from .steam_pad import (
    _PAD_A,
    _PAD_B,
    _PAD_BACK,
    _PAD_SHOULDER_L,
    _PAD_SHOULDER_R,
    _PAD_START,
    _PAD_TRIGGER_L,
    _PAD_TRIGGER_R,
    _PAD_X,
    _PAD_Y,
    _pad_button,
    _pad_hat,
    _pad_stick,
    _pad_trigger,
)

# Azahar ships keyboard bindings and starts windowed, so a fresh install
# launched from Steam is a window the Deck's controls do nothing to.
#
# The assignments match a published configuration for this emulator on this
# hardware, which is a tested arrangement rather than a reading of a button
# table. Face buttons go by *position*, not label: the 3DS has A on the right and
# B at the bottom, which is where the Deck prints B and A, so matching the
# letters would put every 3DS prompt on the wrong physical button. L and R land
# on the triggers and ZL/ZR on the shoulders, which is that config's choice --
# swap them in the editor if the physical correspondence matters more.
#
# Keys are emitted in the alphabetical order Azahar itself serialises them in,
# so a value it rewrites on exit is byte-identical to the one written here and
# re-applying stays a no-op.
_AZAHAR_SETUP = {
    "format": emu_config.QT_INI,
    "path": ".config/azahar-emu/qt-config.ini",
    "label": "controller bindings and fullscreen",
    # Bumped whenever these values change, so an emulator already installed
    # picks them up at the next startup. Without it the only route to a
    # corrected setting is reinstalling the emulator, which for an AppImage is a
    # hundred megabytes to rewrite a dozen config lines -- and the first version
    # of these bindings was wrong, so that route mattered immediately.
    #
    #   1  bindings using maptype:all, which the released Azahar ignores
    #   2  bound to Steam Input's virtual pad, matching the tested config
    #   3  motion taken from the gyro server instead of Azahar's mouse-driven
    #      fake, so the 3DS games built around tilting one actually tilt
    "version": 3,
    # Bindings an earlier version of this plugin wrote, before it recorded what
    # it had written. They were wrong -- `maptype:all` does not exist in the
    # released Azahar -- and without this they would be mistaken for the user's
    # own choices and left in place forever. Nothing but this plugin has ever
    # written that string, so it cannot claim a real user binding.
    "superseded": (r"engine:sdl,maptype:all,api:controller",),
    "sections": {
        "UI": {"fullscreen": "true"},
        "Controls": {
            r"profiles\1\button_a": _pad_button(_PAD_B),
            r"profiles\1\button_b": _pad_button(_PAD_A),
            r"profiles\1\button_x": _pad_button(_PAD_Y),
            r"profiles\1\button_y": _pad_button(_PAD_X),
            r"profiles\1\button_l": _pad_trigger(_PAD_TRIGGER_L),
            r"profiles\1\button_r": _pad_trigger(_PAD_TRIGGER_R),
            r"profiles\1\button_zl": _pad_button(_PAD_SHOULDER_L),
            r"profiles\1\button_zr": _pad_button(_PAD_SHOULDER_R),
            r"profiles\1\button_start": _pad_button(_PAD_START),
            r"profiles\1\button_select": _pad_button(_PAD_BACK),
            r"profiles\1\button_up": _pad_hat("up"),
            r"profiles\1\button_down": _pad_hat("down"),
            r"profiles\1\button_left": _pad_hat("left"),
            r"profiles\1\button_right": _pad_hat("right"),
            r"profiles\1\circle_pad": _pad_stick(0, 1),
            r"profiles\1\c_stick": _pad_stick(3, 4),
            # The 3DS had a gyroscope and an accelerometer, and Azahar ships
            # `motion_emu` -- a fake driven by dragging the mouse, which on a
            # handheld with no mouse is no motion at all. `cemuhookudp` is the
            # real one, fed by the server in `ENTRY["motion"]`.
            #
            # Every key here arrives with Qt's `default` flag still set, so
            # unlike some emulators this needs no step from the user. The
            # address and port are already what the server binds, and they are
            # restated rather than assumed for the reason `_CEMU_SETTINGS`
            # restates its own: a value we depend on is one to write, not one to
            # hope stays put.
            r"profiles\1\motion_device": '"engine:cemuhookudp"',
            r"profiles\1\udp_input_address": deck_gyro.DSU_HOST,
            r"profiles\1\udp_input_port": str(deck_gyro.DSU_PORT),
            # Slot 0 is the pad the server serves.
            r"profiles\1\udp_pad_index": "0",
        },
    },
}

ENTRY = {
    "id": "azahar",
    "name": "Azahar",
    "summary": "Nintendo 3DS. The continuation of Citra and Lime3DS.",
    # No Flathub entry, so this is the AppImage. Deliberately the plain
    # build rather than azahar-wayland: Game Mode runs gamescope, and the
    # X11 build goes through XWayland, which is the better-tested path.
    "source": {
        "kind": "github",
        "repo": "azahar-emu/azahar",
        "asset": r"^azahar\.AppImage$",
    },
    # Config under one, the NAND, keys, installed titles and saves under
    # the other. Both, or a reset leaves the half that holds the games.
    "data": [".config/azahar-emu", ".local/share/azahar-emu"],
    "databases": ["Nintendo - Nintendo 3DS"],
    "args": "{rom}",
    # Azahar has no fullscreen flag at all -- it is a config setting, which
    # is what `setup` is for.
    "fullscreen_args": "",
    # The 3DS is the third system here whose motion reaches the emulator over a
    # local socket rather than through SDL, so the pad stays Steam's virtual one
    # and Steam Input keeps working. See `deck_gyro.DSU_SERVER`.
    #
    # Confirmed in the shipped build rather than assumed: `cemuhookudp` is in
    # the AppImage's own 39MB binary, and Azahar already defaults its UDP
    # address and port to exactly what the server binds.
    "motion": {
        "server": deck_gyro.DSU_SERVER,
        "verify": {
            "path": ".config/azahar-emu/qt-config.ini",
            "contains": "cemuhookudp",
        },
    },
    "setup": _AZAHAR_SETUP,
    "verified": True,
    "firmware": [
        {
            "name": "aes_keys.txt",
            "note": "Only needed for encrypted dumps and eShop titles.",
            "match": r"(?i)^(aes_keys\.txt|seeddb\.bin)$",
            "expects": "aes_keys.txt, and seeddb.bin if you have it.",
            # Confirmed on a real install: Azahar creates this folder itself.
            "dest": ".local/share/azahar-emu/sysdata",
        }
    ],
}
