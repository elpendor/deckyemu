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
 * **It cannot be settled by looking at the dates, but a person can settle it
 * by reading them.** Which copy is "newer" depends on this Deck's clock, a
 * storage provider's, and whatever device wrote the other one, none of which
 * have been compared -- so the plugin will not rule on it. Somebody who
 * remembers playing this on the sofa yesterday can, and both dates are on
 * screen for exactly that. Steam's own cloud conflict works this way, and it
 * is the version of this that people already know.
 *
 * **The game waits while this is open**, which is what the launcher's heartbeat
 * is for. It is not dismissable: B and the X would leave the game held with
 * nothing on screen until the wait ran out. Every way out is an answer.
 */
interface Choice {
  appId: number;
  title: string;
  names: string[];
  /** Unix seconds, newest on each side. 0 when nothing is known. */
  here: number;
  there: number;
  closeModal?: () => void;
}

function Conflict({ appId, title, names, here, there, closeModal }: Choice) {
  const answer = (choice: "cloud" | "deck" | "stop") => {
    closeModal?.();
    void cloudAnswerConflict(appId, choice).catch((error) =>
      logError("could not answer a save conflict", error),
    );
  };

  const side = (when: number) => (when ? `Changed ${ago(when)}` : "Date unknown");

  return (
    <ModalRoot>
      <style>{DANGER_CSS}</style>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Which saves should {title} use?
      </div>
      <div style={{ ...MUTED, marginBottom: "12px" }}>
        {names.length === 1 ? "One save is" : `${names.length} saves are`} different
        here and in your cloud storage. This usually means it was played somewhere
        else since this Deck last copied anything up.
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
          on. Three at most: this is a dialog over a game that is waiting. */}
      <div style={{ ...MUTED, marginBottom: "14px" }}>
        {names.slice(0, 3).map((name) => (
          <FileName key={name} name={name} />
        ))}
        {names.length > 3 && <div>and {names.length - 3} more</div>}
      </div>

      <Focusable style={{ display: "flex", gap: "8px" }}>
        <DialogButton onClick={() => answer("deck")} style={{ flex: 1, minWidth: "auto" }}>
          Play with this Deck's
        </DialogButton>
        <DialogButton onClick={() => answer("cloud")} style={{ flex: 1, minWidth: "auto" }}>
          Play with the cloud's
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

      <div style={{ ...MUTED, marginTop: "12px" }}>
        Neither answer loses anything. Taking the cloud's copies keeps what they
        replace, and keeping this Deck's puts them in your storage on the next
        copy up — where what they replace is kept too.
      </div>
    </ModalRoot>
  );
}

/** Put the question up. The game stays held until it is answered. */
export function showCloudDiffer(options: {
  appId: number;
  title: string;
  names: string[];
  here: number;
  there: number;
}): void {
  openModal(<Conflict {...options} />);
}
