"""RetroAchievements: signing in, and the config RetroArch needs to use it.

RetroArch has achievement support built in. It needs three things: the feature
turned on, an account username, and a *Connect token* -- not a password. The
token comes from one login and is reused forever after, which is why this stores
only the token and forgets the password immediately.

Two credentials exist on retroachievements.org and they are not interchangeable:

* the **Web API key** shown on the site's settings page reads public data and
  cannot unlock anything;
* the **Connect token**, returned by `dorequest.php?r=login2`, is what emulators
  use to unlock achievements.

There is no OAuth or device-code flow -- the API documentation says OAuth2 is
"not production-ready yet" -- so one username-and-password login is unavoidable.
The browser cannot do it either: the endpoint sends no CORS headers, so a page
served to a phone could not read the token back.

The token is password-equivalent for achievement purposes. It is stored the way
the SteamGridDB key is (settings.json, never sent to the frontend) and written
only into the plugin's own override file, which is created 0600.
"""

import os
import re

import decky

import net
import ra_detect

LOGIN_URL = "https://retroachievements.org/dorequest.php"

# The API documentation is explicit that dorequest.php must never be called
# without a User-Agent, and asks integrations to identify themselves.
USER_AGENT = "DeckyEmu/%s" % (getattr(decky, "DECKY_PLUGIN_VERSION", "") or "0")

# Their rate limit is advertised as 10 requests per window (x-ratelimit-limit),
# which is generous for a one-off login and unforgiving of a retry storm. One
# attempt, and the error is reported rather than retried.
LOGIN_TIMEOUT = 20

# RetroArch's own key names, so what is written here matches what its menu would.
KEY_ENABLE = "cheevos_enable"
KEY_HARDCORE = "cheevos_hardcore_mode_enable"
KEY_USERNAME = "cheevos_username"
KEY_TOKEN = "cheevos_token"


def _valid_username(username):
    """RetroAchievements usernames are alphanumeric, so anything else is a typo.

    Also a guard: this value is written into a config file as `key = "value"`,
    and a quote in it would end the string early.
    """
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,32}", (username or "").strip()))


def login(username, password):
    """Exchange a username and password for a Connect token.

    Returns {"ok": True, "username", "token"} or {"ok": False, "error"}.

    The password is used here and nowhere else: it is not stored, not logged, and
    not returned. Posted as a form body rather than put in the query string,
    which would otherwise reach proxy logs and shell history.
    """
    username = (username or "").strip()
    if not _valid_username(username):
        return {"ok": False, "error": "That does not look like a RetroAchievements username."}
    if not (password or ""):
        return {"ok": False, "error": "Enter your RetroAchievements password."}

    payload = net.post_json(
        LOGIN_URL,
        {"r": "login2", "u": username, "p": password},
        headers={"User-Agent": USER_AGENT},
        timeout=LOGIN_TIMEOUT,
    )

    if payload is None:
        return {"ok": False, "error": "Could not reach retroachievements.org."}

    if not payload.get("Success"):
        # Their message is written for players ("Invalid user/password
        # combination"), so it is better than anything invented here.
        return {
            "ok": False,
            "error": payload.get("Error") or "RetroAchievements rejected the sign-in.",
        }

    token = (payload.get("Token") or "").strip()
    if not token:
        return {"ok": False, "error": "RetroAchievements returned no token."}

    # Their casing is authoritative: it is what appears in achievement feeds.
    return {"ok": True, "username": payload.get("User") or username, "token": token}


def retroarch_credentials(install):
    """Any login RetroArch already has, so signing in again is unnecessary.

    Anyone who has used achievements in RetroArch, or had another tool set them
    up, already has a token sitting in retroarch.cfg, and asking them for a
    password to obtain a token they already possess would be busywork.

    Returns {"username": str, "has_token": bool}. The token itself is only read
    when it is about to be adopted.
    """
    empty = {"username": "", "has_token": False}
    if not install:
        return empty
    config = os.path.join(install.get("config_dir", ""), "retroarch.cfg")
    if not os.path.isfile(config):
        return empty
    values = ra_detect.parse_cfg(config)
    return {
        "username": (values.get(KEY_USERNAME) or "").strip(),
        "has_token": bool((values.get(KEY_TOKEN) or "").strip()),
    }


def adopt_retroarch_credentials(install):
    """Read RetroArch's stored login so it can be copied into our settings."""
    found = retroarch_credentials(install)
    if not found["username"] or not found["has_token"]:
        return {"ok": False, "error": "RetroArch has no achievements login stored."}

    config = os.path.join(install.get("config_dir", ""), "retroarch.cfg")
    values = ra_detect.parse_cfg(config)
    token = (values.get(KEY_TOKEN) or "").strip()
    if not token:
        return {"ok": False, "error": "RetroArch has no achievements login stored."}
    return {"ok": True, "username": found["username"], "token": token}


def config_lines(settings):
    """The cheevos settings to append at launch, as (key, value) pairs.

    Nothing at all unless achievements are switched on *and* a login exists.
    Writing `cheevos_enable = "false"` when the feature is off would override the
    user's own choice for games launched from here, and this plugin's rule for
    RetroArch settings is to say nothing rather than to impose a default.

    Hardcore is always stated when enabling, never left to RetroArch's default:
    its default is *on*, and it disables save states, rewind, slowdown and
    cheats. Someone switching achievements on from here has not asked to lose
    save states, so the absence of an opinion would be the wrong answer.
    """
    if not settings.get("cheevos_enable"):
        return []
    username = (settings.get("cheevos_username") or "").strip()
    token = (settings.get("cheevos_token") or "").strip()
    if not username or not token:
        return []

    return [
        (KEY_ENABLE, "true"),
        (KEY_HARDCORE, "true" if settings.get("cheevos_hardcore") else "false"),
        (KEY_USERNAME, username),
        (KEY_TOKEN, token),
    ]
