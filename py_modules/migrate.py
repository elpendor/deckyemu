"""Carrying an older install's state over to the service's own folders.

Installs before the service kept settings, data and logs under
`appenv.PREVIOUS_ROOT`. Each folder is moved once, into `appenv.ROOT`, and a
symlink is left where it was: every Steam shortcut already added names a
launcher script by its old path, and the link keeps all of them working
without touching a single shortcut.

Never destructive. A folder only moves if the new one is missing or empty, so
a second run, or a run after the user has started over, changes nothing.
"""

import os
import shutil

import appenv

#: (folder under the old root, its counterpart under appenv)
FOLDERS = (
    (("settings", "deckyemu"), "SETTINGS_DIR"),
    (("data", "deckyemu"), "DATA_DIR"),
    (("logs", "deckyemu"), "LOG_DIR"),
)


def _empty(path):
    try:
        return not os.listdir(path)
    except FileNotFoundError:
        return True


def carry_over():
    """Move what is there to move. Returns a line per folder, for the log."""
    notes = []
    for parts, attr in FOLDERS:
        old = os.path.join(appenv.PREVIOUS_ROOT, *parts)
        new = getattr(appenv, attr)
        if os.path.islink(old) or not os.path.isdir(old):
            continue
        if not _empty(new):
            notes.append("kept %s; %s already has state" % (old, new))
            continue
        try:
            os.makedirs(os.path.dirname(new), exist_ok=True)
            if os.path.isdir(new):
                os.rmdir(new)
            shutil.move(old, new)
            os.symlink(new, old)
            notes.append("moved %s to %s" % (old, new))
        except OSError as error:
            notes.append("could not move %s: %s" % (old, error))
    for directory in (appenv.SETTINGS_DIR, appenv.DATA_DIR, appenv.LOG_DIR):
        os.makedirs(directory, exist_ok=True)
    return notes
