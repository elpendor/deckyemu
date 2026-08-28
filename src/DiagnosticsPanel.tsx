import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";

import { describe, FRONTEND_BUILD, FRONTEND_VERSION, isStale } from "./version";
import { useBackendVersion } from "./useBackendVersion";
import { openModal } from "./modalStack";
import { ReportModal } from "./ReportModal";

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

const VERSION_VALUE: React.CSSProperties = {
  fontSize: "0.9em",
  wordBreak: "break-word",
};

/**
 * What is actually running, and how to report it when it misbehaves.
 *
 * Split out of the Updates tab, where all of this sat under a section already
 * titled "Diagnostics" — a label admitting it was in the wrong place. Somebody
 * checking for an update had to scroll past two version rows, a possible
 * restart warning and a bug-report button to reach the thing they came for.
 *
 * The three belong together and nowhere else: the version pair exists because
 * the two halves can disagree, the restart notice is that disagreement firing,
 * and the report gathers the same facts one layer deeper. Updates is now only
 * about what is available and installing it.
 */
export function DiagnosticsPanel() {
  const backend = useBackendVersion();
  const stale = backend ? isStale(backend.version, backend.build) : false;

  return (
    <>
      {/* Which half is which, spelled out. "Installed" and "Interface" alone
          did not say, and the distinction only matters because they differ --
          which is the first question whenever something here misbehaves, and
          answering it from outside meant reading timestamps out of the CEF
          debugger. */}
      <PanelSection title="Versions">
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

        {/* The two halves load independently: decky restarts the backend on
            every update while Steam keeps the bundle it already evaluated. The
            symptom is that an update appears to have changed nothing. */}
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
      </PanelSection>

      {/* Titled for the thing rather than for the situation: "Something wrong"
          is a sentence fragment where every other group is a noun, and this is
          already what the report calls itself on the page it is served on. */}
      <PanelSection title="Reporting a problem">
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
