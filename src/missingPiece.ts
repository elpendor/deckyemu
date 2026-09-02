/**
 * What to say when a launch was stopped because part of the game is gone.
 *
 * A pure module so the wording can be checked, the same reason `emulatorLegend`
 * and `motionState` are not inside their panels: importing a component pulls in
 * Steam's React, which is not an installed package.
 *
 * **The wording carries the whole value of this feature.** Without it the game
 * launches, fails, and returns to the library in a second with nothing on
 * screen — the failure the launch log was added for, and which nobody reads a
 * log to solve. So each message says what is missing, the likeliest reason, and
 * the one place to fix it.
 */

export type MissingPiece = "rom" | "emulator";

export interface MissingMessage {
  heading: string;
  body: string;
}

export function missingPieceMessage(
  piece: MissingPiece,
  title: string,
  name = "",
): MissingMessage {
  const heading = `${title} did not start`;

  if (piece === "rom") {
    return {
      heading,
      // The card first, because it is overwhelmingly the reason and the one
      // cause somebody can fix in ten seconds.
      body:
        "Its game file is missing. If it is on an SD card, the card has not " +
        "mounted — reinsert it and try again.",
    };
  }

  // Named when the launcher recorded a name, which is nearly always. "Ryujinx
  // is not installed" sends somebody straight to the row they need; "the
  // emulator it needs" leaves them to work out which of eight it was.
  //
  // Plain text, no markdown: this goes into a Steam dialog's description, which
  // renders a string and would print the asterisks.
  // `name` arrives ready to start a sentence -- "Ryujinx", or "The mesen core"
  // -- because which of those it is is the launcher's business, not the
  // dialog's, and one place deciding it is one place to correct.
  const subject = name || "The emulator it needs";
  // **It does not say how the emulator went.** An earlier version said "removed
  // outside this plugin", which is false in the most likely case of all: the
  // Emulators tab has a Remove button. Guessing at a cause the plugin cannot
  // know buys nothing and can be wrong; what the reader needs is the name and
  // the fix.
  return {
    heading,
    body: `${subject} is not installed. Install it from the Emulators tab — your saves are kept.`,
  };
}
