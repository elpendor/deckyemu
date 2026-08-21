import { ConfirmModal, showModal, type ConfirmModalProps } from "@decky/ui";
import { useState } from "react";

import { steamText, terminateGame, type RunningGame } from "./steam";

export interface LaunchConflict {
  /** The game the user asked for. */
  title: string;
  /** What is already running. Never empty -- the caller does not open this otherwise. */
  running: RunningGame[];
  /** Start the game. Called after whatever the user chose has been done. */
  onLaunch: () => void;
}

interface Props extends LaunchConflict {
  closeModal?: () => void;
}

/**
 * Keep the dialog up when OK is pressed.
 *
 * Steam's `GenericDialog` destructures `bCloseAfterOK` with a default of true
 * and skips its own `closeModal` when it is false, which is what makes a
 * two-press button possible inside a `ConfirmModal` at all. `@decky/ui` does
 * not list the prop, but `ConfirmModal` spreads everything it does not
 * recognise straight through to that dialog, so it arrives.
 *
 * The cast is the honest shape of that: a real prop of the component underneath,
 * missing from the types in between.
 */
const STAYS_OPEN_ON_OK = { bCloseAfterOK: false } as unknown as ConfirmModalProps;

/** Steam's own class for this line is `margin-top: .75rem` and nothing else. */
const WARNING = { marginTop: "0.75rem" };

/**
 * Open the dialog.
 *
 * The one way in, and the reason it is here rather than a `showModal` at the
 * call site: `playGame` decides when this is needed and is a plain module that
 * can be tested, which it stops being the moment it imports anything that
 * renders -- `react` is not an installed package, only Steam's copy at runtime.
 * A one-line function on this side of that boundary is what keeps the decision
 * on the other side of it.
 */
export function showLaunchConflict(conflict: LaunchConflict) {
  showModal(<LaunchConflictModal {...conflict} />);
}

/**
 * "You are currently running X" -- Steam's own dialog, reproduced.
 *
 * Pressing play in the added-games list goes through `SteamClient.Apps.RunGame`,
 * which is the launch and nothing else. The warning about running two games at
 * once lives in Steam's *library button*, several layers above it, so launching
 * from here started a second game over the first and said nothing. On a handheld
 * that reads as a stutter and a hot device rather than as a mistake, and the
 * first game is still sitting there holding memory when the second one quits.
 *
 * Deliberately a copy rather than an improvement, down to the layout. It is a
 * `ConfirmModal` with a middle button because that is exactly what Steam's own
 * is -- its three-button footer is the branch `strMiddleButtonText` selects --
 * and an earlier version of this built the same three buttons by hand out of
 * `ModalRoot` and `DialogButton`, which put a stack of full-width buttons where
 * Steam puts a footer row. It looked like a different dialog saying the same
 * words, which is the one thing a copy must not do.
 *
 * The words come from the client too (`GameAction_Launch_Multiple_*`), so they
 * arrive in whatever language it is set to and fall back to the English below.
 *
 * Two things are deliberately not copied. Steam's kiosk-mode branch disables
 * "launch anyway" outright; nothing here runs in kiosk mode, and a dead button
 * nobody can explain is worse than no button. And Steam only warns about apps
 * whose `app_type` is in its own game mask, which this does not try to
 * reconstruct from a minified constant -- everything Steam reports as running
 * is contending for the same GPU, which is the thing being warned about.
 */
export function LaunchConflictModal({ closeModal, title, running, onLaunch }: Props) {
  // Steam asks twice before closing a game and so does this. The first press
  // swaps the label rather than acting, which is the whole mechanism: the
  // button that can lose unsaved data is never the one under a thumb that was
  // already moving.
  const [confirming, setConfirming] = useState(false);

  const other = running[0].title;
  const many = running.length > 1;

  const description = many
    ? steamText(
        "#GameAction_Launch_Multiple_Description_Multiple",
        "You are currently running other games. It is not recommended to run multiple " +
          "games simultaneously as it can impact performance. How would you like to proceed?",
      )
    : steamText(
        "#GameAction_Launch_Multiple_Description",
        "You are currently running %1$s. It is not recommended to run multiple games " +
          "simultaneously as it can impact performance. How would you like to proceed?",
        other,
      );

  const closeAndLaunch = many
    ? steamText(
        "#GameAction_Launch_Multiple_CloseAndLaunch_Multiple",
        "Close other games and launch %1$s",
        title,
      )
    : steamText(
        "#GameAction_Launch_Multiple_CloseAndLaunch",
        "Close %1$s and launch %2$s",
        other,
        title,
      );

  const launch = () => {
    onLaunch();
    closeModal?.();
  };

  return (
    <ConfirmModal
      {...STAYS_OPEN_ON_OK}
      closeModal={closeModal}
      strTitle={steamText("#GameAction_Launch_Multiple_Title", "Launch %1$s", title)}
      // The same shape Steam builds: the sentence, a break, then the warning on
      // its own indented line.
      strDescription={
        <>
          {description}
          <br />
          <div style={WARNING}>
            {steamText(
              "#GameAction_Launch_Multiple_Warning",
              "Warning: closing a game may result in losing unsaved data.",
            )}
          </div>
        </>
      }
      strOKButtonText={
        confirming
          ? steamText(
              "#GameAction_Launch_Multiple_CloseAndLaunch_Confirm",
              "Confirm close and launch",
            )
          : closeAndLaunch
      }
      onOK={() => {
        if (!confirming) {
          setConfirming(true);
          return;
        }
        for (const game of running) terminateGame(game.gameId);
        // Closed by hand, because STAYS_OPEN_ON_OK turned off the automatic one.
        launch();
      }}
      strMiddleButtonText={steamText(
        "#GameAction_Launch_Multiple_LaunchSimultaneous",
        "Launch %1$s anyway",
        title,
      )}
      // The middle button closes the dialog itself, whatever bCloseAfterOK says.
      onMiddleButton={onLaunch}
      strCancelButtonText={steamText("#GameAction_Launch_Multiple_Cancel", "Cancel")}
    />
  );
}
