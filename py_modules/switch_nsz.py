"""Unpacking a Switch `.nsz` into the `.nsp` Ryujinx can read, on the Deck.

**Ryujinx cannot open an NSZ.** Checked on 1.3.3: its binary carries no `.nsz`,
`.xcz`, `NCZSECTN` or `NCZBLOCK`, and a game added as one crashes ten seconds
in, when `CheckLaunchState` takes the first of an empty list of applications.
So the compressed file has to become the uncompressed one before it is added.

**No keys.** An NSZ is a PFS0 like any NSP, with each `.nca` stored as `.ncz`:
the NCA's first 0x4000 bytes as they were, a table of sections carrying their
own AES key and counter, then the decrypted body -- one zstd stream, or
`NCZBLOCK` blocks compressed one by one. Undoing it is decompressing, then
encrypting each AES-CTR section again with the key beside it. The layout is
nicoboss/nsz's; `IndependentNczDecompressor.py` there is the reference.

**Checked, not trusted.** An NCA is named after the first half of its SHA-256,
so the `.nca` written back has to hash to the `.ncz`'s own name. Either it is
the original file bit for bit, or the unpack fails and leaves nothing behind.

**libzstd and libcrypto through ctypes.** The standard library has neither
zstd nor AES and nothing can be installed into Decky's Python, but both are
part of SteamOS itself -- pacman depends on them. Measured on the Deck: a
577 MB NSZ became a 1.34 GB NSP in 4.7 seconds, two of them zstd and one the
hash. AES runs at about 10 GB/s there and is not what costs the time.

**Space.** The `.nsp` is written beside the `.nsz`, and the `.nsz` stays until
the new file has checked out -- when there is room for both. When there is
not, the parts of the `.nsz` already read are handed back to the filesystem as
the `.nsp` grows, so the peak is the `.nsp` alone: 1.38 GB for the file above
rather than 1.91. That uses the source up, so a failure part way means sending
it again, which is why it is only done when nothing else fits.
"""

import ctypes
import hashlib
import os
import re
import shutil
import struct

import decky

#: Written beside the real name while unpacking, as `unpack` does, so nothing
#: scanning the transfer folder picks up a half-written package.
_PARTIAL = ".deckyemu-tmp"

#: Left over the free space on the drive, as `unpack` leaves it.
_SPACE_MARGIN = 256 * 1024 * 1024

#: How much is read, decompressed and written at a time.
_CHUNK = 4 * 1024 * 1024

_NCA_HEADER = 0x4000

#: How much of the source is read before it is released, when space is short.
#: Coarse on purpose: each release is a system call, and what matters is the
#: peak, which a 64 MB step moves by 64 MB.
_RELEASE_STEP = 64 * 1024 * 1024

#: How often progress is reported, in bytes written.
_PROGRESS_STEP = 64 * 1024 * 1024

#: The largest block this will hold in memory. nsz writes 2^20; its own reader
#: accepts up to 2^32, which is two 4 GB buffers on a 16 GB Deck.
_MAX_BLOCK_EXPONENT = 28

#: Filesystems that can release part of a file. Not exFAT or FAT, which is what
#: an SD card formatted somewhere else tends to be.
_RELEASABLE = {"ext4", "btrfs", "xfs", "f2fs", "tmpfs"}

_FALLOC_FL_KEEP_SIZE = 0x01
_FALLOC_FL_PUNCH_HOLE = 0x02

_HASH_NAME = re.compile(r"^[0-9a-f]{32}$")


class Unavailable(Exception):
    """libzstd or libcrypto could not be loaded."""


class _InBuffer(ctypes.Structure):
    _fields_ = [("src", ctypes.c_void_p), ("size", ctypes.c_size_t), ("pos", ctypes.c_size_t)]


class _OutBuffer(ctypes.Structure):
    _fields_ = [("dst", ctypes.c_void_p), ("size", ctypes.c_size_t), ("pos", ctypes.c_size_t)]


_loaded: dict = {}


def _load():
    """(libzstd, libcrypto, libc), loaded once. Raises Unavailable."""
    if "error" in _loaded:
        raise Unavailable(_loaded["error"])
    if "libraries" not in _loaded:
        try:
            zstd = ctypes.CDLL("libzstd.so.1")
            crypto = ctypes.CDLL("libcrypto.so.3")
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
        except OSError as error:
            _loaded["error"] = str(error)
            raise Unavailable(str(error))
        c_void_p, c_size_t, c_int = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
        zstd.ZSTD_createDStream.restype = c_void_p
        zstd.ZSTD_freeDStream.argtypes = [c_void_p]
        zstd.ZSTD_initDStream.argtypes = [c_void_p]
        zstd.ZSTD_initDStream.restype = c_size_t
        zstd.ZSTD_decompressStream.argtypes = [
            c_void_p, ctypes.POINTER(_OutBuffer), ctypes.POINTER(_InBuffer)]
        zstd.ZSTD_decompressStream.restype = c_size_t
        zstd.ZSTD_decompress.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t]
        zstd.ZSTD_decompress.restype = c_size_t
        zstd.ZSTD_isError.argtypes = [c_size_t]
        zstd.ZSTD_isError.restype = ctypes.c_uint
        zstd.ZSTD_getErrorName.argtypes = [c_size_t]
        zstd.ZSTD_getErrorName.restype = ctypes.c_char_p
        crypto.EVP_CIPHER_CTX_new.restype = c_void_p
        crypto.EVP_CIPHER_CTX_free.argtypes = [c_void_p]
        crypto.EVP_aes_128_ctr.restype = c_void_p
        crypto.EVP_EncryptInit_ex.argtypes = [
            c_void_p, c_void_p, c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        crypto.EVP_EncryptInit_ex.restype = c_int
        crypto.EVP_EncryptUpdate.argtypes = [
            c_void_p, c_void_p, ctypes.POINTER(c_int), c_void_p, c_int]
        crypto.EVP_EncryptUpdate.restype = c_int
        libc.fallocate.argtypes = [c_int, c_int, ctypes.c_longlong, ctypes.c_longlong]
        libc.fallocate.restype = c_int
        _loaded["libraries"] = (zstd, crypto, libc)
    return _loaded["libraries"]


def available():
    """Whether an .nsz can be unpacked on this system at all."""
    try:
        _load()
    except Unavailable:
        return False
    return True


def _buffer(size):
    """A bytearray and the address ctypes can hand to C."""
    data = bytearray(size)
    return data, ctypes.addressof((ctypes.c_char * size).from_buffer(data))


class _Ctr:
    """AES-128-CTR for one section, carrying on across calls."""

    def __init__(self, crypto, key, counter):
        self._crypto = crypto
        self._context = crypto.EVP_CIPHER_CTX_new()
        self._length = ctypes.c_int()
        if not self._context or crypto.EVP_EncryptInit_ex(
                self._context, crypto.EVP_aes_128_ctr(), None, key, counter) != 1:
            self.close()
            raise RuntimeError("could not start AES")

    def into(self, out_address, in_address, size):
        if self._crypto.EVP_EncryptUpdate(
                self._context, out_address, ctypes.byref(self._length), in_address, size) != 1:
            raise RuntimeError("AES failed")

    def close(self):
        if self._context:
            self._crypto.EVP_CIPHER_CTX_free(self._context)
            self._context = None


def _aes_ctr(key, counter, data):
    """AES-128-CTR of `data` from `counter`. The tests' known answers use it."""
    crypto = _load()[1]
    source, source_address = _buffer(len(data))
    source[:] = data
    out, out_address = _buffer(len(data))
    cipher = _Ctr(crypto, key, counter)
    try:
        cipher.into(out_address, source_address, len(data))
    finally:
        cipher.close()
    return bytes(out)


def _read_at(handle, offset, size):
    handle.seek(offset)
    return handle.read(size)


def _listing(handle):
    """[(name, absolute offset, size)] of a PFS0 package, or None."""
    head = _read_at(handle, 0, 16)
    if len(head) < 16 or head[:4] != b"PFS0":
        return None
    count, strings_size = struct.unpack_from("<II", head, 4)
    table = handle.read(24 * count + strings_size)
    if len(table) < 24 * count + strings_size:
        return None
    names = table[24 * count:]
    start = 16 + 24 * count + strings_size
    files = []
    for index in range(count):
        offset, size, name_at, _reserved = struct.unpack_from("<QQII", table, 24 * index)
        end = names.find(b"\0", name_at)
        if end < 0:
            return None
        files.append((names[name_at:end].decode("utf-8", "replace"), start + offset, size))
    return files


def _ncz(handle, offset, size):
    """(sections, body offset, blocks or None, NCA size) of one .ncz.

    Raises ValueError for anything this cannot unpack. The sections have to
    run on from the header without a gap, since the body is written straight
    after it.
    """
    at = offset + _NCA_HEADER
    if _read_at(handle, at, 8) != b"NCZSECTN":
        raise ValueError("a .ncz inside it is not compressed the way nsz does it")
    count = struct.unpack("<q", handle.read(8))[0]
    # Bounded by the file rather than by a guess. It was fewer than 64, which
    # refused a real update: an update's NCA is split into many small encrypted
    # regions, and that one listed 169.
    if count <= 0 or _NCA_HEADER + 16 + 64 * count > size:
        raise ValueError("a .ncz inside it lists %d sections" % count)
    raw = handle.read(64 * count)
    if len(raw) < 64 * count:
        raise ValueError("a .ncz inside it ends in its section table")
    sections = []
    expected = _NCA_HEADER
    for index in range(count):
        section_offset, section_size, kind, _padding = struct.unpack_from("<qqqq", raw, 64 * index)
        if section_offset != expected or section_size < 0:
            raise ValueError("a .ncz inside it has sections that do not follow on")
        sections.append((section_offset, section_size, kind,
                         raw[64 * index + 32:64 * index + 48], raw[64 * index + 48:64 * index + 64]))
        expected += section_size
    body = at + 16 + 64 * count
    blocks = None
    if _read_at(handle, body, 8) == b"NCZBLOCK":
        head = handle.read(16)
        if len(head) < 16:
            raise ValueError("a .ncz inside it ends in its block header")
        _version, _kind, _unused, exponent, number, decompressed = struct.unpack("<BBBBIq", head)
        if not 14 <= exponent <= _MAX_BLOCK_EXPONENT:
            raise ValueError("a .ncz inside it uses blocks of 2^%d bytes" % exponent)
        sizes = struct.unpack("<%dI" % number, handle.read(4 * number))
        if decompressed != expected - _NCA_HEADER:
            raise ValueError("a .ncz inside it disagrees with itself about its size")
        blocks = (exponent, sizes, decompressed)
        body += 24 + 4 * number
    if body > offset + size:
        raise ValueError("a .ncz inside it is cut short")
    return sections, body, blocks, expected


def _header(files):
    """A PFS0 header for [(name, size)], padded the way nsz pads it."""
    names = "\0".join(name for name, _size in files) + "\0"
    unpadded = 0x10 + len(files) * 0x18 + len(names.encode())
    names += "\0" * (0x20 - (unpadded & 0x1F))
    encoded = names.encode()
    header = b"PFS0" + struct.pack("<II", len(files), len(encoded)) + b"\0" * 4
    offset = 0
    name_at = 0
    for name, size in files:
        header += struct.pack("<QQII", offset, size, name_at, 0)
        offset += size
        name_at += len(name.encode()) + 1
    return header + encoded


def _planned(handle):
    """(listing, {name: layout}, [(output name, size)]). Raises ValueError."""
    files = _listing(handle)
    if not files:
        raise ValueError("this does not look like an .nsz: it has no package listing")
    layouts = {}
    entries = []
    for name, offset, size in files:
        if name.lower().endswith(".ncz"):
            layouts[name] = _ncz(handle, offset, size)
            entries.append((name[:-4] + ".nca", layouts[name][3]))
        else:
            entries.append((name, size))
    if not layouts:
        raise ValueError("nothing inside this .nsz is compressed")
    return files, layouts, entries


def plan(path):
    """(name of the .nsp, its size in bytes, error) for the .nsz at `path`."""
    try:
        with open(path, "rb") as handle:
            _files, _layouts, entries = _planned(handle)
    except (OSError, ValueError, struct.error) as error:
        return "", 0, "This .nsz could not be read: %s." % error
    name = os.path.splitext(os.path.basename(path))[0] + ".nsp"
    return name, len(_header(entries)) + sum(size for _name, size in entries), ""


class _Writer:
    def __init__(self, handle, total, progress):
        self._handle = handle
        self._total = total
        self._progress = progress
        self.written = 0
        self._reported = 0

    def write(self, view):
        while len(view):
            count = self._handle.write(view)
            view = view[count:]
            self.written += count
        if self._progress and (self.written - self._reported >= _PROGRESS_STEP
                               or self.written == self._total):
            self._reported = self.written
            try:
                self._progress(self.written, self._total)
            except Exception as error:  # noqa: BLE001 -- a bar is not worth the unpack
                decky.logger.warning("nsz progress report failed: %s", error)


class _Release:
    """Hands the already-read front of the source back, when space is short."""

    def __init__(self, libc, handle, active):
        self._libc = libc
        self._handle = handle
        self.active = active
        self.done = 0

    def upto(self, position):
        if not self.active:
            return
        end = position & ~0xFFF
        if end - self.done < _RELEASE_STEP:
            return
        if self._libc.fallocate(self._handle.fileno(), _FALLOC_FL_PUNCH_HOLE | _FALLOC_FL_KEEP_SIZE,
                                self.done, end - self.done) != 0:
            number = ctypes.get_errno()
            raise OSError(number, "could not free space as it went: %s" % os.strerror(number))
        self.done = end


class _Sections:
    """The NCA body, in order, encrypted again wherever a section says so."""

    def __init__(self, crypto, sections, writer, digest):
        self._crypto = crypto
        self._sections = sections
        self._writer = writer
        self._digest = digest
        self._index = 0
        self._cipher = None
        self.position = sections[0][0]
        self._scratch, self._scratch_address = _buffer(_CHUNK)
        self._open()

    def _open(self):
        self.close()
        offset, _size, kind, key, counter = self._sections[self._index]
        if kind in (3, 4):
            self._cipher = _Ctr(self._crypto, key, counter[:8] + (offset >> 4).to_bytes(8, "big"))

    def feed(self, data, address, length):
        done = 0
        while done < length:
            offset, size, _kind, _key, _counter = self._sections[self._index]
            if self.position >= offset + size:
                if self._index + 1 == len(self._sections):
                    raise ValueError("a .ncz inside it holds more than its sections describe")
                self._index += 1
                self._open()
                continue
            count = min(length - done, offset + size - self.position, _CHUNK)
            if self._cipher:
                self._cipher.into(self._scratch_address, address + done, count)
                view = memoryview(self._scratch)[:count]
            else:
                view = memoryview(data)[done:done + count]
            self._digest.update(view)
            self._writer.write(view)
            self.position += count
            done += count

    def close(self):
        if self._cipher:
            self._cipher.close()
            self._cipher = None


def _solid(zstd, handle, position, end, sink, release):
    stream = zstd.ZSTD_createDStream()
    if not stream:
        raise RuntimeError("could not start zstd")
    try:
        zstd.ZSTD_initDStream(stream)
        compressed, compressed_address = _buffer(_CHUNK)
        plain, plain_address = _buffer(_CHUNK)
        source = _InBuffer(compressed_address, 0, 0)
        target = _OutBuffer(plain_address, _CHUNK, 0)
        full = False
        while True:
            if source.pos == source.size:
                if position < end:
                    handle.seek(position)
                    count = handle.readinto(memoryview(compressed)[:min(_CHUNK, end - position)])
                    if not count:
                        raise ValueError("a .ncz inside it is cut short")
                    position += count
                    source.size, source.pos = count, 0
                    # Read into memory, so that much of the file can go.
                    release.upto(position)
                elif not full:
                    # Nothing left to read, and the last call did not fill
                    # the buffer, so zstd has nothing held back either.
                    break
            target.pos = 0
            result = zstd.ZSTD_decompressStream(stream, ctypes.byref(target), ctypes.byref(source))
            if zstd.ZSTD_isError(result):
                raise ValueError("zstd: %s" % zstd.ZSTD_getErrorName(result).decode())
            if target.pos:
                sink.feed(plain, plain_address, target.pos)
            full = target.pos == target.size
    finally:
        zstd.ZSTD_freeDStream(stream)


def _blocks(zstd, handle, position, end, blocks, sink, release):
    exponent, sizes, remaining = blocks
    block = 1 << exponent
    stored_data, stored_address = _buffer(block)
    plain, plain_address = _buffer(block)
    for stored in sizes:
        expect = min(block, remaining)
        if stored > block or position + stored > end:
            raise ValueError("a block inside it runs past the end")
        handle.seek(position)
        if handle.readinto(memoryview(stored_data)[:stored]) != stored:
            raise ValueError("a .ncz inside it is cut short")
        position += stored
        # A block that did not get smaller is kept as it was, as nsz does.
        if stored < expect:
            result = zstd.ZSTD_decompress(plain_address, block, stored_address, stored)
            if zstd.ZSTD_isError(result) or result != expect:
                raise ValueError("a block inside it did not decompress")
            sink.feed(plain, plain_address, expect)
        else:
            sink.feed(stored_data, stored_address, expect)
        remaining -= expect
        release.upto(position)


def _nca(libraries, handle, name, offset, size, layout, writer, release):
    zstd, crypto, _libc = libraries
    sections, body, blocks, nca_size = layout
    digest = hashlib.sha256()
    header = _read_at(handle, offset, _NCA_HEADER)
    if len(header) != _NCA_HEADER:
        raise ValueError("%s ends inside its header" % name)
    digest.update(header)
    writer.write(memoryview(header))
    sink = _Sections(crypto, sections, writer, digest)
    try:
        if blocks is None:
            _solid(zstd, handle, body, offset + size, sink, release)
        else:
            _blocks(zstd, handle, body, offset + size, blocks, sink, release)
    finally:
        sink.close()
    if sink.position != nca_size:
        raise ValueError("%s came out %d bytes short" % (name, nca_size - sink.position))
    stem = name[:-4].lower()
    # Every tool names these after the hash. One that did not cannot be checked,
    # which is not a reason to refuse it.
    if _HASH_NAME.match(stem) and digest.hexdigest()[:32] != stem:
        raise ValueError("%s did not come out as the file it was made from" % name)


def _write(path, temporary, total, release_source, progress, state):
    libraries = _load()
    with open(path, "r+b" if release_source else "rb", buffering=0) as handle:
        files, layouts, entries = _planned(handle)
        if release_source and any(files[i][1] > files[i + 1][1] for i in range(len(files) - 1)):
            # Releasing assumes the data is read front to back. Out of order,
            # the front could still be needed after it had gone.
            raise ValueError("its contents are out of order, so it cannot be unpacked "
                             "in the space there is")
        release = _Release(libraries[2], handle, release_source)
        state["release"] = release
        with open(temporary, "wb", buffering=0) as out:
            writer = _Writer(out, total, progress)
            writer.write(memoryview(_header(entries)))
            for name, offset, size in files:
                if name in layouts:
                    _nca(libraries, handle, name, offset, size, layouts[name], writer, release)
                else:
                    handle.seek(offset)
                    left = size
                    while left:
                        data = handle.read(min(_CHUNK, left))
                        if not data:
                            raise ValueError("%s is cut short" % name)
                        writer.write(memoryview(data))
                        left -= len(data)
                release.upto(offset + size)
            if writer.written != total:
                raise ValueError("wrote %d bytes of %d" % (writer.written, total))
            os.fsync(out.fileno())


def _releasable(path, destination):
    """Whether freeing the source as it is read would make room in `destination`."""
    try:
        if os.stat(path).st_dev != os.stat(destination).st_dev:
            return False
        real = os.path.realpath(path)
        best, kind = "", ""
        with open("/proc/self/mounts", encoding="utf-8") as mounts:
            for line in mounts:
                fields = line.split()
                if len(fields) < 3:
                    continue
                point = fields[1].replace("\\040", " ")
                inside = real == point or real.startswith(point.rstrip("/") + "/")
                if inside and len(point) > len(best):
                    best, kind = point, fields[2]
        return kind in _RELEASABLE
    except OSError:
        return False


def into_folder(path, destination, progress=None, name=None, use_up=True):
    """Unpack the .nsz at `path` into `destination`. Returns (names, error).

    All or nothing, like `unpack.into_folder`: written under a temporary name
    and renamed only once every NCA has checked out. Deleting the `.nsz` is the
    caller's, as deleting the zip is. `progress(written, total)` is called from
    this thread every so often.

    `name` is what the `.nsp` is called, the `.nsz`'s own stem by default.
    `use_up` says the `.nsz` is the plugin's to spend when that is the only way
    the `.nsp` fits -- true for the transfer folder, never for a file somebody
    keeps anywhere else.
    """
    try:
        _load()
    except Unavailable as missing:
        return [], ("Unpacking an .nsz needs libzstd and libcrypto, and this "
                    "system does not have them (%s)." % missing)

    planned, total, error = plan(path)
    if error:
        return [], error
    name = name or planned
    target = os.path.join(destination, name)
    if os.path.exists(target):
        return [], ("%s is already there. Delete it first, or the unpacked copy "
                    "would replace it." % name)

    source_size = os.path.getsize(path)
    try:
        free = shutil.disk_usage(destination).free
    except OSError:
        # Not knowing is not a reason to refuse, as in `unpack`.
        free = None
    release_source = False
    if free is not None and total + _SPACE_MARGIN > free:
        releasable = use_up and _releasable(path, destination)
        needed = total - source_size if releasable else total
        if not releasable or total + _SPACE_MARGIN > free + source_size:
            return [], ("There is not enough room: unpacking this needs %.1f GB "
                        "and %.1f GB is free." % (max(needed, 0) / 1e9, free / 1e9))
        release_source = True

    temporary = target + _PARTIAL
    state: dict = {}
    try:
        _write(path, temporary, total, release_source, progress, state)
        os.replace(temporary, target)
    except (OSError, ValueError, RuntimeError, struct.error) as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        decky.logger.warning("Could not unpack %s: %s", path, error)
        release = state.get("release")
        if release is not None and release.done:
            return [], ("Could not unpack this .nsz: %s. There was only room by "
                        "using it up as it went, so it has to be sent again." % error)
        return [], "Could not unpack this .nsz: %s." % error

    decky.logger.info("Unpacked %s into %s (%d bytes%s)", os.path.basename(path), name, total,
                      ", freeing the source as it went" if release_source else "")
    return [name], ""
