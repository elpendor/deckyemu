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
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>What it works around</div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>{workaround.because}</div>
        </div>
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>What it costs</div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>{workaround.costs}</div>
        </div>
        {/* Every workaround names the fix that will retire it -- the schema
            requires it -- so this is always something rather than sometimes. */}
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500 }}>Until it is fixed</div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>
            This goes away once the emulator itself is fixed. Being tracked at{" "}
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
