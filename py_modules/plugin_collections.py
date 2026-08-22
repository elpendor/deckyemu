"""The part of the Plugin class that decides where a game is filed.

What a game's system is called, what shelf that makes, and the repair work when
the answer changes underneath a library that already exists. Steam collections
are the reason the plugin is usable at forty games rather than four: without one
every added game lands in the same undifferentiated pile of non-Steam shortcuts.

The naming is computed rather than remembered, and that is the load-bearing
decision here. A game records what it *is* -- its core, its system -- and the
label is derived from that every time, so switching between short and full names
re-labels games that were added years earlier. The cost is that changing the
format has to move games between shelves, which is what
`plan_collection_migration` and `collection_targets` are for.

**Split out of main.py against what §2 used to say**, and the measurement is
worth keeping because the rule it replaces sounded right. That entry protected
this block on the grounds that it and the shortcuts block were mutually
referential. They are not, and were not: shortcuts calls in here ten times and
nothing in here has ever called back. A one-way dependency across a surface of
six helpers is what plugin_base is for, and four of the six were already
declared in it before this file existed.

What did *not* come along: `_menu_combo`, `_launch_options` and `_clean_options`
were in the collections block and are not about collections -- they are how a
game runs. They went to the shortcuts block, next to their callers.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import re

from typing import Optional

import decky

import plugin_base

import emulators
import libretro_meta
import platforms
import store


class Collections(plugin_base.PluginContext):
    """Where a game is filed, and the repairs when that changes. See the docstring."""

    @staticmethod
    def _platform_label(core=None, system="", short=False):
        """A human system name for use in a collection title.

        `short` gives the name people actually use -- SNES rather than "Super
        Nintendo Entertainment System", which is 46 characters of shelf header.
        Otherwise the core's own `systemname` is preferred over the libretro
        database name, which reads badly once appended to a collection name.
        """
        database = system
        if not database and core and core.get("databases"):
            database = core["databases"][0]

        if short:
            label = platforms.short_name(database, (core or {}).get("system_name", ""))
            if label:
                return label

        if core:
            if core.get("system_name"):
                return core["system_name"]
            if core.get("databases"):
                return core["databases"][0].split(" - ")[-1]
        if system:
            return system.split(" - ")[-1]
        return ""

    @staticmethod
    def _system_for(core, resolved="", fallback=""):
        """Which of a core's databases a game actually belongs to.

        Only interesting when a core covers more than one system, which Dolphin
        does: it declares GameCube *and* Wii, and taking `databases[0]` filed
        every Wii game under GameCube. `libretro_meta.resolve` already works the
        real one out -- it probes each database's boxart directory and reports
        which one had the game -- and that answer was being thrown away here.

        `resolved` is only believed when the core actually claims it, so a stale
        value cannot survive a core change.
        """
        databases = (core or {}).get("databases") or []
        if not databases:
            return ""
        for candidate in (resolved, fallback):
            if candidate and candidate in databases:
                return candidate
        return databases[0]

    @classmethod
    def _entry_platform(cls, settings, core, entry=None):
        """The platform label for a game under the current naming style.

        Computed rather than read back from the entry, so switching between short
        and full names re-labels games that were already added.
        """
        entry = entry or {}
        short = settings.get("platform_names", "short") == "short"
        label = cls._platform_label(core, entry.get("system", ""), short)
        return label or entry.get("platform", "")

    @classmethod
    def _collection_name(cls, settings, platform):
        """The collection a game belongs in under the current settings.

        Empty means "nowhere", which is a real answer rather than a missing one:
        collections switched off, or a name cleared to nothing. The switch is
        read here rather than at each call site because it was read at four of
        them and missed at the fifth -- `plan_collection_migration` computed
        targets as though collections were on, so turning them off planned no
        moves and the setting appeared to do nothing.
        """
        if not settings.get("add_to_collection", True):
            return ""
        base = (settings.get("collection_name") or "").strip()
        if not base:
            return ""
        if not (settings.get("collection_per_platform") and platform):
            return base

        template = settings.get("collection_template") or store.DEFAULT_COLLECTION_TEMPLATE
        return cls._render_collection(template, base, platform)

    #: The naming formats offered in the UI.
    #:
    #: Here rather than in the frontend so that the thing which *renders* a
    #: collection name is also the thing that previews one. There were three
    #: renderers of this template across two languages -- the one below, the
    #: pattern that recognises a name, and a preview in the settings panel --
    #: and they did not agree: the preview substituted only the first occurrence
    #: of a placeholder, and neither of the other two applied the trailing
    #: separator strip. They agreed on the seven formats offered and would have
    #: parted company on the first one added.
    COLLECTION_TEMPLATES = (
        "[{name}] {platform}",
        "{platform}",
        "{name}: {platform}",
        "{name} · {platform}",
        "{name} - {platform}",
        "{platform} ({name})",
        "{name}\\n{platform}",
    )

    @staticmethod
    def _render_collection(template, base, platform):
        """One template, one name. The only thing that turns one into the other."""
        # Stored as an escape so the template survives a round trip through JSON
        # and the settings UI as one line.
        name = template.replace("\\n", "\n")
        name = name.replace("{name}", base).replace("{platform}", platform)
        # Collapse runs of spaces and tabs, but keep any newline the user asked
        # for; trailing separators are left over when a placeholder is unused.
        name = re.sub(r"[ \t]+", " ", name)
        return name.strip(" \t-:·|/,")

    async def collection_templates(self):
        """Every offered naming format, with the name it would actually produce.

        The preview is rendered here, by the same function that names a real
        collection, so the dropdown cannot promise a format the filing does not
        use. `{platform}` is filled with a stand-in system for the sake of the
        example; everything else is the user's own settings.
        """
        settings = await self._run(store.get_settings)
        base = (settings.get("collection_name") or "").strip() or "Collection"
        return {
            "templates": [
                {
                    "template": template,
                    "preview": self._render_collection(template, base, "Nintendo 64"),
                }
                for template in self.COLLECTION_TEMPLATES
            ]
        }

    # Per-game launch overrides. Only explicit overrides are stored, so a game
    # left alone keeps following the global setting when that setting changes.
    _OSD_MODES = ("keep", "startup", "all")

    async def collection_name_for(self, core_id: str):
        """What collection a game on `core_id` should go into right now.

        Empty when collections are off; `_collection_name` owns that rule.
        """
        settings = await self._run(store.get_settings)
        core = self._core_by_id(core_id)
        return self._collection_name(settings, self._entry_platform(settings, core))

    async def plan_collection_migration(self, previous: Optional[dict] = None):
        """Moves needed to bring existing games in line with current settings.

        Renaming the collection or toggling per-platform naming has to move games
        that were already added, otherwise the setting appears to do nothing
        until the next ROM is added.

        `previous` carries the settings as they were before the change. It matters
        for games added by an older version of this plugin, which did not record
        which collection they went into: without it their old collection is
        unknown, so they would be added to the new one and never removed from the
        old -- leaving the old collection sitting there, still populated.
        """
        settings = await self._run(store.get_settings)
        library = await self._run(store.get_library)

        moves = []
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id:
                continue
            core = self._core_by_id(entry.get("core_id", ""))
            platform = self._entry_platform(settings, core, entry)
            target = self._collection_name(settings, platform)

            current = entry.get("collection", "")
            if not current and previous:
                # Derive the old name entirely from the old settings -- the
                # platform style may have changed too, so reusing the label
                # computed above would name a collection that never existed.
                current = self._collection_name(
                    previous, self._entry_platform(previous, core, entry)
                )

            # An empty `to` means "take it out and put it nowhere" -- collections
            # switched off, or the name cleared. This used to require a target,
            # so the one setting that removes games from collections planned
            # nothing at all and looked inert on an existing library. The
            # frontend removes, then deletes the collection only if it is left
            # empty, since one of ours can hold games dragged in by hand.
            if target != current:
                moves.append(
                    {
                        "app_id": app_id,
                        "title": entry.get("title", ""),
                        "from": current,
                        "to": target,
                    }
                )

        decky.logger.info(
            "plan_collection_migration: %d move(s)%s",
            len(moves),
            "" if not previous else " (using previous settings for unrecorded games)",
        )
        return {"moves": moves}

    async def collection_shape(self):
        """What a collection name made by this plugin looks like.

        For finding the ones it left behind empty. Every other way of knowing
        which collections are ours goes through a registered game -- and an
        empty collection is precisely one with no game left to ask.

        The pattern rather than a list of names: the platform half can be any
        system label the plugin has ever produced, including for a core since
        uninstalled, and enumerating those is guesswork where the template is
        exactly what was used to build the name in the first place.
        """
        settings = await self._run(store.get_settings)
        base = (settings.get("collection_name") or "").strip()
        per_platform = bool(settings.get("collection_per_platform"))
        template = settings.get("collection_template") or store.DEFAULT_COLLECTION_TEMPLATE
        return {
            "base": base,
            "per_platform": per_platform,
            "template": template.replace("\\n", "\n"),
            # What was actually done, as opposed to what the current settings
            # would do. The pattern above can only recognise shelves this naming
            # would produce today, so every one made under a naming since
            # changed fell out of it -- and an empty shelf is reached long after
            # the settings that made it moved on. These are the answer; the
            # pattern stays as the answer for anything filed before this record
            # existed.
            "known": await self._run(store.known_collections),
        }

    async def forget_collections(self, names: list):
        """Stop claiming collections that no longer exist.

        Called after they are deleted. Without it the record only grows, and a
        name this plugin once used would go on being claimed if the user later
        made a collection of their own by that name -- which is the one way
        recording ownership could be worse than deriving it.
        """
        dropped = await self._run(store.forget_collections, names or [])
        if dropped:
            decky.logger.info("No longer claiming collection(s): %s", ", ".join(dropped))
        return {"ok": True, "forgotten": dropped}

    async def collection_targets(self):
        """{app_id: collection} for every registered game, under current settings.

        Used to find games missing from the collection they belong to, and games
        sitting in one they do not.

        Nothing at all when collections are switched off, which is part of "under
        current settings" and not a special case: a game belongs nowhere then, so
        neither of those questions has an answer. It went unnoticed while the
        only callers were buttons on a panel that hides itself when the switch is
        off -- the library check has no such gate and would have reported every
        game as missing from a collection nobody asked for.
        """
        settings = await self._run(store.get_settings)
        if not settings.get("add_to_collection"):
            return {"targets": {}, "titles": {}}

        library = await self._run(store.get_library)

        targets = {}
        titles = {}
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id:
                continue
            core = self._core_by_id(entry.get("core_id", ""))
            platform = self._entry_platform(settings, core, entry)
            targets[str(app_id)] = self._collection_name(settings, platform)
            titles[str(app_id)] = entry.get("title", "")
        return {"targets": targets, "titles": titles}

    async def record_collections(self, assignments: dict):
        """Persist which collection each game now lives in."""
        library = await self._run(store.get_library)
        updated = {}
        for app_id, name in (assignments or {}).items():
            entry = library.get(str(app_id))
            if not entry:
                continue
            entry["collection"] = name
            updated[app_id] = entry
        await self._run(store.remember_games, updated)
        return {"ok": True, "recorded": len(assignments or {})}
