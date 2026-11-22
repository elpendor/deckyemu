"""Add games, end to end on the Deck: the review and Add, with no dialog open.

Run on the Deck against a development build (scripts/deploy.sh), which puts
the batch store on `window.__deckyemu.batchTest`:

    python3 batch_e2e.py [--offline] [--no-retroarch]

The two flags are opt-in because each disturbs the Deck for a while: one cuts
DeckyEmu's own network (and nothing else's), the other uninstalls RetroArch
and installs the same build again. Both put everything back.

Every file it uses is made here, with made-up names, in the transfer folder,
beside whatever the user has there and never touching it. Games it adds are
taken back out of Steam and the library, and every file it made is deleted,
even when a check fails. It installs one RetroArch core if that core is
missing, and removes it again afterwards.
"""

import glob
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
import zipfile

_found = sorted(glob.glob(os.path.expanduser("~/.local/share/deckyemu/app/*/py_modules")))
if not _found:
    raise SystemExit("the DeckyEmu service is not installed; its CDP client is needed")
sys.path.insert(0, _found[-1])
import cdp  # noqa: E402

HOME = os.path.expanduser("~")
INBOX = os.path.join(HOME, "deckyemu", "transfer")
ROMS = os.path.join(HOME, "deckyemu", "roms")
CORES = os.path.join(HOME, ".var/app/org.libretro.RetroArch/config/retroarch/cores")
# Virtual Boy: no core this Deck has runs it, so adding one installs a core.
SWAN_CORE = os.path.join(CORES, "mednafen_vb_libretro.so")

SWITCH = "E2E Switch Game"
NAMES = {
    "dup": None,  # a copy of a game already in the library; named below
    "unknown": "Zzyzx Test Cart (USA).gba",
    "vanish": "Zzyzx Vanishing Cart (USA).gba",
    "broken": "E2E Broken Disc (USA).cue",
    "patch": "E2E Hack.ips",
    "bios": "scph5501.bin",
    "definition": "e2e-test.deckyemu.json",
    "save": "E2E Saves.zip",
    "wud": "E2E Wii U Disc (USA).wud",
    "base": "%s [01009E2E00000000][v0].nsp" % SWITCH,
    "update": "%s [01009E2E00000800][v65536].nsp" % SWITCH,
    "dlc": "%s [01009E2E00001001][v0].nsp" % SWITCH,
    "swan": "Zzyzx Swan Cart (Japan).vb",
    "ps1zip": "E2E PS1 Game (USA).zip",
    "xbla": "E2E Arcade Title.zip",
}

PS2_BIOS = os.path.join(HOME, ".var/app/net.pcsx2.PCSX2/config/PCSX2/bios")
PS2_GAME = "E2E PS2 Game (USA).iso"
HINTS = os.path.join(HOME, ".local/share/deckyemu/data/system-hints.json")

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("%s %-60s %s" % ("PASS" if ok else "FAIL", label, detail if not ok else ""))


def shared():
    for target in cdp.targets():
        if "sharedjscontext" in (target.get("title") or "").lower():
            return cdp.Page(target["webSocketDebuggerUrl"])
    raise SystemExit("SharedJSContext not found")


def js(body, timeout=300):
    """Run `body` as an async function with T bound to the test hook."""
    expression = """(async () => {
      const T = window.__deckyemu && window.__deckyemu.batchTest;
      if (!T) throw new Error("no batch test hook: deploy a development build");
      const rows = () => T.getBatch().rows.map((r) => ({
        name: r.name, path: r.path, title: r.title, bucket: r.verdict.bucket,
        reason: r.verdict.reason, include: r.include, blocked: !!r.verdict.blocked,
        step: r.verdict.step || "", other: r.verdict.other || "", core: r.coreId,
        content: T.contentSummary(r), send: T.sendFor(r), outcome: r.outcome, error: r.error,
        added: r.added.length,
      }));
      const result = await (async () => { %s })();
      return JSON.stringify(result);
    })()""" % body
    return json.loads(shared().evaluate(expression, await_promise=True, timeout=timeout))


def review(names):
    """Start a review of these files, as Add all… would. Returns its rows."""
    return js("""
      T.closeBatch();
      const wanted = %s;
      const files = (await T.transferInputs()).filter((f) => wanted.includes(f.name));
      await T.startBatch(files);
      return { files: files.length, rows: rows(), hidden: [...T.contentWithGames(T.getBatch().rows).keys()] };
    """ % json.dumps(names))


def by_name(rows, name):
    return next((row for row in rows if row["name"] == name), None)


# --- test files --------------------------------------------------------------

def write(name, data):
    with open(os.path.join(INBOX, name), "wb") as handle:
        handle.write(data)


def noise(size):
    return bytes(random.getrandbits(8) for _ in range(size))


def make_files():
    library = json.load(open(os.path.join(HOME, ".local/share/deckyemu/settings/library.json")))
    gba = next((g for g in library.values() if g.get("rom_path", "").startswith(os.path.join(ROMS, "gba"))
                and os.path.isfile(g["rom_path"])), None)
    if gba:
        NAMES["dup"] = os.path.basename(gba["rom_path"])
        shutil.copy(gba["rom_path"], os.path.join(INBOX, NAMES["dup"]))
    write(NAMES["unknown"], noise(256 * 1024))
    write(NAMES["vanish"], noise(256 * 1024))
    write(NAMES["broken"], b'FILE "E2E Broken Disc (USA) (Track 1).bin" BINARY\n'
                           b"  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n")
    write(NAMES["patch"], b"PATCH" + b"\x00\x00\x10\x00\x01\x41" + b"EOF")
    write(NAMES["bios"], noise(512 * 1024))
    write(NAMES["definition"], json.dumps({"id": "e2e-test", "definitions": []}).encode())
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": 2, "emulators": {"ppsspp": "PPSSPP"}}))
        archive.writestr("saves/ppsspp/SAVEDATA/ZZYZX00001/DATA.BIN", b"save")
    write(NAMES["save"], bundle.getvalue())
    write(NAMES["wud"], noise(1024 * 1024))
    for key in ("base", "update", "dlc"):
        write(NAMES[key], noise(64 * 1024))
    write(NAMES["swan"], noise(128 * 1024))
    disc = io.BytesIO()
    stem = "E2E PS1 Game (USA)"
    with zipfile.ZipFile(disc, "w") as archive:
        archive.writestr(stem + ".cue", 'FILE "%s.bin" BINARY\n  TRACK 01 MODE2/2352\n'
                         "    INDEX 01 00:00:00\n" % stem)
        archive.writestr(stem + ".bin", bytes(2352 * 32))
    write(NAMES["ps1zip"], disc.getvalue())
    # An Xbox 360 content package: what is inside is told by its header alone.
    xbla = io.BytesIO()
    with zipfile.ZipFile(xbla, "w") as archive:
        archive.writestr("E2E Arcade Title", b"LIVE" + noise(4096))
    write(NAMES["xbla"], xbla.getvalue())


def made_by_us(name):
    return (name.startswith(("E2E ", "Zzyzx ")) or name in (NAMES["bios"], NAMES["definition"])
            or (NAMES["dup"] and name.startswith(os.path.splitext(NAMES["dup"])[0])))


def clean_files():
    gone = 0
    for folder in [INBOX] + glob.glob(os.path.join(ROMS, "*")):
        for path in glob.glob(os.path.join(folder, "*")):
            name = os.path.basename(path)
            # The library's copy of the duplicate stays; only the inbox's goes.
            if folder != INBOX and NAMES["dup"] and name == NAMES["dup"]:
                continue
            if made_by_us(name) and os.path.isfile(path):
                os.remove(path)
                gone += 1
    return gone


# --- scenarios ---------------------------------------------------------------

def the_review():
    names = [name for name in NAMES.values() if name]
    got = review(names)
    rows, hidden = got["rows"], got["hidden"]
    check("every test file reaches the review", got["files"] == len(names), "%d of %d" % (got["files"], len(names)))

    if NAMES["dup"]:
        dup = by_name(rows, NAMES["dup"])
        check("a game already in the library is not ticked",
              dup and not dup["include"] and "Already in your library" in dup["reason"], dup)
    unknown = by_name(rows, NAMES["unknown"])
    check("a game nothing recognises is under Check these, ticked",
          unknown and unknown["bucket"] == "check" and unknown["include"], unknown)
    broken = by_name(rows, NAMES["broken"])
    check("a sheet whose track is missing is not ticked", broken and not broken["include"], broken)
    for key, kind in (("patch", "patch"), ("bios", "firmware"), ("definition", "definition"), ("save", "save")):
        row = by_name(rows, NAMES[key])
        check("a %s is under Other files" % kind, row and row["bucket"] == "other" and row["other"] == kind, row)
    wud = by_name(rows, NAMES["wud"])
    keys = os.path.join(HOME, ".var/app/info.cemu.Cemu/data/Cemu/keys.txt")
    real_keys = os.path.isfile(keys) and any(
        line.strip() and not line.startswith("#") for line in open(keys, errors="replace"))
    if real_keys:
        check("a .wud with Cemu's keys in place has no warning",
              wud and not wud["blocked"] and "keys.txt" not in wud["reason"], wud)
    else:
        check("a .wud without Cemu's keys warns but can be ticked",
              wud and not wud["blocked"] and "keys.txt" in wud["reason"], wud)
    base = by_name(rows, NAMES["base"])
    check("a Switch game counts the update and DLC sent with it",
          base and base["content"] == "+ 1 update · 1 DLC", base)
    check("and they are not listed again under Other files",
          NAMES["update"] in hidden and NAMES["dlc"] in hidden, hidden)
    swan = by_name(rows, NAMES["swan"])
    had_core = os.path.isfile(SWAN_CORE)
    check("a file whose core is missing says Add installs it",
          swan and (swan["step"] == "core" if not had_core else swan["core"]), swan)
    ps1 = by_name(rows, NAMES["ps1zip"])
    check("a zipped disc unpacks first", ps1 and ps1["step"] == "unpack", ps1)
    xbla = by_name(rows, NAMES["xbla"])
    check("a zipped Xbox 360 package unpacks first", xbla and xbla["step"] == "unpack", xbla)
    return rows


def unpacking():
    got = review([NAMES["ps1zip"]] + ([NAMES["dup"]] if NAMES["dup"] else []))
    zip_path = by_name(got["rows"], NAMES["ps1zip"])["path"]
    out = js("return { paths: await T.unpackRow(%s), rows: rows() };" % json.dumps(zip_path))
    cue = next((row for row in out["rows"] if row["name"].endswith(".cue")), None)
    check("a zipped disc unpacks to its sheet, which a PS1 core runs",
          cue and cue["core"] and not cue["step"], out["rows"])
    xbla = review([NAMES["xbla"]])["rows"][0]["path"]
    out = js("return { paths: await T.unpackRow(%s), rows: rows() };" % json.dumps(xbla))
    package = next((row for row in out["rows"] if row["name"] == "E2E Arcade Title"), None)
    xenia = any(os.path.isdir(p) for p in glob.glob(os.path.join(HOME, "deckyemu/emulators/xenia*")))
    check("an unpacked Xbox 360 package says what runs it, or that nothing does",
          package and (package["core"] if xenia else package["bucket"] == "cant"), out["rows"])
    if NAMES["dup"]:
        got = review([NAMES["dup"]])
        dup_path = by_name(got["rows"], NAMES["dup"])["path"]
        out = js("return { paths: await T.unpackRow(%s), rows: rows() };" % json.dumps(dup_path))
        gba = next((row for row in out["rows"] if row["name"].endswith(".gba")), None)
        check("Unpack instead takes a playable zip apart", gba is not None, out["rows"])


def adding():
    had_core = os.path.isfile(SWAN_CORE)
    names = [NAMES["unknown"], NAMES["vanish"], NAMES["swan"]]
    got = review(names)
    check("three games to add are in the review", len(got["rows"]) == 3, got["rows"])
    # Gone between the review and Add: the stand-in for a failure mid-batch.
    os.remove(os.path.join(INBOX, NAMES["vanish"]))
    started = time.time()
    out = js("""
      for (const r of T.getBatch().rows) T.setIncluded(r.path, true);
      await T.addBatch();
      return { phase: T.getBatch().phase, rows: rows() };
    """, timeout=600)
    rows = out["rows"]
    check("Add runs to the end with no dialog open", out["phase"] == "done", out["phase"])
    unknown = by_name(rows, NAMES["unknown"])
    check("the game that was there is added", unknown and unknown["outcome"] == "added", unknown)
    vanish = by_name(rows, NAMES["vanish"])
    check("the one that went missing is listed as not added, with why",
          vanish and vanish["outcome"] == "failed" and vanish["error"], vanish)
    swan = next((row for row in rows if row["name"].startswith("Zzyzx Swan")), None)
    check("the one needing a core gets it installed, then is added",
          swan and swan["outcome"] == "added" and os.path.isfile(SWAN_CORE), swan)
    print("     (adding took %.0f s)" % (time.time() - started))
    taken = js("return await T.takeBack();")
    library = json.load(open(os.path.join(HOME, ".local/share/deckyemu/settings/library.json")))
    left = [g["title"] for g in library.values() if "Zzyzx" in g.get("rom_path", "")]
    check("taking them back leaves nothing in the library", taken >= 1 and not left, left)
    if not had_core:
        # Through the plugin, so its list of cores forgets it too: deleting
        # the files behind its back left the next run seeing a core not there.
        removed = js("return await T.uninstallCore('mednafen_vb');")
        check("the core it installed is removed again",
              removed.get("ok") and not os.path.isfile(SWAN_CORE), removed)


def bios_missing():
    """A PS2 game while PCSX2 has no BIOS: it warns, and can still be ticked. The BIOS is
    moved aside for the check and always put back."""
    if not os.path.isdir(PS2_BIOS):
        print("     (skipped: PCSX2 has no BIOS folder)")
        return
    aside = PS2_BIOS + ".e2e-aside"
    kept = sorted(os.listdir(PS2_BIOS))
    write(PS2_GAME, noise(1024 * 1024))
    game = os.path.realpath(os.path.join(INBOX, PS2_GAME))
    hints = json.load(open(HINTS)) if os.path.isfile(HINTS) else {}
    # What an upload with "PlayStation 2" picked on the page records.
    json.dump(dict(hints, **{game: "Sony - PlayStation 2"}), open(HINTS, "w"))
    try:
        os.rename(PS2_BIOS, aside)
        os.makedirs(PS2_BIOS)
        try:
            row = review([PS2_GAME])["rows"][0]
            check("a PS2 game without PCSX2's BIOS warns, and can be ticked",
                  not row["blocked"] and row["include"] and "BIOS" in row["reason"]
                  and row["core"] == "emu:pcsx2", row)
        finally:
            os.rmdir(PS2_BIOS)
            os.rename(aside, PS2_BIOS)
            restored = sorted(os.listdir(PS2_BIOS)) == kept
            print("     PCSX2's BIOS folder %s" % ("restored, every file back" if restored else "NOT RESTORED"))
            check("PCSX2's BIOS is back as it was", restored)
        row = review([PS2_GAME])["rows"][0]
        check("and with the BIOS back the warning is gone",
              not row["blocked"] and "not found" not in row["reason"] and row["core"] == "emu:pcsx2", row)
    finally:
        hints = json.load(open(HINTS)) if os.path.isfile(HINTS) else {}
        hints.pop(game, None)
        json.dump(hints, open(HINTS, "w"))


def picking():
    """A file nothing claims waits for an emulator from the pencil, then adds."""
    name = "E2E Odd Thing.qqq"
    write(name, noise(64 * 1024))
    row = review([name])["rows"][0]
    check("a file nothing claims waits for an emulator to be picked",
          row["bucket"] == "check" and row["blocked"] and "pencil" in row["reason"], row)
    out = js("""
      const row = T.getBatch().rows[0];
      const core = row.probe.all_cores.find((c) => c.id.startsWith("emu:")) || row.probe.all_cores[0];
      await T.setRowCore(row.path, core.id);
      const picked = rows()[0];
      await T.addBatch();
      return { picked, core: core.id, rows: rows() };
    """, timeout=300)
    check("picking one makes it addable", not out["picked"]["blocked"] and out["picked"]["include"], out["picked"])
    check("and Add adds it with that emulator",
          out["rows"][0]["outcome"] == "added" and out["rows"][0]["core"] == out["core"], out["rows"])
    check("taking it back works", js("return await T.takeBack();") == 1)


def one_disc():
    """Two discs of one game, and only the first wanted: one entry, no playlist."""
    discs = ["E2E Two Disc Game (USA) (Disc %d).iso" % n for n in (1, 2)]
    hints = json.load(open(HINTS)) if os.path.isfile(HINTS) else {}
    for disc in discs:
        write(disc, noise(1024 * 1024))
        hints[os.path.realpath(os.path.join(INBOX, disc))] = "Sony - PlayStation 2"
    json.dump(hints, open(HINTS, "w"))
    got = review(discs)
    check("two discs of one game are one row", len(got["rows"]) == 1, got["rows"])
    out = js("""
      const row = T.getBatch().rows[0];
      T.setDiscMode(row.path, "single");
      T.setIncluded(row.path, true);
      const plan = T.discPlan(T.getBatch().rows[0]);
      await T.addBatch();
      return { plan, rows: rows() };
    """, timeout=300)
    added = out["rows"][0]
    check("This disc only adds one entry", out["plan"] == "single"
          and added["outcome"] == "added" and added["added"] == 1, out)
    check("and the other disc stays in the transfer folder",
          os.path.isfile(os.path.join(INBOX, discs[1])))
    check("taking it back works", js("return await T.takeBack();") == 1)


# --- the disruptive ones: opt-in, and each puts everything back ------------

SERVICE = "deckyemu.service"
DROPIN = os.path.join(HOME, ".config/systemd/user/%s.d/e2e-offline.conf" % SERVICE)
RA = "org.libretro.RetroArch"


def sh(*argv):
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def restart_backend():
    """Restart DeckyEmu's service and wait until the panel reaches it again."""
    sh("systemctl", "--user", "daemon-reload")
    sh("systemctl", "--user", "restart", SERVICE)
    for _ in range(60):
        time.sleep(1)
        try:
            js("await T.transferInputs(); return 0;", timeout=10)
            return
        except Exception:  # noqa: BLE001 -- not answering yet
            continue
    raise RuntimeError("DeckyEmu did not come back after a restart")


def service_env():
    pid = sh("systemctl", "--user", "show", "-p", "MainPID", "--value", SERVICE).stdout.strip()
    try:
        # The launcher's child is the backend; its environment is inherited.
        return open("/proc/%s/environ" % pid, "rb").read().decode(errors="replace")
    except OSError:
        return ""


def offline():
    """No network for DeckyEmu alone: its proxy points at a closed port, so
    every lookup fails as it would offline, while Steam and SSH carry on."""
    name = "Zzyzx Offline Cart (USA).gba"
    write(name, noise(256 * 1024))
    os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
    with open(DROPIN, "w") as handle:
        handle.write("[Service]\n"
                     "Environment=HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9\n"
                     "Environment=http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9\n"
                     "Environment=NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1\n")
    try:
        restart_backend()
        check("DeckyEmu's service has no network", "HTTPS_PROXY=http://127.0.0.1:9" in service_env())
        started = time.time()
        row = review([name])["rows"][0]
        took = time.time() - started
        check("offline, the review still finishes, quickly", took < 60, "%.0f s" % took)
        check("and the game is still ticked, its lookup said to have failed",
              row["include"] and row["reason"] in ("Lookup failed", "Not recognised"), row)
        out = js("await T.addBatch(); return rows();", timeout=300)
        check("offline, Add still adds it", out[0]["outcome"] == "added", out[0])
        check("and taking it back works too", js("return await T.takeBack();") == 1)
    finally:
        if os.path.isfile(DROPIN):
            os.remove(DROPIN)
        restart_backend()
        check("the network is back for DeckyEmu", "127.0.0.1:9" not in service_env())


def flatpak_commit():
    info = sh("flatpak", "info", "--user", RA).stdout
    return next((line.split(":", 1)[1].strip() for line in info.splitlines()
                 if line.strip().startswith("Commit:")), "")


def no_retroarch():
    """RetroArch uninstalled (its data kept): a game it would run is blocked.
    The same build is installed again afterwards."""
    commit = flatpak_commit()
    if not commit:
        print("     (skipped: RetroArch is not a user flatpak here)")
        return
    name = "Zzyzx NoRA Cart (USA).gba"
    write(name, noise(256 * 1024))
    try:
        gone = sh("flatpak", "uninstall", "--user", "-y", "--noninteractive", RA)
        check("RetroArch uninstalled, its data kept", gone.returncode == 0
              and os.path.isdir(os.path.join(HOME, ".var/app", RA)), gone.stderr[-300:])
        restart_backend()
        row = review([name])["rows"][0]
        check("without RetroArch, a game it would run cannot be ticked",
              row["blocked"] and "RetroArch" in row["reason"], row)
    finally:
        if not flatpak_commit():
            back = sh("flatpak", "install", "--user", "-y", "--noninteractive", "flathub", RA)
            if back.returncode:
                print("     reinstall failed: %s" % back.stderr[-400:])
        if flatpak_commit() != commit:
            sh("flatpak", "update", "--user", "-y", "--noninteractive", "--commit=" + commit, RA)
        check("RetroArch is back, the same build as before", flatpak_commit() == commit, flatpak_commit())
        restart_backend()
    row = review([name])["rows"][0]
    check("and with it back the game can be ticked", not row["blocked"] and row["core"], row)


def main():
    random.seed(7)
    disruptive = set(sys.argv[1:])
    os.makedirs(INBOX, exist_ok=True)
    before = set(os.listdir(INBOX))
    try:
        make_files()
        print("== the review: every kind of file at once")
        the_review()
        print("== unpacking")
        unpacking()
        print("== adding, with one that fails and one that needs a core")
        adding()
        print("== a BIOS no game starts without")
        bios_missing()
        print("== a file nothing claims")
        picking()
        print("== one disc of a set")
        one_disc()
        if "--offline" in disruptive:
            print("== no network")
            offline()
        if "--no-retroarch" in disruptive:
            print("== RetroArch uninstalled")
            no_retroarch()
    finally:
        try:
            js("T.closeBatch(); return 0;")
        except Exception as error:  # noqa: BLE001 -- cleanup must go on
            print("could not close the batch: %s" % error)
        removed = clean_files()
        # Taking a game back records its system for a re-add; ours are gone.
        if os.path.isfile(HINTS):
            hints = json.load(open(HINTS))
            json.dump({k: v for k, v in hints.items()
                       if not made_by_us(os.path.basename(k))}, open(HINTS, "w"))
        untouched = before <= set(os.listdir(INBOX))
        print("cleaned up %d test file(s); the user's own files %s"
              % (removed, "untouched" if untouched else "CHANGED"))
    failed = results.count(False)
    print("\n%d passed, %d failed" % (results.count(True), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
