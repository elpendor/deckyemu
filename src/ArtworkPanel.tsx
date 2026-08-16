import {
  ButtonItem,
  DropdownItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  TextField,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  findExistingSgdbKey,
  getSettings,
  importExistingSgdbKey,
  setSettings,
  validateSgdbKey,
  type PluginSettings,
} from "./backend";
import { callWithRetry } from "./timeout";
import { pasteInto } from "./pasteText";

const ART_SOURCE_OPTIONS: SingleDropdownOption[] = [
  { data: "auto", label: "Auto (SteamGridDB, then libretro)" },
  { data: "libretro", label: "libretro thumbnails only" },
  { data: "sgdb", label: "SteamGridDB only" },
];

const SGDB_ORIGIN = "https://www.steamgriddb.com";

/** Where a SteamGridDB key is generated. */
const SGDB_KEY_URL = `${SGDB_ORIGIN}/profile/preferences/api`;

/**
 * Sign in to SteamGridDB without leaving Game Mode.
 *
 * SteamGridDB authenticates through Steam OpenID, but its own "Login via Steam"
 * button calls `window.open()`, and Steam's in-app browser ignores that -- so
 * the button does nothing in Game Mode and the key appears unobtainable without
 * a desktop browser.
 *
 * This is the same URL the site builds, navigated to in the current tab so no
 * popup is involved. Steam's in-app browser is already authenticated to
 * steamcommunity.com, so this usually completes with no typing; if the session
 * has lapsed, Steam's own sign-in form appears, which works fine on a Deck.
 * `mobileminimal=1` is what the site itself passes, and renders a lighter page.
 *
 * It ends on a blank page rather than anywhere useful: `/login/steam` is a JSON
 * endpoint the site only ever opens as a popup, which signals its opener and is
 * closed. There is no page to land on and no redirect parameter to aim it
 * somewhere better, hence step 2 being a separate button.
 */
const SGDB_STEAM_LOGIN_URL = `https://steamcommunity.com/openid/login?${new URLSearchParams({
  "openid.ns": "http://specs.openid.net/auth/2.0",
  "openid.mode": "checkid_setup",
  "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
  "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
  "openid.realm": SGDB_ORIGIN,
  "openid.return_to": `${SGDB_ORIGIN}/login/steam`,
  mobileminimal: "1",
}).toString()}`;

/**
 * Which step was last pressed, so focus can be put back on it.
 *
 * Module scope on purpose: opening the browser navigates the whole UI away and
 * unmounts this panel, so state or a ref would be rebuilt empty on the way back.
 * Coming back to the top of the list means hunting for your place in a
 * three-step sequence with a thumbstick.
 */
let lastStep: "signin" | "key" | "paste" | null = null;

/**
 * Ask Steam to focus this step on mount, if it is the one you left from.
 *
 * `autoFocus` is missing from decky's `ButtonItem` typings but reaches the
 * focusable Steam renders: the component spreads every prop it does not
 * recognise onto it, and its own nav code reads `autoFocus` (`BWantsAutoFocus`)
 * to claim focus as it mounts. Going through Steam's focus manager rather than
 * calling `.focus()` on the DOM node is deliberate -- a plain `.focus()` does
 * make the button `document.activeElement`, but Steam's manager never learns
 * about it, so the focus ring stays where it was and the gamepad still moves
 * from the old position.
 */
function focusIfResuming(step: typeof lastStep): { autoFocus?: true } {
  return lastStep === step ? { autoFocus: true } : {};
}

/**
 * Where artwork comes from, and the SteamGridDB key that unlocks the better
 * source.
 *
 * Its own tab because getting a key is a multi-step errand through an external
 * browser; wedged into Settings between notification toggles and collection
 * naming, it read as one more option rather than a sequence to follow.
 */
export function ArtworkPanel() {
  const [settings, setLocalSettings] = useState<PluginSettings | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  // A key already stored by another plugin, offered as a one-tap import.
  const [importable, setImportable] = useState<{ found: boolean; source: string }>({
    found: false,
    source: "",
  });
  // TextField is not ref-forwarding, so reach the <input> through a wrapper.
  const keyBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    callWithRetry(getSettings).then(setLocalSettings).catch(() => undefined);
    findExistingSgdbKey().then(setImportable).catch(() => undefined);
  }, []);

  const patch = useCallback(async (changes: Record<string, unknown>) => {
    try {
      setLocalSettings(await setSettings(changes));
    } catch (error) {
      console.error("[deckyemu] failed to save settings", error);
    }
  }, []);

  /**
   * Check a key and store it.
   *
   * One path for every way a key arrives -- pasted, typed, or left in the field
   * -- so none of them can save an unchecked key. Validated first because a
   * mistyped key otherwise fails much later, when artwork silently comes from
   * libretro instead.
   */
  const commitKey = useCallback(
    async (raw: string): Promise<boolean> => {
      const key = raw.trim();
      if (!key) return false;
      setSavingKey(true);
      try {
        const result = await validateSgdbKey(key);
        if (!result.ok) {
          toaster.toast({
            title: "SteamGridDB key rejected",
            body: result.error ?? "Could not verify the key.",
          });
          return false;
        }
        await patch({ sgdb_api_key: key });
        setKeyInput("");
        toaster.toast({
          title: "SteamGridDB key saved",
          body: "New games will use SteamGridDB artwork.",
        });
        return true;
      } finally {
        setSavingKey(false);
      }
    },
    [patch],
  );

  /**
   * Open a URL in Steam's own browser. The side menus have to be closed or the
   * browser opens behind them.
   */
  const openExternal = useCallback((url: string) => {
    try {
      Navigation.NavigateToExternalWeb(url);
      Navigation.CloseSideMenus();
    } catch (navError) {
      console.error("[deckyemu] could not open the browser", navError);
      toaster.toast({ title: "Could not open the browser", body: url });
    }
  }, []);

  /**
   * Take the key off the clipboard and save it in one step.
   *
   * The text is read out of the `paste` event rather than the clipboard.
   * `navigator.clipboard.readText()` on this module's window is refused outright
   * -- plugin code is evaluated in SharedJSContext, which never holds document
   * focus, so it answers `NotAllowedError: Document is not focused` and its
   * `clipboard-read` permission stays at "prompt". Through the input's own
   * window it does work, but only while that window has focus and only on a
   * permission nothing in Game Mode can grant if it is ever refused.
   * `event.clipboardData` needs neither.
   *
   * The default is prevented because the field is controlled: letting the
   * browser insert the text would put it only in the DOM, where React's next
   * render throws it away.
   */
  const pasteKey = useCallback(async () => {
    const input = keyBoxRef.current?.querySelector("input");
    if (!input) {
      toaster.toast({
        title: "Could not paste",
        body: "Type the key with the on-screen keyboard instead.",
      });
      return;
    }

    // Every hard part of this -- reading the text off the event rather than
    // the clipboard API, and pasting through the element's own window -- is in
    // pasteText.ts, because the Vita licence key needs the same thing.
    const text = (await pasteInto(input)).trim();
    if (text) {
      await commitKey(text);
      return;
    }

    // Distinct from "paste did not work": Steam pasted and there was nothing to
    // paste. A copy made in Steam's browser does survive coming back here, so
    // the likeliest cause really is that nothing was copied.
    toaster.toast({
      title: "Nothing on the clipboard",
      body: "Long-press the key on the API key page and choose Copy first.",
    });
  }, [commitKey]);

  const importKey = useCallback(async () => {
    setSavingKey(true);
    try {
      const result = await importExistingSgdbKey();
      if (!result.ok) {
        toaster.toast({ title: "Could not import key", body: result.error ?? "" });
        return;
      }
      setLocalSettings(await getSettings());
      setImportable({ found: false, source: "" });
      toaster.toast({ title: "SteamGridDB key imported", body: `Key ${result.how}.` });
    } finally {
      setSavingKey(false);
    }
  }, []);

  const clearKey = useCallback(async () => {
    await patch({ sgdb_api_key: "" });
    setKeyInput("");
    toaster.toast({
      title: "SteamGridDB key removed",
      body: "Artwork will come from libretro thumbnails.",
    });
  }, [patch]);

  if (!settings) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading..." />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      {/* Untitled first: the sidebar already labels this page "Artwork", and a
          PanelSection title that repeats its tab prints the heading twice. The
          key errand below is a group of its own. */}
      <PanelSection>
        <PanelSectionRow>
          <DropdownItem
            label="Artwork source"
            rgOptions={ART_SOURCE_OPTIONS}
            selectedOption={settings.art_source}
            onChange={(option) => void patch({ art_source: String(option.data) })}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="SteamGridDB">
        <PanelSectionRow>
          <Field
            description={
              settings.sgdb_api_key_set
                ? "Key saved. Steam-shaped capsules, heroes and logos are available."
                : "Optional. Without a key, boxart comes from libretro thumbnails. Getting one takes the three steps below."
            }
          />
        </PanelSectionRow>

        {settings.sgdb_api_key_set ? (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={clearKey}>
              Remove SteamGridDB key
            </ButtonItem>
          </PanelSectionRow>
        ) : (
          <>
            {importable.found && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={importKey}
                  disabled={savingKey}
                  description="Skips the steps below -- this key is already on the Deck."
                >
                  {savingKey ? "Checking..." : `Import key from ${importable.source}`}
                </ButtonItem>
              </PanelSectionRow>
            )}

            {/* "B twice" is not a slip. Signing in is a redirect chain -- Steam's
                OpenID page, then SteamGridDB's -- and each leaves its own history
                entry, so the first B goes back to the sign-in page rather than
                out of the browser. Nothing here can collapse that: the history
                belongs to Steam's browser, not to the plugin. */}
            <PanelSectionRow>
              <ButtonItem
                {...focusIfResuming("signin")}
                layout="below"
                onClick={() => {
                  lastStep = "signin";
                  openExternal(SGDB_STEAM_LOGIN_URL);
                }}
                disabled={savingKey}
                description="Step 1 of 3 — signs in through Steam, usually without typing anything. It ends on a blank page: that is the sign-in finishing, not an error. Press B twice to come back, since the sign-in page sits behind it."
              >
                Sign in to SteamGridDB
              </ButtonItem>
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                {...focusIfResuming("key")}
                layout="below"
                onClick={() => {
                  lastStep = "key";
                  openExternal(SGDB_KEY_URL);
                }}
                disabled={savingKey}
                description="Step 2 of 3 — opens your API key page. Hold your finger (or the trigger) on the key until the menu appears, choose Copy, then press B to come back."
              >
                Open the API key page
              </ButtonItem>
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                {...focusIfResuming("paste")}
                layout="below"
                onClick={() => {
                  lastStep = "paste";
                  void pasteKey();
                }}
                disabled={savingKey}
                description="Step 3 of 3 — pastes the copied key and saves it. Nothing else to press."
              >
                {savingKey ? "Checking..." : "Paste key and save"}
              </ButtonItem>
            </PanelSectionRow>

            {/* Kept for the hand-typed case, and because the on-screen keyboard has
                a paste key of its own that works here. Saved on blur so there is no
                second button to hunt for: leaving the field is the confirmation. */}
            <PanelSectionRow>
              <div ref={keyBoxRef}>
                <TextField
                  label="Or type the key"
                  value={keyInput}
                  bIsPassword
                  disabled={savingKey}
                  onChange={(event) => setKeyInput(event.target.value)}
                  onBlur={() => void commitKey(keyInput)}
                />
              </div>
            </PanelSectionRow>
        </>
      )}
    </PanelSection>
    </>
  );
}
