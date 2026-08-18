#!/usr/bin/env python3
"""The library check must not report the plugin's own setup shortcut.

    python scripts/tests/test_setup_shortcut_audit.py

There is one hidden Steam shortcut, "DeckyEmu setup", repointed at whichever
emulator is being opened -- several will only install firmware through their own
window, and gamescope composites nothing Steam did not launch, so a shortcut is
the only door. It runs a script in the launcher directory, and ownership in
`steam_shortcuts.ours()` is exactly "the executable is in that directory".

So the audit saw both halves of a working feature and called them faults:

* the shortcut as an **orphan**, because the registry does not know it -- it is
  remembered in the settings, not in library.json;
* its script as a **stray launcher**, offered for deletion.

The second is the dangerous one. Deleting the script is what that finding
offers, and it breaks the shortcut that runs it -- after which the next audit
calls the shortcut `dead` and offers to delete that too. A check that
manufactures the fault it then reports is worse than one that misses it.

`shortcut_health` shares the rule and is where it was most visible: the panel
asks on every open, so this put a permanent "something is wrong" nudge in front
of anyone who had ever opened an emulator's own window.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT  # noqa: E402

sys.path.insert(0, REPO_ROOT)

import emulators  # noqa: E402
import launchers  # noqa: E402
import main  # noqa: E402
import steam_shortcuts  # noqa: E402
import store  # noqa: E402

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


class _Audit(main.Plugin):
    """The composed class, not the mixin.

    `audit_library` reaches for `_stray_launchers`, which `Plugin` owns and the
    mixin only declares -- running the mixin alone raises AttributeError before
    reaching anything worth checking. Which is the arrangement working: it is
    what the declarations in plugin_base are for.

    `_run` is replaced with a synchronous one so the whole audit is a single
    pass with no executor to wait on.
    """

    def _run(self, function, *args, **kwargs):
        future = LOOP.create_future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as error:  # noqa: BLE001 - surfaced by the await below
            future.set_exception(error)
        return future


def _run(coro):
    return LOOP.run_until_complete(coro)


section("the setup shortcut is the plugin's own, not a game gone astray")

_plugin = _Audit()

# A registered emulator, so the GUI launcher has something to be derived from.
# Flatpak rather than a path: `save` requires a path target to be absolute and
# POSIX, and this file has no reason to be one of the ones that only runs on
# Linux. Which kind it is changes nothing here -- the launcher is written and
# named the same way either way.
_emulator, _error = emulators.save({
    "name": "Vita3K", "kind": "flatpak", "target": "net.vita3k.Vita3K",
    "args": "{rom}", "extensions": "pkg", "platform": "PlayStation Vita",
})
check("an emulator to open the window of", (_error, (_emulator or {}).get("id")),
      ("", "vita3k"))

_gui = launchers.write_gui_launcher(_emulator, "Vita3K")
check("its GUI launcher is written where the audit will scan",
      os.path.dirname(os.path.normpath(_gui)),
      os.path.normpath(launchers.LAUNCHER_DIR))
# The writer and the audit have to agree on this path or the fix is a no-op that
# happens to pass: one derives it, the other is told it.
check("and the derived path is the one that was written",
      os.path.normpath(launchers.gui_launcher_path(_emulator)), os.path.normpath(_gui))

SETUP_APP_ID = 4082493598
store.set_settings({"setup_app_id": SETUP_APP_ID})

# Steam's own record. Stubbed rather than written into a real shortcuts.vdf --
# what is being checked is the audit's reading, not the parser's.
_real_ours = steam_shortcuts.ours
steam_shortcuts.ours = lambda: [
    {"app_id": SETUP_APP_ID, "title": launchers.SETUP_SHORTCUT_TITLE,
     "exe": _gui, "launcher": os.path.basename(_gui), "launcher_exists": True},
]
try:
    _report = _run(_plugin.audit_library())

    _titles = [item["title"] for item in _report["unknown_shortcuts"]]
    check("the setup shortcut is not reported as an unknown shortcut", _titles, [])
    check("nor is its launcher offered for deletion",
          [p for p in _report["strays"] if os.path.normpath(p) == os.path.normpath(_gui)],
          [])

    # The panel's own nudge, which is the surface this was seen on.
    _health = _run(_plugin.shortcut_health())
    check("and the panel is not told something is wrong",
          (_health["unknown"], _health["orphan"]), (0, 0))

    # The other direction, so this is not just "the audit reports nothing". A
    # real leftover still has to be found, or the fix has quietly turned the
    # check off.
    _stray = os.path.join(launchers.LAUNCHER_DIR, "some-game-a1b2c3d4.sh")
    with open(_stray, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\n")
    steam_shortcuts.ours = lambda: [
        {"app_id": SETUP_APP_ID, "title": launchers.SETUP_SHORTCUT_TITLE,
         "exe": _gui, "launcher": os.path.basename(_gui), "launcher_exists": True},
        {"app_id": 999001, "title": "A Game", "exe": _stray,
         "launcher": os.path.basename(_stray), "launcher_exists": True},
    ]
    _report = _run(_plugin.audit_library())
    check("a real orphaned shortcut is still reported",
          [(i["title"], i["kind"]) for i in _report["unknown_shortcuts"]],
          [("A Game", "orphan")])
    check("and a real stray launcher still is",
          [os.path.basename(p) for p in _report["strays"]],
          ["some-game-a1b2c3d4.sh"])

    # A script from an emulator that is no longer registered has nothing using
    # it, and is a stray. The exclusion is derived from what exists rather than
    # from the `open-` name, which is what makes this the correct answer.
    emulators.remove("vita3k")
    _report = _run(_plugin.audit_library())
    check("a GUI launcher whose emulator is gone becomes a stray",
          os.path.basename(_gui) in [os.path.basename(p) for p in _report["strays"]],
          True)

    # ---- and the shortcut left by an uninstall, which is the way back --------
    #
    # Uninstalling the plugin removes the settings and the launcher scripts and
    # cannot touch Steam: decky has no frontend uninstall hook, and the only one
    # it does have fires on every reload, so removing shortcuts there would
    # delete somebody's library every time the plugin restarted. The setup
    # shortcut therefore outlives an uninstall as a hidden entry that starts
    # nothing, and a fresh install's library check is the only thing that can
    # ever find it again.
    #
    # Which is why the skip above is keyed on the recorded id and must stay that
    # way. Widening it to the title -- the obvious next "improvement" -- would
    # make this shortcut invisible to the one tool able to clean it up, forever.
    store.set_settings({"setup_app_id": 0})
    os.remove(_gui)
    steam_shortcuts.ours = lambda: [
        {"app_id": SETUP_APP_ID, "title": launchers.SETUP_SHORTCUT_TITLE,
         "exe": _gui, "launcher": os.path.basename(_gui), "launcher_exists": False},
    ]
    _report = _run(_plugin.audit_library())
    check("a setup shortcut whose record is gone is still reported",
          [(i["title"], i["kind"]) for i in _report["unknown_shortcuts"]],
          [(launchers.SETUP_SHORTCUT_TITLE, "dead")])
    # `dead` and not `orphan`, because that is the group OrphanModal offers a
    # "Remove" button for, and removing it is the only thing to do with it.
    _health = _run(_plugin.shortcut_health())
    check("and the panel counts it, so it is findable at all",
          (_health["unknown"], _health["dead"]), (1, 1))
finally:
    steam_shortcuts.ours = _real_ours
    store.set_settings({"setup_app_id": 0})
    for _path in (_gui, os.path.join(launchers.LAUNCHER_DIR, "some-game-a1b2c3d4.sh")):
        try:
            os.remove(_path)
        except OSError:
            pass
    asyncio.set_event_loop(None)
    LOOP.close()

check("the real shortcut reader is back", steam_shortcuts.ours is _real_ours, True)


if __name__ == "__main__":
    summary()
