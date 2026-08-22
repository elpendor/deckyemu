import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
} from "@decky/ui";

import { clampNotes, countItems, parseNotes } from "./releaseNotes";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  checkForUpdate,
  getSettings,
  pluginVersion,
  setSettings,
  stageUpdate,
  type PluginVersion,
  type UpdateCheck,
} from "./backend";
import { OVER_THE_NETWORK, callWithRetry } from "./timeout";
import { canInstallUpdates, installUpdate } from "./updater";
import { noteCheck, setUpdateDotEnabled } from "./updateSignal";
import { describe, FRONTEND_BUILD, FRONTEND_VERSION, isStale } from "./version";
import { ReportModal } from "./ReportModal";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/**
 * Two halves side by side rather than stacked: they are one fact -- which build
 * is running -- and as full-width rows they pushed the actual controls off the
 * first screen.
 */
const VERSIONS: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  // 4px under the labels and no outer padding, which is the rhythm Steam's own
  // rows use: a 19px label block with a 4px gap, then the value. An invented
  // padding here made this row taller than every Field beside it.
  gap: "4px 12px",
  width: "100%",
};

const VERSION_LABEL: React.CSSProperties = {
  fontSize: "0.75em",
  textTransform: "uppercase",
  letterSpacing: "0.5px",
  opacity: 0.6,
};

const NOTES_HEADING: React.CSSProperties = {
  fontSize: "0.75em",
  textTransform: "uppercase",
  letterSpacing: "0.5px",
  opacity: 0.6,
  marginBottom: "2px",
};

/**
 * Release notes, rendered as something legible rather than as a string.
 *
 * The notes are markdown -- `## New` headings and `- entry` bullets -- and there
 * is no markdown renderer here. Handed to a Field as text they came out as one
 * run-on line: the description is plain text in a div that collapses whitespace,
 * so every newline became a space and the whole changelog read as
 * "- one - two - three".
 *
 * Preserving the newlines with `pre-wrap` was not enough either. A wrapped bullet
 * re-indents to the left margin, so a long entry stops looking like one item, and
 * long lines cannot wrap at all in the place this first went -- Field renders
 * `children` *inline*, in the narrow column beside the label, unless told
 * otherwise. So this is real elements: a muted heading per section, and bullets
 * whose text hangs in its own column so a wrap lines up under the text rather
 * than under the marker.
 *
 * Rendered identically wherever it appears. The version you are running and the
 * version on offer are the same kind of thing, so capping one and not the other
 * made the pair read as two different features.
 *
 * A long one is folded rather than cut. This was shown in full on the grounds
 * that the tab scrolls anyway -- which was true and still missed the point: it
 * made the distance from the top of the page to **Check for updates** a function
 * of how much had changed, so the button was furthest away exactly when a
 * release was big enough to want checking. Folding keeps the button close and
 * keeps every entry reachable, which cutting with an ellipsis would not.
 */
function Notes({ text, limit = 0 }: { text: string; limit?: number }) {
  const shown = clampNotes(parseNotes(text), limit);
  if (shown.length === 0) return null;

  return (
    <div style={{ fontSize: "0.9em" }}>
      {shown.map((section, index) => (
        <div key={index} style={{ marginBottom: "8px" }}>
          {section.heading && <div style={NOTES_HEADING}>{section.heading}</div>}
          {section.items.map((item, itemIndex) => (
            <div key={itemIndex} style={{ display: "flex", gap: "6px", marginBottom: "2px" }}>
              <span style={{ opacity: 0.5 }}>&bull;</span>
              <span style={{ flex: 1, minWidth: 0 }}>{item}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * How many entries are shown before the notes are folded away.
 *
 * Enough to see what kind of release it is, few enough that the button under it
 * is reachable without scrolling past the whole changelog.
 */
const NOTES_PREVIEW = 5;

const VERSION_VALUE: React.CSSProperties = {
  fontSize: "0.95em",
  wordBreak: "break-word",
};

/**
 * Version and update checking.
 *
 * Its own tab rather than a corner of Settings: none of it is a setting.
 */
export function UpdatePanel() {
  const [backend, setBackend] = useState<PluginVersion | null>(null);
  const [update, setUpdate] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  // Which changelogs the user has unfolded, by the version they belong to.
  // Keyed rather than a single flag: the notes for what you are running and
  // the notes for what is on offer are two separate readings.
  const [openNotes, setOpenNotes] = useState<Record<string, boolean>>({});
  // Undefined until the settings have been read, so the switch is not drawn in
  // the wrong position for the moment that takes.
  const [dot, setDot] = useState<boolean | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setBackend(await callWithRetry(pluginVersion));
    } catch (error) {
      logError("could not read version", error);
    }
    try {
      setDot((await callWithRetry(getSettings)).show_update_dot !== false);
    } catch (error) {
      logError("could not read the update dot setting", error);
    }
  }, []);

  /**
   * Write it, and tell the icon.
   *
   * The icon is rendered outside this tree and never re-reads settings, so
   * without the second call the switch would move and the dot would stay where
   * it was until something reloaded the plugin.
   */
  const setDotSetting = useCallback(async (on: boolean) => {
    setDot(on);
    setUpdateDotEnabled(on);
    try {
      await setSettings({ show_update_dot: on });
    } catch (error) {
      logError("could not save the update dot setting", error);
    }
  }, []);

  const check = useCallback(async (force: boolean) => {
    setChecking(true);
    try {
      // Through callWithRetry like every other call here: decky restarts the
      // backend whenever its files change and drops whatever was in flight, so a
      // single attempt reports "the backend did not answer" for what is really a
      // reload that has already finished.
      //
      // **But not on the default timings**, and this is the one call in the
      // plugin where that matters. The defaults -- eight attempts, two seconds
      // each -- are justified by the work behind a backend call taking single
      // -digit milliseconds. This one crosses the network to GitHub, so two
      // seconds is a perfectly ordinary duration rather than evidence of a lost
      // reply. Retrying then does not recover anything: decky cannot cancel, so
      // the abandoned attempt's request keeps running and the retry starts
      // another. Measured while GitHub was timing out: 23 requests in fifteen
      // seconds against a budget of sixty an hour, which is how a slow check
      // turns into a rate-limited one.
      //
      // Long enough to let a real answer arrive, and one retry -- which is all
      // the reload case ever needed.
      const found = await callWithRetry(() => checkForUpdate(force), OVER_THE_NETWORK);
      setUpdate(found);
      // The icon reads this too. Without it, pressing "check for updates" here
      // and learning there is none would leave the dot lit until the panel was
      // opened or the timer came round again -- the one screen that knows the
      // most would be the one place that could not put it right.
      noteCheck(found);
    } catch (error) {
      // The real message, not a guess at what went wrong. Two rounds were spent
      // on "the backend did not answer" while the actual error sat in a console
      // nobody was reading.
      logError("update check failed", error);
      const detail =
        error instanceof Error ? error.message : String(error ?? "no detail");
      // The *end* of a Python traceback, not the start: decky returns the whole
      // thing and the exception line -- the only part that says what went wrong --
      // is the last one. Truncating from the front showed only decky's own frames.
      const tail = detail.trim().split(/\r?\n/).filter(Boolean).slice(-3).join(" | ");
      setUpdate({
        available: false,
        current: FRONTEND_VERSION,
        checked: false,
        error: `The call failed: ${tail || detail}`.slice(0, 400),
        count: 0,
      });
    } finally {
      setChecking(false);
    }
  }, []);

  /*
   * Both on mount, and the check unforced.
   *
   * This tab is where the panel's update row sends you, and it used to greet
   * whoever arrived with "Not checked yet." -- making somebody press a button to
   * be told the thing that sent them here. Unforced because that row came from
   * the same cached answer the backend has been holding for the last hour, so
   * arriving from it costs nothing and answers immediately. The button below
   * stays forced: pressing it is somebody asking for a fresh look.
   */
  useEffect(() => {
    void load();
    void check(false);
  }, [load, check]);

  /**
   * Hand the release to decky and let it take over.
   *
   * Staged locally first: decky downloads the URL itself and holds no
   * credentials, so what it installs is a digest-checked file served from
   * loopback -- which also keeps a build aimed at a private repository working,
   * since decky would 404 on that asset.
   */
  const install = useCallback(async () => {
    const release = update?.latest;
    if (!release) return;
    setInstalling(true);
    try {
      // Fewer attempts than a plain read: this downloads the release, so a retry
      // costs a repeated transfer rather than a repeated question.
      const staged = await callWithRetry(() => stageUpdate(), { attempts: 3 });
      if (!staged.ok || !staged.url) {
        toaster.toast({
          title: "Could not prepare the update",
          body: staged.error ?? "The release could not be downloaded.",
        });
        return;
      }
      await installUpdate(staged.url, staged.version ?? release.version, staged.sha256 ?? "");
      toaster.toast({
        title: `Installing ${release.version}`,
        body: "Decky will confirm and show progress.",
      });
    } catch (error) {
      logError("could not start the update", error);
      toaster.toast({
        title: "Could not start the update",
        body: error instanceof Error ? error.message : "Decky did not accept the request.",
      });
    } finally {
      setInstalling(false);
    }
  }, [update?.latest]);

  const stale = backend ? isStale(backend.version, backend.build) : false;

  /** What the last check actually found, in one line. */
  function status(): string {
    if (!update) return "Not checked yet.";
    if (!update.checked) return update.error || "Could not reach GitHub.";
    if (update.available) return `Version ${update.latest?.version} is available.`;
    // Distinct from a failure: the request worked, there is just nothing there.
    if (update.count === 0) return "No releases have been published yet.";
    return "This is the newest release.";
  }

  // Both changelogs fold the same way. Written once so the one you are running
  // and the one on offer cannot drift into behaving differently -- they are the
  // same kind of thing, and looking different made them read as two features.
  const changelog = (key: string, label: string, text: string) => {
    const total = countItems(parseNotes(text));
    const open = openNotes[key] ?? false;
    const folded = !open && total > NOTES_PREVIEW;
    return (
      <>
        <PanelSectionRow>
          <Field label={label} description={<Notes text={text} limit={folded ? NOTES_PREVIEW : 0} />} />
        </PanelSectionRow>
        {total > NOTES_PREVIEW && (
          <PanelSectionRow>
            {/* A button rather than a scrolling box. A scroll region holding
                only text has nothing focusable in it, so a controller cannot
                enter it and the hidden part would be unreachable -- and the
                library's own ScrollPanel is located by matching stringified
                Steam internals, which is undefined the day that bundle shifts.
                A button is focusable by construction and cannot go missing. */}
            <ButtonItem
              layout="below"
              onClick={() => setOpenNotes((was) => ({ ...was, [key]: !open }))}
            >
              {open ? "Show fewer changes" : `Show all ${total} changes`}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </>
    );
  };

  return (
    <>
    {/* No title: the sidebar already labels this page "Updates", and a section
        of the same name under it reads as the heading having been printed
        twice. Any further group gets a real one -- see below. */}
    <PanelSection>
      {/* Both always shown, not only when they disagree: which build is running is
          the first question whenever something here misbehaves, and answering it
          from the outside meant reading timestamps out of the CEF debugger.
          The labels say which half each is -- "Installed" and "Interface" alone
          did not, and the distinction only matters because they can differ. */}
      <PanelSectionRow>
        <div style={VERSIONS}>
          <div style={VERSION_LABEL}>Plugin on disk</div>
          <div style={VERSION_LABEL}>Interface Steam loaded</div>
          <div style={VERSION_VALUE}>
            {backend
              ? describe(backend.version, backend.build) +
                (backend.built_at ? ` — built ${backend.built_at.slice(0, 10)}` : "")
              : "Loading..."}
          </div>
          <div style={VERSION_VALUE}>{describe(FRONTEND_VERSION, FRONTEND_BUILD)}</div>
        </div>
      </PanelSectionRow>

      {/* The two halves load independently: decky restarts the backend on every
          update while Steam keeps the bundle it already evaluated. The symptom is
          that an update appears to have changed nothing. */}
      {stale && backend && (
        <PanelSectionRow>
          <Field
            label="Restart Steam to finish updating"
            description={`The backend is ${describe(
              backend.version,
              backend.build,
            )} but this interface is still ${describe(
              FRONTEND_VERSION,
              FRONTEND_BUILD,
            )}. Steam keeps the interface it loaded until it restarts.`}
          />
        </PanelSectionRow>
      )}

      {/* What the build you are running actually changed.

          Above the update check on purpose: it answers "what did I just get?",
          which is the question you have immediately after updating and the one
          nothing could answer before -- notes only ever appeared for a release
          you had *not* installed yet, so they vanished at the moment they became
          true of you. Read from the build stamp, so it needs no network and, while
          the repository is private, no token. Absent on a local build, which has
          no stamp to read. */}
      {backend?.notes && changelog("installed", `What's new in ${backend.version}`, backend.notes)}

      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => void check(true)}
          disabled={checking || installing}
          description={status()}
        >
          {checking ? "Checking..." : "Check for updates"}
        </ButtonItem>
      </PanelSectionRow>

      {/* Only the dot has a switch, and only because it is the only part of
          this that arrives without being asked for. decky has a setting of its
          own for exactly this and honours it for the plugins in its store; a
          plugin cannot read that setting, so somebody who has already said they
          do not want to hear about plugin updates can only be answered here. */}
      {dot !== undefined && (
        <PanelSectionRow>
          <ToggleField
            label="Mark the icon when an update is out"
            description="Puts a dot on the DeckyEmu icon in the Quick Access bar. Turning it off changes nothing on this tab — checks keep running and this page keeps answering."
            checked={dot}
            onChange={(value) => void setDotSetting(value)}
          />
        </PanelSectionRow>
      )}

      {update?.available && update.latest && (
        <>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void install()}
              disabled={installing || !canInstallUpdates()}
              description={
                canInstallUpdates()
                  ? "Decky downloads and installs it, then reloads the plugin."
                  : "Decky's installer is not reachable from this window."
              }
            >
              {installing ? "Preparing..." : `Update to ${update.latest.version}`}
            </ButtonItem>
          </PanelSectionRow>

          {update.latest.notes &&
            changelog("offered", `What's new in ${update.latest.version}`, update.latest.notes)}
        </>
      )}

      {/* Nothing to configure. The check reads public releases and needs no
          credentials; the token this page deliberately never offered to store
          is gone from the plugin entirely. */}
    </PanelSection>

    {/* Reporting a problem lives here rather than under Library, which is about
        games added to Steam -- a bug is as likely to be in artwork, a transfer,
        an emulator install or an update as in the library. This tab already
        answers "which build am I running", which is the first question of any
        bug report and the first section of the report itself.

        After the update check on purpose: those are the two things you do when
        something is wrong, and they are in the right order, because being a
        version behind is one of the answers.

        Titled for the thing rather than for the situation: "Something wrong" is
        a sentence fragment where every other group on this page is a noun --
        Launching, Naming, Install cores. "Reporting a problem" would fit that
        and then say the button's own words back at it, and this is already what
        the report calls itself on the page it is served on. */}
    <PanelSection title="Diagnostics">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => openModal(<ReportModal />)}
          description="Gathers what a bug report needs — this build, what is installed, and the end of the log — and puts it where a phone or PC can read it. Keys, tokens and your game names are removed from it."
        >
          Report a problem
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
    </>
  );
}
