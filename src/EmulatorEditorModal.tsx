import {
  DialogButton,
  Dropdown,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
  type SingleDropdownOption,
} from "@decky/ui";
import { FileSelectionType, openFilePicker, toaster } from "@decky/api";

import { WorkaroundInfo } from "./WorkaroundInfo";
import { adoptedSystemId, initialSystemId, systemFields } from "./systemChoice";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  listSystems,
  listWorkarounds,
  saveEmulator,
  setWorkaround,
  suggestLaunchOptions,
  type CustomEmulator,
  type SystemOption,
  type Workaround,
} from "./backend";

interface Props {
  /** An existing emulator to edit, or undefined to add a new one. */
  emulator?: CustomEmulator;
  onSaved: () => void;
  closeModal?: () => void;
}

const KIND_OPTIONS: SingleDropdownOption[] = [
  { data: "flatpak", label: "Flatpak" },
  { data: "path", label: "Executable or AppImage" },
];

const FIELD_GAP = { display: "flex", flexDirection: "column" as const, gap: "4px" };

function Label({ children, hint }: { children: string; hint?: string }) {
  return (
    <div>
      <div style={{ fontSize: "14px", fontWeight: 500 }}>{children}</div>
      {hint && <div style={{ fontSize: "12px", opacity: 0.6 }}>{hint}</div>}
    </div>
  );
}

/**
 * The corrections this emulator carries that a user is allowed to decline.
 *
 * Almost every emulator has none, and then this renders nothing at all. The bar
 * for appearing here is deliberately high: a bug upstream has been told about,
 * with a fix on the way, and a cost worth letting somebody refuse. Being told
 * which binary to run is not one of those -- see `schema.WORKAROUND_FIELDS`.
 *
 * These save on the spot rather than with the rest of the form. Switching one
 * rewrites every launcher for that emulator, which is not a thing to do halfway
 * through editing a name, and a toggle that waited for Save would appear to take
 * and then change nothing.
 */
function Workarounds({ emulatorId }: { emulatorId: string }) {
  const [items, setItems] = useState<Workaround[] | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let live = true;
    listWorkarounds(emulatorId)
      .then((result) => {
        if (live) setItems(result.ok ? (result.workarounds ?? []) : []);
      })
      .catch(() => {
        if (live) setItems([]);
      });
    return () => {
      live = false;
    };
  }, [emulatorId]);

  const toggle = useCallback(
    async (item: Workaround) => {
      setBusy(item.id);
      try {
        const result = await setWorkaround(emulatorId, item.id, !item.enabled);
        if (!result.ok) {
          toaster.toast({ title: "DeckyEmu", body: result.error ?? "That did not work." });
          return;
        }
        setItems((current) =>
          (current ?? []).map((one) =>
            one.id === item.id ? { ...one, enabled: !item.enabled } : one,
          ),
        );
      } finally {
        setBusy("");
      }
    },
    [emulatorId],
  );

  if (!items || items.length === 0) return null;

  return (
    <div style={FIELD_GAP}>
      <Label>Fixes</Label>
      {items.map((item) => (
        <Focusable
          key={item.id}
          style={{ display: "flex", gap: "8px", alignItems: "center" }}
        >
          <DialogButton
            // Always pressable, both ways. A fix being retired or unable to run
            // changes what the row *says*, never what the switch will do --
            // every rule that removed an option was one more thing to know
            // before you could predict a control, and one of them stranded
            // anyone who happened to be off when a fix stopped fitting.
            disabled={busy === item.id}
            onClick={() => toggle(item)}
            style={{ flexGrow: 1 }}
          >
            {busy === item.id
              ? "Working..."
              : `${item.name}: ${item.enabled ? "on" : "off"}`}
          </DialogButton>
          <WorkaroundInfo workaround={item} />
        </Focusable>
      ))}
      {/* Under the rows rather than inside them: a row is a name and a control,
          and this is the same sentence the Emulators tab and the launch dialog
          show, in the same words. */}
      {items
        .filter((item) => item.state && item.enabled)
        .map((item) => (
          <div key={`${item.id}-note`} style={{ fontSize: "13px", opacity: 0.8 }}>
            {item.name}: {item.note}
          </div>
        ))}
    </div>
  );
}

/**
 * Add or edit a standalone emulator.
 *
 * The system field is the one that matters beyond launching: artwork lookup and
 * the SteamGridDB release-era check both key on the libretro system name, so
 * setting it makes a custom emulator get boxart and collection grouping exactly
 * like a libretro core does. Leaving it unset still launches games, but artwork
 * then depends entirely on SteamGridDB matching the title by name.
 */
export function EmulatorEditorModal({ emulator, onSaved, closeModal }: Props) {
  const [name, setName] = useState(emulator?.name ?? "");
  const [kind, setKind] = useState<"flatpak" | "path">(emulator?.kind ?? "flatpak");
  const [target, setTarget] = useState(emulator?.target ?? "");
  const [args, setArgs] = useState(emulator?.args ?? "{rom}");
  const [extensions, setExtensions] = useState((emulator?.extensions ?? []).join(", "));
  // Systems with no libretro database are identified by a synthetic id, so the
  // selection is tracked by id rather than by database name. See
  // `systemChoice.ts` for why an id can fail to name a row at all.
  const [systemId, setSystemId] = useState(initialSystemId(emulator));
  const [fullscreenArgs, setFullscreenArgs] = useState(emulator?.fullscreen_args ?? "");
  const [systems, setSystems] = useState<SystemOption[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listSystems()
      .then(setSystems)
      .catch(() => setSystems([]));
  }, []);

  /**
   * One list, ordered by the full "Manufacturer - System" name.
   *
   * Short names are what collections use, but they make a poor picker: they
   * scatter one manufacturer's systems across the alphabet (3DS, GBA, N64,
   * SNES, Switch, Wii) and only some carry the maker's name. The full names sort
   * every Nintendo system together. Whether libretro has artwork for a system is
   * a consequence of the choice rather than part of its name, so that stays in
   * the hint below.
   */
  const systemOptions: SingleDropdownOption[] = useMemo(
    () => [
      { data: "", label: "None" },
      ...(systems ?? []).map((system) => ({ data: system.id, label: system.label })),
    ],
    [systems],
  );

  const selectedSystem = (systems ?? []).find((entry) => entry.id === systemId);

  // An id that names no row means the record is describing a system this list
  // presents under a different id, not that it has none.
  useEffect(() => {
    const adopted = adoptedSystemId(systems, systemId, emulator);
    if (adopted) setSystemId(adopted);
  }, [systems, systemId, emulator]);

  /**
   * Fill in the launch recipe for a recognised emulator.
   *
   * Both fields are set together: a fullscreen flag placed before a positional
   * ROM path can swallow it, so some emulators need an explicit -g as well.
   * Only replaces values the user has not customised.
   */
  const applySuggestions = useCallback(
    (targetPath: string) => {
      if (!targetPath.trim()) return;
      suggestLaunchOptions(targetPath)
        .then((result) => {
          if (result.args && (!args.trim() || args.trim() === "{rom}")) {
            setArgs(result.args);
          }
          if (result.fullscreen_args && !fullscreenArgs.trim()) {
            setFullscreenArgs(result.fullscreen_args);
          }
        })
        .catch(() => undefined);
    },
    [args, fullscreenArgs],
  );

  const suggestForTarget = useCallback(() => applySuggestions(target), [applySuggestions, target]);

  const browse = useCallback(async () => {
    try {
      const picked = await openFilePicker(
        FileSelectionType.FILE,
        "/usr/bin",
        true,
        true,
        undefined,
        undefined,
        false,
        true,
      );
      const path = picked?.realpath || picked?.path || "";
      if (path) {
        setTarget(path);
        applySuggestions(path);
      }
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        console.error("[deckyemu] emulator picker failed", pickError);
      }
    }
  }, [applySuggestions]);

  const save = useCallback(async () => {
    setSaving(true);
    setError("");
    try {
      const result = await saveEmulator({
        id: emulator?.id,
        name,
        kind,
        target,
        args,
        extensions,
        fullscreen_args: fullscreenArgs,
        ...systemFields(systemId, selectedSystem, emulator),
      });
      if (!result.ok) {
        setError(result.error ?? "Could not save that emulator.");
        return;
      }
      if (result.notice) {
        toaster.toast({ title: name || "Emulator saved", body: result.notice });
      }
      onSaved();
      closeModal?.();
    } catch (saveError) {
      console.error("[deckyemu] could not save emulator", saveError);
      setError("Could not save that emulator.");
    } finally {
      setSaving(false);
    }
  }, [
    name,
    kind,
    target,
    args,
    extensions,
    fullscreenArgs,
    selectedSystem,
    systemId,
    emulator,
    onSaved,
    closeModal,
  ]);

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        {emulator ? `Edit ${emulator.name}` : "Add an emulator"}
      </div>

      <Focusable style={{ ...FIELD_GAP, gap: "14px", maxHeight: "58vh", overflowY: "auto" }}>
        <div style={FIELD_GAP}>
          <Label hint="Shown when choosing how to run a ROM.">Name</Label>
          <TextField value={name} onChange={(event) => setName(event.target.value)} />
        </div>

        <div style={FIELD_GAP}>
          <Label>How it is installed</Label>
          <Dropdown
            rgOptions={KIND_OPTIONS}
            selectedOption={kind}
            onChange={(option) => setKind(option.data as "flatpak" | "path")}
          />
        </div>

        <div style={FIELD_GAP}>
          <Label
            hint={
              kind === "flatpak"
                ? "Application id, e.g. org.DolphinEmu.dolphin-emu"
                : "Full path to the binary or AppImage"
            }
          >
            {kind === "flatpak" ? "Flatpak application id" : "Executable"}
          </Label>
          <TextField
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            onBlur={suggestForTarget}
          />
          {kind === "path" && (
            <DialogButton onClick={browse} style={{ width: "auto", minWidth: "140px" }}>
              Browse...
            </DialogButton>
          )}
        </div>

        <div style={FIELD_GAP}>
          <Label hint="Comma separated, e.g. iso, rvz, gcm, wbfs">File extensions</Label>
          <TextField
            value={extensions}
            onChange={(event) => setExtensions(event.target.value)}
          />
        </div>

        <div style={FIELD_GAP}>
          <Label
            hint={
              !selectedSystem
                ? "Determines the boxart source and the collection name. Pick the system this emulator runs."
                : selectedSystem.libretro
                  ? `Collections will call it "${selectedSystem.short}". Boxart from libretro thumbnails, or SteamGridDB if a key is set.`
                  : `Collections will call it "${selectedSystem.short}". libretro has no thumbnails for this system, so boxart comes from SteamGridDB — a key is recommended.`
            }
          >
            System
          </Label>
          {systems === null ? (
            <Spinner style={{ height: "20px" }} />
          ) : (
            <Dropdown
              rgOptions={systemOptions}
              selectedOption={systemId}
              onChange={(option) => setSystemId(String(option.data))}
            />
          )}
        </div>

        <div style={FIELD_GAP}>
          <Label hint="{rom} is replaced with the ROM path. Leave as-is unless the emulator needs flags.">
            Arguments
          </Label>
          <TextField value={args} onChange={(event) => setArgs(event.target.value)} />
        </div>

        <div style={FIELD_GAP}>
          <Label hint="Added when 'Launch fullscreen' is on in Settings. Every emulator uses a different switch, so this is per-emulator — e.g. -f, -fullscreen, --no-gui.">
            Fullscreen switch
          </Label>
          <TextField
            value={fullscreenArgs}
            onChange={(event) => setFullscreenArgs(event.target.value)}
          />
        </div>

        {/* Only for an emulator that exists: there is nothing to correct about
            one that has not been registered yet. */}
        {emulator?.id && <Workarounds emulatorId={emulator.id} />}
      </Focusable>

      {error && (
        <div style={{ color: "#e35d5d", fontSize: "13px", marginTop: "10px" }}>{error}</div>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
        <DialogButton onClick={save} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()} disabled={saving}>
          Cancel
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
