import {
  DialogBody,
  DialogButtonPrimary,
  DialogFooter,
  DialogHeader,
  ModalRoot,
} from "@decky/ui";

import { openModal } from "./modalStack";
import type { LaunchNotice } from "./backend";

/**
 * What a game's fixes are doing, said as it starts, where it will be read.
 *
 * This was a toast, and a toast was wrong for it: ten seconds at the moment a
 * game takes over the screen is the least readable place to put a sentence, and
 * what it says is not decoration — a fix the user switched on is either
 * redundant or not running, and both are states they asked to be in and are not.
 *
 * **It informs and nothing else.** It had a "switch it off" button for a while,
 * and that button had to write two records — the emulator's answer and the
 * game's override — and then prove it had, because both buttons closed the
 * dialog and a real action looked exactly like dismissing one. Two bugs came out
 * of that. A switch lives in one place, and this is not that place.
 *
 * **It does not gate the launch.** The game is already starting behind it and
 * carries on regardless: nothing here is urgent enough to stand between someone
 * and the thing they pressed play on.
 */
interface Props {
  notices: LaunchNotice[];
  closeModal?: () => void;
}

export function FixNoticeModal({ notices, closeModal }: Props) {
  const many = notices.length > 1;

  return (
    <ModalRoot closeModal={closeModal}>
      <DialogHeader>
        {many ? "Some fixes are not doing their job" : notices[0].name}
      </DialogHeader>
      <DialogBody>
        {notices.map((notice) => (
          <div key={notice.id} style={{ marginBottom: many ? "12px" : 0 }}>
            {/* The sentence comes from the backend, which is what keeps this
                dialog, the row and the Emulators tab saying the same thing in
                the same words. */}
            {many ? `${notice.name}: ${notice.note}` : notice.note}
          </div>
        ))}
        {/* Only where the sentence does not already say where to go. */}
        {!notices.some((notice) => notice.state === "source_moved") && (
          <div style={{ marginTop: "0.75rem", opacity: 0.8 }}>
            You can change this on the Emulators tab.
          </div>
        )}
      </DialogBody>
      <DialogFooter>
        <DialogButtonPrimary onClick={() => closeModal?.()}>
          OK
        </DialogButtonPrimary>
      </DialogFooter>
    </ModalRoot>
  );
}

/**
 * Open it. The one way in, for the reason `showLaunchConflict` has one: the
 * module that decides when this is needed is plain and testable, and stops
 * being either the moment it imports something that renders.
 */
export function showFixNotice(notices: LaunchNotice[]) {
  if (notices.length === 0) return;
  openModal(<FixNoticeModal notices={notices} />);
}
