"""Moving from this plugin to the standalone service, from the panel.

The service installs as the user and needs no root, so the plugin can run its
installer: unpack the release, then `service.py --install`, which copies itself
under `appenv.ROOT`, writes the systemd user unit and starts it. The state is
already shared (see migrate.py), so nothing else moves.

The installer is the system's Python, not the loader's, and runs with the
loader's library redirection removed and the user session's bus named, which a
process started by the loader does not have.
"""

import os
import shutil
import subprocess
import tarfile

import appenv
import sysenv

PYTHON = "/usr/bin/python3"


class Refused(Exception):
    """The release is not something to install. The message says why."""


def unpack(payload, work):
    """Write and unpack the release under `work`. Returns the service's folder."""
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    archive = os.path.join(work, "service.tar.gz")
    with open(archive, "wb") as handle:
        handle.write(payload)
    root = os.path.realpath(work)
    try:
        tarred = tarfile.open(archive, "r:gz")
    except (tarfile.TarError, OSError) as error:
        raise Refused("the release is not a tarball: %s" % error) from error
    with tarred:
        members = tarred.getmembers()
        for member in members:
            dest = os.path.realpath(os.path.join(work, member.name))
            if dest != root and not dest.startswith(root + os.sep):
                raise Refused("the release names a path outside itself: %s" % member.name)
            if not (member.isfile() or member.isdir()):
                raise Refused("the release holds something that is not a file: %s" % member.name)
        tarred.extractall(work, members=members, filter="data")
    folder = os.path.join(work, "deckyemu")
    if not os.path.isfile(os.path.join(folder, "service.py")):
        raise Refused("the release has no service.py")
    return folder


def install_env(base=None):
    """The environment the installer runs in."""
    env = sysenv.clean_env(base)
    for name in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    runtime = "/run/user/%d" % os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=%s/bus" % env["XDG_RUNTIME_DIR"])
    env["HOME"] = appenv.USER_HOME
    env["DECKYEMU_USER_HOME"] = appenv.USER_HOME
    return env


def start_unit(run=subprocess.run):
    """Start the installed service, and at every login from now on.
    Returns (worked, what systemctl printed)."""
    try:
        done = run(
            ["systemctl", "--user", "enable", "--now", "deckyemu.service"],
            env=install_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return done.returncode == 0, ((done.stdout or "") + (done.stderr or "")).strip()


def install(folder, run=subprocess.run):
    """Run the service's installer. Returns (worked, what it printed)."""
    try:
        done = run(
            [PYTHON, os.path.join(folder, "service.py"), "--install"],
            cwd=folder,
            env=install_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    said = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, said
