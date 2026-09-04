import { DialogButton, Focusable, ModalRoot } from "@decky/ui";

import { ago } from "./ago";
import { cloudAnswerConflict } from "./backend";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { MUTED } from "./dialogStyle";
import { FileName } from "./FileName";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/**
 * The one question the cloud half asks, in the shape Steam asks it.
 *
 * Everything else about a launch is decided without anybody: a save on the
 * storage that is not on this Deck comes down silently, because writing a file
 * that is not there cannot lose one. This is the other case -- the same file
 * exists in both places and they are not the same file.
 *
 * **It is about an emulator, not a game.** A conflict is found per emulator --
 * one record, one folder, one comparison, because a save cannot reliably be
 * traced to a game: RetroArch names them after the ROM but RPCS3 files by title
 * id, and a PS1 memory card holds a dozen games in one file. So the question
 * names the emulator and says the answer covers all of it. It first shipped
 * titled after the game being launched, which promised something narrower than
 * it delivered.
 *
 * **It cannot be settled by looking at the dates, but a person can settle it
 * by reading them.** Which copy is "newer" depends on this Deck's clock, a
 * storage provider's, and whatever device wrote the other one, none of which
 * have been compared -- so the plugin will not rule on it. Somebody who
 * remembers playing this on the sofa yesterday can, and both dates are on
 * screen for exactly that. Steam's own cloud conflict works this way, and it
 * is the version of this that people already know.
 *
 * **The game waits while this is open**, as a stopped process, costing nothing
 * for as long as it takes somebody to read two dates. It is not dismissable: B
 * and the X would leave it stopped with nothing on screen until the launcher's
 * own watchdog woke it. Every way out is an answer.
 */
interface Choice {
  appId: number;
  /** The game being started. Context for why this is on screen, not the scope. */
  title: string;
  /** The emulator whose saves these are, which *is* the scope. */
  emulator: string;
  names: string[];
  /** Unix seconds, newest on each side. 0 when nothing is known. */
  here: number;
  there: number;
  /**
   * Told what was chosen, before the backend is.
   *
   * "Play with the cloud's" is the one answer with work behind it -- the files
   * have to come down before the game is let go -- and the game is a stopped
   * process while that happens, so the screen would otherwise be Steam's
   * loading spinner with nothing to say how long. The caller puts the progress
   * dialog up in its place.
   */
  onAnswer?: (choice: "cloud" | "deck" | "stop") => void;
  closeModal?: () => void;
}

function Conflict(
  { appId, title, emulator, names, here, there, onAnswer, closeModal }: Choice,
) {
  const answer = (choice: "cloud" | "deck" | "stop") => {
    closeModal?.();
    onAnswer?.(choice);
    void cloudAnswerConflict(appId, choice).catch((error) =>
      logError("could not answer a save conflict", error),
    );
  };

  const side = (when: number) => (when ? `Changed ${ago(when)}` : "Date unknown");

  return (
    <ModalRoot>
      <style>{DANGER_CSS}</style>
      {/* **Named after the emulator, because that is what the answer covers.**
          A conflict is found per emulator -- one record, one folder, one
          comparison -- so a dialog titled after the game being started promised
          something narrower than it delivered: answering it for one game's save
          also answered it for every other save that emulator keeps. Saying
          "RetroArch" costs nothing and is true. */}
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Which {emulator} saves should this Deck use?
      </div>
      <div style={{ ...MUTED, marginBottom: "12px" }}>
        Starting {title}. {names.length === 1 ? "One save is" : `${names.length} saves are`}{" "}
        different here and in your cloud storage, which usually means {emulator} was
        played somewhere else since this Deck last copied anything up.{" "}
        <b>This choice applies to all of them.</b>
      </div>

      {/* Both dates, side by side, because that is the whole of the decision and
          it is one nothing here can make: the two clocks have never been
          compared. A person knows what they did yesterday. */}
      <Focusable style={{ display: "flex", gap: "10px", marginBottom: "12px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600 }}>This Deck</div>
          <div style={MUTED}>{side(here)}</div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600 }}>Cloud storage</div>
          <div style={MUTED}>{side(there)}</div>
        </div>
      </Focusable>

      {/* Named, because "a save is different" is not something anybody can act
          on -- and because the list is where somebody sees that the game they
          are starting is not the only thing this covers. Five rather than
          three for the same reason; more than that is a report, not a dialog
          over a waiting game. */}
      <div style={{ ...MUTED, marginBottom: "14px" }}>
        {names.slice(0, 5).map((name) => (
          <FileName key={name} name={name} />
        ))}
        {names.length > 5 && <div>and {names.length - 5} more</div>}
      </div>

      {/* The buttons are the column headings above, word for word. The
          question at the top already supplies the verb -- "which saves should X
          use?" -- so a button repeating it ("Play with this Deck's") was three
          words spent saying what had just been asked. Reading a date in a
          column and then pressing that column's name is one movement. */}
      <Focusable style={{ display: "flex", gap: "8px" }}>
        <DialogButton onClick={() => answer("deck")} style={{ flex: 1, minWidth: "auto" }}>
          This Deck
        </DialogButton>
        <DialogButton onClick={() => answer("cloud")} style={{ flex: 1, minWidth: "auto" }}>
          Cloud storage
        </DialogButton>
        {/* Not destructive, but it is the one that does something unexpected --
            the game does not start. Last, where this plugin puts the answer a
            thumb should not land on without meaning to. */}
        <div className={DANGER_CLASS} style={{ flex: 1, display: "flex" }}>
          <DialogButton onClick={() => answer("stop")} style={{ flex: 1, minWidth: "auto" }}>
            Don't start
          </DialogButton>
        </div>
      </Focusable>

      {/* True in both directions, which it was not when this first shipped: a
          copy up kept what it replaced in the cloud, but taking the cloud's
          copies overwrote files here with nothing kept -- and those are exactly
          the versions the storage does not have. */}
      <div style={{ ...MUTED, marginTop: "12px" }}>
        Neither answer loses anything. Whichever copies get replaced are kept in
        your storage, and <b>Restore save data</b> lists them by date.
      </div>
    </ModalRoot>
  );
}

/**
 * Put the question up. The game stays held until it is answered.
 *
 * Hands back the way to take it down, because the launch it is about can end
 * without an answer -- backed out of, or cancelled by Steam -- and a question
 * about a game that is no longer starting should not be left on screen.
 */
export function showCloudDiffer(options: {
  appId: number;
  title: string;
  emulator: string;
  names: string[];
  here: number;
  there: number;
  onAnswer?: (choice: "cloud" | "deck" | "stop") => void;
}): () => void {
  const handle = openModal(<Conflict {...options} />);
  return () => handle.Close();
}
