"""What cloud saves need, which is one binary and nobody's account but yours.

Kept beside the emulator definitions rather than inside one because it belongs
to no emulator: every system's saves go the same way, and a copy of this under
each entry would fetch the same file several times and disagree with itself
about whether it was there.

**Why rclone and not something written here.** Every comparable project reached
the same answer -- Ludusavi, EmuDeck's CloudSync, decky-cloud-save -- and none
of them wrote a transfer layer. Seventy-odd storage backends behind one command,
and no account of this project's anywhere in it: the remote is the user's, the
credentials are the user's, and nothing here ever sees a password.
"""

#: The transfer binary.
#:
#: The project publishes a zip whose single interesting member is a bare
#: `rclone`, which is what `extract` is for -- the same shape as the motion
#: server, and the reason `install_tool` grew the key in the first place.
#:
#: `needed_by` names a feature rather than an emulator, which is the whole
#: difference between this and the tools in `deck_gyro`. The panel prints it
#: when offering to remove the file, and "Cloud saves will lose it" is the only
#: form of that sentence that is true here.
RCLONE = {
    "name": "rclone",
    "label": "Cloud transfer",
    "repo": "rclone/rclone",
    "asset": r"^rclone-v[\d.]+-linux-amd64\.zip$",
    "extract": r"^rclone$",
    "feature": "cloud_saves",
    "needed_by": ["Cloud saves"],
    "why": ("Copies save data to the storage you choose. Runs only while a "
            "backup or a restore is happening, and talks to nothing else."),
}

#: Tools this plugin fetches for itself. One row each, same shape as the specs
#: an emulator declares, plus `feature`: the setting whose being on is what
#: makes the tool wanted. Without that a row for a switched-off feature would
#: read as a missing piece and invent a chore -- the rule the firmware list and
#: `tools_report` already follow.
PLUGIN_TOOLS = (RCLONE,)
