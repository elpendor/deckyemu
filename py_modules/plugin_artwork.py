"""The part of the Plugin class that picks a game's artwork and icon by hand.

The automatic match happens while adding a game (plugin_probe.py); this is the
picker for when it was wrong, and the icon lookup for games that have none.
"""

import appenv

import plugin_base

import gameicon
import libretro_meta
import net
import sgdb
import store


class Artwork(plugin_base.PluginContext):
    async def list_art_candidates(self, rom_path: str, core_id: str, query: str = ""):
        """Alternative artwork matches, for when the automatic one is wrong.

        `query` lets the user search by a name of their own choosing, which is
        the only way out when both sources mis-identify a ROM.
        """
        core = self._core_by_id(core_id)
        databases = core["databases"] if core else []
        # The ROM set's real name, not its short filename (`racer2`). The
        # search hint over the full title: a subtitle SteamGridDB lacks would
        # rank the right game lower.
        _set_title, _set_hint = await self._romset_names(rom_path)
        term = (query or "").strip() or _set_hint or _set_title or (
            libretro_meta.display_title(libretro_meta.rom_stem(rom_path))
        )

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()

        libretro_hits = await self._run(libretro_meta.index_candidates, databases, term)
        sgdb_hits = []
        if api_key:
            sgdb_hits = await self._run(sgdb.search_candidates, api_key, term, databases, "", 10)

        appenv.logger.info(
            "list_art_candidates(%r): %d libretro, %d steamgriddb",
            term,
            len(libretro_hits),
            len(sgdb_hits),
        )
        return {
            "query": term,
            "libretro": libretro_hits,
            "steamgriddb": sgdb_hits,
            "sgdb_available": bool(api_key),
        }

    async def apply_art_candidate(
        self, source: str, ref: str, system: str = "", picked_name: str = ""
    ):
        """Fetch artwork for a candidate the user picked by hand.

        Picking one says which game this is, so a `suggested_title` comes back;
        the caller decides whether to rename. `picked_name` is the pressed row's
        label, the fallback when the name lookup fails.
        """
        # Logged first, so a report shows what was actually picked.
        appenv.logger.info(
            "apply_art_candidate: source=%s ref=%r system=%r row=%r",
            source, ref, system, picked_name,
        )

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()

        if source == "steamgriddb":
            if not api_key:
                return {"ok": False, "error": "No SteamGridDB API key is set."}
            try:
                game_id = int(ref)
            except (TypeError, ValueError):
                return {"ok": False, "error": "Invalid SteamGridDB game id."}
            urls = await self._run(sgdb.art_urls, api_key, game_id)
            art = await self._download_art(urls)
            if not art:
                return {"ok": False, "error": "That game has no usable artwork on SteamGridDB."}
            # The database's spelling, else the row's.
            name = await self._run(sgdb.game_name, api_key, game_id)
            name = name or (picked_name or "").strip()[:120]
            appenv.logger.info(
                "apply_art_candidate -> %d image(s), named %r (database) / %r (row)",
                len(art), name, picked_name,
            )
            return {
                "ok": True,
                "art": art,
                "art_source": "steamgriddb",
                "art_game_name": name,
                "suggested_title": libretro_meta.display_title(name),
            }

        if source == "libretro":
            if not system:
                return {"ok": False, "error": "No system was supplied for that thumbnail."}
            url = libretro_meta.boxart_url(system, ref)
            art = await self._download_art({"capsule": url})
            if not art:
                return {"ok": False, "error": "That thumbnail could not be downloaded."}
            appenv.logger.info(
                "apply_art_candidate -> %d image(s), named %r (thumbnail)", len(art), ref,
            )
            return {
                "ok": True,
                "art": art,
                "art_source": "libretro",
                "art_game_name": ref,
                # Tidied like a filename: thumbnails carry tags like "(USA)".
                "suggested_title": libretro_meta.display_title(ref),
            }

        return {"ok": False, "error": "Unknown artwork source %r." % source}

    async def games_without_icon(self) -> list:
        """Tracked games wearing the shipped icon, or none at all.

        A found icon is saved under the game's app id, so a missing file says
        which games fell back.
        """
        library = await self._run(store.get_library)
        rows = []
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id or await self._run(gameicon.has_own, app_id):
                continue
            rows.append({"app_id": app_id, "title": entry.get("title", "")})
        return rows

    async def fetch_game_icon(self, app_id: int) -> dict:
        """Look one game up on SteamGridDB and give it the icon it finds.

        Three requests (search, icon, download), not `art_urls`' five, as this
        runs per game across a library. No icon is `found: False`, not an
        error, and `path` then falls back to the shipped picture.
        """
        library = await self._run(store.get_library)
        entry = library.get(str(app_id))
        if not entry:
            return {"ok": False, "error": "That game is no longer tracked."}

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()
        if not api_key:
            return {"ok": False, "error": "No SteamGridDB API key is set."}

        async def nothing_found():
            return {"ok": True, "found": False,
                    "path": await self._run(gameicon.for_game, app_id, "")}

        system = (entry.get("system") or "").strip()
        game_id = await self._run(
            sgdb.search_game, api_key, entry.get("title", ""),
            [system] if system else None, "")
        if not game_id:
            return await nothing_found()

        url = await self._run(sgdb.icon_url, api_key, game_id)
        if not url:
            return await nothing_found()

        # Raw bytes, as many are `.ico`; `gameicon.save` names the file by them.
        payload, _content_type = await self._run(net.get_bytes, url)
        if not payload:
            return await nothing_found()

        path = (await self._run(gameicon.save, app_id, payload)
                or await self._run(gameicon.for_game, app_id, ""))
        found = await self._run(gameicon.has_own, app_id)
        appenv.logger.info("fetch_game_icon: app_id=%s found=%s", app_id, found)
        return {"ok": True, "found": found, "path": path}

    async def game_icon(self, app_id: int, data: str = "") -> dict:
        """Where to point Steam for this game's icon.

        `data` is the artwork lookup's icon as a data URI, saved under the
        game's app id; without it, the shipped picture. Always a file that
        exists, or nothing.
        """
        return {"path": await self._run(gameicon.for_game, app_id, data)}
