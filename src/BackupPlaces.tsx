import { DialogButton, Focusable } from "./steamui";

/** The place that is not a drive: a phone or PC on the network. */
export const NETWORK = "network";

/**
 * Where a full backup goes or comes from: each drive, then Phone or PC. Shown
 * by Back up and Restore alike, and only when there is a choice to make.
 * The ✓ marks the choice; focus is Steam's own highlight.
 */
export function BackupPlaces({
  drives,
  chosen,
  onChoose,
}: {
  drives: { path: string; label: string }[];
  chosen: string;
  onChoose: (place: string) => void;
}) {
  if (drives.length === 0) return null;
  const places = [
    ...drives.map((drive) => ({ id: drive.path, label: drive.label })),
    { id: NETWORK, label: "Phone or PC" },
  ];
  return (
    <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
      {places.map((place) => (
        <DialogButton
          key={place.id}
          autoFocus={place.id === chosen}
          onClick={() => onChoose(place.id)}
        >
          {place.id === chosen ? `✓ ${place.label}` : place.label}
        </DialogButton>
      ))}
    </Focusable>
  );
}
