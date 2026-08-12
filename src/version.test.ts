import { describe, expect, it } from "vitest";

import { FRONTEND_BUILD, FRONTEND_VERSION, describe as describeBuild, isStale, shortBuild } from "./version";

/**
 * Whether the running frontend is the one that shipped with this backend.
 *
 * The two halves load independently -- decky restarts the Python side when its
 * files change while Steam keeps whatever bundle it already evaluated -- so
 * after an update they can disagree for as long as Steam stays running, and the
 * symptom is a change appearing to have done nothing at all.
 */
describe("isStale", () => {
  it("says nothing during development, whichever half is a dev build", () => {
    expect(isStale("0.5.0", "dev")).toBe(false);
    // FRONTEND_BUILD is "dev" under vitest, which is the other half of the same
    // rule: a local build has no stamp worth comparing.
    expect(FRONTEND_BUILD).toBe("dev");
    expect(isStale("9.9.9", "a1b2c3d")).toBe(false);
  });

  it("compares the build rather than the version", () => {
    // Two builds of the same version from different commits are not the same
    // code, and a rebuild from the same commit is.
    const same = (v: string, b: string) => isStale(v, b);
    expect(same(FRONTEND_VERSION, FRONTEND_BUILD)).toBe(false);
  });
});

describe("shortBuild", () => {
  it("leaves a development stamp alone and trims a commit", () => {
    expect(shortBuild("dev")).toBe("dev");
    expect(shortBuild("a1b2c3d4e5f6a7b8")).toBe("a1b2c3d");
  });
});

describe("describe", () => {
  it("reads as a version and where it came from", () => {
    expect(describeBuild("0.5.0", "dev")).toBe("0.5.0 (dev)");
    expect(describeBuild("0.5.0", "a1b2c3d4e5f6")).toBe("0.5.0 (a1b2c3d)");
  });
});
