import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSectionRow,
} from "@decky/ui";

import { type RomProbe } from "./backend";
import { InstallProgress } from "./InstallProgress";
import { PackagedGamesModal } from "./PackagedGamesModal";
import { VitaGamesModal } from "./VitaGamesModal";
import { type LicenceChoice, type MissingEmulator, type PackagedGame } from "./packageState";
import { updateDraft } from "./romDraft";
import { openModal } from "./modalStack";

/**
 * The rows the add panel shows for a game that arrived as a package.
 *
 * Three consoles hand over a `.pkg`, and each needs saying before the install
 * rather than after it -- a PS3 store game wants its `.rap` under the content
 * id, a Vita package cannot be decrypted without its zRIF, and neither failure
 * announces itself as anything but a black screen. That is most of what these
 * rows are: findings with an action, placed above the button rather than inside
 * a disabled one.
 *
 * Split out of AddGamePanel, where they were two hundred lines of one six
 * hundred line `return`. They are here as components rather than a function
 * returning an array so the conditions stay next to the markup they guard.
 */

/** For a sentence, where "ps3" would read as a filename. */
const CONSOLE_NAMES = {
  ps3: "PlayStation 3",
  ps4: "PlayStation 4",
  vita: "PlayStation Vita",
} as const;

interface EntryProps {
  ps3Count: number;
  ps4Count: number;
  vitaCount: number;
  disabled: boolean;
  onGameAdded: () => void;
}

/**
 * The way back to games these emulators already have installed.
 *
 * A PS3 or PS4 game is the one thing with no ROM to point the picker at: the
 * `.pkg` was consumed installing it, and what boots lives inside a hidden
 * directory under a product code. Without these rows, a game removed from the
 * library and kept on disk could only be added back by typing that path.
 *
 * Counted rather than listed, and counted after subtracting what is already in
 * the library, so the number on the button matches the number of rows behind
 * it. Advertising "(2)" and opening an empty list is worse than no button.
 */
export function PackagedGameEntries({
  ps3Count,
  ps4Count,
  vitaCount,
  disabled,
  onGameAdded,
}: EntryProps) {
  return (
    <>
      {ps3Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<PackagedGamesModal system="ps3" />)}
            disabled={disabled}
            description="Games RPCS3 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 3 games in RPCS3 (${ps3Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {ps4Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<PackagedGamesModal system="ps4" />)}
            disabled={disabled}
            description="Games shadPS4 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 4 games in shadPS4 (${ps4Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {/* Vita3K installs and decrypts its own games, so unlike every other
          system here there is no file to pick — the installed list is the only
          door in. */}
      {vitaCount > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<VitaGamesModal onAdded={onGameAdded} />)}
            disabled={disabled}
            description="Games Vita3K has installed. It decrypts them as it installs, so they are added from here rather than by choosing a file."
          >
            {`PlayStation Vita games in Vita3K (${vitaCount})`}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

interface PendingProps {
  packaged: PackagedGame | null;
  probe?: RomProbe | null;
  licence: LicenceChoice;
  unpacking: boolean;
  unpackPercent: number;
  unpackStatus: string;
  adding: boolean;
  onInstall: (keyName: string) => void;
  /** The emulator this package needs, when it is not installed yet. */
  missing: MissingEmulator | null;
  /** Install that emulator and carry straight on into unpacking. */
  onInstallEmulator: () => void;
  /** Set while that install is running, so the row can show it. */
  installingEmulator: boolean;
  emulatorPercent: number;
  emulatorStatus: string;
}

/** What is known about a package before it is installed, and the button. */
export function PendingPackageRows({
  packaged,
  probe,
  licence,
  unpacking,
  unpackPercent,
  unpackStatus,
  adding,
  onInstall,
  missing,
  onInstallEmulator,
  installingEmulator,
  emulatorPercent,
  emulatorStatus,
}: PendingProps) {
  const { candidates, chosen, blocked } = licence;
  return (
    <>
      {/* The emulator, before anything else this package needs.
          A package is not a file anything can be pointed at -- it is installed
          *into* an emulator -- so with that emulator missing every other row
          here is advice about a step that cannot be reached. It used to be
          found out by pressing Install: RPCS3 and Vita3K refused straight away,
          and shadPS4 was not asked at all, so a PS4 package unpacked for
          minutes, deleted its own .pkg and failed at the very end with nowhere
          to put the result.

          Offered here rather than as a link to the Emulators tab, which is what
          the game editor does for a missing core: leaving the panel loses the
          picked file, and coming back means finding it again. The catalog
          install is one call, so the same press can do both. */}
      {missing && (
        <PanelSectionRow>
          {installingEmulator ? (
            <InstallProgress
              label={`Installing ${missing.name}`}
              percent={emulatorPercent}
              status={emulatorStatus}
            />
          ) : (
            <ButtonItem
              layout="below"
              onClick={onInstallEmulator}
              disabled={adding || unpacking}
              description={
                `A ${CONSOLE_NAMES[packaged!.system]} package is installed into ${missing.name}, ` +
                `and it is not here yet. This installs it and then unpacks the game.` +
                // Necessary but not sufficient, and worth knowing before the
                // download rather than at the black screen afterwards.
                (missing.needsFirmware
                  ? ` ${missing.name} also needs its firmware before games will boot — the panel says so once it is installed.`
                  : "")
              }
            >
              {`Install ${missing.name} and unpack this game`}
            </ButtonItem>
          )}
        </PanelSectionRow>
      )}
      {/* A PS3 store game needs its .rap, and RPCS3 reads one only under the
          package's own content id. Said here, before the install, because the
          alternative is finding out from "Failed to decrypt content" on a
          black screen — and because naming the file is the whole fix. */}
      {/* Shown while the package is still a package, which is the only moment
          this can be known: the content id comes out of the .pkg header, and
          the .pkg is deleted once it installs. It is also the moment the
          warning is most use, since the licence can be sent before unpacking
          rather than discovered afterwards. */}
      {packaged?.system === "ps3" &&
        packaged.state.licence_state === "" &&
        packaged.state.content_id && (
          <PanelSectionRow>
            <Field
              label="No licence for this game"
              description={
                `Store games need a .rap licence. Send it to the same folder as ` +
                `the game and it goes in when the game does — it is renamed for ` +
                `you. If there is more than one .rap there, name this one ` +
                `${packaged.state.content_id}.rap so it can be told apart. ` +
                `Licence-free games work without one.`
              }
            />
          </PanelSectionRow>
        )}

      {/* Said even though there is nothing to do, because the alternative is
          what happened: a licence already in place looks exactly like a check
          that never ran, and the only way to tell them apart was to go and
          look in exdata over ssh. All three answers are now visible. */}
      {packaged?.system === "ps3" && packaged.state.licence_state === "installed" && (
        <PanelSectionRow>
          <Field
            label="Licence installed"
            description="RPCS3 already has this game's .rap, from an earlier install. Nothing to send."
          />
        </PanelSectionRow>
      )}

      {/* Nothing to do — the install puts it in place. Said anyway, because
          "your licence is here and will be used" is worth knowing before
          pressing a button on a game that would otherwise not boot. */}
      {packaged?.system === "ps3" && packaged.state.licence_state === "waiting" && (
        <PanelSectionRow>
          <Field
            label="Licence found"
            description="This game's .rap is here and will be installed along with it."
          />
        </PanelSectionRow>
      )}

      {/* A .vpk or a NoNpDrm .zip. Recognised so it can be explained: this is
          the one console whose content cannot be handed over as a file. Vita3K
          decrypts as it installs, and its own launcher re-splits any path with
          a space in it, so a shortcut pointing at this file could never work —
          which is what it used to offer, failing only at launch. */}
      {probe?.vita_release?.vita && (
        <PanelSectionRow>
          <Field
            label="PS Vita releases are installed, not opened"
            description={
              `${probe.vita_release.title || "This release"} has to be installed into Vita3K before ` +
              `it can be added, because Vita3K decrypts games as it installs them. Two ways in: send ` +
              `the game as a .pkg with its .zrif key and this panel installs it for you, or install ` +
              `this file from Vita3K's own interface on the Emulators tab. Either way it then appears ` +
              `under "PlayStation Vita games in Vita3K" here.`
            }
          />
        </PanelSectionRow>
      )}

      {/* The licence, said before the button rather than inside it.
          Vita3K cannot install a package without the zRIF that decrypts it and
          cannot derive one, so this is the whole of what stands between the
          file being here and the game being installed — which makes it a
          finding with an action, not a footnote on a control that is greyed
          out. Two different problems, because they have different answers. */}
      {packaged?.system === "vita" && packaged.state.licence === false && (
        <>
          <PanelSectionRow>
            <Field
              label={
                candidates.length > 0
                  ? "Which key is this game's?"
                  : "This package needs its licence key"
              }
              description={
                candidates.length > 0
                  ? // There is a key here, but nothing ties it to this package.
                    // Using it anyway is what installed a gigabyte and a half
                    // under another game's licence, so it is offered by name
                    // and pressed by a person who can see the name.
                    `Nothing here is named for ${packaged.state.title_id || "this package"}, so it cannot be ` +
                    `matched automatically. Pick the one that came with this game, or send it again as ` +
                    `${packaged.state.licence_name || "the title id with a .zrif extension"} and it will be ` +
                    `used without asking. The wrong key installs the whole game and then fails to decrypt it.`
                  : `Vita3K decrypts a package as it installs and cannot work the key out, so it has to be here too. ` +
                    `Send it to the same folder as the game — a .zrif or a .txt with the key in it, named ` +
                    `${packaged.state.licence_name || "after the title id"}. It is picked up as soon as it lands.`
              }
            />
          </PanelSectionRow>

          {/* The same shape as "Run with" above: choose, then press the one
              install button, which names the choice so the filename is still
              readable without opening the list. */}
          {!unpacking && candidates.length > 0 && (
            <PanelSectionRow>
              <DropdownItem
                // Filenames, and long ones -- a licence is named after the game
                // it unlocks. Half a row truncates them where they are still
                // identical to each other.
                layout="below"
                label="Licence key"
                description="The file that came with this game. Picking the wrong one installs it and then fails to decrypt it."
                rgOptions={candidates.map((name) => ({ data: name, label: name }))}
                selectedOption={chosen}
                // Written to the draft, not to component state: opening this
                // dropdown opens a ContextMenu and Steam unmounts the panel
                // behind it, so a choice held in useState is discarded on the
                // way back and the control snaps to the first entry.
                onChange={(option) => updateDraft({ keyChoice: String(option.data) })}
                disabled={adding}
              />
            </PanelSectionRow>
          )}
        </>
      )}

      {packaged && !missing && (
        <PanelSectionRow>
          {unpacking ? (
            <InstallProgress
              label={
                packaged.system === "ps4"
                  ? "Installing into shadPS4"
                  : packaged.system === "vita"
                    ? "Installing into Vita3K"
                    : "Installing into RPCS3"
              }
              percent={unpackPercent}
              status={unpackStatus}
            />
          ) : (
            <ButtonItem
              layout="below"
              // `chosen` is empty for every console but Vita, and for Vita
              // whenever the backend matched the key by name itself -- which is
              // the case where it must stay empty, because a name the user did
              // not choose is not one to send back as though they had.
              onClick={() => onInstall(chosen)}
              // Refused rather than allowed to fail: without a key Vita3K
              // reports a corrupt package, which reads as a bad download.
              disabled={adding || blocked}
              // One shape for all three: what the package is not yet, the one
              // thing that is different about this console, then the .pkg being
              // deleted. They were written separately and read like three
              // different features -- three lengths, three orders, and the
              // shared facts phrased differently each time.
              //
              // What went is what is already said elsewhere on the panel. The
              // PS3 licence had a sentence here and has its own row above in all
              // three of its states; "no window and nothing to press" was said
              // twice for Vita. A description that repeats the row above it is
              // one more thing to read and no more information.
              description={
                packaged.system === "vita"
                  ? // What is missing is said in its own row above, not here:
                    // this description belongs to a button that cannot be
                    // pressed, and a disabled control is the last place to put
                    // the one thing the reader has to act on.
                    blocked
                    ? "Waiting for the licence key — see above."
                    : chosen
                      ? // Named again at the moment of pressing. The dropdown is
                        // above and may well be scrolled off, and this is the
                        // press that spends a gigabyte or two on the answer
                        // being right.
                        `A PlayStation Vita package is not a game until Vita3K installs it. ` +
                        `Using ${chosen} to decrypt it — the wrong key installs the game and then fails. ` +
                        `The .pkg is deleted afterwards.`
                      : "A PlayStation Vita package is not a game until Vita3K installs it. " +
                        "It decrypts as it installs, using the key found beside it. " +
                        "The .pkg is deleted afterwards."
                  : packaged.system === "ps4"
                    ? // Where the extractor comes from is kept: it is the one
                      // thing here that downloads something the emulator did not
                      // bring, and that is worth a clause before it happens.
                      "A PlayStation 4 package is not a game until it is unpacked. " +
                      "shadPS4 cannot do that itself, so the first one fetches a small " +
                      "extractor built from its own code — large games take a while. " +
                      "The .pkg is deleted afterwards."
                    : "A PlayStation 3 package is not a game until RPCS3 unpacks it. " +
                      "This takes a few seconds and opens no windows. " +
                      "The .pkg is deleted afterwards."
              }
            >
              {/* "Install", not "Unpack", on all three. Only RPCS3 and the PS4
                  extractor literally unpack anything -- Vita3K installs -- and
                  the word the user cares about is the same in every case: the
                  game ends up in the emulator. */}
              {/* No name in it. It said the product code once -- "Install
                  PCSA00011" -- and then the filename, and the row above this
                  one is the picker, which shows the file that was chosen. A
                  button repeating what is directly above it is one more thing
                  to read and no more information. */}
              Install this game
            </ButtonItem>
          )}
        </PanelSectionRow>
      )}
    </>
  );
}
