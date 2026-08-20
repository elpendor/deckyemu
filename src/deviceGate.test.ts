import { describe, expect, it } from "vitest";

import { deviceGate } from "./deviceGate";
import { type DeviceState } from "./backend";

const deck: DeviceState = {
  supported: true,
  allowed: true,
  waived: false,
  model: "Steam Deck (OLED)",
  why: "deck",
};

const desktop: DeviceState = {
  supported: false,
  allowed: false,
  waived: false,
  model: "Valve-less PC",
  why: "not-valve",
};

describe("the panel on hardware this plugin does not support", () => {
  it("blocks a machine that is not Valve hardware", () => {
    expect(deviceGate(desktop).blocked).toBe(true);
  });

  it("names what the machine actually is, so the message is checkable", () => {
    expect(deviceGate(desktop).body).toContain("Valve-less PC");
  });

  // The expensive failure is the opposite one: a block screen on a real Deck
  // makes the plugin look broken to everybody who has one.
  it("never blocks a Steam Deck", () => {
    expect(deviceGate(deck).blocked).toBe(false);
  });

  it("does not block a Valve board it has never heard of", () => {
    // A Deck revision released after this version shipped. A whitelist that
    // has not been updated must not lock its owner out.
    expect(
      deviceGate({ ...deck, model: "Valve hardware (unrecognised board)", why: "valve-unknown" })
        .blocked,
    ).toBe(false);
  });

  // A backend without the field is a real state during an update: the frontend
  // reloads before the backend does. Silence is not a "no".
  it("does not block when the backend said nothing about the device", () => {
    expect(deviceGate(undefined).blocked).toBe(false);
  });

  it("steps aside once the user has chosen to continue", () => {
    expect(deviceGate({ ...desktop, allowed: true, waived: true }).blocked).toBe(false);
  });

  // "Could not identify this device" is not the same claim as "this is not a
  // Deck", and a Deck whose DMI is unreadable must not be told it is a desktop.
  it("does not accuse a machine that simply would not say what it is", () => {
    const gate = deviceGate({ ...desktop, why: "unknown", model: "unknown" });
    expect(gate.blocked).toBe(true);
    expect(gate.title).toBe("Could not identify this device");
  });

  it("says what continuing costs, wherever the block came from", () => {
    for (const why of ["not-valve", "unknown"]) {
      expect(deviceGate({ ...desktop, why }).caveat).toContain("Nothing here has been tested");
    }
  });
});
