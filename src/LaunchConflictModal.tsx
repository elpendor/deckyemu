import { DialogButton, Focusable, ModalRoot, showModal } from "@decky/ui";
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

const BUTTON = { width: "100%" };

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
 * Deliberately a copy rather than an improvement. The words, the three choices,
 * their order and the second press on the destructive one are all Steam's, read
 * out of the client itself (`GameAction_Launch_Multiple_*`), because somebody
 * who has already seen this dialog should not have to read it again to find out
 * it says the same thing. `steamText` takes them by token, so they arrive in
 * whatever language the client is set to and fall back to the English below.
 *
 * Two things are deliberately not copied. Steam's kiosk-mode branch disables
 * "launch anyway" outright; nothing here runs in kiosk mode, and a dead button
 * nobody can explain is worse than no button. And Steam only warns about apps
 * whose `app_type` is in its own game mask, which this does not try to
 * reconstruct from a minified constant -- everything Steam reports as running
 * is something contending for the same GPU, which is the thing being warned
 * about.
 *
 * Built from `ModalRoot` rather than `ConfirmModal` because the second press
 * needs the modal to stay open, and `ConfirmModal` is Steam's own component
 * found by matching minified source -- its close-on-press behaviour is not
 * ours to rely on. Three stacked buttons rather than a row: "Close Mina the
 * Hollower and launch Sonic The Hedgehog" does not fit beside anything.
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
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        {steamText("#GameAction_Launch_Multiple_Title", "Launch %1$s", title)}
      </div>

      <div style={{ marginBottom: "8px" }}>{description}</div>
      <div style={{ marginBottom: "16px", opacity: 0.8 }}>
        {steamText(
          "#GameAction_Launch_Multiple_Warning",
          "Warning: closing a game may result in losing unsaved data.",
        )}
      </div>

      <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <DialogButton
          style={BUTTON}
          onClick={() => {
            if (!confirming) {
              setConfirming(true);
              return;
            }
            for (const game of running) terminateGame(game.gameId);
            launch();
          }}
        >
          {confirming
            ? steamText(
                "#GameAction_Launch_Multiple_CloseAndLaunch_Confirm",
                "Confirm close and launch",
              )
            : closeAndLaunch}
        </DialogButton>

        <DialogButton style={BUTTON} onClick={launch}>
          {steamText("#GameAction_Launch_Multiple_LaunchSimultaneous", "Launch %1$s anyway", title)}
        </DialogButton>

        <DialogButton style={BUTTON} onClick={() => closeModal?.()}>
          {steamText("#GameAction_Launch_Multiple_Cancel", "Cancel")}
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
