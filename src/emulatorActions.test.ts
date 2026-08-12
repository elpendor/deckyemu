import { describe, expect, it } from "vitest";

import { emulatorRowActions } from "./emulatorActions";
import type { CatalogEmulator } from "./backend";

const entry = (over: Partial<CatalogEmulator> = {}): CatalogEmulator =>
  ({
    id: "x",
    name: "X",
    summary: "",
    note: "",
    kind: "flatpak",
    system: "",
    short: "",
    extensions: [],
    verified: true,
    firmware: [],
    installed: false,
    present: false,
    registered: false,
    scope: "user",
    imported: false,
    source_file: "",
    ...over,
  }) as CatalogEmulator;

describe("emulatorRowActions", () => {
  it("offers install for a catalog emulator that is not there yet", () => {
    const a = emulatorRowActions(entry());
    expect(a.install).toBe(true);
    expect(a.remove).toBe(false);
    expect(a.locate).toBe(false);
    expect(a.forget).toBe(false);
  });

  it("swaps install for remove once it is present", () => {
    const a = emulatorRowActions(entry({ present: true }));
    expect(a.install).toBe(false);
    expect(a.remove).toBe(true);
  });

  // The bug this file exists for. An imported definition that names a source
  // has to be installable: deciding install and forget together made the
  // download button unreachable, and a row with no way to install it says
  // nothing about why.
  it("offers install for an imported definition that names a source", () => {
    const a = emulatorRowActions(entry({ imported: true, kind: "github" }));
    expect(a.install).toBe(true);
    expect(a.forget).toBe(true);
  });

  it("and remove alongside forget once that one is installed", () => {
    const a = emulatorRowActions(entry({ imported: true, kind: "github", present: true }));
    expect(a.remove).toBe(true);
    expect(a.forget).toBe(true);
    expect(a.install).toBe(false);
  });

  // Bring-your-own is the other half: the plugin never obtains the binary, so
  // it must not offer to install it or to take it away.
  it("offers locate, and never install or remove, for bring-your-own", () => {
    const a = emulatorRowActions(entry({ kind: "byo", imported: true }));
    expect(a.locate).toBe(true);
    expect(a.install).toBe(false);
    expect(a.remove).toBe(false);
    expect(a.forget).toBe(true);
  });

  it("still offers locate once one has been located", () => {
    // Replacing the AppImage with a newer build is ordinary, not an error.
    const a = emulatorRowActions(entry({ kind: "byo", present: true }));
    expect(a.locate).toBe(true);
    expect(a.remove).toBe(false);
  });

  it("never offers forget for a bundled entry", () => {
    expect(emulatorRowActions(entry({ present: true })).forget).toBe(false);
  });

  it("offers register only when present but unknown to the plugin", () => {
    expect(emulatorRowActions(entry({ present: true })).register).toBe(true);
    expect(emulatorRowActions(entry({ present: true, registered: true })).register).toBe(false);
    expect(emulatorRowActions(entry()).register).toBe(false);
  });

  it("opens the emulator's own window only when it is registered", () => {
    expect(emulatorRowActions(entry({ present: true, registered: true })).gui).toBe(true);
    expect(emulatorRowActions(entry({ present: true })).gui).toBe(false);
  });

  // Every row must offer something. A row with no buttons at all is the shape
  // of the failure that prompted this file.
  it("every state offers at least one action", () => {
    for (const kind of ["flatpak", "github", "byo"] as const) {
      for (const present of [false, true]) {
        for (const registered of [false, true]) {
          for (const imported of [false, true]) {
            const a = emulatorRowActions(entry({ kind, present, registered, imported }));
            expect(Object.values(a).some(Boolean), `${kind}/${present}/${registered}/${imported}`)
              .toBe(true);
          }
        }
      }
    }
  });
});
