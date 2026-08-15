"""What every part of the Plugin class may assume about the rest of it.

`Plugin` is assembled from mixins -- see main.py -- and each one calls helpers
that live on the composed object rather than in its own file. That works,
because Python resolves the attribute at call time on the instance, and it left
each mixin silently depending on twelve members that nothing declared. Reading
plugin_audit.py told you it used `self._run`; nothing told you what `_run` was,
which class owned it, or that adding a thirteenth such call is a decision.

So the shared surface is written down once, here, and every mixin says it needs
it. Three things follow:

* A type checker stops reporting eighty-one attribute errors that were never
  wrong, and starts reporting the one that is -- a helper renamed on `Plugin`
  now fails at the mixins that use it, in the editor, rather than on the Deck.
* The dependency is visible. A mixin reaching for something new has to add it
  here, which is a small deliberate act rather than an invisible one.
* Nothing changes at runtime. These are declarations; the bodies live on
  `Plugin`, which supplies every one of them.

Deliberately not an ABC and deliberately not instantiable: it declares, it does
not implement. `Plugin` inherits the mixins, the mixins inherit this, and the
real methods further along the MRO satisfy it.
"""

import asyncio
from typing import Any, Awaitable, Callable, Optional


class PluginContext:
    """The members a mixin may use from the composed Plugin. See the module docstring."""

    # --- state the plugin holds ------------------------------------------
    #: The event loop the plugin runs on; used to schedule background work.
    loop: asyncio.AbstractEventLoop
    #: The detected RetroArch install, or None when there is not one. Re-read by
    #: `refresh_retroarch`, so never cache it across an await.
    _install: Optional[dict]

    # --- running things --------------------------------------------------
    def _run(self, function: Callable[..., Any], *args: Any) -> Awaitable[Any]:
        """Run a blocking call in the executor. Every filesystem touch goes through this."""
        raise NotImplementedError

    def _detach(self, coro: Any, event: str, *args: Any) -> "asyncio.Task[None]":
        """Start background work whose end the UI is waiting on `event` to hear."""
        raise NotImplementedError

    def _run_emulator_tool(
        self, emulator: dict, args: list, allow: Any = (), seconds: int = 0,
        on_line: Any = None, display: bool = False,
    ) -> Awaitable[Any]:
        """Run an emulator as a command-line tool, with no window."""
        raise NotImplementedError

    def _refresh_emulators(self) -> Awaitable[list]:
        """Re-read the registered emulators and return them."""
        raise NotImplementedError

    # --- resolving what a game is ----------------------------------------
    def _core_by_id(self, core_id: str) -> Optional[dict]:
        """The core or emulator entry behind a core id, or None."""
        raise NotImplementedError

    def _emulator_for_core_id(self, core_id: str) -> Optional[dict]:
        """The standalone emulator behind a core id, or None for a libretro core."""
        raise NotImplementedError

    def _entry_platform(self, settings: dict, core: Optional[dict], entry: Any = None) -> str:
        """The platform label for a game, which decides its collection."""
        raise NotImplementedError

    @classmethod
    def _collection_name(cls, settings: dict, platform: str) -> str:
        """The collection a game belongs in under the current settings."""
        raise NotImplementedError

    @classmethod
    def _entry_for(
        cls, settings: dict, app_id: int, title: str, rom_path: str, core_id: str,
        core: Optional[dict], launcher_path: str, system: str = "",
        previous: Optional[dict] = None,
    ) -> dict:
        """The registry record for one game. Pass `previous` to keep its fields."""
        raise NotImplementedError

    @classmethod
    def _launch_options(cls, settings: dict, entry: dict) -> dict:
        """How one game launches: its own overrides resolved over the globals."""
        raise NotImplementedError

    @staticmethod
    def _menu_combo(settings: dict) -> str:
        """The controller combo that opens RetroArch's menu."""
        raise NotImplementedError

    # --- endpoints one part calls on another ------------------------------
    def prepare_shortcut(
        self, title: str, core_id: str, rom_path: str, system: str = "",
        title_id: str = "",
    ) -> Awaitable[dict]:
        """Write a launcher and return the fields Steam needs."""
        raise NotImplementedError

    def rebuild_launchers(self) -> Awaitable[dict]:
        """Rewrite every launcher script from the current settings."""
        raise NotImplementedError
