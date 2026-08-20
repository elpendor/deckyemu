import { type DeviceState } from "./backend";

/**
 * Whether to replace the panel with an explanation, and what it should say.
 *
 * Pure, and separate from the component, because the decision is the part worth
 * being sure about: rendering a block screen on a real Steam Deck would make the
 * plugin look broken to every user who has one, and that failure is far more
 * expensive than the one the gate prevents. So the rule is written where a test
 * can state each case as an outcome.
 *
 * Everything unknown resolves to "not blocked". A backend older than the
 * `device` field is a real state during an update, and the honest reading of a
 * missing answer is that nothing has said this machine is unsupported -- not
 * that it is.
 */
export interface DeviceGate {
  blocked: boolean;
  title: string;
  body: string;
  /** Shown under the override, so turning it on is a considered act. */
  caveat: string;
}

const OPEN: DeviceGate = { blocked: false, title: "", body: "", caveat: "" };

/**
 * Wording per reason. `not-valve` is the ordinary case -- a desktop or another
 * handheld -- while `unknown` means the machine would not identify itself at
 * all, which may have nothing to do with what it is, so it is not accused of
 * being the wrong hardware.
 */
function explain(device: DeviceState): { title: string; body: string } {
  if (device.why === "unknown") {
    return {
      title: "Could not identify this device",
      body:
        "This machine did not report what it is, so DeckyEmu cannot tell whether it is a Steam Deck. " +
        "Everything here is built and tested on one, and nothing else is supported yet. " +
        "If this is a Steam Deck, that is a bug worth reporting.",
    };
  }
  return {
    title: "Not a Steam Deck",
    body:
      "DeckyEmu is for the Steam Deck, and this machine is not one. " +
      "Everything here — Game Mode, the controller setup, the emulator configuration — " +
      "is built and tested on Deck hardware and on nothing else, so it is not supported here yet.",
  };
}

export function deviceGate(device: DeviceState | undefined): DeviceGate {
  // No answer is not a "no". See the module comment.
  if (!device) return OPEN;
  if (device.allowed) return OPEN;

  return {
    blocked: true,
    ...explain(device),
    caveat:
      "You can continue anyway. Nothing here has been tested on this machine, " +
      "and it writes Steam shortcuts and emulator configuration, so it may not work " +
      "and may leave a mess behind. Your diagnostic report will record that you chose this.",
  };
}
