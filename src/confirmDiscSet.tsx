import { ConfirmModal, DialogButton, ModalRoot } from "@decky/ui";

import type { DiscChoice } from "./addFlow";
import { discSetFor } from "./backend";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/**
 * Ask whether the discs beside this one are the same game.
 *
 * **The point is that merging is never implied.** The detection is a guess from
 * filenames — the disc number is not in the file, and a PlayStation serial is
 * different on each disc of a set, so it names the disc rather than the game —
 * and a guess that acts on its own is one nobody was told about. So both ways
 * into the add flow put it — the transfer dialog's **Add** and the panel's file
 * browser — at the moment the file is chosen and before anything is decided for
 * you.
 *
 * Either answer is final for that press: the panel adds what you said and shows
 * no row about discs at all. Asked per press, so pressing disc 2 later asks
 * again — a different file is a new decision. Changing your mind means picking
 * the file again, which is one press and is the whole of the correction story
 * for now.
 */
export function confirmDiscSet(discs: string[], playlist: string): Promise<DiscChoice> {
  return new Promise((resolve) =>
    openModal(
      <ConfirmModal
        strTitle={`Add ${discs.length} discs as one game?`}
        strDescription={
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {/*
             * Named, in order, and that is why this is a dialog rather than a
             * toast: the order is the order they go into the playlist, and it
             * is the only thing here you can check.
             */}
            <div style={{ overflowWrap: "anywhere" }}>
              {discs.map((disc) => (
                <div key={disc}>{disc}</div>
              ))}
            </div>
            <div>
              One entry in your library, filed together under {playlist}, and the
              emulator changes disc from its own menu. Separately, each disc is
              its own entry with the same name.
            </div>
          </div>
        }
        strOKButtonText="One game"
        strCancelButtonText="This disc only"
        onOK={() => resolve("set")}
        onCancel={() => resolve("single")}
      />,
    ),
  );
}

/**
 * Put the question, if there is one to put. Undefined when there is not.
 *
 * Here rather than in `addFlow` for a mechanical reason worth writing down:
 * `addFlow` is imported by tests that run without Steam's webpack, and pulling
 * `@decky/ui` into it through this made two suites fail to load at all.
 *
 * Asked before `selectRom` rather than inside it, because the transfer dialog
 * navigates away the moment the flow starts, and the question has to be
 * answered on the screen it was asked from.
 *
 * A failure to ask is not a failure to add: the set is a nicety and the press
 * was about getting this file into the flow, so it goes there undecided, which
 * is the state the panel already handles.
 */
export async function askDiscChoice(romPath: string): Promise<DiscChoice | undefined> {
  try {
    const set = await discSetFor(romPath);
    if (set.discs.length >= 2) return await confirmDiscSet(set.discs, set.playlist);
  } catch (error) {
    logError("could not check for a disc set", error);
  }
  return undefined;
}

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
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <DialogButton onClick={() => choose("set")}>Add to {title}</DialogButton>
        <DialogButton onClick={() => choose("single")}>
          Add as its own entry
        </DialogButton>
        <DialogButton onClick={dismiss}>Cancel</DialogButton>
      </div>
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
