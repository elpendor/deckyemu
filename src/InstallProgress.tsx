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

interface Props {
  /** What is being installed, e.g. "Installing PCSX2". */
  label: string;
  /** -1 or 0 for "no number available", which draws the sliding segment. */
  percent: number;
  /** The installer's own last line of output. */
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

  return (
    <div style={{ width: "100%", padding: inline ? "2px 0 0" : "4px 0" }}>
      <style>{PROGRESS_CSS}</style>

      {/* Omitted inline: the row's own label already names the emulator, and
          repeating it under itself is the thing that looked wrong. */}
      {!inline && (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "14px" }}>
          <span>{label}</span>
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
          {/* Inline, the status line carries the label when there is no output
              yet -- otherwise the row reads as a name over an empty bar and
              says nothing about what is happening. */}
          {status || (inline ? label : "")}
        </span>
        {/* Inline the percentage lives here rather than up beside a label there
            is none of. */}
        {inline && !indeterminate && <span style={{ flexShrink: 0 }}>{percent}%</span>}
      </div>
    </div>
  );
}
