import { describe, expect, it } from "vitest";

import { type PackageState, type RomProbe } from "./backend";
import { licenceChoice, pendingPackage } from "./packageState";

const state = (fields: Partial<PackageState> = {}): PackageState =>
  ({ title_id: "PCSA00011", installed: false, title: "", eboot: "", ...fields } as PackageState);

const probe = (fields: Partial<RomProbe>): RomProbe => fields as RomProbe;

describe("pendingPackage", () => {
  it("is nothing when the file is an ordinary ROM", () => {
    expect(pendingPackage(probe({ extension: "sfc" }))).toBeNull();
    expect(pendingPackage(null)).toBeNull();
    expect(pendingPackage(undefined)).toBeNull();
  });

  it("names the console the package belongs to", () => {
    expect(pendingPackage(probe({ ps3_package: state() }))?.system).toBe("ps3");
    expect(pendingPackage(probe({ ps4_package: state() }))?.system).toBe("ps4");
    expect(pendingPackage(probe({ vita_package: state() }))?.system).toBe("vita");
  });

  // The panel shows one of two states and never both: once the package is
  // installed the draft points at the game inside it, and offering to install it
  // again would unpack a second copy of something already there.
  it("is nothing once the package has been installed", () => {
    const installed = state({ installed: true, title: "Braid", eboot: "/x/EBOOT.BIN" });
    expect(pendingPackage(probe({ ps3_package: installed }))).toBeNull();
  });
});

describe("licenceChoice", () => {
  it("has nothing to choose for a console that needs no key", () => {
    const ps3 = pendingPackage(probe({ ps3_package: state({ licence_state: "" }) }));
    expect(licenceChoice(ps3, "")).toEqual({ candidates: [], chosen: "", blocked: false });
  });

  // The backend matched a key by name, so there is nothing to ask. `chosen` must
  // stay empty: a name the user did not pick is not one to send back as though
  // they had, and the backend re-finds it itself.
  it("stays out of the way when the key was matched by name", () => {
    const vita = pendingPackage(probe({ vita_package: state({ licence: true }) }));
    expect(licenceChoice(vita, "")).toEqual({ candidates: [], chosen: "", blocked: false });
  });

  it("blocks the install when a Vita package has no key at all", () => {
    const vita = pendingPackage(probe({ vita_package: state({ licence: false }) }));
    // Refused rather than allowed to fail: without a key Vita3K reports a
    // corrupt package, which reads as a bad download.
    expect(licenceChoice(vita, "")).toEqual({ candidates: [], chosen: "", blocked: true });
  });

  it("offers the keys that are here but unmatched, and unblocks on one", () => {
    const vita = pendingPackage(
      probe({
        vita_package: state({
          licence: false,
          licence_candidates: ["something.zrif", "other.zrif"],
        }),
      }),
    );
    const choice = licenceChoice(vita, "");
    expect(choice.candidates).toEqual(["something.zrif", "other.zrif"]);
    // The first is the default so the button is pressable, and it is named on
    // the button itself -- this is the press that spends a gigabyte or two on
    // the answer being right.
    expect(choice.chosen).toBe("something.zrif");
    expect(choice.blocked).toBe(false);
  });

  it("keeps a choice the user made", () => {
    const vita = pendingPackage(
      probe({
        vita_package: state({ licence: false, licence_candidates: ["a.zrif", "b.zrif"] }),
      }),
    );
    expect(licenceChoice(vita, "b.zrif").chosen).toBe("b.zrif");
  });

  // The bug this shape exists to prevent: a choice kept in step with the list by
  // hand outlives the list. Another ROM picked, or the key sent under its proper
  // name since, and the stored name is one the backend would reject -- so it is
  // derived from what is on offer every time rather than stored and cleaned up.
  it("drops a choice that is no longer on offer", () => {
    const vita = pendingPackage(
      probe({ vita_package: state({ licence: false, licence_candidates: ["a.zrif"] }) }),
    );
    expect(licenceChoice(vita, "gone.zrif").chosen).toBe("a.zrif");

    const matchedSince = pendingPackage(probe({ vita_package: state({ licence: true }) }));
    expect(licenceChoice(matchedSince, "gone.zrif").chosen).toBe("");
  });

  it("has nothing to choose when there is no package", () => {
    expect(licenceChoice(null, "a.zrif")).toEqual({
      candidates: [],
      chosen: "",
      blocked: false,
    });
  });
});
