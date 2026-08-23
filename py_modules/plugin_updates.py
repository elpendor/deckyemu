"""The part of the Plugin class that knows what build this is and finds newer ones.

Four things, and they are one subject: what is installed, whether anything newer
exists, watching for that in the background, and handing a chosen release to
decky's own installer.

**A self-distributed plugin has to do this itself.** decky notifies for the
plugins in its store and will never notify for this one, so without a check here
an install stays on whatever version it was first given, indefinitely, with
nothing anywhere saying otherwise.

**The stamp is why `plugin_version` is not just a version string.** CI writes
`build.json` beside `package.json` naming the commit, and the frontend carries
the same commit compiled in. A frontend Steam cached before an update is
otherwise indistinguishable from a bug -- the backend behaves like the new
version and the interface is the old one -- and the two halves being able to
disagree out loud is what makes that diagnosable at all.

`releases.py` does the looking and `handoff.py` serves the file over loopback;
neither reaches back here. What is left is the policy: how often to look, how
long to back off when the network is not there, and refusing to hand decky
anything whose hash does not match what the release said.

Split out of main.py because it answers a different question from the file it
sat in -- that one is about putting games in a library, and this is about the
plugin itself.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import asyncio
import hashlib
import json
import os

import decky

import plugin_base

import handoff
import releases
import sysenv


class Updates(plugin_base.PluginContext):
    """Version, update checks and staging. See the module docstring."""

    async def plugin_version(self):
        """What this backend is, for display and for spotting a stale frontend.

        package.json is the source of truth for the version. `build.json` is written
        by CI beside it and names the commit; a local build has none, and reports
        "dev" so the frontend knows not to compare.
        """

        def _read():
            root = sysenv.PLUGIN_ROOT
            version, build, built_at = "0.0.0", "dev", ""
            # What changed in the build that is actually installed. CI writes it
            # into the stamp so the Updates tab can answer "what did I get?"
            # without a network -- and, while the repository is private, without a
            # token. A local build has none, which reads as "nothing to show".
            notes = ""
            try:
                with open(os.path.join(root, "package.json"), "r", encoding="utf-8") as handle:
                    version = json.load(handle).get("version") or version
            except (OSError, ValueError):
                pass
            try:
                with open(os.path.join(root, "build.json"), "r", encoding="utf-8") as handle:
                    stamp = json.load(handle)
                build = stamp.get("commit") or build
                built_at = stamp.get("built_at") or ""
                notes = (stamp.get("notes") or "").strip()
                # CI writes the version it built, which is authoritative over a
                # package.json that could have been edited since.
                version = stamp.get("version") or version
            except (OSError, ValueError):
                pass
            return {
                "version": version,
                "build": build,
                "built_at": built_at,
                "notes": notes,
            }

        return await self._run(_read)

    async def check_for_update(self, force: bool = False):
        """Whether a newer release exists, and what the frontend needs to install it.

        Only looks. Decky's loader does the installing -- it runs as root and this
        backend runs as `deck`, which cannot write the plugin's own directory.
        """
        current = (await self.plugin_version())["version"]
        result = await self._run(releases.check, current, force, False)
        # Logged either way. When this only spoke up for an available update, a
        # check that never ran looked exactly like one that found nothing.
        decky.logger.info(
            "Update check: current=%s checked=%s releases=%d available=%s%s",
            current,
            result.get("checked"),
            result.get("count", 0),
            result.get("available"),
            (" error=%s" % result["error"]) if result.get("error") else "",
        )
        return result

    #: How long to wait after a check that answered. Decky's own updater uses
    #: six hours, and six hours is four requests a day against a budget of sixty
    #: an hour that every unauthenticated caller on the address shares.
    #:
    #: **It is six hours of *awake* time, not six hours of clock.**
    #: `asyncio.sleep` measures with `time.monotonic()`, which on Linux is
    #: `CLOCK_MONOTONIC` and does not advance while the machine is suspended --
    #: and a Deck suspends rather than shutting down. Measured on the device:
    #: 6.36 hours since boot, 5.35 counted, 1.01 spent asleep and invisible to
    #: this timer. Somebody who plays an hour a night reaches the second check
    #: nearly a week after the first.
    #:
    #: That is survivable only because this is not the path a user waits on.
    #: Opening the Quick Access panel checks too -- see `loadUpdate` in
    #: index.tsx -- bounded by `releases.CACHE_SECONDS`, an hour. This timer is
    #: the floor for a device whose panel is never opened, and the first check
    #: of the loop runs immediately rather than after a sleep, so a reload or a
    #: reboot gets a fresh answer at once.
    #:
    #: `CLOCK_BOOTTIME` would count the suspend, and `asyncio` will not use it.
    #: Changing that means not sleeping for the whole interval -- waking often
    #: and comparing wall clocks -- which buys very little over the panel path
    #: and costs a timer that fires on a sleeping device.
    _UPDATE_INTERVAL = 6 * 60 * 60

    #: How long to wait after a check that did *not* answer, per attempt.
    #:
    #: This replaces the fixed 30-second delay decky puts before its first check
    #: ("Internet might not immediately be up"). That delay is a guess about how
    #: long the network takes to arrive: it covers a wifi association that
    #: finishes in ten seconds and does nothing for one that finishes in four
    #: minutes -- and the cost of guessing short is not a retry, it is six hours
    #: of silence, because the loop's next move is the interval above.
    #:
    #: Climbing instead. The first check happens immediately, and a failure is
    #: retried on this ladder before settling back into the ordinary cadence, so
    #: the answer arrives whenever the network does rather than whenever the
    #: guess said it would.
    #:
    #: Four rungs inside twenty minutes: long enough to outlast a slow boot,
    #: short enough that a device with no network spends five requests every six
    #: hours failing instantly.
    _UPDATE_RETRY_DELAYS = (60, 120, 300, 600)

    async def _watch_for_updates(self):
        """Look for a newer release on a timer, and say so when there is one.

        A task rather than something the panel drives, because of what it feeds:
        the dot on the plugin's icon has to be right *before* the panel is
        opened, and a check that only runs on open can never make it so.

        Nothing here is gated on the device being a Steam Deck. `_watch_` starts
        with an underscore so the gate decorator skips it, and `check_for_update`
        is on the ungated list on purpose -- a machine the gate refuses is
        exactly the machine that may need to hear a newer version exists.

        The result is not returned anywhere. It goes into the same cache the
        panel reads, and out as an event for the icon.
        """
        attempt = 0
        while True:
            answered = False
            try:
                # Forced only on a retry. The first attempt of a cycle is happy
                # with a cached answer -- a reload ten minutes after the last
                # check should not spend a request -- but a retry exists
                # *because* the last attempt failed, and the module's own
                # failure backoff would otherwise turn every rung below fifteen
                # minutes into a call that never leaves the house.
                found = await self.check_for_update(attempt > 0)
                answered = bool(found.get("checked"))

                # Only when there is an answer. Emitting on a failed check would
                # send `available=False` -- indistinguishable from "you are up
                # to date" -- and put out a dot that a working check had lit.
                if answered:
                    # Both directions when it did answer, though: "no longer
                    # available" is a real transition, and an event that only
                    # ever means yes can light the dot but never put it out.
                    await decky.emit(
                        "update_available",
                        bool(found.get("available")),
                        (found.get("latest") or {}).get("version", ""),
                    )
            except asyncio.CancelledError:
                # decky shutting the plugin down. Must be allowed to.
                raise
            except Exception:
                # A failed check is expected here -- no network at a Deck's
                # first boot of the day is the ordinary case -- so it is logged
                # and the loop continues. Raising would end the task and there
                # would be no more checks until the next restart.
                decky.logger.exception("Update watch: could not check")

            if answered:
                attempt = 0
                delay = self._UPDATE_INTERVAL
            elif attempt < len(self._UPDATE_RETRY_DELAYS):
                delay = self._UPDATE_RETRY_DELAYS[attempt]
                attempt += 1
            else:
                # The ladder is for a network still arriving. Past the end of it
                # this is a network that is not coming, so stop climbing and
                # wait like everybody else -- and start the ladder again after,
                # because by then it may well be a different situation.
                attempt = 0
                delay = self._UPDATE_INTERVAL

            await asyncio.sleep(delay)

    async def stage_update(self):
        """Download the newest release and offer it to decky over loopback.

        Decky installs from a URL it fetches itself. Downloading here first and
        re-offering the bytes on 127.0.0.1 means the digest decky verifies is
        computed from the file actually obtained, rather than from a second trip
        to the network that could answer differently.
        """
        current = (await self.plugin_version())["version"]
        found = await self._run(releases.check, current, True, False)

        release = found.get("latest")
        if not release:
            return {"ok": False, "error": "No release to install."}

        try:
            payload = await self._run(releases.download, release)
        except Exception as error:  # noqa: BLE001 - reported, not raised, to the UI
            decky.logger.exception("Could not download the release")
            return {"ok": False, "error": "Could not download it: %s" % error}

        if not payload:
            return {"ok": False, "error": "The release could not be downloaded."}

        def _write():
            os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
            # The asset name is whatever the releases API said, so it decides a
            # path here. A basename cannot climb out of the runtime directory,
            # and an empty one falls back rather than naming the directory
            # itself. `handoff` serves this file back under the same name.
            name = os.path.basename(release.get("asset_name") or "") or "deckyemu.zip"
            path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, name)
            with open(path, "wb") as handle:
                handle.write(payload)
            return path, hashlib.sha256(payload).hexdigest()

        path, digest = await self._run(_write)

        expected = release.get("sha256") or ""
        if expected and expected != digest:
            await self._run(os.remove, path)
            return {"ok": False, "error": "The download did not match its published digest."}

        url = await self._run(handoff.serve, path)
        if not url:
            return {"ok": False, "error": "Could not offer the download to decky."}

        decky.logger.info("Staged %s for decky at %s", release["version"], url)
        return {"ok": True, "url": url, "version": release["version"], "sha256": digest}
