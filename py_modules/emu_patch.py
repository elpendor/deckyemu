"""Correcting a bug inside an emulator's own binary, when nothing else reaches it.

Most workarounds are things the launcher can say -- an environment variable, a
Steam layout. Those reach an emulator because it reads them at start. An
emulator that compiles its dependencies in reads nothing: Vita3K's AppImage
bundles SDL statically, so the SDL bug that kills Deck motion is not reachable
by `LD_PRELOAD`, by a hint, or by anything else that exists at launch. `ldd`
names no SDL at all.

So the correction is applied to the file. Which sounds alarming, and is why
every rule here is about refusing rather than trying harder:

* **The site is found by symbol, never by scanning the file.** Vita3K's four
  bytes occur nine times in its 54MB binary and exactly once inside
  `HIDAPI_DriverSteamDeck_UpdateDevice`. A patcher that scanned the file would
  be choosing at random between nine addresses, eight of them unrelated code.
  Upstream ships an unstripped binary with a full `.symtab`, so the function's
  bounds are a lookup rather than a guess.
* **Exactly one match inside those bounds, or nothing happens.** Zero means the
  build changed and the patch no longer describes it. More than one means the
  description is not specific enough to act on. Both are refusals.
* **The stock build is never modified.** The patched build is written beside it
  as a separate file, and the launcher points at whichever one the user's choice
  says. Turning a workaround off therefore means running exactly what upstream
  shipped, with nothing of ours left in the file.

What it costs: a second copy of the emulator, and about eight seconds at install
time -- measured on the Deck, unpack 0.6s and repack 5.8s. Both are paid for the
ability to say "off means stock" without arguing, per patch, about whether this
particular edit happens to be inert while the workaround is off.
"""

import json
import os
import re
import shutil
import struct
import subprocess

import decky

import emulator_catalog

#: Which patched builds exist, written beside the AppImage they were made from.
#:
#: Beside the binary rather than in the settings directory, for the same reason
#: `emu_install.BUILD_RECORD` is: decky owns its settings directory and clears
#: it, and a patched file whose provenance was forgotten is worse than one that
#: was never made.
PATCH_RECORD = ".patches.json"

#: A workaround id becomes part of a filename, so it is held to the same shape
#: as an entry id rather than trusted because the catalog is ours.
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Both ship with SteamOS -- checked on the device, where every package carries
#: the image's own install date and nothing had been added by hand. Absence is
#: still handled, because an emulator that cannot be patched has to degrade to
#: the stock build rather than fail to install.
_UNSQUASHFS = "unsquashfs"
_MKSQUASHFS = "mksquashfs"

#: Long enough for a 66MB AppImage on the Deck's slowest storage.
_TOOL_SECONDS = 300

#: Where unpacking happens, beside the build being patched.
#:
#: A fixed name rather than a random one, and beside the emulator rather than in
#: a system temp directory. Beside it because the finished image is moved into
#: place with `os.replace`, which is only atomic within one filesystem -- and the
#: Deck's SD card is a different filesystem from its internal drive. Fixed
#: because a crash then leaves one identifiable directory that the next install
#: clears, rather than a new 186MB one every time.
_WORK_DIR = ".patch-work"


def patched_name(asset_name, workaround_id):
    """What the patched copy of `asset_name` is called for `workaround_id`.

    A suffix on the original name rather than a separate directory, so the two
    builds sort together and `emu_install._remove_others` can recognise a
    sibling of the build it is keeping.
    """
    return "%s.%s" % (asset_name, workaround_id)


def patch_specs(entry):
    """[(workaround_id, spec)] for every workaround of `entry` that patches.

    Reads the catalog rather than a resolved entry: which builds exist is a
    property of what is installed, not of what any one game switched on.
    Preparing every patched build at install is what makes the switch itself
    instant and unable to fail -- and what lets the panel say "this build cannot
    take that fix" before the user turns it on rather than afterwards.
    """
    found = []
    for item in emulator_catalog.workarounds_for(entry):
        spec = (item.get("apply") or {}).get("patch")
        if spec:
            found.append((item.get("id") or "", spec))
    return found


# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------

def _elf_symbol(buf, name):
    """(vaddr, size) of `name` from the ELF's `.symtab`, or None.

    None covers both "no such symbol" and "no symbol table at all", which are
    the same thing to the caller: the site cannot be located, so nothing is
    patched. A stripped build is the expected future cause.
    """
    wanted = name.encode() if isinstance(name, str) else name
    try:
        shoff = struct.unpack_from("<Q", buf, 0x28)[0]
        shentsize = struct.unpack_from("<H", buf, 0x3a)[0]
        shnum = struct.unpack_from("<H", buf, 0x3c)[0]
        shstrndx = struct.unpack_from("<H", buf, 0x3e)[0]

        def section(index):
            return struct.unpack_from("<IIQQQQIIQQ", buf, shoff + index * shentsize)

        names_at = section(shstrndx)[4]
        sections = {}
        for index in range(shnum):
            header = section(index)
            start = names_at + header[0]
            sections[bytes(buf[start:buf.index(b"\0", start)])] = header

        symtab, strtab = sections.get(b".symtab"), sections.get(b".strtab")
        if not symtab or not strtab:
            return None

        offset, size, entsize = symtab[4], symtab[5], symtab[9]
        strings_at = strtab[4]
        for index in range(size // entsize):
            at = offset + index * entsize
            name_offset, _, _, _, value, symbol_size = struct.unpack_from(
                "<IBBHQQ", buf, at)
            if not name_offset:
                continue
            start = strings_at + name_offset
            if bytes(buf[start:start + len(wanted) + 1]) == wanted + b"\0":
                return value, symbol_size
    except (struct.error, ValueError, IndexError):
        # A file that does not parse as an ELF is not a file to patch.
        return None
    return None


def _vaddr_to_offset(buf, vaddr):
    """Where `vaddr` lives in the file, via the program headers.

    Not a fixed subtraction: the delta between a virtual address and a file
    offset is per segment, and reading it from the headers is the difference
    between a patcher that works on one build and one that works on whatever
    layout the linker produced.
    """
    try:
        phoff = struct.unpack_from("<Q", buf, 0x20)[0]
        phentsize = struct.unpack_from("<H", buf, 0x36)[0]
        phnum = struct.unpack_from("<H", buf, 0x38)[0]
        for index in range(phnum):
            kind, _, offset, addr, _, filesz, _, _ = struct.unpack_from(
                "<IIQQQQQQ", buf, phoff + index * phentsize)
            if kind == 1 and addr <= vaddr < addr + filesz:   # PT_LOAD
                return offset + (vaddr - addr)
    except (struct.error, IndexError):
        return None
    return None


def patch_bytes(buf, spec):
    """Apply `spec` to `buf` in place. Returns (offset, error).

    The offset comes back so the caller can record what was changed where: a
    patched file nobody can describe afterwards is not auditable.
    """
    within = spec.get("within") or ""
    try:
        find = bytes.fromhex(spec.get("find") or "")
        replace = bytes.fromhex(spec.get("replace") or "")
    except ValueError:
        return -1, "patch bytes are not hex"
    if not find or len(find) != len(replace):
        return -1, "patch bytes must be the same length"

    symbol = _elf_symbol(buf, within)
    if not symbol:
        return -1, ("%s is not in this build -- it may be stripped, or the code "
                    "it names may be gone" % within)
    vaddr, size = symbol
    if not size:
        return -1, "%s has no size recorded" % within
    start = _vaddr_to_offset(buf, vaddr)
    if start is None:
        return -1, "%s does not map into the file" % within

    region = bytes(buf[start:start + size])
    hits = []
    at = region.find(find)
    while at != -1:
        hits.append(start + at)
        at = region.find(find, at + 1)

    if len(hits) != 1:
        # The only two ways this ends without patching, and they mean the same
        # thing: the build no longer matches what the catalog describes.
        return -1, ("expected one site inside %s, found %d -- this build has "
                    "changed" % (within, len(hits)))

    buf[hits[0]:hits[0] + len(find)] = replace
    return hits[0], ""


# ---------------------------------------------------------------------------
# AppImage
# ---------------------------------------------------------------------------

def _payload_offset(path):
    """Where the squashfs starts inside an AppImage, or (0, error).

    Computed from the runtime's own ELF headers rather than by running the
    AppImage with `--appimage-offset`: this happens at install time on a file
    that has just been downloaded, and executing it to ask a question about it
    is a worse trade than reading four fields. Checked against the squashfs
    magic, so a wrong answer is caught here instead of producing a corrupt
    image.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(64)
            shoff = struct.unpack_from("<Q", header, 0x28)[0]
            shentsize = struct.unpack_from("<H", header, 0x3a)[0]
            shnum = struct.unpack_from("<H", header, 0x3c)[0]
            offset = shoff + shentsize * shnum
            handle.seek(offset)
            if handle.read(4) != b"hsqs":
                return 0, "no squashfs where the runtime ends -- not an AppImage?"
    except (OSError, struct.error) as error:
        return 0, "could not read %s: %s" % (os.path.basename(path), error)
    return offset, ""


def _payload_params(payload_path):
    """(compression, block size) of a squashfs, defaulting to Vita3K's shape.

    Read rather than assumed, so a repack is the same shape as the original.
    Upstream is zstd at 128K today; an AppImage that changed either and got
    repacked with mksquashfs's defaults would be a size and speed regression
    nobody would connect to this.
    """
    compression, block = "zstd", "131072"
    try:
        result = subprocess.run([_UNSQUASHFS, "-s", payload_path],
                                capture_output=True, text=True, timeout=30)
        for line in (result.stdout or "").splitlines():
            if line.startswith("Compression"):
                compression = line.split()[-1]
            elif line.startswith("Block size"):
                block = line.split()[-1]
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return compression, block


def have_tools():
    """Whether this machine can unpack and repack an AppImage."""
    return bool(shutil.which(_UNSQUASHFS) and shutil.which(_MKSQUASHFS))


def _safe_member(name):
    """Whether `name` is a path this may touch inside an unpacked AppImage."""
    if not name or name.startswith("/") or os.path.isabs(name):
        return False
    parts = name.replace("\\", "/").split("/")
    return ".." not in parts and "" not in parts


def _last_line(text, fallback="unknown"):
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else fallback


def apply_to_appimage(stock_path, spec, out_path):
    """Write a patched copy of `stock_path` to `out_path`. Returns an error.

    Empty means it worked. Every other return leaves `out_path` absent and
    `stock_path` untouched, which is the whole contract: a failure here costs
    the fix, never the emulator.
    """
    member = spec.get("file") or ""
    if not _safe_member(member):
        return "patch names a path outside the package: %r" % member
    if not have_tools():
        return "this system has no squashfs tools, so nothing can be patched"

    offset, error = _payload_offset(stock_path)
    if error:
        return error

    work = os.path.join(os.path.dirname(stock_path), _WORK_DIR)
    shutil.rmtree(work, ignore_errors=True)
    try:
        os.makedirs(work, exist_ok=True)
        tree = os.path.join(work, "root")
        payload = os.path.join(work, "payload.sqfs")

        # Split the runtime off the payload by hand. `--appimage-extract` would
        # do this too, by executing the file that was just downloaded.
        with open(stock_path, "rb") as source:
            runtime = source.read(offset)
            with open(payload, "wb") as handle:
                shutil.copyfileobj(source, handle)

        compression, block = _payload_params(payload)

        result = subprocess.run([_UNSQUASHFS, "-d", tree, "-no-progress", payload],
                                capture_output=True, text=True, timeout=_TOOL_SECONDS)
        if result.returncode != 0:
            return "could not unpack the build: %s" % _last_line(result.stderr)

        target = os.path.join(tree, member)
        if not os.path.isfile(target):
            return "%s is not in this build" % member
        with open(target, "rb") as handle:
            buf = bytearray(handle.read())

        at, error = patch_bytes(buf, spec)
        if error:
            return error
        mode = os.stat(target).st_mode
        with open(target, "wb") as handle:
            handle.write(buf)
        os.chmod(target, mode)

        repacked = os.path.join(work, "new.sqfs")
        result = subprocess.run(
            [_MKSQUASHFS, tree, repacked, "-comp", compression, "-b", block,
             "-all-root", "-noappend", "-no-progress"],
            capture_output=True, text=True, timeout=_TOOL_SECONDS)
        if result.returncode != 0:
            return "could not repack the build: %s" % _last_line(result.stderr)

        staged = os.path.join(work, "image")
        with open(staged, "wb") as handle:
            handle.write(runtime)
            with open(repacked, "rb") as source:
                shutil.copyfileobj(source, handle)
        os.chmod(staged, 0o755)
        # Into place in one step, so a patched build is either whole or absent
        # and never half-written for a launcher to find.
        os.replace(staged, out_path)
        decky.logger.info("Patched %s at 0x%x -> %s",
                          member, at, os.path.basename(out_path))
        return ""
    except subprocess.TimeoutExpired:
        return "unpacking or repacking the build timed out"
    except OSError as error:
        return "could not patch the build: %s" % error
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# What exists on disk
# ---------------------------------------------------------------------------

def record_path(entry_id):
    import emu_install
    return os.path.join(emu_install.emulators_dir(entry_id, create=False),
                        PATCH_RECORD)


def read_record(entry_id):
    """{workaround id: {"file": name, "error": str}} for what was attempted."""
    if not emulator_catalog.is_safe_id(entry_id):
        return {}
    try:
        with open(record_path(entry_id), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _write_record(entry_id, record):
    try:
        with open(record_path(entry_id), "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
    except OSError as error:
        decky.logger.warning("Could not record patches for %s: %s", entry_id, error)


def refresh(entry, stock_path):
    """Re-derive every patched build of `entry` from `stock_path`.

    Called after an install and after an update, and it always starts by
    deleting what was there. A patched build is derived from one stock build and
    means nothing beside another: keeping yesterday's copy because today's patch
    did not apply would leave the launcher pointing at an emulator that silently
    stopped being updated, which is a worse failure than losing the fix.

    Returns the record it wrote -- an entry per patching workaround, carrying
    either the file it made or the reason it could not.
    """
    entry_id = entry.get("id") or ""
    specs = patch_specs(entry)
    if not emulator_catalog.is_safe_id(entry_id) or not specs:
        return {}

    directory = os.path.dirname(stock_path)
    asset = os.path.basename(stock_path)
    record = {}
    for workaround_id, spec in specs:
        if not _SAFE_ID.match(workaround_id or ""):
            continue
        out_path = os.path.join(directory, patched_name(asset, workaround_id))
        try:
            os.unlink(out_path)
        except OSError:
            pass
        error = apply_to_appimage(stock_path, spec, out_path)
        if error:
            decky.logger.warning("No patched build for %s/%s: %s",
                                 entry_id, workaround_id, error)
            record[workaround_id] = {"file": "", "error": error}
        else:
            record[workaround_id] = {"file": os.path.basename(out_path), "error": ""}
    _write_record(entry_id, record)
    return record


def stock_path(path, entry):
    """`path` with any patched-build suffix removed.

    So deriving a patched build from an emulator record that already names one
    cannot produce `...AppImage.vita-motion.vita-motion`. Cheap insurance:
    `emulators.save` carries `target`, so a resolved record reaching storage
    would otherwise compound every time it was resolved again.
    """
    for workaround_id, _ in patch_specs(entry):
        suffix = ".%s" % workaround_id
        if workaround_id and path.endswith(suffix):
            return path[:-len(suffix)]
    return path


def target_for(path, workaround_id):
    """The build to run for `workaround_id`, or "" to run the stock one.

    Answered from the file rather than from the record, because the record says
    what happened at install and a launcher needs what is true now.
    """
    if not path or not _SAFE_ID.match(workaround_id or ""):
        return ""
    candidate = os.path.join(os.path.dirname(path),
                             patched_name(os.path.basename(path), workaround_id))
    return candidate if os.path.isfile(candidate) else ""


def unapplied(entry):
    """[{id, name, error}] for workarounds this build could not take.

    The honest half of a patch that fails safe. Without it, a fix that could not
    be applied looks exactly like one that worked: the switch says on, the
    emulator behaves as though it were off, and nothing anywhere says why.
    """
    entry_id = entry.get("id") or ""
    record = read_record(entry_id)
    rows = []
    for item in emulator_catalog.workarounds_for(entry):
        workaround_id = item.get("id") or ""
        if not (item.get("apply") or {}).get("patch"):
            continue
        state = record.get(workaround_id) or {}
        if state and not state.get("file"):
            rows.append({
                "id": workaround_id,
                "name": item.get("name") or workaround_id,
                "error": state.get("error") or "",
            })
    return rows
