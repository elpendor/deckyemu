import { DialogButton, Focusable, ModalRoot } from "./steamui";


/** Join the game already added, or be an entry of its own. */
export type DiscChoice = "set" | "single";

/**
 * The answers, and the way out. `minWidth: auto` so a long label cannot bully
 * the row: without it a button will not shrink below its own text.
 */
const BUTTON_WIDE = { flex: 2, minWidth: "auto" };
const BUTTON_NARROW = { flex: 1, minWidth: "auto" };
import { openModal } from "./modalStack";

/**
 * Ask before putting an arrival into a game that is already in the library.
 *
 * The transfer dialog's version of the same question, and it exists for the
 * same reason: the match is a guess from filenames and a guess that acts on its
 * own is one nobody was told about. Shorter, because the row it was pressed on
 * has already named the disc, and there is one disc rather than a set.
 *
 * **Three answers, not two.** A two-button dialog has to make dismissing it
 * mean one of them, and here the only candidate was "add it as its own entry"
 * -- so pressing B on a row touched by mistake made a second Steam entry. The
 * two things this can do are both things, so backing out has to be its own
 * answer rather than the quieter of them.
 */
function JoinDiscModal({
  title,
  disc,
  answer,
  closeModal,
}: {
  title: string;
  disc: string;
  answer: (choice: DiscChoice | "cancel") => void;
  closeModal?: () => void;
}) {
  const choose = (choice: DiscChoice | "cancel") => {
    answer(choice);
    closeModal?.();
  };
  // Both, because B and the dialog closing itself are different paths and only
  // one of them is `onCancel`. Answering twice is harmless -- the promise keeps
  // the first.
  const dismiss = () => choose("cancel");

  return (
    <ModalRoot closeModal={dismiss} onCancel={dismiss} bAllowFullSize>
      <h1 style={{ marginTop: 0, marginBottom: "4px", fontSize: "23px" }}>
        Add this disc to {title}?
      </h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        <div style={{ overflowWrap: "anywhere", fontWeight: 600 }}>{disc}</div>
        <div style={{ marginTop: "4px" }}>
          It is filed beside {title}&apos;s other discs and added to its
          playlist, keeping the entry you already have.
        </div>
      </div>
      {/* The answer everybody presses takes the width, the withdrawal the
          narrow end, so a thumb entering from the left lands on it. */}
      <Focusable style={{ display: "flex", gap: "8px" }}>
        <DialogButton onClick={() => choose("set")} style={BUTTON_WIDE}>
          Add to {title}
        </DialogButton>
        <DialogButton onClick={() => choose("single")} style={BUTTON_WIDE}>
          Its own entry
        </DialogButton>
        <DialogButton onClick={dismiss} style={BUTTON_NARROW}>
          Cancel
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

/** Resolves `"cancel"` when the dialog is dismissed rather than answered. */
export function confirmJoinDisc(
  title: string,
  disc: string,
): Promise<DiscChoice | "cancel"> {
  return new Promise((resolve) =>
    openModal(<JoinDiscModal title={title} disc={disc} answer={resolve} />),
  );
}
