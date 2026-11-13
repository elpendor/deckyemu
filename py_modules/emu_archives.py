"""Unpacking downloaded archives, refusing members that leave their folder."""

import os
import re
import shutil
import tarfile
import zipfile

import appenv


def _nothing_matched(pattern, names):
    """The error for an `extract` pattern that named no member of the archive.

    Lists what the archive holds, since patterns and releases drift, often
    only in letter case.
    """
    listed = ", ".join(sorted(names)[:8]) or "nothing"
    if len(names) > 8:
        listed += ", ..."
    return "Nothing in the download is named like %s. It holds: %s." % (pattern, listed)


def _replace(target):
    """Take a file out of the way so the new one can be written over it.

    An archive can ship read-only files, and `open(..., "wb")` cannot reopen
    one, so a second build failed over the first. Removed, not chmod-ed, so
    the new file inherits nothing.
    """
    try:
        os.remove(target)
    except FileNotFoundError:
        pass
    except OSError as error:
        appenv.logger.warning("Could not replace %s: %s", target, error)


def _safe_target(destination, name):
    """Where `name` lands under `destination`, or "" if it tries to leave it.

    Archives come off the network, so an absolute or `..` member is refused,
    and the resolved path is checked against the destination.
    """
    # Backslashes first: normpath on Linux would keep `a\..\..` as one name.
    relative = os.path.normpath(name.replace("\\", "/"))
    if relative.startswith("/") or relative.split("/")[0] == "..":
        return ""
    target = os.path.join(destination, *relative.split("/"))
    root = os.path.realpath(destination)
    if os.path.commonpath([root, os.path.realpath(os.path.dirname(target))]) != root:
        return ""
    return target


def _common_prefix(names):
    """The single folder every member sits in, or "".

    Stripped so a tarball's top folder does not nest inside ours. Only when
    every member shares it.
    """
    first = ""
    for name in names:
        head = name.replace("\\", "/").split("/")[0]
        if "/" not in name.replace("\\", "/"):
            return ""
        if first and head != first:
            return ""
        first = head
    return first


def _unpack_tarball(archive, destination, pattern):
    """`_unpack_release` for a .tar.gz. Same contract, same refusals.

    Only regular files come out, so links and devices are never written.
    `filter="data"` needs Python 3.12; the runtime was 3.11.
    """
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = ""
    seen = []
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = [m for m in bundle.getmembers() if m.isfile()]
            strip = _common_prefix([m.name for m in members])
            for member in members:
                name = member.name
                if strip:
                    name = name.replace("\\", "/")[len(strip) + 1:]
                    if not name:
                        continue
                target = _safe_target(destination, name)
                if not target:
                    return "", "The download holds a path that leaves its own folder."
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _replace(target)
                source = bundle.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                # The recorded mode carries the execute bit.
                if member.mode:
                    os.chmod(target, member.mode & 0o777)
                seen.append(os.path.basename(target))
                if matcher.match(os.path.basename(target)):
                    found = target
    except (OSError, tarfile.TarError, ValueError) as error:
        return "", "Could not unpack the download: %s" % error
    if not found:
        return "", _nothing_matched(pattern, seen)
    return found, ""


def _unpack_release(archive, destination, pattern):
    """Unpack a whole archive, and return the member `pattern` names. (path, error).

    Unpacked beside `destination` first and moved over it only once whole, so
    a failure leaves the installed build as it was. Files already there that
    the release does not ship (the program's own data) stay.
    """
    staging = os.path.join(os.path.dirname(destination),
                           "." + os.path.basename(destination) + ".unpacking")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        os.makedirs(staging)
        if tarfile.is_tarfile(archive):
            found, error = _unpack_tarball(archive, staging, pattern)
        else:
            found, error = _unpack_zip(archive, staging, pattern)
        if error:
            return "", error
        for root, _dirs, files in os.walk(staging):
            for name in files:
                source = os.path.join(root, name)
                target = os.path.join(destination, os.path.relpath(source, staging))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(source, target)
        return os.path.join(destination, os.path.relpath(found, staging)), ""
    except OSError as error:
        return "", "Could not unpack the download: %s" % error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _unpack_zip(archive, destination, pattern):
    """`_unpack_release` for a zip. Same contract, same refusals."""
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = ""
    seen = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = info.filename
                if info.is_dir() or not name:
                    continue
                target = _safe_target(destination, name)
                if not target:
                    return "", "The download holds a path that leaves its own folder."
                os.makedirs(os.path.dirname(target), exist_ok=True)
                # A read-only file from the last build cannot be written over.
                _replace(target)
                with bundle.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                # Keep the recorded mode.
                mode = info.external_attr >> 16
                if mode:
                    os.chmod(target, mode & 0o777)
                seen.append(os.path.basename(target))
                if matcher.match(os.path.basename(target)):
                    found = target
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return "", "Could not unpack the download: %s" % error
    if not found:
        return "", _nothing_matched(pattern, seen)
    return found, ""


def _extract_member(archive, destination, pattern):
    """Pull one file out of a downloaded zip by basename. Returns (path, error).

    Written by basename, never the archive's path. Exactly one must match;
    two means the pattern is ambiguous.
    """
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = []
    seen = []
    partial = ""
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = os.path.basename(info.filename)
                if info.is_dir() or not name:
                    continue
                seen.append(name)
                if not matcher.match(name):
                    continue
                found.append(info)
        if len(found) != 1:
            return "", (_nothing_matched(pattern, seen)
                        if not found else
                        "The download contained %d files matching %r; expected "
                        "one." % (len(found), pattern))
        target = os.path.join(destination, os.path.basename(found[0].filename))
        # Written aside and renamed, so a failure keeps the installed copy.
        partial = target + ".part"
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open(found[0]) as source, open(partial, "wb") as handle:
                shutil.copyfileobj(source, handle)
        os.replace(partial, target)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        if partial:
            try:
                os.remove(partial)
            except OSError:
                pass
        return "", "Could not unpack the download: %s" % error
    return target, ""
