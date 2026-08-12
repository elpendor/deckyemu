import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Spinner,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  installCore,
  listInstallableCores,
  uninstallCore,
  type InstallableCore,
} from "./backend";
import { callWithRetry } from "./timeout";

interface Props {
  /** Bumped by the parent whenever the installed core set changes. */
  onCoresChanged: () => void;
  /**
   * Changes when something outside this panel deleted cores — the development
   * Reset tab. The catalog cache below is module-level and outlives the panel,
   * so nothing else would ever make it re-read.
   */
  reloadKey?: number;
}

// Steam unmounts Quick Access content whenever a modal opens, so this panel is
// remounted constantly. Caching the catalog at module scope keeps that from
// re-fetching 188 entries every time. Also remembers the user's place in the
// list across remounts.
let cachedCatalog: InstallableCore[] | null = null;
let lastSystem = "";
let lastCoreId = "";

export function CoreInstallPanel({ onCoresChanged, reloadKey = 0 }: Props) {
  const [catalog, setCatalog] = useState<InstallableCore[] | null>(cachedCatalog);
  const [system, setSystem] = useState(lastSystem);
  const [coreId, setCoreId] = useState(lastCoreId);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (refresh: boolean) => {
    setError("");
    try {
      const loaded = await callWithRetry(() => listInstallableCores(refresh), {
        attempts: 2,
        ms: 30000,
      });
      cachedCatalog = loaded;
      setCatalog(loaded);
    } catch (loadError) {
      console.error("[retroarch] could not load core catalog", loadError);
      setError("Could not reach the libretro buildbot.");
      setCatalog([]);
    }
  }, []);

  useEffect(() => {
    // Only hit the backend when we have nothing cached, or after an install
    // changed the installed flags.
    if (cachedCatalog === null) void load(false);
  }, [load]);

  // Something outside this panel changed what is installed — today that is the
  // development Reset tab. The cache is module-level and outlives the panel, so
  // without this it kept offering to remove a core that had been deleted, and
  // only "Refresh catalog" put it right.
  useEffect(() => {
    if (reloadKey) void load(false);
  }, [reloadKey, load]);

  const systems = useMemo(() => {
    if (!catalog) return [];
    const names = new Set(catalog.map((core) => core.system_name).filter(Boolean));
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [catalog]);

  const systemOptions: SingleDropdownOption[] = useMemo(
    () => systems.map((name) => ({ data: name, label: name })),
    [systems],
  );

  const coresForSystem = useMemo(
    () => (catalog ?? []).filter((core) => core.system_name === system),
    [catalog, system],
  );

  const coreOptions: SingleDropdownOption[] = useMemo(
    () =>
      coresForSystem.map((core) => ({
        data: core.id,
        label: core.installed ? `${core.display_name} (installed)` : core.display_name,
      })),
    [coresForSystem],
  );

  const selected = coresForSystem.find((core) => core.id === coreId);

  const onSystemChange = useCallback(
    (option: SingleDropdownOption) => {
      const next = String(option.data);
      setSystem(next);
      lastSystem = next;
      const first = (catalog ?? []).find((core) => core.system_name === next);
      setCoreId(first?.id ?? "");
      lastCoreId = first?.id ?? "";
    },
    [catalog],
  );

  const doInstall = useCallback(async () => {
    if (!selected) return;
    setBusy(selected.id);
    setError("");
    try {
      const result = await installCore(selected.id);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      toaster.toast({
        title: `Installed ${selected.display_name}`,
        body: `${result.core_count} core(s) now available`,
      });
      await load(false);
      onCoresChanged();
    } catch (installError) {
      console.error("[retroarch] core install failed", installError);
      setError("Install failed. Check the plugin log for details.");
    } finally {
      setBusy("");
    }
  }, [selected, load, onCoresChanged]);

  const doUninstall = useCallback(async () => {
    if (!selected) return;
    setBusy(selected.id);
    setError("");
    try {
      const result = await uninstallCore(selected.id);
      if (!result.ok) {
        setError(result.error ?? "Could not remove the core.");
        return;
      }
      toaster.toast({
        title: `Removed ${selected.display_name}`,
        body: `${result.core_count ?? 0} core(s) remaining`,
      });
      await load(false);
      onCoresChanged();
    } finally {
      setBusy("");
    }
  }, [selected, load, onCoresChanged]);

  if (!catalog) {
    return (
      <PanelSection title="Install cores">
        <PanelSectionRow>
          <Field label="Loading core catalog">
            <Spinner style={{ height: "20px" }} />
          </Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <PanelSection title="Install cores">
      <PanelSectionRow>
        <DropdownItem
          label="System"
          description={`${catalog.length} cores across ${systems.length} systems`}
          rgOptions={systemOptions}
          selectedOption={system}
          onChange={onSystemChange}
          disabled={Boolean(busy)}
        />
      </PanelSectionRow>

      {system && (
        <PanelSectionRow>
          <DropdownItem
            label="Core"
            rgOptions={coreOptions}
            selectedOption={coreId}
            onChange={(option) => {
              setCoreId(String(option.data));
              lastCoreId = String(option.data);
            }}
            disabled={Boolean(busy) || coreOptions.length === 0}
          />
        </PanelSectionRow>
      )}

      {selected && (
        <PanelSectionRow>
          <Field
            label="Handles"
            description={selected.extensions.map((ext) => `.${ext}`).join(" ")}
          />
        </PanelSectionRow>
      )}

      {error && (
        <PanelSectionRow>
          <div style={{ color: "#e35d5d", fontSize: "13px", padding: "4px 0" }}>{error}</div>
        </PanelSectionRow>
      )}

      {selected && !selected.installed && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={doInstall} disabled={Boolean(busy)}>
            {busy === selected.id ? "Installing..." : `Install ${selected.display_name}`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {selected?.installed && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={doUninstall} disabled={Boolean(busy)}>
            {busy === selected.id ? "Removing..." : "Remove this core"}
          </ButtonItem>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void load(true)} disabled={Boolean(busy)}>
          Refresh catalog
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
