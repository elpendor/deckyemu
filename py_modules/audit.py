"""An append-only note of everything that removed or replaced somebody's data.

**Decky keeps five logs and rotates the rest away.** That is the right call for
a log that is mostly progress lines, and the wrong one for the only question
that matters after data goes missing: what removed it, and when. Measured -- a
storage was found holding 23 files where it had held 608 six
hours earlier, and by the time anyone looked the logs covering those six hours
had already been rotated away. The answer was not recoverable from the Deck at
all.

So the destructive acts get their own file, and it is never rotated. One line
each, in the order they happened: what, where, how much, and whether it worked.

**Cheap enough to keep for years.** A line is a couple of hundred bytes and only
an act that removes or replaces something writes one -- a copy that changed
nothing is silent. The cap below is a floor under pathological growth, not a
retention policy: it keeps the newest half rather than starting again, because
the oldest entry is usually the one being looked for.
"""

import json
import os
import time

import decky

#: Beside the settings rather than in the log directory, which is the directory
#: this exists to survive.
PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "destructive.log")

#: Past this, the oldest half goes. Reached after roughly ten thousand
#: destructive acts, which is not a number this plugin can produce in a year.
_CAP = 2 * 1024 * 1024


def record(what, **facts):
    """Note one act that removed or replaced data. Never raises.

    `what` is the verb -- "purge", "kept", "replaced", "forgot" -- and `facts`
    is whatever a reader would need to make sense of it a month later. Written
    as JSON, one object per line, so it can be read by a person or by a script.

    Failures are swallowed on purpose: an audit note that cannot be written must
    not take down the copy it was describing. It logs, and the ordinary log is
    where that particular loss shows up.
    """
    try:
        line = json.dumps(
            dict(facts, at=time.strftime("%Y-%m-%d %H:%M:%S"), what=what),
            sort_keys=True,
        )
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _trim()
    except (OSError, ValueError, TypeError) as error:
        decky.logger.warning("Could not write the destructive-acts note: %s", error)


def _trim():
    """Keep the newest half once the file is absurdly large."""
    try:
        if os.path.getsize(PATH) <= _CAP:
            return
        with open(PATH, encoding="utf-8") as handle:
            lines = handle.readlines()
        with open(PATH, "w", encoding="utf-8") as handle:
            handle.writelines(lines[len(lines) // 2:])
    except OSError as error:
        decky.logger.warning("Could not trim the destructive-acts note: %s", error)


def entries(limit=200):
    """The most recent notes, newest last, for a report or a diagnostic."""
    try:
        with open(PATH, encoding="utf-8") as handle:
            lines = handle.readlines()[-limit:]
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found
