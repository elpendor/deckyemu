"""The Steam Input pad, and how to name one of its buttons in a config file.

Shared because it is the same pad for every emulator: a game launched from Steam
never sees the Deck's own controller, only the virtual one Steam presents. An
emulator module needs these when it writes controller bindings by GUID.
"""

# Steam Input's virtual gamepad, which is the only pad a game launched from
# Steam ever sees: Steam hides the Deck's own controller (28de:1205) through
# SDL_GAMECONTROLLER_IGNORE_DEVICES and presents this instead.
#
# Safe to hardcode despite the CRC in bytes 2-3. That CRC is SDL's checksum of
# the name the kernel reports for the pad, which is "Microsoft X-Box 360 pad 0"
# -- crc16 of exactly that string is 0xf679, the 79 f6 sitting in bytes 2 and 3.
# Confirmed by computing it, not by assuming it: an earlier note here named the
# wrong string, and RPCS3 binds against that same kernel name directly, where a
# wrong guess would be silent.
#
# An earlier attempt used `maptype:all,api:controller`, which binds to any pad
# and needs no GUID. That exists only on Azahar's master branch: release
# 2125.1.3 reads `params.Get("guid", "0")` and resolves "0" to a placeholder
# joystick, so every button read returned false and nothing responded. Verify
# against the tag that is actually installed, not against master.
_STEAM_PAD_GUID = "030079f6de280000ff11000001000000"

# Read off the device with SDL_GameControllerMappingForGUID, so these are the
# pad's real indices rather than the GameController abstraction's:
#
#   a:b0 b:b1 x:b2 y:b3  back:b6 start:b7  leftshoulder:b4 rightshoulder:b5
#   lefttrigger:a2 righttrigger:a5  leftx:a0 lefty:a1  rightx:a3 righty:a4
#   dpup:h0.1 dpright:h0.2 dpdown:h0.4 dpleft:h0.8
#
# The D-pad is a hat and the right stick is axes 3/4, neither of which matches
# the GameController numbering.
_PAD_A, _PAD_B, _PAD_X, _PAD_Y = 0, 1, 2, 3
_PAD_SHOULDER_L, _PAD_SHOULDER_R = 4, 5
_PAD_BACK, _PAD_START = 6, 7
_PAD_TRIGGER_L, _PAD_TRIGGER_R = 2, 5

def _pad_button(index):
    return '"button:%d,engine:sdl,guid:%s,port:0"' % (index, _STEAM_PAD_GUID)


def _pad_hat(direction):
    """The D-pad is a hat on this pad, not four buttons."""
    return '"direction:%s,engine:sdl,guid:%s,hat:0,port:0"' % (direction, _STEAM_PAD_GUID)


def _pad_trigger(axis):
    return '"axis:%d,direction:+,engine:sdl,guid:%s,port:0,threshold:0.5"' % (
        axis, _STEAM_PAD_GUID,
    )


def _pad_stick(axis_x, axis_y):
    # A deadzone is stated rather than left at Azahar's 0.0, which lets stick
    # noise register as input.
    return '"axis_x:%d,axis_y:%d,deadzone:0.100000,engine:sdl,guid:%s,port:0"' % (
        axis_x, axis_y, _STEAM_PAD_GUID,
    )
