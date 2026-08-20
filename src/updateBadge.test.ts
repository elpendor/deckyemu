import { describe, expect, it } from "vitest";

import { updateBadge } from "./updateBadge";
import { type UpdateCheck } from "./backend";

const found: UpdateCheck = {
  available: true,
  current: "1.2.0",
  checked: true,
  error: "",
  count: 3,
  latest: {
    version: "1.3.0",
    tag: "v1.3.0",
    notes: "",
    asset_url: "https://example.com/deckyemu.zip",
    asset_name: "deckyemu.zip",
    sha256: "",
    prerelease: false,
    published_at: "",
  },
};

describe("the update row in the Quick Access panel", () => {
  it("names the version on offer", () => {
    expect(updateBadge(found)?.label).toContain("1.3.0");
  });

  it("and says how far behind you are", () => {
    expect(updateBadge(found)?.description).toContain("1.2.0");
  });

  it("says nothing when you are up to date", () => {
    expect(updateBadge({ ...found, available: false })).toBeNull();
  });

  // The panel calls this on every open, so "not yet" is the state it renders in
  // most often -- and a row that flickers in on every open is worse than one
  // that appears a moment late.
  it("says nothing before the check has run", () => {
    expect(updateBadge(null)).toBeNull();
  });

  // A failed check belongs in the Updates tab, where somebody went to ask. In
  // the panel it is an error about a thing the user was not doing.
  it("says nothing when the check failed", () => {
    expect(
      updateBadge({ ...found, available: false, checked: false, error: "GitHub did not answer." }),
    ).toBeNull();
  });

  // Defensive: `available` is computed from `latest` in the backend, so this
  // pairing should not occur -- but the row's entire content is a version
  // number, and rendering "DeckyEmu undefined is available" is worse than
  // rendering nothing.
  it("does not announce a version it does not have", () => {
    expect(updateBadge({ ...found, latest: undefined })).toBeNull();
  });
});
