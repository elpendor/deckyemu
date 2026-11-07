"""The plugin build's backend: its own host, its update relay, and the switch.

    python scripts/tests/test_plugin_build.py

Runs against the plugin's modules (plugin/py_modules) shadowing the shared
ones, as its package lays them out.
"""

import asyncio
import hashlib
import io
import os
import sys
import tarfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ != "__main__":
    # Run by test_backend.py, whose process has the service's modules loaded
    # already: this one has to start without them, so it gets a process of
    # its own.
    import subprocess

    from harness import check  # noqa: E402

    _own = subprocess.run([sys.executable, os.path.abspath(__file__)], capture_output=True, text=True)
    if _own.returncode:
        print(_own.stdout[-3000:] + _own.stderr[-2000:])
    check("the plugin build's suite passes in a process of its own", _own.returncode, 0)
    sys.exit(0)

os.environ["DECKYEMU_TEST_BUILD"] = "plugin"
from harness import REPO_ROOT, TMP, check, section, summary  # noqa: E402

if os.name == "nt":
    print("SKIPPED test_plugin_build.py: needs POSIX")
    sys.exit(0)

import appenv  # noqa: E402
import buildhost  # noqa: E402
import builds  # noqa: E402
import handoff  # noqa: E402
import releases  # noqa: E402
import service_switch  # noqa: E402

sys.path.insert(0, REPO_ROOT)
import main as plugin_main  # noqa: E402


section("the plugin's own modules are the ones loaded")

check("appenv is the plugin's", appenv.KIND, "plugin")
check("and so is the host mixin", buildhost.__file__.split(os.sep)[-3:],
      ["plugin", "py_modules", "buildhost.py"])
check("its update check takes the zip", releases.ASSET, "deckyemu.zip")


section("one release carries both builds")

_both = {
    "tag_name": "v0.21.0",
    "body": "Notes.\n\nsha256: %s\nsha256 (deckyemu-service.tar.gz): %s\n\nBuilt from abc1234." % ("a" * 64, "b" * 64),
    "assets": [
        {"name": "deckyemu.zip", "browser_download_url": "https://example/p.zip"},
        {"name": "deckyemu-service.tar.gz", "browser_download_url": "https://example/s.tar.gz"},
    ],
}
_zip = releases.parse_release(_both)
_tar = releases.parse_release(_both, "deckyemu-service.tar.gz")
check("the plugin takes the zip", _zip["asset_url"], "https://example/p.zip")
check("with the plain digest, the one installed plugins read", _zip["sha256"], "a" * 64)
check("the service's file has its own", _tar["sha256"], "b" * 64)
check("and neither digest line reaches the notes", _zip["notes"], "Notes.")
_old_plugin = {"tag_name": "v0.19.2", "body": "sha256: " + "c" * 64,
               "assets": [{"name": "deckyemu.zip", "browser_download_url": "https://example/o.zip"}]}
check("an older plugin-only release is still the plugin's",
      releases.parse_release(_old_plugin)["version"], "0.19.2")
check("but never the service's", releases.parse_release(_old_plugin, "deckyemu-service.tar.gz"), None)

_real_get_json = releases.net.get_json
releases.net.get_json = lambda url, headers=None, failure=None: [
    _old_plugin,
    _both,
    dict(_both, tag_name="v0.22.0-beta", prerelease=True),
]
releases.clear_cache()
try:
    check("the plugin's check sees every release with a zip",
          [r["version"] for r in releases.fetch_releases(force=True)], ["0.22.0-beta", "0.21.0", "0.19.2"])
    check("and the service offered is the newest stable one",
          releases.other_release("service")["version"], "0.21.0")
finally:
    releases.net.get_json = _real_get_json
    releases.clear_cache()


section("an update is offered to the loader over loopback")

# The loader downloads the URL it is given, so the release is fetched here and
# re-offered on loopback: the digest it checks is then one computed from the
# bytes actually received.
relay_file = os.path.join(TMP, "deckyemu.zip")
with open(relay_file, "wb") as handle:
    handle.write(b"PK pretend zip")

_plugin = plugin_main.Plugin()
_plugin.loop = asyncio.new_event_loop()
staged = _plugin.loop.run_until_complete(
    _plugin._install_release(relay_file, {"version": "0.21.0"}, "d" * 64))
relay_url = staged.get("url", "")
check("the relay offers a loopback url", relay_url.startswith("http://127.0.0.1:"), True)
check("with the file's name in it", relay_url.endswith("/deckyemu.zip"), True)
if relay_url:
    with urllib.request.urlopen(relay_url, timeout=5) as response:
        check("and serves the bytes", response.read(), b"PK pretend zip")
    base = relay_url.rsplit("/", 2)[0]
    try:
        urllib.request.urlopen(base + "/wrongtoken/deckyemu.zip", timeout=5)
        guessed = 200
    except urllib.error.HTTPError as error:
        guessed = error.code
    check("a wrong token is refused", guessed, 404)
_plugin.loop.run_until_complete(_plugin._host_stopping())
check("stopping leaves nothing listening", handoff.running(), False)
check("serving a file that is not there fails cleanly", handoff.serve(os.path.join(TMP, "nope.zip")), "")
os.remove(relay_file)


section("unpacking and installing the service")


def _tarball(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tarred:
        for name, body in members.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tarred.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


SERVICE = _tarball({"deckyemu/service.py": "print('installed')\n"})
WORK = os.path.join(TMP, "switch-work")


def _refusal(payload):
    try:
        service_switch.unpack(payload, WORK)
    except service_switch.Refused as refusal:
        return str(refusal)
    return ""


check("a whole release unpacks to its service folder",
      os.path.isfile(os.path.join(service_switch.unpack(SERVICE, WORK), "service.py")), True)
check("one that names a path outside itself is refused",
      "outside itself" in _refusal(_tarball({"../escape.txt": "x"})), True)
check("as is one with no service.py", "no service.py" in _refusal(_tarball({"deckyemu/x": ""})), True)
check("and one that is not a tarball", "not a tarball" in _refusal(b"not a tarball"), True)

_env = service_switch.install_env({"LD_LIBRARY_PATH": "/loader/lib", "PYTHONHOME": "/loader",
                                   "PATH": "/usr/bin"})
check("the loader's library path is gone", "LD_LIBRARY_PATH" in _env, False)
check("and its Python home", "PYTHONHOME" in _env, False)
check("the user session's bus is named",
      _env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/%d/bus" % os.getuid())


section("the switch, end to end")

_plugin._install = None
_plugin._cores = []
_plugin._emulators = []
_plugin._blocked = None
_calls = []


async def _unload():
    _calls.append("unload")


async def _main():
    _calls.append("main")
    _plugin._blocked = None


_plugin._unload = _unload
_plugin._main = _main
_release = {"version": "0.21.0", "sha256": hashlib.sha256(SERVICE).hexdigest(),
            "asset_url": "https://example/s.tar.gz", "prerelease": False}
_real = (releases.other_release, releases.download, service_switch.install, service_switch.start_unit)
releases.other_release = lambda kind, force=False: _release if kind == "service" else None
releases.download = lambda release: SERVICE
try:
    check("the offer names the service's version, to download",
          _plugin.loop.run_until_complete(_plugin.switch_offer()),
          {"available": True, "to": "service", "installed": False, "version": "0.21.0"})

    def _installed(folder):
        # What the service's installer does, as far as the plugin can see.
        builds._write(builds._record_path("service"), {
            "build": "The DeckyEmu service", "version": "0.21.0", "app_dir": appenv.ROOT})
        builds.use("service")
        return True, "installed"

    service_switch.install = _installed
    result = _plugin.loop.run_until_complete(_plugin.switch_build())
    check("it reports the version it switched to", result, {"ok": True, "version": "0.21.0"})
    check("after stopping the plugin", _calls, ["unload"])
    check("which stays off, and says for which", _plugin._blocked,
          {"reason": "switched", "kind": "service", "build": "The DeckyEmu service", "version": "0.21.0"})
    check("and the unpacked release is cleaned up",
          os.path.exists(os.path.join(appenv.DATA_DIR, "service-switch")), False)

    _calls.clear()
    _plugin._blocked = None
    check("installed, the offer says so",
          _plugin.loop.run_until_complete(_plugin.switch_offer()),
          {"available": True, "to": "service", "installed": True, "version": "0.21.0"})
    builds.use("plugin")
    _units = []
    service_switch.start_unit = lambda: (_units.append("start"), (True, ""))[1]
    result = _plugin.loop.run_until_complete(_plugin.switch_build())
    check("and switching starts it, without a download",
          (result["ok"], _calls, _units, builds.in_use()), (True, ["unload"], ["start"], "service"))

    _calls.clear()
    _plugin._blocked = None
    service_switch.start_unit = lambda: (False, "no bus")
    result = _plugin.loop.run_until_complete(_plugin.switch_build())
    check("a service that does not start is reported", result["ok"], False)
    check("and the plugin starts again, named as in use",
          (_calls, _plugin._blocked, builds._read(os.path.join(appenv.ROOT, builds.IN_USE))),
          (["unload", "main"], None, {"kind": "plugin"}))

    os.remove(builds._record_path("service"))
    _calls.clear()
    _plugin._blocked = None
    service_switch.install = lambda folder: (False, "no bus")
    result = _plugin.loop.run_until_complete(_plugin.switch_build())
    check("a failed install is reported", result["ok"], False)
    check("and the plugin starts again", (_calls, _plugin._blocked), (["unload", "main"], None))

    _calls.clear()
    releases.download = lambda release: b"something else"
    result = _plugin.loop.run_until_complete(_plugin.switch_build())
    check("a download that does not match its digest stops before anything",
          (result["ok"], _calls), (False, []))
finally:
    (releases.other_release, releases.download, service_switch.install,
     service_switch.start_unit) = _real
    _plugin.loop.close()


if __name__ == "__main__":
    summary()
