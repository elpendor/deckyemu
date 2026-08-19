import { describe, expect, it } from "vitest";

import { sourceLabel } from "./emulatorSource";

describe("sourceLabel", () => {
  it("names the place the build is fetched from", () => {
    expect(sourceLabel("flatpak")).toBe("Flathub");
    expect(sourceLabel("github")).toBe("GitHub");
  });

  // Bring-your-own has no source: the plugin never obtains the binary, so a
  // parenthetical here would be a claim about a download that never happens.
  it("says nothing for an emulator the plugin does not obtain", () => {
    expect(sourceLabel("byo")).toBe("");
  });
});
