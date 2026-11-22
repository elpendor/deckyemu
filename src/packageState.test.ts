import { describe, expect, it } from "vitest";

import { type PackageState, type RomProbe } from "./backend";
import { pendingPackage } from "./packageState";

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
