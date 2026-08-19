/*
 * A sliding segment, which is the conventional way to say "working, duration
 * unknown". A pulsing full-width bar reads as stalled instead.
 *
 * This is the normal case rather than a fallback: flatpak only prints
 * percentages when its output is a terminal, and the plugin reads it through a
 * pipe. Even under a pseudo-terminal it printed none here, so there is usually
 * no number to show. An AppImage download is the exception -- Content-Length
 * makes a real percentage available -- which is why both modes exist.
 */
const PROGRESS_CSS = `
@keyframes deckyemu-slide {
  0%   { transform: translateX(-110%); }
  100% { transform: translateX(410%); }
}`;

/**
 * Whether the installer's own last line of output is shown under the bar.
 *
 * Off, so the line under the bar says "Installing PCSX2" and nothing else.
 * What it said instead was flatpak's bookkeeping -- ref names, commit hashes,
 * "Updating appstream data for user flathub" -- which is meaningless to
 * somebody who asked to install an emulator, changes several times a second,
 * and reads like something going wrong. The label already answers the only
 * question being asked.
 *
 * A constant rather than a setting on purpose: it is a debugging aid for
 * whoever is looking at a stalled install, not a choice worth putting in front
 * of anyone. The callers still compute `status`, so flipping this is the whole
 * of turning it back on.
 */
const SHOW_INSTALLER_OUTPUT = false;

interface Props {
  /** What is being installed, e.g. "Installing PCSX2". */
  label: string;
  /** -1 or 0 for "no number available", which draws the sliding segment. */
  percent: number;
  /** The installer's own last line of output. Drawn only under the flag above. */
  status: string;
  /**
   * Drawn as the description of a row that already names the thing.
   *
   * A list of `Field` rows has a rhythm Steam owns -- the label block, then the
   * value -- and replacing one row with a block of hand-rolled markup breaks it:
   * the name jumps to a different size and the row loses its inset, which reads
   * as a different kind of thing appearing in the middle of the list. Inline
   * keeps the row and puts the bar where the description goes, so only the
   * right-hand side changes while something installs.
   */
  inline?: boolean;
}

/**
 * "Installing PCSX2" -> "Installing PCSX2...".
 *
 * What used to say the work was still going was the line changing several
 * times a second. Now that it is one fixed sentence, the ellipsis is the only
 * thing left carrying that: a static "Installing PCSX2" over a bar reads as a
 * caption for the row rather than as something happening right now.
 *
 * Left alone when the caller ended the label itself, so nothing arrives with
 * six dots on it.
 */
function working(label: string): string {
  return !label || label.endsWith(".") ? label : `${label}...`;
}

/**
 * Install progress, drawn with plain markup.
 *
 * `ProgressBarItem` was the obvious choice, but it is an Item: it puts its label
 * on the left and the bar in the right-hand column, and passing `layout="below"`
 * did not change that. Rather than keep guessing at how Steam's component lays
 * itself out, this owns its layout -- label above, bar full width, status
 * beneath.
 */
export function InstallProgress({ label, percent, status, inline = false }: Props) {
  const indeterminate = percent <= 0;
  const detail = SHOW_INSTALLER_OUTPUT ? status : "";

  return (
    <div style={{ width: "100%", padding: inline ? "2px 0 0" : "4px 0" }}>
      <style>{PROGRESS_CSS}</style>

      {/* Omitted inline: the row's own label already names the emulator, and
          repeating it under itself is the thing that looked wrong. */}
      {!inline && (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
          <span>{working(label)}</span>
          {!indeterminate && <span style={{ opacity: 0.7 }}>{percent}%</span>}
        </div>
      )}

      <div
        style={{
          height: inline ? "4px" : "6px",
          margin: inline ? "0 0 5px" : "8px 0 6px",
          borderRadius: "3px",
          background: "rgba(255, 255, 255, 0.15)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            // A short segment that travels, versus a fill that grows.
            width: indeterminate ? "25%" : `${percent}%`,
            borderRadius: "3px",
            background: "#1a9fff",
            transition: indeterminate ? undefined : "width 0.3s ease-out",
            animation: indeterminate
              ? "deckyemu-slide 1.6s cubic-bezier(0.4, 0, 0.6, 1) infinite"
              : undefined,
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "8px",
          fontSize: "12px",
          opacity: 0.6,
        }}
      >
        <span
          style={{
            // flatpak's lines are long; keep them to one line rather than
            // reflowing the panel on every update.
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {/* Inline, this line carries the label -- otherwise the row reads as
              a name over an empty bar and says nothing about what is happening.
              Not inline, the label is already drawn above the bar and this is
              left empty rather than repeating it under itself. */}
          {detail || (inline ? working(label) : "")}
        </span>
        {/* Inline the percentage lives here rather than up beside a label there
            is none of. */}
        {inline && !indeterminate && <span style={{ flexShrink: 0 }}>{percent}%</span>}
      </div>
    </div>
  );
}
