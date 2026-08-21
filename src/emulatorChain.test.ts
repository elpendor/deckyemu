import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Installing the emulator a package needs, then unpacking the package.
 *
 * The whole of what this file is defending is that **the panel is not there for
 * most of it**. Installing an emulator takes half a minute and launches it
 * headless in gamescope, so Quick Access is unmounted for nearly all of the
 * wait — and the completion arrives as an event, not as a promise resolving.
 * The first version subscribed inside the panel's own effect, which meant the
 * event fired into nothing: shadPS4 installed, the unpack never followed, and
 * the package it was installed for was still sitting in the transfer folder.
 * The flag survived the unmount because it lives in the draft; the listener did
 * not, because it lived in the component.
 *
 * So these run the whole chain with no component anywhere, which is the
 * condition the device version failed under.
 *
 * `./backend` and `@decky/api` are mocked because neither loads under Node.
 * `./romDraft` is real — the draft is half of what is being checked.
 */

type Handler = (...args: any[]) => void;
const listeners: Record<string, Handler[]> = {};

const installEmulator = vi.fn(async (..._args: unknown[]) => ({ ok: true }));
const installPs4Package = vi.fn(async (..._args: unknown[]) => ({
  ok: true,
  title_id: "CUSA07010",
  title: "Sonic Mania Plus",
}));
const probeRom = vi.fn();
const toast = vi.fn();

vi.mock("@decky/api", () => ({
  toaster: { toast: (...args: unknown[]) => toast(...args) },
  addEventListener: (name: string, fn: Handler) => {
    (listeners[name] ||= []).push(fn);
    return fn;
  },
  removeEventListener: (name: string, fn: Handler) => {
    listeners[name] = (listeners[name] || []).filter((item) => item !== fn);
  },
}));

vi.mock("./backend", () => ({
  installEmulator: (...args: unknown[]) => installEmulator(...args),
  installPs3Package: vi.fn(),
  installPs4Package: (...args: unknown[]) => installPs4Package(...args),
  installVitaPackage: vi.fn(),
  probeRom: (...args: unknown[]) => probeRom(...args),
  resolveGame: vi.fn(),
  setSettings: vi.fn(),
  suggestCoresForExtension: vi.fn(),
  listInstalledPs3Games: vi.fn(),
  listInstalledPs4Games: vi.fn(async () => ({
    games: [{ title_id: "CUSA07010", title: "Sonic Mania Plus", eboot: "/games/eboot.bin" }],
  })),
  listInstalledVitaGames: vi.fn(),
  ps3CoreId: vi.fn(),
  ps4CoreId: vi.fn(async () => ({ ok: true, core_id: "emu:shadps4" })),
  vitaCoreId: vi.fn(),
}));

const { installEmulatorAndUnpack, continueAfterEmulator } = await import("./addFlow");
const { getDraft, resetDraft, updateDraft } = await import("./romDraft");

const emit = (name: string, ...args: unknown[]) => {
  for (const fn of [...(listeners[name] || [])]) fn(...args);
};

/** A probe answer for the package, with the emulator present or not. */
const packageProbe = (ready: boolean) => ({
  extension: "pkg",
  matching_cores: [],
  ps4_package: {
    emulator_id: "shadps4",
    emulator_name: "shadPS4",
    emulator_ready: ready,
    needs_firmware: false,
    title_id: "CUSA07010",
    installed: false,
    title: "",
    eboot: "",
  },
});

const settle = async () => {
  for (let i = 0; i < 40; i += 1) await Promise.resolve();
};

beforeEach(() => {
  for (const key of Object.keys(listeners)) delete listeners[key];
  for (const spy of [installEmulator, installPs4Package, probeRom, toast]) spy.mockClear();
  installEmulator.mockResolvedValue({ ok: true });
  probeRom.mockResolvedValue(packageProbe(true) as never);
  resetDraft();
  updateDraft({ romPath: "/transfer/sonic.pkg" });
});

afterEach(() => {
  resetDraft();
});

describe("installing the emulator a package needs", () => {
  it("subscribes before the install starts, so nothing can be missed", async () => {
    // The event can arrive at any point after the call. Subscribing afterwards
    // is a race this cannot afford, because the loser is a package that never
    // unpacks.
    void installEmulatorAndUnpack("shadps4");
    await settle();
    expect(listeners["emulator_install_done"]?.length).toBe(1);
    expect(installEmulator).toHaveBeenCalledWith("shadps4");
  });

  it("marks the install in the draft, which is what survives the unmount", async () => {
    void installEmulatorAndUnpack("shadps4");
    await settle();
    expect(getDraft().installingEmulator).toBe("shadps4");
  });

  it("moves the bar from the install's own events", async () => {
    void installEmulatorAndUnpack("shadps4");
    await settle();
    emit("emulator_install_progress", "shadps4", "Downloading", 40);
    expect(getDraft().emulatorPercent).toBe(40);
    expect(getDraft().emulatorStatus).toBe("Downloading");
  });

  it("carries on into the unpack when the install finishes", async () => {
    // The case that failed on the device: no component exists here at all, and
    // it still has to happen.
    void installEmulatorAndUnpack("shadps4");
    await settle();
    emit("emulator_install_done", "shadps4", true, "");
    await settle();
    expect(installPs4Package).toHaveBeenCalledWith("/transfer/sonic.pkg");
    expect(getDraft().installingEmulator).toBe("");
  });

  it("ignores an install of some other emulator", async () => {
    // The Emulators tab emits the same events. One started there must not drive
    // this bar or unpack a package nobody asked about.
    void installEmulatorAndUnpack("shadps4");
    await settle();
    emit("emulator_install_progress", "rpcs3", "Downloading", 90);
    emit("emulator_install_done", "rpcs3", true, "");
    await settle();
    expect(getDraft().emulatorPercent).toBe(0);
    expect(getDraft().installingEmulator).toBe("shadps4");
    expect(installPs4Package).not.toHaveBeenCalled();
  });

  it("says so and unpacks nothing when the install fails", async () => {
    void installEmulatorAndUnpack("shadps4");
    await settle();
    emit("emulator_install_done", "shadps4", false, "No space left");
    await settle();
    expect(getDraft().error).toBe("No space left");
    expect(getDraft().installingEmulator).toBe("");
    expect(installPs4Package).not.toHaveBeenCalled();
  });

  it("stops listening once it is done, so a later install is not ours", async () => {
    void installEmulatorAndUnpack("shadps4");
    await settle();
    emit("emulator_install_done", "shadps4", true, "");
    await settle();
    expect(listeners["emulator_install_done"]?.length ?? 0).toBe(0);
  });

  it("clears the flag when the install will not even start", async () => {
    installEmulator.mockResolvedValue({ ok: false, error: "No network" } as never);
    await installEmulatorAndUnpack("shadps4");
    await settle();
    expect(getDraft().installingEmulator).toBe("");
    expect(getDraft().error).toBe("No network");
    expect(listeners["emulator_install_done"]?.length ?? 0).toBe(0);
  });
});

describe("picking up an install nobody heard finish", () => {
  it("unpacks once the emulator turns out to be there", async () => {
    // The recovery path: the plugin reloaded mid-install, so even the module
    // scope listener went. The panel asks on its next mount.
    expect(await continueAfterEmulator()).toBe(true);
    await settle();
    expect(installPs4Package).toHaveBeenCalledWith("/transfer/sonic.pkg");
  });

  it("does nothing while the emulator is still missing", async () => {
    // An install that is genuinely still running, or one that failed. Either
    // way this must not start an unpack that will be refused.
    probeRom.mockResolvedValue(packageProbe(false) as never);
    expect(await continueAfterEmulator()).toBe(false);
    expect(installPs4Package).not.toHaveBeenCalled();
  });

  it("does nothing when there is no ROM to be about", async () => {
    resetDraft();
    expect(await continueAfterEmulator()).toBe(false);
    expect(probeRom).not.toHaveBeenCalled();
  });
});
