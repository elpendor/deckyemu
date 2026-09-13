import { FaToggleOff, FaToggleOn } from "react-icons/fa";

/**
 * What a button that is a switch says: a switch glyph and the name.
 *
 * Shared by the two lists built this way -- a game's ROM hacks and an
 * emulator's fixes -- so they cannot come to look like different controls.
 *
 * **The state has a fixed place and a look, not a word.** It was
 * "`<name>: on`", and with a long patch name the word landed wherever the name
 * ended, or was the first thing cut. The glyph sits at the start of every row, so
 * a column of them reads straight down, and its shape differs as well as its
 * colour, so nothing rests on colour alone. An off row's name is dimmed on top.
 *
 * The blue is Steam's own for a switch that is on.
 */
export function SwitchLabel({ name, on }: { name: string; on: boolean }) {
  const Glyph = on ? FaToggleOn : FaToggleOff;
  return (
    <span
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        minWidth: 0,
        textAlign: "left",
      }}
    >
      <Glyph
        style={{
          flexShrink: 0,
          fontSize: "22px",
          // Off takes the button's own text colour rather than a grey of its
          // own. A fixed grey was invisible on a focused button, which Steam
          // draws light, so the one row being looked at lost its state.
          color: on ? "#1a9fff" : "currentColor",
        }}
      />
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
