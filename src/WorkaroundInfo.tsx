import { DialogButton, ModalRoot } from "@decky/ui";
import { FaQuestion } from "react-icons/fa";

import { openModal } from "./modalStack";
import type { Workaround } from "./backend";

/**
 * What one workaround is for, and what it costs, out of the way until asked.
 *
 * The rows themselves are a name and a control and nothing else. Three lines of
 * explanation under each one reads as a wall long before a second workaround
 * exists, and the explanation is the part somebody reads once -- so it lives
 * behind a button rather than in front of every glance at the setting.
 */
export function WorkaroundModal({
  workaround,
  closeModal,
}: {
  workaround: Workaround;
  closeModal?: () => void;
}) {
  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        {workaround.name}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        {/* First, because it changes what the rest of this means. The same
            sentence the row, the Emulators tab and the launch dialog show --
            worded once, on the backend, so four surfaces cannot describe one
            fact four ways. */}
        {workaround.note && (
          <div>
            <div style={{ fontSize: "14px", fontWeight: 500 }}>
              {workaround.state === "retired" ? "No longer needed" : "Not running"}
            </div>
            <div style={{ fontSize: "13px", opacity: 0.8 }}>{workaround.note}</div>
          </div>
        )}
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>What it works around</div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>{workaround.because}</div>
        </div>
        {/* Said for every fix of this kind, from the catalog, rather than left
            to whoever writes the entry to remember. Changing a file somebody
            downloaded is the thing they are most entitled to be told, and it is
            also what makes "not running" make any sense. */}
        {workaround.patches && (
          <div>
            <div style={{ fontSize: "14px", fontWeight: 500 }}>How it is applied</div>
            <div style={{ fontSize: "13px", opacity: 0.8 }}>
              This one cannot be done from outside, so a corrected copy of the
              emulator is made when it installs. The original is kept, and is
              what runs whenever this is switched off.
            </div>
          </div>
        )}
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>What it costs</div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>{workaround.costs}</div>
        </div>
        {/* Shown whatever state it is in. This used to hide once a workaround
            was retired, which was exactly backwards: the moment somebody is
            told a fix is no longer needed is the moment they would want to see
            what fixed it. The schema requires `upstream`, so there is always
            something to name. */}
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>
            {workaround.state === "retired" ? "What fixed it" : "Until it is fixed"}
          </div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>
            {workaround.state === "retired"
              ? "Tracked at "
              : "This goes away once the emulator itself is fixed. Being tracked at "}
            {workaround.upstream.replace(/^https:\/\//, "")}.
          </div>
        </div>
      </div>
    </ModalRoot>
  );
}

/** The small button beside a workaround row that opens the explanation. */
export function WorkaroundInfo({ workaround }: { workaround: Workaround }) {
  return (
    <DialogButton
      onClick={() => openModal(<WorkaroundModal workaround={workaround} />)}
      style={{
        width: "40px",
        minWidth: "40px",
        height: "40px",
        padding: "0",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <FaQuestion />
    </DialogButton>
  );
}
