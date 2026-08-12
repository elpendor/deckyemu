import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type Core,
  cheevosAdopt,
  cheevosLogin,
  cheevosSignOut,
  cheevosStatus,
  listCores,
  realCores,
  setSettings,
  type CheevosStatus,
} from "./backend";
import { callWithRetry } from "./timeout";

/**
 * Why some cores answer "achievements are unsupported" at launch.
 *
 * RetroAchievements reads the emulated console's memory as the game runs, so a
 * core that publishes no memory map cannot take part -- there is nothing to
 * read. It is a property of the core, not of the game or the account, and
 * nothing this plugin sets can change it. The fix is always to run that system
 * on a different core.
 */
const UNSUPPORTED_EXPLANATION =
  "Achievements work by watching the emulated console's memory, so a core that does not publish a memory map cannot support them — RetroArch says so when the game starts. It depends on the core, not on your account or the ROM. Supported here means the core can take part, not that every game has achievements.";

/**
 * The one thing that must not be discovered by accident.
 *
 * RetroArch defaults hardcore *on*, and hardcore is not a difficulty setting:
 * it turns off save states, rewind, slowdown and cheats, which on a handheld is
 * most of how people actually play. So it defaults off here and says what it
 * costs, rather than being a word next to a switch.
 */
const HARDCORE_DESCRIPTION =
  "Achievements only count in hardcore mode on the hardcore leaderboard. It disables save states, rewind, slowdown and cheats for games launched from here. Off is the normal way to play; achievements still unlock.";

/**
 * Signing in to RetroAchievements and switching it on for launched games.
 *
 * A password is asked for exactly once. RetroAchievements has no OAuth or
 * device-code flow -- their API documentation says OAuth2 is "not
 * production-ready yet" -- and the web API key their settings page offers is a
 * different credential that cannot unlock anything. So one login is unavoidable;
 * what is avoidable is doing it twice, which is why a login already sitting in
 * retroarch.cfg is offered as a one-tap adopt instead.
 *
 * Only the returned Connect token is kept. The password is sent once, over
 * HTTPS, and never stored or logged.
 */
export function AchievementsPanel() {
  const [status, setStatus] = useState<CheevosStatus | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  // Installed cores grouped by what their .info file declares. Named rather than
  // described in the abstract: "BlastEm cannot" is actionable, "some cores
  // cannot" is not.
  const [cores, setCores] = useState<Core[]>([]);
  // TextField does not forward a ref, so reach the <input> through a wrapper.
  const passwordBoxRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    callWithRetry(cheevosStatus).then(setStatus).catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    callWithRetry(listCores)
      .then((all) => setCores(realCores(all)))
      .catch(() => undefined);
  }, []);

  const named = (support: Core["cheevos"]) =>
    cores
      .filter((core) => core.cheevos === support)
      .map((core) => core.short_name)
      // A middle dot, not a comma: core names carry hyphens and slashes of their
      // own ("Sega - Mega Drive - Genesis"), and a comma disappears among them.
      .join(" · ");

  const patch = useCallback(
    async (changes: Record<string, unknown>) => {
      try {
        await setSettings(changes);
        load();
      } catch (error) {
        console.error("[deckyemu] could not save achievement settings", error);
      }
    },
    [load],
  );

  const signIn = useCallback(async () => {
    const user = username.trim();
    if (!user || !password) return;
    setBusy(true);
    try {
      const result = await cheevosLogin(user, password);
      // Cleared on every outcome, not just success: a rejected password is the
      // case where it is most likely to be the wrong one, and leaving it in the
      // box invites pressing the button again unchanged.
      setPassword("");
      if (!result.ok) {
        toaster.toast({
          title: "Could not sign in",
          body: result.error ?? "RetroAchievements rejected the sign-in.",
        });
        return;
      }
      setUsername("");
      toaster.toast({
        title: `Signed in as ${result.username}`,
        body: "Achievements are on for games launched from here.",
      });
      load();
    } catch (error) {
      console.error("[deckyemu] achievements sign-in failed", error);
      toaster.toast({ title: "Could not sign in", body: "The backend did not answer." });
    } finally {
      setBusy(false);
    }
  }, [username, password, load]);

  const adopt = useCallback(async () => {
    setBusy(true);
    try {
      const result = await cheevosAdopt();
      if (!result.ok) {
        toaster.toast({ title: "Could not use that login", body: result.error ?? "" });
        return;
      }
      toaster.toast({
        title: `Signed in as ${result.username}`,
        body: "Taken from RetroArch's own settings — nothing to type.",
      });
      load();
    } finally {
      setBusy(false);
    }
  }, [load]);

  const signOut = useCallback(async () => {
    setBusy(true);
    try {
      await cheevosSignOut();
      toaster.toast({
        title: "Signed out",
        body: "RetroArch's own achievements login is untouched.",
      });
      load();
    } finally {
      setBusy(false);
    }
  }, [load]);

  /**
   * Fill the password from the clipboard, the same way the SteamGridDB key is
   * pasted: through the paste event, and through the window the input actually
   * lives in. See the comment in ArtworkPanel for why both matter.
   */
  const pastePassword = useCallback(async () => {
    const input = passwordBoxRef.current?.querySelector("input");
    if (!input) return;

    const pasted = new Promise<string>((resolve) => {
      const onPaste = (event: ClipboardEvent) => {
        event.preventDefault();
        window.clearTimeout(timer);
        resolve(event.clipboardData?.getData("text") ?? "");
      };
      const timer = window.setTimeout(() => {
        input.removeEventListener("paste", onPaste);
        resolve("");
      }, 1000);
      input.addEventListener("paste", onPaste, { once: true });
    });

    input.focus();
    try {
      const view = input.ownerDocument.defaultView as
        /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
        (Window & { SteamClient?: any }) | null;
      view?.SteamClient?.Browser?.Paste?.();
    } catch (error) {
      console.error("[deckyemu] Steam paste failed", error);
    }

    const text = (await pasted).trim();
    if (text) setPassword(text);
    else
      toaster.toast({
        title: "Nothing on the clipboard",
        body: "Type the password with the on-screen keyboard instead.",
      });
  }, []);

  if (!status) {
    return (
      <PanelSection title="Achievements">
        <PanelSectionRow>
          <Field label="Loading..." />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <PanelSection title="Achievements">
      {status.signed_in ? (
        <>
          <PanelSectionRow>
            <ToggleField
              label="Track RetroAchievements"
              description={`Signed in as ${status.username}. Achievements need a supported core and an exact ROM match — a dump that does not match any known version earns nothing, silently.`}
              checked={status.enabled}
              onChange={(value) => void patch({ cheevos_enable: value })}
              disabled={busy}
            />
          </PanelSectionRow>

          {status.enabled && (
            <PanelSectionRow>
              <ToggleField
                label="Hardcore mode"
                description={HARDCORE_DESCRIPTION}
                checked={status.hardcore}
                onChange={(value) => void patch({ cheevos_hardcore: value })}
                disabled={busy}
              />
            </PanelSectionRow>
          )}

          {status.enabled && cores.length > 0 && (
            <>
              <PanelSectionRow>
                <Field label="Core compatibility" description={UNSUPPORTED_EXPLANATION} />
              </PanelSectionRow>

              <PanelSectionRow>
                <Field
                  label="Supported"
                  description={named("yes") || "None of your installed cores."}
                />
              </PanelSectionRow>

              <PanelSectionRow>
                <Field
                  label="Unsupported"
                  description={named("no") || "None — every installed core can take part."}
                />
              </PanelSectionRow>

              {/* Only when there are any. A core whose .info file omits the field
                  has not refused, and guessing either way would state something
                  the file does not say. */}
              {named("unknown") && (
                <PanelSectionRow>
                  <Field
                    label="Not declared"
                    description={`${named("unknown")} — their core info does not say either way, so the only way to find out is to launch a game and read RetroArch's own notice.`}
                  />
                </PanelSectionRow>
              )}
            </>
          )}

          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void signOut()}
              disabled={busy}
              description="Forgets the sign-in stored here. RetroArch's own achievements login is left alone."
            >
              Sign out
            </ButtonItem>
          </PanelSectionRow>
        </>
      ) : (
        <>
          <PanelSectionRow>
            <Field
              description={
                status.can_adopt
                  ? `RetroArch is already signed in as ${status.retroarch_username}. Use that and there is nothing to type.`
                  : "Unlocks achievements in supported cores. Needs a free retroachievements.org account — they have no other way to sign in, so the password is asked for once and only the token it returns is kept."
              }
            />
          </PanelSectionRow>

          {status.can_adopt && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void adopt()} disabled={busy}>
                {busy ? "Working..." : `Use RetroArch's login (${status.retroarch_username})`}
              </ButtonItem>
            </PanelSectionRow>
          )}

          <PanelSectionRow>
            <TextField
              label="Username"
              value={username}
              disabled={busy}
              onChange={(event) => setUsername(event.target.value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <div ref={passwordBoxRef}>
              <TextField
                label="Password"
                value={password}
                bIsPassword
                disabled={busy}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          </PanelSectionRow>

          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => void pastePassword()} disabled={busy}>
              Paste password from clipboard
            </ButtonItem>
          </PanelSectionRow>

          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void signIn()}
              disabled={busy || !username.trim() || !password}
              description="Sent once over HTTPS to retroachievements.org. The password is not stored; the token it returns is."
            >
              {busy ? "Signing in..." : "Sign in"}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}
