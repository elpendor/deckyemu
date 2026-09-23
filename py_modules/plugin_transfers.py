"""The part of the Plugin class that moves files on and off the device.

One HTTP server, used in both directions. Sending is the point: a ROM, a BIOS
dump or an emulator definition reaches `~/deckyemu` from a phone or a laptop
over a QR code or a six-digit code, with no cable, no Desktop Mode and no
keyboard worth the name. Reading a diagnostic report back off the Deck is the
same server run backwards, with the same token and the same lockout, because the
alternative was asking somebody in Game Mode to find a log file.

The endpoints here are thin: `fileserver` owns the sockets, the token, the
lockout and the idle timeout, and `fileserver_page` owns what goes over the
wire. What is left in this file is what the *plugin* has to decide -- where a
send should land by default, which emulators are installed so a definition can
name one, and what a report may contain before it leaves the device.

Split out of main.py because it answers a different question from the file it
sat in: adding a game to a library is not the same subject as getting the file
onto the device in the first place, and neither half reads the other.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import asyncio
import os
import time

import decky

import plugin_base

#: Said to somebody who pressed a button while saves were already moving. Which
#: copy is running is deliberately not named: from where they are standing the
#: answer is "wait a moment", and the other copy is usually the one their own
#: last game started on the way out.
_ALREADY = "Saves are being copied right now. Try that again in a moment."

import audit
import cloudsave
import cloudsync
import diagnostics
import emu_config
import emu_install
import emulator_catalog
import emulators
import fileserver
import launchers
import procout
import discset
import romshelf
import savedata
import switch_nsz
import unpack
import vita_games
import gamecontent
import store


def _received_owners(received):
    """{path: the sheet that owns it} for the arrivals that are part of a game.

    Grouped by folder before asking, because `romshelf.sheet_owners` answers for
    one directory at a time and the received list is not guaranteed to be one:
    it follows the running server, and a firmware send saves somewhere else.
    """
    folders = {}
    for item in received:
        folders.setdefault(os.path.dirname(item["path"]), []).append(item["name"])

    owners = {}
    for folder, names in folders.items():
        for name, sheet in romshelf.sheet_owners(folder, names).items():
            owners[os.path.join(folder, name)] = sheet
    return owners


def _owned_beside(path):
    """The files in this folder that the playlist at `path` owns.

    Empty for anything that is not a playlist, and for one whose tracks are not
    here -- `sheet_owners` only ever names files the listing had.
    """
    folder = os.path.dirname(path)
    name = os.path.basename(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return []

    owners = romshelf.sheet_owners(folder, names)
    return [os.path.join(folder, child)
            for child, sheet in sorted(owners.items())
            if sheet == name and os.path.isfile(os.path.join(folder, child))]


def _disc_homes(library):
    """{(base, extension): {"app_id", "title", "numbers"}} for the added discs.

    Which game a disc waiting in the transfer folder would join, worked out from
    the games already in the library. `discset.find_set` cannot answer this: it
    only ever looks beside the file, and the discs this one belongs to were
    filed into `roms/<system>` when the game was added.

    A key two games both answer to is dropped rather than guessed at. Two
    entries whose discs share a base name is either a mistake somebody is about
    to fix or two genuinely different games, and picking one of them to offer
    would be wrong half the time -- so neither is offered and the ordinary
    **Add** stands.
    """
    homes = {}
    for app_id, entry in (library or {}).items():
        rom_path = entry.get("rom_path", "")
        if not rom_path:
            continue
        if rom_path.lower().endswith(".m3u"):
            names = romshelf.named_by(rom_path) or []
        else:
            names = [os.path.basename(rom_path)]

        for name in names:
            key = discset.set_key(name)
            if not key:
                continue
            home = homes.setdefault(key, {"app_id": int(app_id),
                                          "title": entry.get("title", ""),
                                          "numbers": set(), "one": True})
            if home["app_id"] != int(app_id):
                home["one"] = False
            home["numbers"].add(discset.disc_number(name))
    return {key: home for key, home in homes.items() if home["one"]}


def _disc_for(item, homes):
    """The game this arrival would join, or None. See `_disc_homes`.

    A track is never a disc however its name reads, and `part_of` has already
    said so -- a `.cue` in the folder names it, which is the only evidence there
    is. A disc the game already has is not offered either: adding disc 2 to a
    game that has disc 2 does nothing, and a button that does nothing is worse
    than no button.
    """
    if item.get("part_of"):
        return None
    key = discset.set_key(item.get("name", ""))
    home = homes.get(key) if key else None
    if not home or discset.disc_number(item["name"]) in home["numbers"]:
        return None
    # The number goes with it: the row says "disc 2 of Zed" rather than putting
    # the game's name on a button, where a long title has nowhere to go.
    return {"app_id": home["app_id"], "title": home["title"],
            "disc": discset.disc_number(item["name"])}


class Transfers(plugin_base.PluginContext):
    """Sending files to the Deck and reading a report back. See the module docstring."""

    async def file_server_status(self):
        status = await self._run(fileserver.status)
        # Its own folder, not wherever ROMs are browsed from -- see
        # fileserver.default_dir.
        status["suggested_dir"] = await self._run(fileserver.default_dir)
        # A CD rip is one sheet and a dozen tracks, and every one of them used
        # to get its own row with its own Add -- which on a track makes a Steam
        # entry out of raw sectors. Each track carries the sheet that owns it so
        # the dialog can show the game once. Cheap enough to do on every poll:
        # the sheets are the only files opened and `_referenced` will not read a
        # large one.
        owners = await self._run(_received_owners, status.get("received") or [])
        # A Switch update or DLC names the game it is for, so its row can offer
        # Install into that game rather than Add, which would make a Steam entry
        # out of something that is not a game. The library is read only when
        # there is a package to ask about.
        # Which added game each arrival would join, if it is a disc of one. The
        # library is read once here rather than per row; it is the same read the
        # package rows below make, and they share it.
        library = await self._run(store.get_library)
        homes = await self._run(_disc_homes, library)
        for item in status.get("received") or []:
            item["part_of"] = owners.get(item["path"], "")
            disc_for = _disc_for(item, homes)
            if disc_for:
                item["disc_for"] = disc_for
            # A Vita licence key is only read while its package installs, so its
            # row says that instead of offering Add. `.txt` too, but only when
            # there really is a key in it.
            if item.get("name", "").lower().endswith(vita_games.ZRIF_SUFFIXES):
                item["licence_key"] = bool(await self._run(vita_games.zrif_from, item["path"]))
            if not item.get("name", "").lower().endswith(gamecontent.SUFFIXES):
                continue
            item["game_content"] = await self._run(gamecontent.owner, item["path"], library)
        return status

    async def start_report(self):
        """Gather a diagnostic report and put it where another device can read it.

        The plugin logs plenty and none of it is reachable from Game Mode, so the
        best report a user can give is "it didn't work" -- which is also the
        least useful one. This is the same problem the transfer server already
        solves in the other direction, so it is the same server: a QR code for a
        camera, six digits for anything with a keyboard.

        What is gathered and what is struck out of it is `diagnostics`, and the
        striking out is the part that matters -- the settings hold a
        RetroAchievements token that is password-equivalent, and this text is
        going into a public issue.
        """
        # The session's own transfer token is struck by value: it is minted per
        # session so no settings file holds it, it reaches the log as a bare
        # request path that no URL rule catches, and it is live on the network
        # at the moment somebody reads the report.
        serving = await self._run(fileserver.status)
        report = await self._run(
            diagnostics.build,
            await self.plugin_version(),
            self._install,
            self._emulators,
            await self._run(store.get_library),
            await self._run(self._installed_catalog_ids),
            [serving.get("url", "").rstrip("/").rsplit("/", 1)[-1]],
            await self._run(fileserver.default_dir, False),
            await self._cloud_summary(),
            await self._run(self._links_skipped),
        )

        if not serving.get("running"):
            # Started to hand a report out, and nothing else: a server brought up
            # for this does not accept files. Showing somebody a report should
            # not also hand them somewhere to write, and they could not tell
            # they had been given one.
            started = await self._serve(False)
            if started.get("error"):
                return {"ok": False, "error": started["error"]}

        await self._run(fileserver.offer_report, report)
        decky.logger.info("Diagnostic report ready (%d characters)", len(report))
        return {"ok": True, **await self._run(fileserver.status)}

    async def start_cloud_setup(self):
        """Put the storage setup form where a device with a keyboard can fill it.

        The third errand this server runs and the same shape as the other two: a
        QR code for a camera, six digits for anything else, and uploads off,
        because handing somebody a settings form must not also hand them a
        writable ROM folder.

        On a phone rather than in the panel because of what it collects. A
        WebDAV address, a username and a password typed on the Deck's
        on-screen keyboard is exactly the experience that put ROM transfers on
        another device in the first place.

        **The providers that need a browser login work here too**, which took a
        detour to establish. Their redirect goes to `localhost`, which from a
        phone is the phone, so the login looks like it fails at the last step.
        But the dead page still carries `?code=...` in its address, and rclone's
        callback is an ordinary endpoint -- so the phone pastes that address
        back and the Deck makes the request rclone was waiting for. Nothing is
        typed on the Deck either way, which is the whole point of this page.
        """
        if not await self._run(cloudsave.binary):
            return {"ok": False,
                    "error": "The cloud transfer tool is still downloading."}

        serving = await self._run(fileserver.status)
        if not serving.get("running"):
            started = await self._serve(False)
            if started.get("error"):
                return {"ok": False, "error": started["error"]}
        elif serving.get("accepts_uploads"):
            # A running transfer owns the page, and this errand needs uploads
            # off. Said plainly rather than started anyway: a form that silently
            # never appeared would look like the feature is broken.
            return {"ok": False,
                    "error": "A file transfer is open. Finish that first."}

        await self._run(
            fileserver.offer_cloud_setup,
            cloudsave.offered(cloudsave.BACKENDS), self._cloud_setup,
            cloudsave.offered(cloudsave.OAUTH_BACKENDS), self._cloud_login
        )
        decky.logger.info("Cloud storage setup ready")
        return {"ok": True, **await self._run(fileserver.status)}

    def _cloud_setup(self, kind, values):
        """What the form posts back. Runs on the server's own thread.

        Made and then *checked*, because "saved" is not the answer anybody wants
        -- a typo in a hostname should be a sentence on the page they are still
        looking at, not a backup that fails hours later behind a game that just
        closed. A remote that cannot be reached is removed again rather than
        left behind looking configured.

        The name is minted here rather than asked for, and everything said back
        to the person is the service -- see `cloudsave.next_name`.
        """
        name = cloudsave.next_name(kind)
        label = cloudsave.label_for(kind)
        ok, error = cloudsave.create_remote(name, kind, values)
        if not ok:
            return False, error

        ok, error = cloudsave.check_remote(name)
        if not ok:
            cloudsave.remove_remote(name)
            return False, "Saved, but %s did not answer: %s" % (
                label, cloudsave.said_plainly(error))

        store.set_settings({"cloud_remote": "%s:" % name})
        self._note_cloud_state()
        return True, ""

    def _cloud_login(self, step, kind, pasted):
        """The login half of the form. Runs on the server's own thread.

        Two steps because a login has two halves and a person in between. The
        first hands back a link; the second takes what the browser ended up at
        and gives rclone the code out of it, which is the whole reason this can
        happen on a phone at all.
        """
        if step == "start":
            url, error = cloudsave.login_start(kind)
            return (bool(url), error or "", url)
        if step == "cancel":
            cloudsave.login_cancel()
            return (True, "", "")

        name = cloudsave.next_name(kind)
        label = cloudsave.label_for(kind)
        ok, error = cloudsave.login_finish(name, kind, pasted)
        if not ok:
            return (False, error, "")

        ok, error = cloudsave.check_remote(name)
        if not ok:
            cloudsave.remove_remote(name)
            return (False, "Signed in, but %s did not answer: %s" % (
                label, cloudsave.said_plainly(error)), "")

        store.set_settings({"cloud_remote": "%s:" % name})
        self._note_cloud_state()
        return (True, "", "")

    async def cloud_status(self, details: bool = True):
        """Whether saves have somewhere to go, and where. Never a credential.

        The panel had no way to say any of this, which made a successful setup
        indistinguishable from one that silently failed: the phone said it had
        worked and the Deck said nothing at all.

        What comes back is the remote's *name* and nothing else. rclone holds
        the password and the token, and neither this nor anything downstream of
        it ever reads them back out.
        """
        tool = bool(await self._run(cloudsave.binary))
        settings = await self._run(store.get_settings)
        configured = await self._run(cloudsave.remotes) if tool else []
        chosen = self._chosen_remote()
        # Only a remote that still exists counts. A settings key naming one
        # somebody deleted is a destination that is not there, and saying
        # "ready" about it would be the same lie the panel told by saying
        # nothing at all.
        remote = chosen if chosen in configured else ""

        kinds = await self._run(cloudsave.remote_kinds) if tool else {}
        kind = kinds.get(remote, "")
        # **The service, not just the name somebody typed.** The name is a
        # label -- it defaults to something generic -- so a row reading "saves
        # go to cloud" answered nothing anybody wanted to know. The service is
        # the answer to "am I signed in, and to what".
        return {
            "ok": True,
            "tool": tool,
            "remote": remote,
            "kind": kind,
            "label": await self._run(cloudsave.label_for, kind) if kind else "",
            # Empty for services that will not say, which is most of them --
            # Dropbox answers "doesn't support UserInfo". Not an error, and the
            # panel says the service without claiming to know the account.
            # Whether a game ending copies on its own, and when it last did.
            # An automatic thing that never says it happened cannot be told
            # from one that is broken.
            "after_play": bool(settings.get("cloud_after_play")),
            # Whether a game starting looks for saves this Deck is missing.
            "before_play": bool(settings.get("cloud_before_play", True)),
            "last_sync": int(settings.get("cloud_last_sync") or 0),
            # What is moving right now, if anything: "after-play", "launch",
            # "backup" or "restore". The panel shows the two silent ones,
            # because a copy nothing says a word about is the one somebody
            # reports as the plugin having done nothing.
            "copying": self._copying,
            # **These two are the only things here that touch the network**,
            # and they are for the setup dialog: who the storage says you are,
            # and how much room is left. Every other caller wants the list of
            # accounts, which is a local file -- and paying four seconds of
            # Dropbox to open a screen that shows neither is what made the
            # restore dialog feel broken.
            "account": (await self._run(cloudsave.account_for, remote)
                        if (remote and details) else ""),
            # Numbers can only come back from a service that answered, so this
            # doubles as proof the sign-in still works.
            "space": (await self._run(cloudsave.remote_space, remote)
                      if (remote and details) else {}),
            "remotes": [{"name": name, "kind": kinds.get(name, ""),
                         "label": await self._run(cloudsave.label_for,
                                                  kinds.get(name, ""))}
                        for name in configured],
        }

    async def choose_cloud_remote(self, name: str):
        """Pick which configured storage saves go to. Returns the new status.

        **On the Deck, not on the web page.** Signing in needs a browser and a
        keyboard, so that happens on a phone; choosing between storages already
        set up needs neither, and it is a decision about this device. Putting it
        on the page would mean going and finding another device to answer a
        question the panel is perfectly able to ask.

        **The status it answers with is the cheap one.** Choosing is a settings
        write and nothing else, but this used to end by asking the provider who
        you are signed in as and how much room is left -- two network calls, a
        second or more, with the row still showing the old storage as the one in
        use. Pressing a button that decides something locally should not wait on
        wifi to say it happened. The dialog polls for the rest and fills the
        account and the free space in when they land.
        """
        if not await self._run(cloudsave.binary):
            return {"ok": False, "error": "The cloud transfer tool is missing."}
        if name and name not in await self._run(cloudsave.remotes):
            return {"ok": False, "error": "There is no storage called %r." % name}
        await self._run(store.set_settings,
                        {"cloud_remote": ("%s:" % name) if name else ""})
        await self._run(self._note_cloud_state)
        return await self.cloud_status(False)

    async def forget_cloud_remote(self, name: str):
        """Remove one storage and the credentials with it. Returns the status.

        Also on the Deck, and for a second reason beyond the first: this is the
        destructive one, and a page reachable by anybody holding a six-digit
        code is the wrong place to put the button that deletes a sign-in.

        **Signing out of the one in use moves saves to another, not to nowhere.**
        Leaving no destination while three storages are still signed in stops
        every copy silently: nothing says so except a panel row going back to
        "Set up cloud storage" on a Deck that is set up. So the first storage
        left takes over, and the dialog that asked says which one it will be
        before anything is removed. With none left there is nothing to promote,
        and then no destination is the truth.
        """
        ok, error = await self._run(cloudsave.remove_remote, name)
        if not ok:
            return {"ok": False, "error": error}
        left = await self._run(cloudsave.remotes)
        if await self._run(self._chosen_remote) == name:
            await self._run(store.set_settings,
                            {"cloud_remote": ("%s:" % left[0]) if left else ""})
        # **The switch follows the storages, because it is a statement about
        # them.** It was turned on by opening the setup screen and never turned
        # off by anything: sign the last storage out and the Deck went on
        # fetching and keeping rclone at every startup for a feature with
        # nowhere to put anything, while the tools row said the binary was
        # wanted. Signing out is the honest off, and this is what makes it one.
        if not left:
            await self._run(store.set_settings, {"cloud_saves": False})
        await self._run(self._note_cloud_state)
        # Cheap, for the reason `choose_cloud_remote` gives: the row has gone,
        # and asking a provider about the one left is not what says so.
        return await self.cloud_status(False)

    async def end_cloud_setup(self):
        """Take the form down, and stop the server if it was only serving that.

        The second half is what this said it did for a while without doing it,
        and withdrawing the form alone is worse than not withdrawing it: the
        page falls back to the transfer page, so closing the dialog left a
        stranger's browser looking at this Deck's file list rather than at
        nothing at all.

        The server itself only stops when nothing is moving, the same rule and
        the same guard as `end_report` and `end_save_backup`. It may have been
        up for a transfer that is still running, and cutting off a
        multi-gigabyte ROM because somebody closed an unrelated dialog is the
        failure that guard exists for.
        """
        await self._run(cloudsave.login_cancel)
        await self._run(fileserver.offer_cloud_setup, None, None, None, None)
        # **Opening this screen turns the feature on, so closing it with nothing
        # set up has to turn it off again.** The switch is what fetches rclone,
        # which is why it goes on before the form can be shown -- and that left
        # a Deck with every storage signed out claiming cloud saves was on,
        # because looking at the setup screen afterwards was enough to set it.
        # The flag means "there is somewhere to put saves", and this is the
        # other moment that can stop being true. Signing out is the first --
        # see `forget_cloud_remote`.
        if not await self._run(cloudsave.remotes):
            await self._run(store.set_settings, {"cloud_saves": False})
        status = await self._run(fileserver.status)
        if status.get("running") and not (
            status.get("uploading") or status.get("paused")
            or status.get("downloading") or status.get("settling")
        ):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    def _chosen_remote(self):
        """Which storage saves go to, without its trailing colon, or ""."""
        return (store.get_settings().get("cloud_remote") or "").rstrip(":")

    #: Which copy is running, or "" when none is. Saves move for four
    #: different reasons -- a game closing, a game starting, the copy button and
    #: a restore -- and only the first two are allowed to surprise somebody, so
    #: the other two ask this before they start. It is also what every progress
    #: line is stamped with, because two of those four are silent and a screen
    #: that draws whatever arrives will draw a copy nobody on it asked for.
    _copying: str = ""

    async def _stream_cloud(self, steps, kind=""):
        """Run each copy, reporting how far along it is. Returns (ok, reason).

        Watched rather than waited on, because the thing being copied is
        somebody's save directory over a phone's wifi and a dialog that says
        "Copying..." for ninety seconds is indistinguishable from one that has
        hung. rclone is asked for a stats line a second and the percentage is
        read out of it; each step is one save root, so the bar is that step's
        share of the whole rather than the step's own number, which would
        restart at zero for every emulator.
        """
        total = max(1, len(steps))
        env = self._subprocess_env()
        self._copying = kind
        # Said rather than polled: the panel wants to show that saves are
        # moving, and the two copies worth showing are the two nobody presses a
        # button to start -- so there is no moment the panel could know to ask.
        await decky.emit("cloud_copying", kind)
        try:
            return await self._each_copy(steps, total, env, kind)
        finally:
            # The marker goes now, so a second copy is no longer refused. Saying
            # so is `_copy_settled`, which the caller does once its records are
            # written -- see there.
            self._copying = ""

    async def _each_copy(self, steps, total, env, kind):
        """The copies themselves. Split out so the marker above cannot leak."""
        for index, step in enumerate(steps):
            # A copy carrying `--backup-dir` is one that may move somebody's
            # files out from under them -- into the folder named on the same
            # line, which is what makes it recoverable and what makes it worth
            # writing down.
            if "--backup-dir" in step["argv"]:
                aside = step["argv"][step["argv"].index("--backup-dir") + 1]
                audit.record("copy", emulator=step["id"], moving_aside_into=aside)
            output = procout.Output()
            try:
                process = await asyncio.create_subprocess_exec(
                    *step["argv"],
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                )
            except (OSError, NotImplementedError) as error:
                return False, "Could not run rclone: %s" % error

            async for text in output.segments(process.stdout):
                decky.logger.info("rclone: %s", text)
                within = cloudsync.percent_in(text)
                if within is None:
                    continue
                await decky.emit(
                    "cloud_sync_progress",
                    step["name"],
                    int((index * 100 + within) / total),
                    # Which half of a keep-and-replace this is. Ignored by every
                    # screen but the restore dialog, which says so rather than
                    # showing the copy down's words over the copy up's work.
                    "keeping" if step.get("keeping") else "",
                    kind,
                )

            code = await process.wait()
            if code != 0:
                # The last lines carry the reason; an exit code on its own has
                # cost a debugging round elsewhere in this plugin already. Put
                # through `readable` first: raw rclone log lines in a dialog are
                # six lines of red saying one thing three times.
                return False, "%s: %s" % (
                    step["name"], cloudsync.readable(output.reason))
            await decky.emit(
                "cloud_sync_progress", step["name"],
                int((index + 1) * 100 / total), "", kind)
        return True, ""

    async def _copy_settled(self):
        """Tell the panel a copy is over, once what it changed is written down.

        **After the bookkeeping, not at the end of the copy.** Whether an
        emulator is waiting to be copied is decided by the record of what was
        last sent, and that record is written after the last byte moves -- so a
        panel told at the end of the copy re-read the list a moment early and
        found everything still waiting. Reported on the device as a row that
        would not go away.
        """
        await decky.emit("cloud_copying", "")

    async def _record_pushes(self, remote, steps):
        """Write the record for every emulator a copy just covered.

        One per emulator rather than one per save root: the record is what a
        launch reads, and a launch asks about an emulator.

        All of them in one call, because this runs after the last step with the
        bar at 100% -- see `cloudsync.record_pushes` for what a process each
        was costing there.
        """
        ok, error = await self._run(
            cloudsync.record_pushes, remote,
            sorted({step["id"] for step in steps}))
        if not ok and error:
            decky.logger.warning("Could not record what went up: %s", error)

    async def _adopt_records(self, remote, steps):
        """Take the storage's record for every emulator a restore covered.

        Byte-identical rather than freshly written, which is the whole point:
        `compare` decides "is this our own upload?" by comparing the two, and a
        new record of our own would read as a third device. See
        `cloudsync.adopt_state`.
        """
        for source_id in sorted({step["id"] for step in steps}):
            ok, error = await self._run(cloudsync.adopt_state, remote, source_id)
            if not ok and error:
                decky.logger.warning(
                    "Could not take the storage's record for %s: %s", source_id, error)

    async def _carry_saves(self, steps, done_event, tidy="", adopt="", kind=""):
        """The detached half: run the steps and say how it went, once.

        `tidy` names the storage to prune afterwards, which only a copy *up*
        passes. It happens after the answer has gone out: removing a safety copy
        that has aged out is housekeeping, and nobody should watch a progress
        bar for it.
        """
        names = []
        for step in steps:
            if step["name"] not in names:
                names.append(step["name"])
        try:
            ok, reason = await self._stream_cloud(steps, kind)
            if ok and tidy:
                await self._record_pushes(tidy, steps)
                # **The same stamp a game closing writes.** The panel shows it
                # as "Last copied ...", and copying by hand left it saying
                # hours ago while the copy it describes had just finished. What
                # it covered goes with it: that is how the panel tells an
                # emulator no copy is coming back for from one whose copy has
                # just been.
                await self._run(store.set_settings, {
                    "cloud_last_sync": int(time.time()),
                    "cloud_last_ids": sorted({step["id"] for step in steps}),
                    "cloud_last_remote": tidy,
                })
            if ok and adopt:
                await self._adopt_records(adopt, steps)
            await self._copy_settled()
            await decky.emit(done_event, ok, reason, names if ok else [], kind)
            if ok and tidy:
                await self._run(cloudsync.prune, tidy)
        # Not CancelledError: this runs detached, and `_detach` re-raises a
        # cancellation rather than swallowing it into an emit over a socket that
        # is closing.
        except OSError as error:
            await self._copy_settled()
            await decky.emit(done_event, False, str(error), [], kind)

    @staticmethod
    def _links_skipped():
        """Save folders that are links, which no backup follows. As text.

        In the report because it is the answer to "my saves are not in the
        backup" and nothing else on the Deck says it -- see
        `savedata.links_skipped`.
        """
        lines = []
        for source in savedata.sources():
            for link in source.get("links") or []:
                lines.append("%-22s %s -> %s"
                             % (source["name"], link["at"], link["target"]))
        return "\n".join(lines)

    async def _cloud_summary(self):
        """What the diagnostic report says about cloud saves.

        The rclone version above all -- see the section in `diagnostics`. The
        storage is named by its kind, never by the label this Deck gave it: the
        label is often an account nickname, and a report is a thing people paste
        into a public issue.
        """
        settings = await self._run(store.get_settings)
        if not settings.get("cloud_saves"):
            return "off"
        remote = (settings.get("cloud_remote") or "").rstrip(":")
        kind = (await self._run(cloudsave.remote_kinds)).get(remote, "")
        tool = await self._run(cloudsave.binary)
        told = ""
        if tool:
            ok, output = await self._run(
                cloudsave.rclone, ["version"], 15)
            told = (output or "").strip().splitlines()[0] if ok else "would not answer"
        lines = [
            "%-22s %s" % ("rclone", told or "not installed"),
            "%-22s %s" % ("storage kind", kind or "none chosen"),
            "%-22s %s" % ("storages set up", len(await self._run(cloudsave.remotes))),
            "%-22s %s" % ("copy when a game closes", bool(settings.get("cloud_after_play"))),
            "%-22s %s" % ("check when one starts", bool(settings.get("cloud_before_play", True))),
            "%-22s %s" % ("last copy up", settings.get("cloud_last_sync") or "never"),
        ]
        return "\n".join(lines)

    async def cloud_waiting(self):
        """Which emulators have saves that have not been copied up yet.

        Its own call rather than part of `cloud_status`, because it walks every
        save directory on the Deck and the status row is on the path of every
        panel open. The screen that shows this asks for it after it has drawn.
        """
        settings = await self._run(store.get_settings)
        if not settings.get("cloud_saves") or not (settings.get("cloud_remote") or ""):
            return {"ok": True, "waiting": []}
        waiting = await self._run(
            cloudsync.waiting_to_go, None,
            (settings.get("cloud_remote") or "").rstrip(":"),
            tuple(settings.get("cloud_last_ids") or ()),
            settings.get("cloud_last_remote") or "")
        return {
            "ok": True,
            "waiting": waiting,
            # Separated here rather than in the panel, because what counts as
            # overdue is a fact about the records and the last copy, and two
            # screens deciding it apart is how they come to disagree.
            "overdue": [one for one in waiting if one.get("overdue")],
        }

    async def cloud_backup_now(self, ids=None):
        """Start copying saves up to the storage in use. Returns once it starts.

        Started rather than awaited: a save directory over wifi takes as long as
        it takes, and a call the panel is blocked on cannot report a percentage.
        The answer arrives on `cloud_sync_done`.

        Asked for rather than automatic, and that is deliberate for now: Steam's
        reaper waits for every descendant of a launcher, so an upload started
        from a game's exit trap keeps the library tile reading "Running" until
        it finishes. A button somebody presses has no such cost, and it is the
        thing to have working before anything does it unattended.
        """
        remote = await self._run(self._chosen_remote)
        if not remote:
            return {"ok": False, "error": "No cloud storage is set up yet."}
        if self._copying:
            return {"ok": False, "error": _ALREADY}
        # See `cloudsync.learn_compare`: asked once, and before planning.
        await self._run(cloudsync.learn_compare, remote)
        steps, error = await self._run(cloudsync.push_steps, remote, ids)
        if error:
            return {"ok": False, "error": error}
        self._detach(
            self._carry_saves(steps, "cloud_sync_done", remote, kind="backup"),
            "cloud_sync_done",
            False, "", [],
        )
        return {"ok": True, "started": True}

    #: Launches already being answered, so one that takes four seconds is not
    #: started again on every quarter-second look.
    _fetching: set = set()

    #: A launch waiting on a person to settle a save conflict, by app id. The
    #: value is what they chose, once they have.
    _asked: dict = {}

    #: How long a conflict dialog holds a game before deciding for itself.
    #:
    #: It decides the safe way -- keep what is on this Deck -- because that
    #: overwrites nothing and the storage keeps what it had.
    #:
    #: **Nine minutes, not thirty seconds.** The short version answered for
    #: people who were still reading, which is the one thing a question must not
    #: do. The game is a stopped process the whole time and costs nothing, and
    #: the case this number used to cover -- nobody there at all -- is answered
    #: by `cloud-on` going stale instead. Under the launcher's own watchdog, so
    #: what ends the wait is this rather than the script waking itself.
    _ASK_SECONDS = 540

    def _note_cloud_state(self):
        """Tell the launcher whether waiting for saves is worth it.

        Called from every path that can change the answer -- the setting, the
        chosen storage, signing out of the last one, and startup. One function
        rather than a line at each, because the file being wrong in the "on"
        direction costs every launch a moment for nothing, and in the "off"
        direction costs a save.
        """
        settings = store.get_settings()
        wanted = (bool(settings.get("cloud_saves"))
                  and bool(settings.get("cloud_before_play", True))
                  and bool((settings.get("cloud_remote") or "").strip()))
        launchers.set_cloud_wanted(wanted)

    @staticmethod
    def _source_of(core_id):
        """Which save source a game's core belongs to.

        A catalog emulator carries its own id behind a prefix; anything else is
        a libretro core, and every one of those keeps its saves in RetroArch's
        directories rather than its own.
        """
        if emulators.is_emulator_id(core_id):
            return emulators.emulator_id(core_id)
        return "retroarch"

    async def cloud_backup_after_play(self, core_id: str, app_id: int = 0):
        """Copy one emulator's saves up, after a game using it has closed.

        **Not run from the launcher.** Steam's reaper waits for every descendant
        of the script it started, so an upload in an exit trap holds the library
        tile on "Running" until the network is done -- for a big save directory
        over hotel wifi, minutes of a game that has already quit. This runs in
        decky's own process instead, which the reaper knows nothing about, and
        the panel calls it when it sees the game leave `RunningApps`.

        One emulator, not all of them: that is the whole reason the layout is
        per emulator and the copy is loose files. Closing a Mega Drive game
        sends a handful of kilobytes.

        Silent by design, and it reports only to the log and to
        `cloud_last_sync`. A toast after every game is a notification somebody
        turns off, and the thing it would be announcing is that nothing went
        wrong.
        """
        # **Did this launch reach the emulator at all?** Steam counts an app as
        # running from the moment the script starts, so a launch the two-games
        # gate refused and one declined at the save conflict both end like a
        # session. The launcher says which it was -- see `launchers.took_off`.
        if app_id and not await self._run(launchers.took_off, app_id):
            decky.logger.info("Launch %s never started; nothing copied up", app_id)
            return {"ok": True, "skipped": "never started"}

        # Before the switch below, because this is not about cloud saves: it is
        # the one call the panel makes when any game of ours closes, and the
        # emulator that just ran may have made what one of its settings names.
        await self._reapply_setup(self._source_of(core_id))

        settings = await self._run(store.get_settings)
        if not settings.get("cloud_saves") or not settings.get("cloud_after_play"):
            return {"ok": True, "skipped": "off"}
        remote = (settings.get("cloud_remote") or "").rstrip(":")
        if not remote:
            return {"ok": True, "skipped": "nowhere to put it"}
        if not await self._run(cloudsave.binary):
            return {"ok": True, "skipped": "no rclone"}

        source = self._source_of(core_id)

        # Nothing was written, so there is nothing to send -- and sending
        # anyway is not merely wasteful: it rewrites the record beside the
        # saves, which is how "Don't start" at a save conflict ended up doing
        # the thing it was pressed to avoid. See `changed_since_push`.
        if not await self._run(cloudsync.changed_since_push, source, remote):
            decky.logger.info("Nothing changed for %s; nothing copied up", source)
            return {"ok": True, "skipped": "nothing changed"}

        await self._run(cloudsync.learn_compare, remote)
        steps, error = await self._run(cloudsync.push_steps, remote, [source])
        if error:
            # Ordinary, not a failure: an emulator with no save directory yet
            # has nothing to send, and a game closing is a bad moment to be told
            # about it either way.
            decky.logger.info("Nothing to copy up for %s: %s", source, error)
            return {"ok": True, "skipped": error}

        ok, reason = await self._stream_cloud(steps, "after-play")
        if not ok:
            await self._copy_settled()
            decky.logger.warning("Could not copy %s up after play: %s", source, reason)
            return {"ok": False, "error": reason}

        # The record of what just went up, beside the saves and here. Without it
        # the next launch has nothing to compare and treats the storage as
        # untouched -- see `cloudsync.compare`.
        await self._run(cloudsync.record_push, remote, source)
        await self._run(store.set_settings, {
            "cloud_last_sync": int(time.time()),
            "cloud_last_ids": [source],
            "cloud_last_remote": remote,
        })
        await self._copy_settled()
        await self._run(cloudsync.prune, remote)
        decky.logger.info("Copied %s up after play", source)
        return {"ok": True}

    async def _settle_conflict(self, app_id, remote, source, found):
        """Put a save disagreement to somebody and act on the answer.

        Lifted out of `cloud_before_play`, which was 157 lines holding four
        separate decisions -- whether to look, the comparison, this, and the
        fetch -- with the `finally` that releases the launch 130 lines below the
        `try` that needs it. This is the half where a wrong edit costs a save,
        so it is the half worth reading on its own.

        Returns what the caller should return, or `None` for "keep this Deck's":
        that answer is not an ending, and the caller goes on to fetch what is
        only up there.
        """
        differing = found["differing"]
        # **The game waits while the question is on screen**, which is what
        # Steam's own cloud conflict does and the reason the heartbeat exists.
        # Answering is what releases it. The emulator's name goes with it: the
        # question is about everything that emulator keeps, not about the game
        # being started, and a dialog that names only the game reads as a
        # narrower promise than the answer delivers.
        await decky.emit(
            "cloud_conflict", app_id, differing, found["here"], found["there"],
            await self._run(cloudsync.name_of, source))
        chosen = await self._wait_for_answer(app_id)

        if chosen == "went":
            # The launch this was about has gone. Say so, so the dialog standing
            # over a game that is no longer starting comes down with it.
            await decky.emit("cloud_fetch_done", app_id, [])
            return {"ok": True, "differing": [], "restored": 0}

        if chosen == "stop":
            # Ends the stopped process rather than leaving a note for it to
            # find. A note written a moment too late used to refuse the *next*
            # launch instead of this one.
            await self._run(launchers.refuse_launch, app_id)
            return {"ok": True, "differing": differing, "restored": 0,
                    "stopped": True}

        if chosen == "cloud":
            # **Kept before they are overwritten.** These are the local
            # versions, which by definition the storage does not have -- so
            # without this they are the one thing this feature could destroy,
            # under a dialog promising neither answer loses anything. They land
            # beside every other replaced copy, so the restore screen lists them
            # already.
            kept, keep_error = await self._run(
                cloudsync.preserve_local, remote, source, differing)
            if not kept:
                # **Nothing is overwritten when the net failed.** This used to
                # log and carry on, which is the one path in this feature that
                # can destroy the only copy of a save: the local versions are by
                # definition the ones the storage does not have. A dialog that
                # says neither answer loses anything has to mean it even when a
                # storage is having a bad minute, so the answer is refused
                # rather than half-done, and the Deck keeps what it has -- which
                # is the outcome that can still be changed afterwards.
                decky.logger.error(
                    "Not overwriting %s: could not keep this Deck's copies "
                    "first (%s)", source, keep_error)
                await self._run(cloudsync.remember_answer, source, found["theirs"])
                await self._run(launchers.wake_launch, app_id)
                return {"ok": False, "differing": [], "restored": 0,
                        "error": "Your saves could not be kept before being "
                                 "replaced, so nothing was changed. The game "
                                 "starts with the saves on this Deck."}
            # The roots `compare` already found, rather than a second listing.
            # Measured on the device: listing the whole saves tree on Dropbox is
            # 14.5 seconds, and it was happening between somebody pressing the
            # button and any file moving.
            known = {(source, root) for root in found["roots"]}
            steps, plan_error = await self._run(
                cloudsync.pull_steps, remote, [source], True, "", known)
            if not plan_error:
                pulled, _reason = await self._stream_cloud(steps, "launch")
                if pulled:
                    await self._reapply_setup(source)
            # This Deck now holds what the storage holds, so the record of "what
            # we last put there" is theirs. Without this the next launch would
            # ask the same question again.
            await self._run(cloudsync.adopt_state, remote, source)
            return {"ok": True, "differing": [], "restored": len(differing)}

        # Keeping this Deck's. None of the disagreeing files is touched, and the
        # answer is remembered, or the next launch would compare the same two
        # records, find the same disagreement, and ask again. The next copy up
        # puts these saves in the storage, where what they replace is kept.
        await self._run(cloudsync.remember_answer, source, found["theirs"])
        return None

    async def _reapply_setup(self, source):
        """Re-apply an emulator's settings when what they name may have moved.

        The sweep that keeps settings current runs at startup and when the panel
        opens, and a setting can depend on files that change in between: Xenia's
        `{xenia_profile}` names a profile that lives in its saves folder. Two
        moments, both measured on a Deck:

        * Saves came down before a launch. The sweep had run before the pull, so
          a profile Dropbox brought back booted unnamed, and the game opened
          Xenia's sign-in screen anyway.
        * A game closed. The emulator has just run and may have made what a
          setting names: a first profile, created in Xenia's own dialog, was not
          signed in on the next launch, because a game started from the library
          passes neither of the sweep's moments.

        Only into configs the emulator has already written -- see
        `emu_config.missing_files` -- and free when nothing moved: the writers
        leave a file alone when none of its values would change.
        """
        entry = emulator_catalog.find(source)
        if not entry or not entry.get("setup"):
            return
        if await self._run(emu_config.missing_files, entry["setup"]):
            return
        result = await self._run(emu_config.apply_setup, entry)
        if not result.get("ok"):
            decky.logger.warning("Could not re-apply %s settings after saves came down: %s",
                                 source, result.get("error"))

    async def cloud_before_play(self, app_id: int, core_id: str):
        """Bring down what this Deck is missing before a game opens its saves.

        Called as a launch begins. The launcher is waiting on a file by then --
        see `launchers.hold_for_cloud` -- so this has to answer, and answer
        whatever happens: every path out of here releases the launch.

        **What comes down without asking is only what is not here.** That cannot
        overwrite a save, so there is no question to put to anybody and none is
        asked. Files that exist in both places and differ are reported instead:
        deciding which of two versions somebody wants is not a decision to make
        on their behalf from two clocks, and it is the one thing here worth
        interrupting a launch for.
        """
        settings = await self._run(store.get_settings)
        remote = (settings.get("cloud_remote") or "").rstrip(":")
        # The switch says not to look, so nothing is looked at and the launch
        # goes on. `_note_cloud_state` has already told the launcher not to wait
        # at all, so this is the belt to that brace: a launcher written before
        # the switch was turned off still holds, and still has to be released.
        if (not settings.get("cloud_saves") or not remote
                or not settings.get("cloud_before_play", True)):
            await self._run(launchers.wake_launch, app_id)
            return {"ok": True, "differing": [], "restored": 0}
        if not await self._run(cloudsave.binary):
            await self._run(launchers.wake_launch, app_id)
            return {"ok": True, "differing": [], "restored": 0}

        source = self._source_of(core_id)
        # Before the comparison as well: a launch that has to fetch or set aside
        # plans steps of its own.
        await self._run(cloudsync.learn_compare, remote)
        try:
            found = await self._run(cloudsync.compare, remote, source)
            missing = found["missing"]
            differing = found["differing"]
            roots = found["roots"]
            here_at, there_at = found["here"], found["there"]
            error = found["error"]
            if error:
                # A storage that cannot be reached is not a reason to stop
                # somebody playing. The saves on the Deck are the ones that get
                # used, which is what would have happened anyway.
                decky.logger.info("Could not compare %s before play: %s", source, error)
                return {"ok": True, "differing": [], "restored": 0}

            restored = 0
            answered = False
            if differing:
                settled = await self._settle_conflict(app_id, remote, source, found)
                if settled is not None:
                    return settled
                # Nothing returned means "keep this Deck's", which is not an
                # ending: a save that is only up there was never part of the
                # disagreement, so the fetch below still runs. Refusing it would
                # make that answer mean more than it says.
                answered = True

            if missing:
                # The pairs `compare` already found, rather than a second
                # listing of the same folder: two round trips on the front of a
                # launch is what made the game start without its save.
                known = {(source, root) for root in roots}
                steps, plan_error = await self._run(
                    cloudsync.pull_steps, remote, [source], False, "", known)
                if not plan_error:
                    ok, reason = await self._stream_cloud(steps, "launch")
                    if ok:
                        restored = missing
                        decky.logger.info(
                            "Brought %d file(s) down for %s before play", missing, source)
                        await self._reapply_setup(source)
                    else:
                        decky.logger.warning(
                            "Could not bring %s down before play: %s", source, reason)
            # `differing` is emptied once it has been answered: whatever the
            # answer was, there is no question left standing for the panel.
            return {"ok": True, "differing": [] if answered else differing,
                    "restored": restored}
        finally:
            # Every way out, including a throw. A launch left stopped by a check
            # that died is a game that never starts, which is worse than every
            # problem this method exists to prevent. Harmless after a refusal:
            # the process is gone and `wake_launch` checks before it signals.
            await self._run(launchers.wake_launch, app_id)
            await self._copy_settled()

    #: How often to look for a launcher that is waiting.
    #:
    #: A `listdir` of a directory with at most a couple of files in it, and only
    #: while cloud saves have somewhere to go. The number is how long a launch
    #: sits idle before anything starts happening, so it is small; the cost of
    #: making it small is nothing anybody can measure.
    _WATCH_SECONDS = 0.25

    async def _watch_launches(self):
        """Answer launchers that are waiting for their saves.

        **Why the backend watches rather than the panel telling it.** Steam
        announces a launch to the panel at about the moment the launcher script
        runs, and the round trip from that announcement through decky is slower
        than a shell reaching its next line -- so two versions of this, one with
        a two-second grace on it, both let the game start before the save
        arrived. Measured on the device, twice.

        The launcher now writes its own file before it waits, so there is no
        race left to lose: whatever finds that file has as long as it needs.
        This loop is what finds it.
        """
        while True:
            try:
                await asyncio.sleep(self._WATCH_SECONDS)
                # Said on the way past, because this loop is the one thing that
                # runs for as long as the plugin does. A launch reads the
                # timestamp to tell "nobody has answered yet" from "nobody is
                # there" -- see `launchers.CLOUD_STALE_SECONDS`.
                self._beat = getattr(self, "_beat", 0) + 1
                if self._beat * self._WATCH_SECONDS >= launchers.CLOUD_ALIVE_SECONDS:
                    self._beat = 0
                    await self._run(launchers.say_alive)
                waiting = await self._run(launchers.launches_waiting)
                for app_id in waiting:
                    if app_id in self._fetching:
                        continue
                    # A file whose process has gone is not a launch waiting for
                    # anything. Left alone it would be answered on every look --
                    # the same conflict dialog over and over, for a game that is
                    # not going to start.
                    if await self._run(launchers.gone, app_id):
                        await self._run(launchers.forget_launch, app_id)
                        continue
                    self._fetching.add(app_id)
                    self._detach(
                        self._answer_launch(app_id), "cloud_fetch_done", app_id, [])
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- a loop that must not die
                decky.logger.exception("Launch watch failed: %s", error)

    async def _answer_launch(self, app_id):
        """Fetch what one held launch is missing, then let it go."""
        try:
            library = await self._run(store.get_library)
            entry = (library or {}).get(str(app_id)) or {}
            core_id = entry.get("core_id") or ""
            if not core_id:
                # Not one of ours, or a record we no longer have. Either way the
                # launcher is waiting and nothing here can help it.
                return
            await decky.emit("cloud_fetch_started", app_id, entry.get("title") or "")
            result = await self.cloud_before_play(app_id, core_id)
            await decky.emit(
                "cloud_fetch_done", app_id, result.get("differing") or [])
        finally:
            # Whatever happened, the launch goes and the id is free to be seen
            # again. `cloud_before_play` releases too; this is the path where it
            # was never reached.
            await self._run(launchers.wake_launch, app_id)
            self._fetching.discard(app_id)

    async def _wait_for_answer(self, app_id):
        """Hold until somebody settles a save conflict, or the launch goes away.

        Nothing has to be told this is still going: the launch is a stopped
        process and stays stopped until it is woken, so a dialog somebody is
        reading costs exactly nothing.

        **It ends when the launch does, not only when the clock says so.** The
        question exists for one launch; if that process is gone -- backed out
        of, cancelled by Steam, ended some other way -- there is nobody left to
        answer and nothing left to answer about. Waiting on regardless is worse
        than useless: this app id counts as in flight the whole time, so every
        *later* launch of the same game is skipped without a word. That is
        exactly how a conflict dialog stopped appearing after one was left
        unanswered.
        """
        self._asked[app_id] = ""
        # Which launch this question belongs to. There is one file per game, so
        # relaunching replaces it -- and a question still standing over the
        # previous launch has nobody left to answer it.
        mine = await self._run(launchers.which_launch, app_id)
        waited = 0.0
        while waited < self._ASK_SECONDS:
            await asyncio.sleep(0.2)
            waited += 0.2
            if self._asked.get(app_id):
                return self._asked.pop(app_id)
            # Once a second: two `os.stat` calls, against the alternative of
            # the whole feature going quiet.
            if waited % 1 < 0.2:
                now = await self._run(launchers.which_launch, app_id)
                if now != mine:
                    self._asked.pop(app_id, None)
                    decky.logger.info(
                        "The launch asking about %s is gone; nothing to answer",
                        app_id)
                    return "went"
        self._asked.pop(app_id, None)
        # Nobody there. Keep what is on the Deck, which writes nothing and
        # loses nothing -- the storage still holds its copy.
        decky.logger.info("Save conflict for %s went unanswered; kept the Deck's",
                          app_id)
        return "deck"

    async def cloud_answer_conflict(self, app_id: int, choice: str):
        """What somebody chose in the save conflict dialog.

        "cloud" takes the storage's copies, "deck" keeps what is here, "stop"
        does not start the game at all.
        """
        if choice not in ("cloud", "deck", "stop"):
            return {"ok": False, "error": "That is not an answer."}
        self._asked[app_id] = choice
        return {"ok": True}

    async def cloud_release_launch(self, app_id: int):
        """Let a held launch go now, whatever the fetch is doing.

        The dialog's own button. Whatever was still coming down keeps coming --
        it is a copy into a directory, not a transaction -- and a file that
        lands after the emulator has read it is one the restore screen can put
        back. A game that will not start is the failure none of this is worth.
        """
        await self._run(launchers.wake_launch, app_id)
        return {"ok": True}

    async def cloud_emulators(self, name: str, stamp: str = ""):
        """Which emulators one storage holds saves for. One cheap listing.

        Any storage signed into, not only the one in use. That is the whole of
        the answer to "my saves are in Dropbox and I am on pCloud now": nothing
        was moved, nothing was stranded, and reading the old one is one press
        rather than a migration.

        `stamp` reads what one copy replaced rather than the live saves.

        The restore screen draws its rows from this and fills each in with
        `cloud_describe`, because describing one is a tree walk and describing
        fourteen is eleven seconds of nothing on screen.
        """
        if not await self._run(cloudsave.binary):
            return {"ok": False, "error": "The cloud transfer tool is missing.",
                    "emulators": []}
        if name not in await self._run(cloudsave.remotes):
            return {"ok": False, "error": "That storage is not set up on this Deck.",
                    "emulators": []}
        listed, error = await self._run(cloudsync.listed_on, name, stamp)
        return {"ok": not error, "error": error, "emulators": listed}

    async def cloud_describe(self, name: str, emulator: str, stamp: str = ""):
        """One emulator's row, asked for on its own so a screen can fill in."""
        if name not in await self._run(cloudsave.remotes):
            return {"ok": False, "error": "That storage is not set up on this Deck."}
        row = await self._run(cloudsync.describe_one, name, emulator, stamp)
        return {"ok": True, "row": row or None}

    async def cloud_snapshots(self, name: str):
        """The states a copy replaced on one storage, newest first.

        Offered on the Deck rather than left in the folder. A safety copy that
        can only be reached by opening Dropbox on a laptop is the second device
        this plugin exists to do without -- it would be a net nobody in Game
        Mode can get to.
        """
        if not await self._run(cloudsave.binary):
            return {"ok": True, "snapshots": []}
        if name not in await self._run(cloudsave.remotes):
            return {"ok": False, "error": "That storage is not set up on this Deck.",
                    "snapshots": []}
        listed, error = await self._run(cloudsync.snapshots, name)
        return {"ok": not error, "error": error, "snapshots": listed}

    async def cloud_restore(self, name: str, ids=None, replace: bool = False,
                            stamp: str = "", keep: bool = False):
        """Start bringing saves down from one storage. `replace` overwrites.

        The same two words the local restore uses, meaning the same two things,
        because they are the same decision -- see `cloudsync.pull_steps`. Also
        streamed, and on the same pair of events: only one of these can be
        running and both screens draw one bar.
        """
        if not await self._run(cloudsave.binary):
            return {"ok": False, "error": "The cloud transfer tool is missing."}
        if name not in await self._run(cloudsave.remotes):
            return {"ok": False, "error": "That storage is not set up on this Deck."}
        # **Not while something else is moving the same files.** Quitting a game
        # starts a copy up nobody sees, and this is two presses away from the
        # panel that follows it -- so a restore could be writing an emulator's
        # saves while that copy reads them, and both would write a record
        # afterwards describing a state neither half was in.
        if self._copying:
            return {"ok": False, "error": _ALREADY}
        # Asked once, before anything is planned: what a storage can be
        # compared by decides the flags every step carries, and planning is
        # meant to run no subprocess. See `cloudsync.learn_compare`.
        await self._run(cloudsync.learn_compare, name)

        steps, error = await self._run(
            cloudsync.pull_steps, name, ids, replace, stamp)
        if error:
            return {"ok": False, "error": error}

        # **Before anything moves, including the copy that keeps a copy.** A
        # restore that runs the drive out partway leaves a save set that is half
        # one version and half another, which is worse than either -- and the
        # sizes are already known, so saying it now costs one comparison.
        fits, tight = await self._run(cloudsync.room_for, name, ids, replace, stamp)
        if not fits:
            return {"ok": False, "error": tight}
        # **What this is about to overwrite, kept first -- when asked.**
        # Replacing is the one thing here that destroys a save with nothing put
        # aside, and it is two presses from a list of storages. So the
        # confirmation offers it, rather than a setting deciding for everybody:
        # somebody restoring onto a wiped Deck has nothing worth keeping and no
        # reason to wait for an upload of it.
        #
        # **Planned, not run**, and put in front of the restore's own steps so
        # one bar covers both halves. Run inline it was a dialog sitting still
        # for the length of an upload of every save on the Deck.
        #
        # One `when` for the press rather than one per emulator, so what it
        # keeps is a single dated row under earlier copies -- the same folder,
        # shape and screen as everything else this plugin sets aside.
        # Every replace, kept copy or not: this is the one press that
        # overwrites saves on the Deck itself.
        if replace:
            audit.record("replacing", remote=name, stamp=stamp or "live",
                         emulators=sorted({step["id"] for step in steps}),
                         keeping_a_copy=bool(keep))

        if replace and keep:
            when = time.strftime("%Y%m%d-%H%M%S")
            keeping = []
            for source_id in sorted({step["id"] for step in steps}):
                names = await self._run(cloudsync.everything_local, source_id)
                if not names:
                    continue
                planned, plan_error = await self._run(
                    cloudsync.preserve_steps, name, source_id, names, when)
                if plan_error:
                    # Refused rather than half-done, for the reason the conflict
                    # path gives: the copy is the whole point of asking.
                    return {"ok": False,
                            "error": "Your saves could not be kept first, so "
                                     "nothing was replaced. %s" % plan_error}
                keeping += planned
            steps = keeping + steps
        self._detach(
            # **Taking the storage's copies means taking its record with them.**
            # Answering a launch conflict with "use the cloud's" has always done
            # this; pressing Restore all is the same act with more deliberation
            # behind it, and it was leaving the Deck holding the storage's files
            # under a record describing its own last upload -- so the next game
            # to close copied that emulator up again for nothing.
            #
            # Only for Restore all. Restore missing leaves this Deck's own
            # versions of everything that differed, so it does *not* hold what
            # the storage holds and must not claim to. And not for a snapshot:
            # what was put back is what one copy replaced, which is older than
            # the record sitting beside the live saves.
            self._carry_saves(
                steps, "cloud_sync_done",
                adopt=name if (replace and not stamp) else "",
                kind="restore",
            ),
            "cloud_sync_done", False, "", [],
        )
        return {"ok": True, "started": True}

    async def save_backup_sources(self):
        """What a save backup would carry, per emulator, measured on the device.

        Asked before anything is built, because the sizes are the whole of the
        decision: an emulator that declares its save directory contributes
        kilobytes, and one that does not contributes everything it keeps. The
        panel shows both and lets the second be unticked.
        """
        return {"ok": True, "sources": await self._run(savedata.sources)}

    async def start_save_backup(self, ids=None):
        """Build a save backup and put it where another device can read it.

        The same errand as `start_report` and deliberately the same shape: a
        server that hands one thing out and accepts nothing, a QR code for a
        camera and six digits for anything else. What differs is that this one
        writes a real file, so it has a lifetime -- `end_save_backup` deletes it,
        and so does the next backup, because two copies of somebody's saves in
        decky's runtime directory is one more than anybody asked for.
        """
        await self._run(self._clear_backups)

        destination = os.path.join(savedata.BACKUP_DIR, savedata.default_name())
        built = await self._run(savedata.build, destination, ids)
        if not built.get("ok"):
            return built

        serving = await self._run(fileserver.status)
        if not serving.get("running"):
            # Started to hand a backup out and nothing else. Same rule as the
            # report: showing somebody a file must not also hand them somewhere
            # to write, and they could not tell they had been given one.
            started = await self._serve(False)
            if started.get("error"):
                await self._run(self._clear_backups)
                return {"ok": False, "error": started["error"]}

        await self._run(
            fileserver.offer_download,
            destination,
            os.path.basename(destination),
            built.get("bytes", 0),
            built.get("emulators") or [],
        )
        decky.logger.info(
            "Save backup ready: %s (%d bytes)", os.path.basename(destination),
            built.get("bytes", 0),
        )
        return {"ok": True, "backup": built, **await self._run(fileserver.status)}

    async def end_save_backup(self):
        """Withdraw the backup, delete it, and stop the server if that was all it did.

        The deletion is the part that matters. A report is a log tail held in
        memory; this is a copy of somebody's save files sitting in decky's
        runtime directory, and leaving it there means the next person to read
        that directory finds it. Pressing Done means it is gone.

        The server itself only stops when nothing is moving in either direction.
        It may have been up for a transfer that is still running -- cutting off a
        multi-gigabyte ROM because somebody closed an unrelated dialog is the
        failure this guard exists for -- and it may be streaming this very backup
        to the device that asked for it. That second half was missing: the report
        this borrowed its shape from is one page load and is in the reader's
        browser before anything can interrupt it, and 75MB over a phone's wifi is
        not.
        """
        await self._run(fileserver.offer_download, "")
        await self._run(self._clear_backups)
        status = await self._run(fileserver.status)
        if status.get("running") and not (
            status.get("uploading") or status.get("paused") or status.get("downloading")
        ):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    async def list_save_backups(self):
        """Backups on this Deck, newest first.

        Restoring starts from the Library tab beside taking a backup, rather
        than from the ROM picker: the file is not a game, and every row of the
        add flow -- the name, the artwork, the core -- is about something this
        is not. So the tab finds the file instead of the user pointing at it.

        Both folders are read. `savedata.take_delivery` moves an arriving backup
        into its own, but one that could not be moved is still restorable, and an
        install that predates that has its backups where they landed.
        """
        return {
            "ok": True,
            # Where a backup belongs, so the transfer dialog can be pointed at it
            # and say so truthfully. It used to be started on the ROM inbox and
            # told the user files would land there, while `take_delivery` moved
            # them somewhere else the moment they arrived.
            "dir": await self._run(savedata.arrivals_dir),
            "backups": await self._run(
                savedata.backups_in,
                await self._run(savedata.arrivals_dir),
                await self._run(fileserver.default_dir),
            ),
        }

    async def discard_save_backup(self, path: str):
        """Delete one backup from this Deck without restoring it.

        Restoring already consumes the archive, so this is for the other case:
        a backup somebody has finished with, or sent by mistake, or that is
        simply the old one. Without it the only way to remove a 75MB file is to
        restore from it, which is not a thing to have to do to tidy up.
        """
        backups = await self._run(
            savedata.backups_in,
            await self._run(savedata.arrivals_dir),
            await self._run(fileserver.default_dir),
        )
        # Only something this plugin just listed. The path comes from the
        # frontend, and a delete pointed at an arbitrary path is not what this
        # is for -- the same rule `inbox_path` enforces for the folder next door.
        if not any(entry["path"] == path for entry in backups):
            return {"ok": False, "error": "That backup is not on this Deck."}
        try:
            await self._run(os.remove, path)
        except OSError as error:
            return {"ok": False, "error": "Could not delete it: %s" % error}
        decky.logger.info("Discarded save backup %s", os.path.basename(path))
        return {"ok": True, "removed": True}

    async def describe_save_backup(self, path: str):
        """What an archive holds and whether this Deck can take it.

        Answers before anything is written, because the counts are the decision:
        how many of these files are already here is what separates "put back what
        is missing" from "replace what is there".
        """
        return await self._run(savedata.describe, path)

    async def restore_save_backup(self, path: str, ids=None, replace: bool = False):
        """Put saves back from an archive sent to this Deck, then delete it.

        `replace` overwrites saves already here and is the one destructive thing
        in it; off, nothing already present is touched.

        **The archive goes once it has been read**, the same as
        `unpack_transferred_file` deletes the zip it extracted, and for the rule
        that file states: everything that uses a file takes it out of the folder.

        This was written the other way first, on the reasoning that a partial
        restore skips saves already here and the archive is therefore the only
        copy of the versions it did not write. That reasoning is wrong: the
        archive *arrived from another device*, so the copy it was sent from is
        still there. What it produced was 75MB sitting on the Deck with nothing
        in Game Mode able to remove it -- the same fault
        `discard_transferred_file` exists to fix, one folder over.

        Only after a restore that succeeded. A failure leaves the file, because
        then it really is the way to try again.
        """
        result = await self._run(savedata.restore, path, ids, replace)
        if not result.get("ok"):
            return result
        try:
            await self._run(os.remove, path)
            result["removed"] = os.path.basename(path)
        except OSError as error:
            # The saves are back, which is what was asked for. An archive that
            # could not be deleted is untidy, not a failed restore.
            decky.logger.warning("Restored from %s but could not remove it: %s", path, error)
        return result

    @staticmethod
    def _clear_backups():
        """Delete every archive left in the staging directory.

        Everything in there is this plugin's own, named by `savedata`, and each
        one is a full copy of the saves it was taken from. Cleared before
        building and again when the dialog closes, so the only time one exists is
        while somebody is looking at the address it is offered on.
        """
        try:
            names = os.listdir(savedata.BACKUP_DIR)
        except OSError:
            return
        for name in names:
            path = os.path.join(savedata.BACKUP_DIR, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError as error:
                decky.logger.warning("Could not remove old backup %s: %s", path, error)

    async def end_report(self):
        """Withdraw the report, and stop the server if it was only serving that.

        Pressing Done means done: the report is the tail of a log, and leaving it
        on the network afterwards is exposure nobody asked for. The page already
        open on the other device keeps working -- it is one load, and its text is
        in that browser rather than fetched again -- so ending this costs the
        reader nothing they are looking at.

        The server itself only stops when nothing is arriving. `start_report`
        will have started it if it was down, but it may equally have been up for
        a transfer that is still running, and cutting a multi-gigabyte ROM off
        because somebody closed an unrelated dialog is the failure this guard
        exists for. The transfer's own dialog uses the same rule.
        """
        await self._run(fileserver.offer_report, "")
        status = await self._run(fileserver.status)
        if status.get("running") and not (
            status.get("uploading") or status.get("paused") or status.get("downloading")
        ):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    @staticmethod
    def _installed_catalog_ids():
        """Which catalog emulators are actually on the device, as `id (channel)`.

        Deliberately not async. It goes through `_run` because probing a flatpak
        shells out, and handing `_run` a coroutine function does not run it --
        the executor calls it, gets a coroutine object back, and nothing ever
        awaits it. What reaches the caller is that object rather than a list,
        and the first thing done with it raises somewhere else entirely.
        """
        found = []
        for entry in emulator_catalog.CATALOG:
            source = entry.get("source") or {}
            kind = source.get("kind")
            if kind == "flatpak" and emu_install.flatpak_installed(source.get("id", "")):
                found.append("%s (flatpak)" % entry["id"])
            elif kind == "github" and emu_install.installed_appimage(entry["id"]):
                found.append("%s (appimage)" % entry["id"])
        return found

    async def _serve(self, uploads, target_dir=""):
        """Start the file server the one way there is, and record what it bound.

        **A remembered link is remembered whichever door asks for the server.**
        Three callers start it -- a transfer, a diagnostic report, a save backup
        -- and only the first honoured `transfer_remember`, so somebody who had
        deliberately made their link durable and bookmarked it on a laptop got a
        different address, a different token and a different six digits the
        moment they asked for a report or a backup. The setting says "keep the
        transfer address the same between sessions"; a session is a session.

        Recording matters as much as reusing. The port and token written back are
        whatever was *actually* bound and minted, never what was asked for: a
        remembered port can be taken by something else and fallen back from, and
        the first durable session started by a report would otherwise never be
        saved -- so the next transfer would mint a different one and quietly
        break the bookmark.

        `uploads` stays the caller's business and is deliberately not folded in
        here. It answers a different question -- whether this server is an inbox
        or only hands something out -- and the report and the backup need it off
        for a reason no remembered link changes.
        """
        settings = await self._run(store.get_settings)
        remember = bool(settings.get("transfer_remember"))
        result = await self._run(
            fileserver.start,
            target_dir or await self._run(fileserver.default_dir),
            int(settings.get("transfer_port") or 0) if remember else 0,
            (settings.get("transfer_token") or "") if remember else "",
            uploads,
        )
        if result.get("error"):
            return result
        if remember:
            await self._run(
                store.set_settings,
                {
                    "transfer_port": result.get("port", 0),
                    "transfer_token": await self._run(fileserver.current_token),
                },
            )
        return result

    async def start_file_server(self, target_dir: str = ""):
        # Empty means the default folder. Lets a caller start receiving in one call
        # without first asking where that is.
        result = await self._serve(True, (target_dir or "").strip())
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        # The server may already have been up to hand out a report, which does
        # not accept files. This is a transfer, so it does now.
        await self._run(fileserver.allow_uploads)
        return {"ok": True, **result}

    async def reset_transfer_link(self):
        """Invalidate every saved link. The next start issues a fresh one.

        All or nothing by design: the link is the credential, so there is nothing
        per-device to revoke. Refused while a transfer is running, because taking
        the address away mid-upload would cut off the very device that is using it.
        """
        status = await self._run(fileserver.status)
        if status.get("uploading"):
            return {
                "ok": False,
                "error": "A transfer is still running. Wait for it to finish, or cancel it first.",
            }
        # And the same for the other direction, which this used not to consider.
        # The restart below brings the server back up as an *inbox* -- which is
        # right when it was one, and turns a server that existed only to hand a
        # report or a backup out into somewhere the holder of the old QR code can
        # write. Refusing while something is being offered keeps that from
        # happening behind the user's back, and it is the same answer the line
        # above gives for an upload: finish what you are doing first.
        if status.get("downloading") or status.get("report_url") or status.get("download_url"):
            return {
                "ok": False,
                "error": "Something is still being handed out. Close that dialog first.",
            }

        await self._run(store.set_settings, {"transfer_port": 0, "transfer_token": ""})
        decky.logger.info("Reset the transfer link; saved bookmarks no longer work")

        # Restarted rather than left running, so the old link stops working now
        # instead of at the end of a session the user thinks they have revoked.
        if status.get("running"):
            await self._run(fileserver.stop)
            return await self.start_file_server(status.get("target_dir", ""))
        return {"ok": True, "running": False}

    async def stop_file_server(self):
        """Stop the server, whatever is happening. The Stop button."""
        result = await self._run(fileserver.stop)
        return {"ok": True, **result}

    async def stop_file_server_if_idle(self):
        """Stop it only if nothing is arriving. Dismissing the dialog.

        Its own endpoint rather than a flag on the one above, because the two
        are different promises: Stop is the user ending the transfer, and this
        is the dialog going away, which must never do that. The difference used
        to be decided in the dialog from its last poll -- up to a few seconds
        old -- so closing it quickly after sending a file stopped the server on
        top of the upload that had just begun.
        """
        result = await self._run(fileserver.stop_if_idle)
        return {"ok": True, **result}

    async def discard_transferred_file(self, name: str):
        """Delete one file from the transfer folder. The only way to, in Game Mode.

        Everything else that removes something from there does it as a side
        effect of using it: an import consumes the definition, a firmware
        install moves the file where the emulator reads it, a cancel deletes the
        partial it was writing. Nothing removed a file that was simply not
        wanted -- a refused definition, a ROM thought better of, a BIOS for an
        emulator since uninstalled -- so the staging folder only ever grew, and
        the alternative was Desktop Mode and a file manager, which is the thing
        this plugin exists to avoid.

        By name out of the folder rather than by a path the frontend supplies.
        `inbox_path` refuses anything that is not already the basename of a real
        file in there, so this cannot be pointed at a save game or a launcher.

        A playlist takes its tracks with it. `Game.cue` on its own is not a
        thing anybody wants deleted -- the twelve `.bin` files it named are the
        game, and left behind they are raw sectors nothing will ever point at
        again. The dialog counts them before asking, so what goes is what was
        agreed to.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            # Already gone is the answer the caller wanted, not a failure: two
            # presses on a slow list should not produce an error the second time.
            return {"ok": True, "removed": False,
                    "received": await self._run(fileserver.received_files)}

        # Tracks first and the sheet last, so a failure part-way leaves the
        # sheet still listed. The row stays, pressing it again finishes the
        # job, and the set is never a pile of nameless tracks with nothing
        # above them.
        group = await self._run(_owned_beside, path)
        for victim in group + [path]:
            try:
                await self._run(os.remove, victim)
            except OSError as error:
                return {"ok": False,
                        "error": "Could not delete %s: %s"
                                 % (os.path.basename(victim), error)}

        decky.logger.info("Discarded %s from the transfer folder, with %d "
                          "file(s) it named", name, len(group))
        return {"ok": True, "removed": True,
                "received": await self._run(fileserver.received_files)}

    async def discard_stopped_transfer(self, partial: str):
        """Delete what arrived of a transfer nobody is sending any more.

        A cancelled or interrupted transfer keeps its half-file so sending the
        file again carries on, and until this there was no way to be rid of one
        in Game Mode short of waiting for the next server session. By the
        half-file's bare name; `fileserver.discard_partial` refuses anything
        else, and anything still arriving.
        """
        removed, error = await self._run(fileserver.discard_partial, partial or "")
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "removed": removed}


    async def unpack_transferred_file(self, name: str):
        """Extract a zip in the transfer folder, in place. The only way to, in Game Mode.

        Xbox 360 content is what forced this. Every XBLA release is distributed
        zipped, Xenia refuses a zip outright -- it shows an error box, which
        gamescope will not draw, so it presents as a hang -- and nothing here
        could extract one. The route from "sent to the Deck" to "playable" went
        through Desktop Mode and a file manager, and nothing in this plugin may
        need Desktop Mode to finish. Zipped multi-file games had the same dead
        end long before Xenia existed; nobody had hit it because RetroArch reads
        a zip itself, and every emulator that cannot is a recent arrival.

        A Switch `.nsz` comes through here too. Ryujinx cannot open one, and
        `switch_nsz` writes the `.nsp` it can -- the same press of Unpack, and
        the same rule that the file it came from goes once it is done.

        By name out of the folder, like the delete beside it: `inbox_path`
        refuses anything that is not already the basename of a real file in
        there, so this cannot be aimed at an archive somewhere else on the
        device and made to write its contents into the transfer folder.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}
        if not name.lower().endswith((".zip", ".nsz")):
            # `.7z` and `.rar` are the ones people ask about next. Neither is in
            # the standard library and neither has a tool on a stock SteamOS, so
            # offering the button and failing at the end would be worse than
            # saying so.
            return {"ok": False,
                    "error": "Only .zip and .nsz files can be unpacked here."}

        destination = await self._run(fileserver.default_dir)
        if name.lower().endswith(".nsz"):
            # Minutes for a large game rather than a second or two, so the
            # panel gets a percentage. The work runs in the executor and an
            # event is sent from the loop, so each one is handed back to it.
            loop = asyncio.get_running_loop()

            def report(done, total):
                percent = int(done * 100 / total) if total else -1
                asyncio.run_coroutine_threadsafe(
                    decky.emit("nsz_unpack_progress", name, percent), loop)

            written, error = await self._run(
                switch_nsz.into_folder, path, destination, report)
        else:
            written, error = await self._run(unpack.into_folder, path, destination)
        if error:
            return {"ok": False, "error": error}

        # The zip has served its purpose, so it goes -- the same thing importing
        # a definition does to the definition, installing firmware does by
        # moving the file where the emulator reads it, and adding a ROM does by
        # filing it under its system. The transfer folder is a waypoint, and
        # everything that uses a file takes it out of there.
        #
        # This was briefly the exception, on the reasoning that an extraction
        # can go subtly wrong and the archive is the only way back. That is true
        # of importing a definition too, and it is not how this folder works:
        # what it produced was 47MB of duplicate sitting beside the game, and a
        # second unpack refused because the name was taken.
        #
        # Only after a clean extraction. `into_folder` is all-or-nothing, so
        # reaching here means every member is on disk under its real name.
        try:
            await self._run(os.remove, path)
        except OSError as error:
            # The contents are out, which is what was asked for. A zip that
            # could not be deleted is a tidiness problem with a delete button
            # next to it, not a failed unpack.
            decky.logger.warning("Unpacked %s but could not remove it: %s", name, error)

        return {"ok": True, "written": written,
                "received": await self._run(fileserver.received_files)}

    async def cancel_upload(self, upload_id: int = 0):
        """Abandon a transfer in progress. 0 means every one of them.

        What already arrived is kept, as it is for any other stop. Cancel
        stops the sender and refuses its automatic retry; choosing the same
        file again carries on from the kept bytes. It used to delete them, and
        that sent a transfer which only looked stuck back to zero.
        """
        cancelled = await self._run(fileserver.cancel, upload_id or None)
        status = await self._run(fileserver.status)
        return {"ok": True, "cancelled": cancelled, **status}
