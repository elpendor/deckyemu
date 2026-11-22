import { playNavSound } from "./steamui";

/**
 * What a button that is a switch says: a switch and the name.
 *
 * Shared by the lists built this way -- a game's ROM hacks, an emulator's
 * fixes, the games to compress -- so they cannot come to look like different
 * controls.
 *
 * **The state has a fixed place and a look, not a word.** It was
 * "`<name>: on`", and with a long patch name the word landed wherever the name
 * ended, or was the first thing cut. The switch sits at the start of every row,
 * so a column of them reads straight down, and its shape differs as well as its
 * colour, so nothing rests on colour alone. An off row's name is dimmed on top.
 *
 * Drawn as Steam's own switch, measured on the Deck: a 38x22 rail, a 22px knob
 * that slides 16px, #1a9fff when on. Off, Steam's rail is white at 15%, which
 * vanishes on a focused button (drawn light), so it is the text colour instead.
 */
export function SwitchLabel({ name, on }: { name: string; on: boolean }) {
  return (
    <span
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        width: "100%",
        minWidth: 0,
        textAlign: "left",
      }}
    >
      <span
        aria-hidden
        style={{
          position: "relative",
          flexShrink: 0,
          width: "38px",
          height: "22px",
          borderRadius: "11px",
          background: on ? "#1a9fff" : "color-mix(in srgb, currentColor 25%, transparent)",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "22px",
            height: "22px",
            borderRadius: "50%",
            background: "#fff",
            boxShadow: "rgba(0, 0, 0, 0.35) 0 0 5px 0",
            transform: on ? "translateX(16px)" : "none",
            transition: "transform 0.2s cubic-bezier(0.1, 0.12, 0.53, 1.72)",
          }}
        />
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflowWrap: "anywhere",
          opacity: on ? 1 : 0.6,
        }}
      >
        {name}
      </span>
    </span>
  );
}

/**
 * Steam's switch sound, for the state a press turns a switch row to. It
 * outranks the plain OK sound the button plays, so the switch's is heard.
 */
export function playToggle(on: boolean): void {
  playNavSound(on ? "ToggleOn" : "ToggleOff");
}
