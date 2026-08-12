#!/usr/bin/env python3
"""Report how old the frontend bundle currently loaded in Steam is.

Decky reloads the *backend* whenever its files change, and the plugin log shows
that happening -- so a deploy looks successful while the Steam client keeps
running an older `dist/index.js`. Every frontend change then appears to have no
effect, which is indistinguishable from a bug in the change itself.

This asks the Steam client what it actually fetched:

    python scripts/loaded_frontend.py 192.168.1.42

An IP is required rather than steamdeck.local because aiohttp's resolver does not
do mDNS; ssh does, so `ssh deck@steamdeck.local "ip route get 1.1.1.1"` will tell
you the address.

If the age reported here is older than your last deploy, the code on the device is
not what is running. Restart Steam to re-fetch it.
"""

import asyncio
import json
import sys

try:
    import aiohttp
except ImportError:  # pragma: no cover - developer machine only
    sys.exit("pip install aiohttp")

CEF_PORT = 8081

# The plugin's registered name, which is what appears in the bundle's URL.
PLUGIN = "deckyemu"

_AGES = """JSON.stringify(performance.getEntriesByType('resource')
    .filter(e => /%s/i.test(e.name))
    .map(e => ({
      stamp: (e.name.split('?t=')[1] || '').slice(0, 13),
      secondsAgo: Math.round((performance.now() - e.startTime) / 1000),
    })))""" % PLUGIN


async def main(ip):
    connector = aiohttp.TCPConnector(resolver=aiohttp.resolver.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get("http://%s:%d/json/list" % (ip, CEF_PORT)) as response:
            targets = await response.json()

        # Plugins run in SharedJSContext, not in the Big Picture window.
        target = next((t for t in targets if t.get("title") == "SharedJSContext"), None)
        if not target:
            sys.exit("SharedJSContext not found. Is frontend debugging enabled?")

        url = target["webSocketDebuggerUrl"].replace("steamloopback.host", ip)
        async with session.ws_connect(url) as ws:
            await ws.send_json({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": _AGES, "returnByValue": True},
            })
            while True:
                message = json.loads((await ws.receive()).data)
                if message.get("id") != 1:
                    continue
                value = message.get("result", {}).get("result", {}).get("value")
                fetches = json.loads(value) if value else []
                break

    if not fetches:
        print("The Steam client has not fetched %s's bundle at all." % PLUGIN)
        return

    newest = min(fetches, key=lambda entry: entry["secondsAgo"])
    minutes = newest["secondsAgo"] / 60
    print("%d fetch(es); newest was %.1f minutes ago" % (len(fetches), minutes))
    if minutes > 5:
        print("That is old. If you have deployed since, Steam is running stale code:")
        print("  restart Steam (Steam menu > Restart Steam) to re-fetch it.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
