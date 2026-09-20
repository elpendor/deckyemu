"""The small icon Steam shows for a game this plugin added.

A non-Steam shortcut with no icon gets a blank square in the library list, which
is how every game added here looked. Steam takes the icon as a *path* in
`shortcuts.vdf` and reads it from there afterwards, so a file has to exist and
keep existing -- which is why an icon is written to disk rather than handed over
as image data the way the capsule and hero are.

Two sources. SteamGridDB publishes icons, and one arrives through the ordinary
artwork lookup as the `icon` slot; that gets written under the game's own app
id. When there is none, every game falls back to the picture shipped in
`assets/`, which says the game came from here rather than which game it is.
"""

import base64
import os

import decky

import sysenv

NAME = "game-icon.png"

#: What a game's own icon may be, by the bytes it starts with.
#:
#: `.ico` because SteamGridDB publishes plenty of games with nothing else --
#: Adventures of Lolo 2 has two and no PNG -- and Steam reads one, that being
#: the format a Windows shortcut icon has always been. The extension follows
#: the bytes rather than the URL, because the name in `shortcuts.vdf` is all
#: any later reader has to go on.
KINDS = (
    (".png", b"\x89PNG\r\n\x1a\n"),
    (".ico", b"\x00\x00\x01\x00"),
)


def generic():
    """The shipped icon's path, or "" if it did not ship.

    Empty rather than a guess: the caller hands this to Steam, which records it,
    so a path to a file that is not there would be written into `shortcuts.vdf`
    and stay wrong after the file appeared.
    """
    plugin_dir = getattr(decky, "DECKY_PLUGIN_DIR", "") or ""
    if not plugin_dir:
        return ""
    icon = os.path.join(plugin_dir, "assets", NAME)
    return icon if os.path.isfile(icon) else ""


def _own_path(app_id, suffix=".png", create=True):
    if not str(app_id or "").isdigit():
        return ""
    directory = sysenv.user_dir("icons", create=create)
    return os.path.join(directory, "%s%s" % (app_id, suffix)) if directory else ""


def _own_paths(app_id, create=False):
    """Every name this game's own icon could have."""
    return [path for path in
            (_own_path(app_id, suffix, create) for suffix, _magic in KINDS) if path]


def _kind_of(payload):
    """The extension for these bytes, or "" if they are not an icon we know."""
    for suffix, magic in KINDS:
        if payload.startswith(magic):
            return suffix
    return ""


def _clear_own(app_id):
    """Remove whatever this game's own icon currently is."""
    for path in _own_paths(app_id):
        try:
            os.remove(path)
        except OSError:
            pass


#: The data URIs an icon may arrive as: PNG, and both spellings of `.ico`.
#:
#: JPEG stays refused. Steam would show one, but the name written into
#: `shortcuts.vdf` has to say what the file holds, and `KINDS` has no JPEG.
_ICON_URIS = (
    "data:image/png",
    "data:image/vnd.microsoft.icon",
    "data:image/x-icon",
)


def _bytes_of(data_uri):
    """The bytes inside a `data:image/png;base64,...` URI, or b"".

    `.ico` as well as PNG, because SteamGridDB publishes games that have
    nothing else -- refusing them here is what left those games on the plain
    tile. `save` below checks the bytes themselves, so a URI claiming one thing
    and holding another is caught there rather than written under the wrong
    name.
    """
    text = str(data_uri or "")
    marker = ";base64,"
    if not text.startswith(_ICON_URIS) or marker not in text:
        return b""
    try:
        return base64.b64decode(text.split(marker, 1)[1], validate=True)
    except (ValueError, TypeError):
        return b""


def _png_inside_ico(payload):
    """The largest PNG an `.ico` carries, or b"" if it carries none.

    **Steam draws an `.ico` as nothing at all in Game Mode.** Written, recorded
    in `shortcuts.vdf`, read back by the path it was given -- and the tile is
    blank, where the same game's PNG showed. Measured with Diablo through
    DevilutionX on 2026-09-19.

    An `.ico` is a directory of images, and since Vista the big ones are
    ordinarily PNG already -- that file holds three, up to 256 square. So the
    one Steam can draw is usually inside the one it cannot, and unwrapping it
    needs no decoding and no dependency. An icon that is every-entry BMP still
    lands as `.ico`, which is no worse than before.
    """
    if not payload.startswith(b"\x00\x00\x01\x00") or len(payload) < 6:
        return b""
    count = int.from_bytes(payload[4:6], "little")
    best = b""
    for index in range(count):
        entry = 6 + index * 16
        if entry + 16 > len(payload):
            break
        size = int.from_bytes(payload[entry + 8:entry + 12], "little")
        offset = int.from_bytes(payload[entry + 12:entry + 16], "little")
        image = payload[offset:offset + size]
        if image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) > len(best):
            best = image
    return best


def save(app_id, payload):
    """Write `payload` as this game's own icon. Returns the path, or "".

    Named for what the bytes are rather than for where they came from, and the
    old icon goes first: a game that had a `.png` and now has an `.ico` would
    otherwise keep both, and `has_own` would go on finding the stale one.
    """
    payload = _png_inside_ico(payload or b"") or payload
    suffix = _kind_of(payload or b"")
    path = _own_path(app_id, suffix) if suffix else ""
    if not path:
        return ""
    _clear_own(app_id)
    try:
        with open(path, "wb") as handle:
            handle.write(payload)
    except OSError as error:
        decky.logger.warning("Could not write the icon for %s: %s", app_id, error)
        return ""
    return path


def for_game(app_id, data_uri=""):
    """Where this game's icon is, writing the artwork one if there is any.

    With nothing to write this answers with the icon the game *already* has --
    its own when it has one, the shipped picture otherwise. That matters more
    than it looks: the startup repair asks with nothing, and answering "generic"
    for a game holding a real icon is how it came to overwrite them.

    Falls back to the shipped icon whenever the write fails too. A generic icon
    beats a blank square, and both beat a path to a file that is not there.
    """
    written = save(app_id, _bytes_of(data_uri))
    if written:
        return written
    for path in _own_paths(app_id):
        if os.path.isfile(path):
            return path
    return generic()


def has_own(app_id):
    """Whether this game has an icon of its own rather than the shipped one."""
    return any(os.path.isfile(path) for path in _own_paths(app_id))


def forget(app_id):
    """Delete a game's own icon, if it had one. True if anything went."""
    had = has_own(app_id)
    _clear_own(app_id)
    return had and not has_own(app_id)
