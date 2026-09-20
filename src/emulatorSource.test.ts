import { describe, expect, it } from "vitest";

import { sourceLabel } from "./emulatorSource";

describe("sourceLabel", () => {
  it("names the place the build is fetched from", () => {
    expect(sourceLabel("flatpak")).toBe("Flathub");
    expect(sourceLabel("github")).toBe("GitHub");
  });

  // A project with neither a flatpak nor a release page, installed from the
  // update feed its own updater reads. "Direct" rather than the hostname: it
  // says the build is the publisher's own — not mirrored, not repacked —
  // without dating the row if they ever move.
  it("names a publisher's own site as direct", () => {
    expect(sourceLabel("url")).toBe("Direct");
  });

  // Bring-your-own has no source: the plugin never obtains the binary, so a
  // parenthetical here would be a claim about a download that never happens.
  it("says nothing for an emulator the plugin does not obtain", () => {
    expect(sourceLabel("byo")).toBe("");
  });
});
