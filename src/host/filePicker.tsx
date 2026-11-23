/**
 * Choosing a file or a folder on the Deck, with a controller.
 *
 * The listing comes from the service (`host.list_dir`), which can read the
 * whole disk; this is only the dialog. Cancelling rejects with an error whose
 * message says "cancel", which is what every caller tests for.
 */

import { useCallback, useEffect, useState } from "react";

import { DialogButton, DialogFooter, DialogHeader, Focusable, ModalRoot, Spinner } from "../steamui";
import { openModal } from "../modalStack";
import { call } from "./channel";

export enum FileSelectionType {
  FILE = 0,
  FOLDER = 1,
}

export interface FilePickerResult {
  path: string;
  realpath: string;
}

interface Entry {
  name: string;
  is_dir: boolean;
}

interface Listing {
  path: string;
  realpath: string;
  parent: string | null;
  entries: Entry[];
  error?: string;
}

interface PickerProps {
  select: FileSelectionType;
  startPath: string;
  includeFiles: boolean;
  includeFolders: boolean;
  extensions?: string[];
  showHidden: boolean;
  filter?: RegExp | ((file: { name: string }) => boolean);
  done(result: FilePickerResult | null): void;
  closeModal?: () => void;
}

const join = (dir: string, name: string) => (dir.endsWith("/") ? dir + name : `${dir}/${name}`);

function FilePicker(props: PickerProps) {
  const { select, includeFiles, extensions, showHidden, filter, done, closeModal } = props;
  const [listing, setListing] = useState<Listing | null>(null);
  const [path, setPath] = useState(props.startPath || "/");

  useEffect(() => {
    let live = true;
    setListing(null);
    call<Listing>("host.list_dir", path, select === FileSelectionType.FILE && includeFiles, showHidden, extensions ?? [])
      .then((result) => live && setListing(result))
      .catch((error) => live && setListing({ path, realpath: path, parent: null, entries: [], error: String(error) }));
    return () => {
      live = false;
    };
  }, [path, select, includeFiles, showHidden, extensions]);

  const finish = useCallback(
    (result: FilePickerResult | null) => {
      done(result);
      closeModal?.();
    },
    [done, closeModal],
  );

  const shown = (listing?.entries ?? []).filter((entry) => {
    if (entry.is_dir) return true;
    if (!filter) return true;
    return typeof filter === "function" ? filter({ name: entry.name }) : filter.test(entry.name);
  });

  return (
    <ModalRoot onCancel={() => finish(null)} closeModal={() => finish(null)}>
      <DialogHeader>{select === FileSelectionType.FOLDER ? "Choose a folder" : "Choose a file"}</DialogHeader>
      <div style={{ fontSize: "13px", opacity: 0.7, marginBottom: "8px", wordBreak: "break-all" }}>
        {listing?.realpath ?? path}
      </div>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "50vh", overflowY: "auto" }}>
        {listing?.parent && (
          <DialogButton onClick={() => setPath(listing.parent!)}>.. (up one folder)</DialogButton>
        )}
        {listing === null && <Spinner style={{ height: "32px" }} />}
        {listing?.error && <div>{listing.error}</div>}
        {shown.map((entry) => (
          <DialogButton
            key={entry.name}
            style={{ textAlign: "left" }}
            onClick={() => {
              const full = join(listing!.realpath, entry.name);
              if (entry.is_dir) setPath(full);
              else finish({ path: full, realpath: full });
            }}
          >
            {entry.is_dir ? `📁 ${entry.name}` : entry.name}
          </DialogButton>
        ))}
        {listing && !listing.error && shown.length === 0 && <div style={{ opacity: 0.7 }}>Nothing here.</div>}
      </Focusable>
      <DialogFooter>
        <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
          {select === FileSelectionType.FOLDER && listing && !listing.error && (
            <DialogButton onClick={() => finish({ path: listing.path, realpath: listing.realpath })}>
              Use this folder
            </DialogButton>
          )}
          <DialogButton onClick={() => finish(null)}>Cancel</DialogButton>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}

/** Same arguments, in the same order, as every call site already passes. */
export function openFilePicker(
  select: FileSelectionType,
  startPath: string,
  includeFiles = true,
  includeFolders = true,
  filter?: RegExp | ((file: { name: string }) => boolean),
  extensions?: string[],
  showHidden = false,
  _allowAllFiles = true,
): Promise<FilePickerResult> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (result: FilePickerResult | null) => {
      if (settled) return;
      settled = true;
      if (result) resolve(result);
      else reject(new Error("User canceled"));
    };
    try {
      openModal(
        <FilePicker
          select={select}
          startPath={startPath}
          includeFiles={includeFiles}
          includeFolders={includeFolders}
          extensions={extensions}
          showHidden={showHidden}
          filter={filter}
          done={done}
        />,
      );
    } catch (error) {
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}
