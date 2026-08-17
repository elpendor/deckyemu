import {
  DialogButton,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
} from "@decky/ui";
import { useCallback, useEffect, useState } from "react";

import {
  applyArtCandidate,
  listArtCandidates,
  type AppliedArt,
  type ArtCandidates,
} from "./backend";
import { callWithRetry } from "./timeout";

interface Props {
  romPath: string;
  coreId: string;
  /**
   * What to search for first, when the filename cannot say.
   *
   * A game installed from a package boots `eboot.bin`, so the backend's default
   * term -- the filename -- searches for "Eboot" and finds the same nothing for
   * every PS3, PS4 and Vita game. The name the game is already under is the
   * only thing here that identifies it.
   */
  initialQuery?: string;
  /** Applied artwork, so the panel can show the corrected preview. */
  onApplied: (result: Extract<AppliedArt, { ok: true }>) => void;
  closeModal?: () => void;
}

interface Row {
  key: string;
  source: "libretro" | "steamgriddb";
  ref: string;
  system: string;
  label: string;
  sublabel: string;
}

/**
 * Lets the user correct a wrong artwork match.
 *
 * Automatic matching is good but not infallible -- SteamGridDB's search is
 * fuzzy, and a ROM named unlike its database entry can land on the wrong game.
 * The search box matters as much as the list: when both sources mis-identify a
 * ROM, typing the real name is the only way out.
 */
export function ArtPickerModal({
  romPath,
  coreId,
  initialQuery = "",
  onApplied,
  closeModal,
}: Props) {
  const [candidates, setCandidates] = useState<ArtCandidates | null>(null);
  // Seeded, so the box shows what was searched for and can be edited from it
  // rather than retyped.
  const [query, setQuery] = useState(initialQuery);
  const [searching, setSearching] = useState(true);
  const [applying, setApplying] = useState("");
  const [error, setError] = useState("");

  const search = useCallback(
    async (term: string) => {
      setSearching(true);
      setError("");
      try {
        const result = await callWithRetry(() => listArtCandidates(romPath, coreId, term), {
          attempts: 2,
          ms: 30000,
        });
        setCandidates(result);
        if (!term) setQuery(result.query);
      } catch (searchError) {
        console.error("[deckyemu] artwork search failed", searchError);
        setError("Could not search for artwork.");
      } finally {
        setSearching(false);
      }
    },
    [romPath, coreId],
  );

  useEffect(() => {
    void search(initialQuery);
  }, [search, initialQuery]);

  const apply = useCallback(
    async (row: Row) => {
      setApplying(row.key);
      setError("");
      try {
        const result = await applyArtCandidate(
          row.source, row.ref, row.system, row.label,
        );
        if (!result.ok) {
          setError(result.error);
          return;
        }
        onApplied(result);
        closeModal?.();
      } catch (applyError) {
        console.error("[deckyemu] could not apply artwork", applyError);
        setError("Could not download that artwork.");
      } finally {
        setApplying("");
      }
    },
    [onApplied, closeModal],
  );

  const rows: Row[] = [];
  for (const hit of candidates?.steamgriddb ?? []) {
    rows.push({
      key: `sgdb-${hit.id}`,
      source: "steamgriddb",
      ref: String(hit.id),
      system: "",
      label: hit.name,
      sublabel: `SteamGridDB${hit.year ? ` · ${hit.year}` : ""}`,
    });
  }
  for (const hit of candidates?.libretro ?? []) {
    rows.push({
      key: `libretro-${hit.system}-${hit.name}`,
      source: "libretro",
      ref: hit.name,
      system: hit.system,
      label: hit.name,
      sublabel: `libretro · ${hit.system}`,
    });
  }

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Choose the right game
      </div>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        The name comes from what you choose here, unless you have already
        written your own. Search by name if the right game is not listed.
      </div>

      <Focusable style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
        <div style={{ flexGrow: 1 }}>
          <TextField
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            disabled={searching}
          />
        </div>
        <DialogButton
          onClick={() => void search(query)}
          disabled={searching || !query.trim()}
          style={{ width: "auto", minWidth: "100px" }}
        >
          Search
        </DialogButton>
      </Focusable>

      {error && (
        <div style={{ color: "#e35d5d", fontSize: "13px", marginBottom: "8px" }}>{error}</div>
      )}

      {searching && (
        <div style={{ display: "flex", justifyContent: "center", padding: "20px" }}>
          <Spinner style={{ height: "32px" }} />
        </div>
      )}

      {!searching && rows.length === 0 && (
        <div style={{ opacity: 0.7, padding: "12px 0" }}>
          Nothing found for that name.
          {candidates && !candidates.sgdb_available
            ? " Adding a SteamGridDB key would widen the search."
            : ""}
        </div>
      )}

      {!searching && (
        <Focusable
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "4px",
            maxHeight: "45vh",
            overflowY: "auto",
          }}
        >
          {rows.map((row) => (
            <DialogButton
              key={row.key}
              onClick={() => void apply(row)}
              disabled={Boolean(applying)}
              style={{
                textAlign: "left",
                padding: "10px 12px",
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-start",
                gap: "2px",
              }}
            >
              <span>{applying === row.key ? "Applying..." : row.label}</span>
              <span style={{ fontSize: "12px", opacity: 0.6 }}>{row.sublabel}</span>
            </DialogButton>
          ))}
        </Focusable>
      )}
    </ModalRoot>
  );
}
