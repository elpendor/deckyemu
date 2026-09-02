"""What an emulator needs to see the Deck's own motion sensors.

Shared because none of it is about a particular emulator. Every fact here was
measured on the device, inside a running game.

Motion is **two halves and neither is worth anything alone**:

* **This file** hands the emulator the Deck's *physical* pad, the only pad on
  the machine with sensors on it.
* **The `layout` key** in the catalog entry -- `steam_layouts.DERIVED_URL` --
  powers the sensor on. Steam leaves the IMU down unless the *running game's*
  layout binds gyro to something, and the sensors then read exactly `(0, 0, 0)`,
  not noise. An entry with the environment and no layout reads a sensor that
  never moves, which looks identical to an emulator that ignores motion.

`test_catalog` asserts no entry takes one without the other.

What it costs, the same for everyone: Steam Input no longer shapes the pad.
Layouts, stick curves and the back buttons stop applying, and the Steam button
reaches the game. Trackpad-as-mouse is unaffected -- that is the X11 pointer,
which no joystick hint touches.
"""

#: The Deck's own mapping with `guide:` removed.
#:
#: Removing rather than remapping, because SDL then reports no guide button at
#: all and nothing downstream can act on one. Vita3K is why: `main_window.cpp`
#: calls `on_ps_button()` -> `on_pause_triggered()` on `SDL_GAMEPAD_BUTTON_GUIDE`,
#: which *toggles* pause. Steam normally eats the Steam button so no game sees
#: it -- but reading the physical pad means the emulator gets it, so pressing
#: Steam opened the menu and paused the emulator, and closing the menu left it
#: paused because nothing sent a second press.
#:
#: Shared even with emulators that have no such handler -- shadPS4 reads
#: `SDL_GAMEPAD_BUTTON_GUIDE` nowhere in its tree -- because the mapping is
#: otherwise the Deck's own, so it costs them nothing and there is no second
#: copy of this string to drift.
#:
#: The GUID is the crc-free form, which is what SDL falls back to when the
#: name-based checksum in the runtime GUID does not match. Verified on the
#: device, with buttons and the gyro still present afterwards.
DECK_MAPPING = (
    "03000000de2800000512000000036800,Steam Deck Controller,"
    "a:b0,b:b1,back:b4,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,dpup:h0.1,"
    "leftshoulder:b9,leftstick:b7,lefttrigger:a4,leftx:a0,lefty:a1,"
    "misc1:b11,paddle1:b12,paddle2:b13,paddle3:b14,paddle4:b15,"
    "rightshoulder:b10,rightstick:b8,righttrigger:a5,rightx:a2,"
    "righty:a3,start:b6,x:b2,y:b3,"
)

#: Steam hides the Deck's own controller (`28de:1205`) from a launched game
#: behind `SDL_GAMECONTROLLER_IGNORE_DEVICES` and publishes its virtual pad
#: instead, and that pad has no sensors: probed inside a running game,
#: `gyro=False accel=False`. Replacing the list hands the real controller back,
#: sensors included.
#:
#: The second variable is not optional. Steam's virtual pad reports the
#: *physical* pad's `28de:1205` -- `ALLOW_STEAM_VIRTUAL_GAMEPAD` is what makes
#: SDL mirror the identity -- so no ignore list can separate them and both would
#: be visible at once. With this at `0` exactly one pad is left, the real one.
#: What two pads costs depends on the emulator and is never nothing: Vita3K
#: merges them into port 1 with `axes[0] += ...`, so every stick reads double.
_MOTION_ENV = {
    "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD": "0",
    "SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x28de/0x11ff",
    "SDL_GAMECONTROLLERCONFIG": DECK_MAPPING,
}


def motion_env(**extra):
    """The environment an emulator needs to read the Deck's sensors.

    A fresh dict every call, so an entry adding its own variables cannot reach
    back into the shared one -- shadPS4 pins its Vulkan driver and preloads a
    shim through here, and a mutated module-level dict would hand both to
    Vita3K as well.
    """
    env = dict(_MOTION_ENV)
    env.update(extra)
    return env


#: The motion server, for emulators that speak DSU.
#:
#: The other half of this module, and the opposite trade. `motion_env` above
#: reaches the Deck's sensors through SDL, which means taking the physical pad
#: and giving up Steam Input for every game of that system. An emulator that
#: speaks the DSU protocol does not need that: a small server reads the
#: controller's HID frames and sends motion over a local socket, the pad stays
#: Steam's virtual one, and nothing about the layout changes.
#:
#: **Which also explains why it works where the SDL route needs a gyro layout.**
#: What reads `(0,0,0)` under a layout that binds no gyro is SDL. The hardware
#: underneath keeps producing data, and anything reading hidraw gets it -- so
#: there is no layout to pin here and no cost to decline.
#:
#: One declaration shared by every entry that wants it, and one `name`, so the
#: binary is fetched once and found by all of them. The project publishes a zip
#: rather than a bare binary, which is what `extract` is for.
DSU_SERVER = {
    "name": "gyro-dsu",
    "label": "Motion server",
    "repo": "kmicki/SteamDeckGyroDSU",
    "asset": r"^SteamDeckGyroDSUSetup\.zip$",
    "extract": r"^sdgyrodsu$",
}

#: Where it listens. The protocol's default, and both emulators are told it
#: explicitly rather than left to their own defaults -- Ryujinx drops the keys
#: from its config when the backend does not use them, so "the default" is not
#: something the file can be relied on to still say.
DSU_HOST = "127.0.0.1"
DSU_PORT = 26760
