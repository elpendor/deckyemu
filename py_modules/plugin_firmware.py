"""The part of the Plugin class that puts an emulator's own files in place.

BIOS files, keys and firmware images: what each emulator still needs, what is
waiting in the transfer folder, and moving one into the place that emulator
reads it from. Some are copied, some are unpacked by the emulator itself, and
one is opened in the emulator's own window because it will not do it any other
way -- see emu_firmware for which is which and why.

`_run_emulator_tool` lives here because firmware is what it mostly runs, but it
belongs to the composed class: installing a PS3 package uses it too.

Mixed into `Plugin` rather than called by it. decky exposes the methods it finds
on the plugin object, so an endpoint's name has to stay there; inheritance keeps
the name where decky looks while the code lives somewhere findable.
"""

import asyncio
import os
import re

import decky

import plugin_base

import emu_config
import emu_firmware
import emu_install
import emulator_catalog
import emulators
import launchers
import store
import sysenv


class Firmware(plugin_base.PluginContext):
    """Firmware endpoints. See the module docstring."""

    async def firmware_dir(self):
        """Where the user's own BIOS files, keys and firmware are collected."""
        return {"path": await self._run(emu_install.firmware_dir)}


    async def firmware_status(self):
        """What each installed emulator still needs, and what is waiting for it.

        Only emulators that are actually present are reported: listing firmware
        for something not installed is noise, and the destination directory
        would not exist to check against anyway.
        """

        def _collect(present_ids):
            files = emu_firmware.available()
            present_entries = [
                entry
                for entry in emulator_catalog.CATALOG
                if entry["id"] in present_ids and entry.get("firmware")
            ]
            emulators_report = [
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "requirements": emu_firmware.status(entry, files),
                }
                for entry in present_entries
            ]
            return {
                "path": emu_install.firmware_dir(),
                "emulators": emulators_report,
            }

        present = set()
        for entry in emulator_catalog.CATALOG:
            if entry["source"]["kind"] == "flatpak":
                if await self._run(emu_install.flatpak_installed, entry["source"]["id"]):
                    present.add(entry["id"])
            elif await self._run(emu_install.installed_appimage, entry["id"]):
                present.add(entry["id"])

        return await self._run(_collect, present)


    async def missing_firmware(self, core_id: str):
        """What the emulator behind this core still needs before a game boots.

        Asked while a game is being added, which is the last moment anything
        can be said: after this the user has a shortcut, and pressing it gives
        a black screen or a menu, with nothing anywhere connecting that to a
        BIOS never sent. The PS3 licence check and the Xbox disc check both
        exist for exactly this reason and both cover one console; this is the
        same question asked of every emulator that has requirements at all.

        Reported, never enforced -- same as the licence. A missing BIOS is
        usually fatal and occasionally not, and the plugin is in no position to
        be certain which.

        Silent for libretro cores: RetroArch has its own system directory and
        its own rules about what is needed, and guessing at them here would
        produce a warning nobody could act on.
        """
        if not emulators.is_emulator_id(core_id):
            return {"ok": True, "missing": []}

        emulator = await self._run(emulators.find, emulators.emulator_id(core_id))
        if not emulator:
            return {"ok": True, "missing": []}

        entry = emulator_catalog.find(emulator.get("id", ""))
        if not entry or not entry.get("firmware"):
            return {"ok": True, "missing": []}

        def _unmet():
            files = emu_firmware.available()
            return [
                {"name": item["name"], "waiting": bool(item["waiting"])}
                for item in emu_firmware.status(entry, files)
                # `detectable` is the important one and was learned the hard
                # way: Ryujinx's firmware had nowhere named to look, so it read
                # as absent forever and this warned about it under a Switch
                # game that had just launched perfectly. Not knowing is not the
                # same as missing, and only one of the two is worth saying.
                if item["detectable"] and not item["installed"] and not item["optional"]
            ]

        return {
            "ok": True,
            "emulator": entry["name"],
            "missing": await self._run(_unmet),
        }


    async def delete_firmware(self, names: list):
        """Delete files from the firmware folder, once they are not needed."""
        return await self._run(emu_firmware.remove, names)


    async def install_firmware(self, entry_id: str, requirement: str):
        """Put one requirement where the emulator wants it.

        Usually a copy. For a requirement the emulator has to unpack itself, it
        is the emulator that does the work -- see `_import_firmware` -- and this
        only chooses between the two.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog."}

        spec = emu_firmware.find_requirement(entry, requirement)
        if spec and spec.get("import"):
            return await self._import_firmware(entry, spec)

        return await self._run(emu_firmware.install, entry, requirement)


    async def _import_firmware(self, entry, requirement):
        """Hand a firmware file to the emulator and let it unpack it itself.

        RPCS3's PUP is the case. There is no copy that would work -- the PUP is
        an archive RPCS3 turns into several thousand files under `dev_flash` --
        and until this existed the row could only say "open RPCS3 and use File >
        Install Firmware", which is a Desktop Mode instruction wearing a Game
        Mode hat. `--headless --installfw` does the whole thing in six seconds
        with no window.

        Success is confirmed by looking at what the emulator produced, not by
        trusting its exit code, because the file is deleted afterwards.
        """
        spec = requirement["import"]
        emulator = await self._run(emulators.find, emulators.emulator_id(entry["id"]))
        if not emulator:
            return {
                "ok": False,
                "error": "%s is not set up yet. Install or register it first." % entry["name"],
            }

        waiting = await self._run(emu_firmware.matching, requirement)
        if not waiting:
            return {
                "ok": False,
                "error": "Nothing in the firmware folder looks like %s yet."
                % requirement.get("name", ""),
            }

        source_dir = await self._run(emu_install.firmware_dir)
        name = waiting[0]
        path = os.path.join(source_dir, name)

        args = [token.replace("{file}", path) for token in spec.get("args") or []]
        ok, error = await self._run_emulator_tool(
            emulator,
            args,
            allow=[source_dir],
            seconds=spec.get("seconds", 600),
            display=spec.get("needs_display", False),
        )

        installed = await self._run(emu_firmware.imported, spec)
        if not installed:
            return {
                "ok": False,
                "error": error or "%s ran but did not install anything." % entry["name"],
            }

        # Only now, and only because the emulator's own output says it worked:
        # the PUP is a couple of hundred megabytes, RPCS3 will never read it
        # again, and leaving it means the row offers to install what is already
        # installed. A failed run keeps the file, so the button still works.
        removed = await self._run(emu_firmware.remove, [name], source_dir)

        # The emulator has just run, so a config it had never written now
        # exists -- and settings that could not be applied before this can be
        # applied now. Vita3K is the case: its config is a whole document that
        # must not be invented, so the setup block is refused until the
        # emulator itself has produced one, and the first firmware install is
        # the first time that happens.
        if await self._run(emu_config.needs_setup, entry):
            result = await self._run(emu_config.apply_setup, entry)
            decky.logger.info(
                "Re-applied %s settings after import: %s",
                entry["id"], result.get("error") or "ok",
            )

        decky.logger.info(
            "Imported %s into %s: %s (exit ok=%s)", name, entry["id"], installed, ok
        )
        return {
            "ok": True,
            "copied": [name],
            "kept": [],
            "installed": installed,
            "deleted": removed.get("removed", []),
            "dest": emu_firmware.under_home(spec.get("installed") or ""),
        }


    async def _run_emulator_tool(
        self, emulator, args, allow=(), seconds=600, on_line=None, display=False
    ):
        """Run an emulator headlessly as a command-line tool. Returns (ok, error).

        Output is read rather than discarded so a failure has something to say:
        these runs show nothing on screen by design, so their log lines are the
        only account of what happened.
        """
        argv = emulators.tool_argv(emulator, args, allow)
        decky.logger.info("Running: %s", " ".join(argv))

        env = self._subprocess_env()
        if display:
            # Some emulators will not start without a display even to do
            # something that draws nothing: Vita3K's Qt aborts with "could not
            # connect to display" before it looks at its arguments. Opt-in
            # rather than always, because handing a display to a run that asked
            # to be headless invites it to open a window.
            session = await self._run(sysenv.session_env)
            if not session:
                return False, (
                    "%s needs the Game Mode session to run, and it could not be "
                    "found. Try again from Game Mode." % emulator.get("name", "This")
                )
            env.update(session)

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except (OSError, NotImplementedError) as error:
            decky.logger.exception("Could not start %s", argv[0])
            return False, "Could not run %s: %s" % (emulator.get("name", "emulator"), error)

        tail = []

        async def _read():
            buffer = ""
            while True:
                chunk = await process.stdout.read(256)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                segments = re.split(r"[\r\n]+", buffer)
                buffer = segments.pop()
                for segment in segments:
                    text = segment.strip()
                    if not text:
                        continue
                    decky.logger.info("%s: %s", emulator.get("id", "emu"), text)
                    tail.append(text)
                    del tail[:-5]
                    if on_line:
                        await on_line(text)
            return await process.wait()

        try:
            code = await asyncio.wait_for(_read(), seconds)
        except asyncio.TimeoutError:
            # An emulator that is waiting on something invisible will wait
            # forever, and a button with no end is worse than a failure.
            try:
                process.kill()
            except OSError:
                pass
            return False, "%s did not finish within %d seconds." % (
                emulator.get("name", "The emulator"),
                seconds,
            )

        if code != 0:
            reason = " ".join(tail).strip() or "no output"
            return False, "%s exited with code %d: %s" % (
                emulator.get("name", "The emulator"), code, reason
            )
        return True, ""


    async def fetch_firmware(self, entry_id: str, requirement: str):
        """Download a prerequisite that is not the user's own dump.

        Only xemu's blank disk image qualifies today, and the rule that keeps it
        narrow is in `emu_firmware.fetch`: a requirement without a `fetch` block
        is refused here rather than quietly downloaded from somewhere.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog."}
        return await self._run(emu_firmware.fetch, entry, requirement)


    async def uninstall_firmware(self, entry_id: str, requirement: str):
        """Take a requirement's files back out, so it can be installed again."""
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog."}
        return await self._run(emu_firmware.uninstall, entry, requirement)


    async def prepare_firmware_gui(self, entry_id: str, requirement: str):
        """Open an emulator's window already pointed at the file to install.

        For the one requirement that has no unattended route and never will.
        Ryujinx takes `--install-firmware <path>`, but reads it inside its main
        window's template callback and then waits on a Yes/No dialog -- so the
        window is not optional, and neither is the press. There is no headless
        build to fall back to either; that project is gone from the fork.

        What this removes is the file browser. Instead of opening Ryujinx,
        finding Tools > Install Firmware and steering a picker to the transfer
        folder with a thumbstick, the file is already chosen and the only thing
        left is Yes.

        The same script and the same shortcut as the plain "open the emulator"
        button: the script is rewritten on every press, so the argument is
        present for this run and gone by the next. Nothing appears in the
        library that was not there already.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "Unknown emulator %r." % entry_id}

        spec = await self._run(emu_firmware.find_requirement, entry, requirement)
        gui = (spec or {}).get("gui_install")
        if not gui:
            return {
                "ok": False,
                "error": "%s does not install %s this way." % (entry["name"], requirement),
            }

        emulator = await self._run(emulators.find, emulators.emulator_id(entry_id))
        if not emulator:
            return {"ok": False, "error": "%s is not set up yet." % entry["name"]}

        def _waiting():
            files = emu_firmware.available()
            for item in emu_firmware.status(entry, files):
                if item["name"] == requirement:
                    return item["waiting"]
            return []

        waiting = await self._run(_waiting)
        if not waiting:
            return {
                "ok": False,
                "error": "No firmware file has been sent yet. Send one and try again.",
            }

        folder = await self._run(emu_install.firmware_dir)
        target = os.path.join(folder, waiting[0])
        args = [
            arg.replace("{file}", target) for arg in gui.get("args") or []
        ]

        try:
            script = await self._run(
                launchers.write_gui_launcher,
                emulator,
                entry["name"],
                args,
                # Without this the sandbox cannot read the file it was handed,
                # and Ryujinx calls it invalid rather than unreadable -- which
                # reads as a bad download and sends people to re-dump firmware.
                [folder],
                "# Opens %s to install %s." % (entry["name"], waiting[0]),
            )
        except OSError as error:
            decky.logger.exception("Failed writing firmware GUI launcher")
            return {"ok": False, "error": "Could not write launcher script: %s" % error}

        settings = await self._run(store.get_settings)
        decky.logger.info("Opening %s to install %s", entry["name"], waiting[0])
        return {
            "ok": True,
            # The same one shortcut the Emulators tab uses, repointed. Two doors
            # into the same emulator did not need two library entries.
            "title": launchers.SETUP_SHORTCUT_TITLE,
            "exe": script,
            "start_dir": os.path.dirname(script),
            "app_id": int(settings.get("setup_app_id") or 0),
            "file": waiting[0],
        }
