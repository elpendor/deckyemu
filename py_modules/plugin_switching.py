"""Switching between the service and plugin builds while both are installed.

The build in use is named in a file (builds.py), and each running build
watches it. The one that is no longer named stops and releases the lock; the
one now named takes it once it is free. Either side can start a switch; what
each build does beyond that (starting or stopping the service's unit,
installing the other) is its buildhost.py.
"""

import asyncio

import appenv
import builds
import claim

import plugin_base

#: How often a running build looks at which build is in use.
IN_USE_POLL_SECONDS = 3

#: How long taking over waits for the other build to let go.
TAKE_OVER_SECONDS = 45


class Switching(plugin_base.PluginContext):
    def _watch_in_use(self):
        """Started once per process; it outlives stepping aside."""
        if getattr(self, "_in_use_task", None) is None:
            self._in_use_task = self.loop.create_task(self._in_use_watch())

    async def _stop_watching_in_use(self):
        task = getattr(self, "_in_use_task", None)
        if task is not None and not getattr(self, "_stepping_aside", False):
            task.cancel()
            await asyncio.wait({task}, timeout=2)
            self._in_use_task = None

    async def _in_use_watch(self):
        while True:
            await asyncio.sleep(IN_USE_POLL_SECONDS)
            try:
                await self._check_in_use()
            except Exception:  # noqa: BLE001 - the next look may do better
                appenv.logger.exception("Could not check which build is in use")

    async def _check_in_use(self):
        if getattr(self, "_switching", False) or getattr(self, "_retrying", False):
            return
        using = await self._run(builds.in_use)
        blocked = getattr(self, "_blocked", None)
        if not blocked:
            if using == builds.other_kind():
                await self._step_aside(using)
            return
        if blocked.get("reason") not in ("switched", "running"):
            return
        if using not in (None, appenv.KIND) or await self._run(claim.held):
            return
        self._retrying = True
        try:
            await self._main()
        finally:
            self._retrying = False

    async def _step_aside(self, kind):
        """Stop, release the lock, and stay off: the `kind` build is in use."""
        appenv.logger.info("The %s build is in use now; this one stops", kind)
        self._stepping_aside = True
        try:
            await self._unload()
        finally:
            self._stepping_aside = False
        self._blocked = builds.switched_to(kind)
        await self._host_stepped_aside()

    async def switch_offer(self):
        """The other build the panel offers, if there is one to switch to."""
        return await self._host_switch_offer()

    async def switch_build(self):
        """Switch to the other build, installing it first if this build can."""
        self._switching = True
        try:
            return await self._host_switch()
        finally:
            self._switching = False

    async def take_over(self):
        """Use this build instead of the one in use, from this one's panel."""
        self._switching = True
        try:
            await self._run(builds.use, appenv.KIND)
            appenv.logger.info("Taking over from the other build")
            for _ in range(TAKE_OVER_SECONDS):
                if not await self._run(claim.held):
                    break
                await asyncio.sleep(1)
            await self._main()
        finally:
            self._switching = False
        if self._blocked:
            return {"ok": False, "blocked": self._blocked}
        return {"ok": True}
