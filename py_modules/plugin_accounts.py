"""The part of the Plugin class that signs in to somebody else's service.

Two of them, and they are the same shape: RetroAchievements, whose token turns
into the cheevos_* lines appended at launch, and SteamGridDB, whose key is what
makes artwork lookup work for anything libretro has no thumbnail for. Both ask
for a credential, validate it before storing it, and keep it in settings.

Together because the awkward parts are shared. Neither service can be reached
from Game Mode without the plugin fetching on the user's behalf, both fail in
ways that need saying precisely -- a wrong password and an unreachable host are
not the same problem -- and a key that is stored without being validated is a
feature that silently does nothing.

Mixed into `Plugin` rather than called by it -- see plugin_firmware for why.
"""

import decky

import plugin_base

import cheevos
import sgdb
import store


class Accounts(plugin_base.PluginContext):
    """Third-party sign-in endpoints. See the module docstring."""

    async def cheevos_status(self):
        """Who is signed in, and whether RetroArch already has a login to adopt.

        Reported together because the useful answer is often "you do not need to
        type anything": a token already in retroarch.cfg is as good as one of
        ours, and asking for a password to obtain a token the user already has
        would be busywork.
        """
        settings = await self._run(store.get_settings)
        existing = await self._run(cheevos.retroarch_credentials, self._install)
        username = (settings.get("cheevos_username") or "").strip()
        signed_in = bool(username and (settings.get("cheevos_token") or "").strip())
        return {
            "signed_in": signed_in,
            "username": username,
            "enabled": bool(settings.get("cheevos_enable")),
            "hardcore": bool(settings.get("cheevos_hardcore")),
            # Only worth offering when we have nothing and RetroArch has both.
            "can_adopt": bool(
                not signed_in and existing["username"] and existing["has_token"]
            ),
            "retroarch_username": existing["username"],
        }


    async def cheevos_login(self, username: str, password: str):
        """Exchange a password for a Connect token, then forget the password."""
        result = await self._run(cheevos.login, username, password)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "Sign-in failed.")}

        await self._run(
            store.set_settings,
            {
                "cheevos_username": result["username"],
                "cheevos_token": result["token"],
                # Signing in is only ever done in order to use it.
                "cheevos_enable": True,
            },
        )
        await self.rebuild_launchers()
        return {"ok": True, "username": result["username"]}


    async def cheevos_adopt(self):
        """Take the login RetroArch already has, so nothing needs typing."""
        result = await self._run(cheevos.adopt_retroarch_credentials, self._install)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "Nothing to adopt.")}

        await self._run(
            store.set_settings,
            {
                "cheevos_username": result["username"],
                "cheevos_token": result["token"],
                "cheevos_enable": True,
            },
        )
        await self.rebuild_launchers()
        return {"ok": True, "username": result["username"]}


    async def cheevos_sign_out(self):
        """Forget the token and stop enabling achievements at launch.

        RetroArch's own stored login is left alone: it was not ours to begin
        with, and someone signing out of this plugin has not asked to be signed
        out of RetroArch.
        """
        await self._run(
            store.set_settings,
            {"cheevos_username": "", "cheevos_token": "", "cheevos_enable": False},
        )
        await self.rebuild_launchers()
        return {"ok": True}


    async def find_existing_sgdb_key(self):
        """Whether another plugin already has a key we could import."""
        found = await self._run(sgdb.discover_existing_key)
        return {"found": bool(found["key"]), "source": found["source"]}


    async def import_existing_sgdb_key(self):
        """Validate and save a key discovered elsewhere on this system."""
        found = await self._run(sgdb.discover_existing_key)
        if not found["key"]:
            return {"ok": False, "error": "No existing SteamGridDB key was found."}
        return await self._save_validated_key(found["key"], "imported from %s" % found["source"])


    async def _save_validated_key(self, key: str, how: str):
        check = await self.validate_sgdb_key(key)
        if not check.get("ok"):
            return {
                "ok": False,
                "error": "That key was %s but SteamGridDB rejected it." % how,
            }
        await self._run(store.set_settings, {"sgdb_api_key": key})
        decky.logger.info("Saved SteamGridDB key (%s)", how)
        return {"ok": True, "how": how}


    async def validate_sgdb_key(self, api_key: str):
        key = (api_key or "").strip()
        if not key:
            return {"ok": False, "error": "No API key provided."}
        game_id = await self._run(sgdb.search_game, key, "Half-Life")
        if game_id:
            return {"ok": True}
        return {"ok": False, "error": "SteamGridDB rejected that key or is unreachable."}
