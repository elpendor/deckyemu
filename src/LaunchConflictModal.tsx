import {
  DialogBody,
  DialogButtonPrimary,
  DialogButtonSecondary,
  DialogFooter,
  DialogHeader,
  Focusable,
  ModalRoot,
  showModal,
} from "@decky/ui";
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
 * **The layout below is the real one, read off the running client rather than
 * guessed at.** Two earlier attempts got it wrong from opposite directions: a
 * column of full-width buttons in a bare `ModalRoot`, then a `ConfirmModal` with
 * `strMiddleButtonText`, which gives Steam's *standard* three-button footer.
 * This dialog does not use either. Its footer is a full-width **primary** button
 * on its own row, with Cancel and the secondary action side by side underneath:
 *
 *     <div class="DialogFooter">
 *       <button class="Stacked DialogButton _DialogLayout Primary …">   close and launch
 *       <div class="DialogTwoColLayout _DialogColLayout Panel Focusable">
 *         <button class="DialogButton _DialogLayout Secondary …">       Cancel
 *         <button class="DialogButton _DialogLayout Secondary …">       launch anyway
 *
 * Cancel comes **first** in that pair, which is the sort of thing no amount of
 * reading the minified component tells you. `DialogTwoColLayout`,
 * `_DialogColLayout` and `Stacked` are unhashed global classes and safe to name;
 * `Stacked` is what gives the top button its 10px gap, and the two hashed
 * classes on the real one turn out to be a `margin-top` for the warning line and
 * the yellow tint the confirm state gets, neither worth chasing a build-specific
 * hash for.
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
  // already moving. Owning the footer is what makes it possible -- `ConfirmModal`
  // closes itself, and the prop that stops it is not one @decky/ui declares.
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
    <ModalRoot closeModal={closeModal}>
      <DialogHeader>
        {steamText("#GameAction_Launch_Multiple_Title", "Launch %1$s", title)}
      </DialogHeader>

      {/* Steam's shape exactly: the sentence, a break, then the warning on its
          own line. */}
      <DialogBody>
        {description}
        <br />
        <div style={WARNING}>
          {steamText(
            "#GameAction_Launch_Multiple_Warning",
            "Warning: closing a game may result in losing unsaved data.",
          )}
        </div>
      </DialogBody>

      <DialogFooter>
        <DialogButtonPrimary
          className="Stacked"
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
        </DialogButtonPrimary>

        {/* Focusable supplies the `Panel Focusable` half of the class list the
            real one carries, so this is the same four classes in the same
            order. */}
        <Focusable className="DialogTwoColLayout _DialogColLayout">
          <DialogButtonSecondary onClick={() => closeModal?.()}>
            {steamText("#GameAction_Launch_Multiple_Cancel", "Cancel")}
          </DialogButtonSecondary>
          <DialogButtonSecondary onClick={launch}>
            {steamText(
              "#GameAction_Launch_Multiple_LaunchSimultaneous",
              "Launch %1$s anyway",
              title,
            )}
          </DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}
