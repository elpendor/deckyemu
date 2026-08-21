import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentUpdate,
  noteCheck,
  noteUpdate,
  setUpdateDotEnabled,
  updateDotVisible,
  watchUpdates,
} from "./updateSignal";

// Module state, shared by every test in the file for the same reason it is
// shared by the panel and the icon. Put back before each one, or the order they
// run in decides the result.
beforeEach(() => {
  noteUpdate(false, "");
  setUpdateDotEnabled(true);
});

describe("the update signal behind the icon dot", () => {
  it("remembers what a check found", () => {
    noteUpdate(true, "1.4.0");
    expect(currentUpdate()).toEqual({ available: true, version: "1.4.0" });
  });

  it("tells whoever is watching", () => {
    const seen = vi.fn();
    watchUpdates(seen);
    noteUpdate(true, "1.4.0");
    expect(seen).toHaveBeenCalledTimes(1);
  });

  // The panel checks on every open. Without this, every open re-renders the tab
  // icon to draw the same dot in the same place.
  it("says nothing when nothing changed", () => {
    noteUpdate(true, "1.4.0");
    const seen = vi.fn();
    watchUpdates(seen);
    noteUpdate(true, "1.4.0");
    expect(seen).not.toHaveBeenCalled();
  });

  // The transition that matters most after the first one: the user installed
  // it. A signal that only ever says yes can light the dot but never put it out.
  it("goes out again once the update is gone", () => {
    noteUpdate(true, "1.4.0");
    const seen = vi.fn();
    watchUpdates(seen);
    noteUpdate(false, "");
    expect([currentUpdate().available, seen.mock.calls.length]).toEqual([false, 1]);
  });

  // Same rule as the row: the dot is a claim that a specific version exists, so
  // "available" without one is not something to light it for.
  it("does not light up for an update with no version", () => {
    noteUpdate(true, "");
    expect(currentUpdate().available).toBe(false);
  });

  it("stops telling a watcher that has gone away", () => {
    const seen = vi.fn();
    watchUpdates(seen)();
    noteUpdate(true, "1.4.0");
    expect(seen).not.toHaveBeenCalled();
  });

  // A reply is not the same as an answer. `available: false` is what a check
  // that could not reach GitHub reports, and it cannot be told apart from "you
  // are up to date" unless `checked` is read as well.
  it("leaves the dot alone when the check could not reach GitHub", () => {
    noteUpdate(true, "1.4.0");
    noteCheck({
      available: false,
      current: "1.2.0",
      checked: false,
      error: "GitHub did not answer.",
      count: 0,
    });
    expect(currentUpdate()).toEqual({ available: true, version: "1.4.0" });
  });

  it("but puts it out when a check that worked found nothing", () => {
    noteUpdate(true, "1.4.0");
    noteCheck({ available: false, current: "1.4.0", checked: true, error: "", count: 3 });
    expect(currentUpdate().available).toBe(false);
  });

  it("and lights it when a check that worked found something", () => {
    noteCheck({
      available: true,
      current: "1.2.0",
      checked: true,
      error: "",
      count: 3,
      latest: {
        version: "1.4.0",
        tag: "v1.4.0",
        notes: "",
        asset_url: "https://example.com/deckyemu.zip",
        asset_name: "deckyemu.zip",
        sha256: "",
        prerelease: false,
        published_at: "",
      },
    });
    expect(currentUpdate()).toEqual({ available: true, version: "1.4.0" });
  });

  it("and nothing at all happens for a check that never ran", () => {
    noteUpdate(true, "1.4.0");
    noteCheck(null);
    expect(currentUpdate().available).toBe(true);
  });

  it("shows the dot when an update is out and the dot is wanted", () => {
    noteUpdate(true, "1.4.0");
    expect(updateDotVisible()).toBe(true);
  });

  it("hides it when the user has turned it off", () => {
    noteUpdate(true, "1.4.0");
    setUpdateDotEnabled(false);
    expect(updateDotVisible()).toBe(false);
  });

  // The switch is in the Updates tab and the icon is rendered outside that tree,
  // so the only thing that can move the dot is this notification. Without it the
  // switch moves and the dot stays until something reloads the plugin.
  it("tells the icon the moment the setting changes", () => {
    noteUpdate(true, "1.4.0");
    const seen = vi.fn();
    watchUpdates(seen);
    setUpdateDotEnabled(false);
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("says nothing when the setting is set to what it already was", () => {
    const seen = vi.fn();
    watchUpdates(seen);
    setUpdateDotEnabled(true);
    expect(seen).not.toHaveBeenCalled();
  });

  // Turning off an unsolicited notice is not a request to be refused the
  // information when you go looking for it: the row in the panel and the
  // Updates tab both read the check itself, which is untouched.
  it("hides only the dot, not what the check found", () => {
    noteUpdate(true, "1.4.0");
    setUpdateDotEnabled(false);
    expect(currentUpdate()).toEqual({ available: true, version: "1.4.0" });
  });

  // React runs effect cleanups while other components are updating, so one
  // watcher can drop another mid-notification. Iterating the live set skips
  // whoever was dropped, even though they were subscribed when the change
  // happened -- and being skipped here means a stale dot.
  it("still tells a watcher that another one dropped mid-notification", () => {
    const other = vi.fn();
    let stopOther = () => {};
    watchUpdates(() => stopOther());
    stopOther = watchUpdates(other);

    noteUpdate(true, "1.4.0");
    expect(other).toHaveBeenCalledTimes(1);
  });
});
