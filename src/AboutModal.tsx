import { Focusable, GamepadButton, ModalRoot, type GamepadEvent } from "@decky/ui";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { MUTED } from "./dialogStyle";
import { describe, FRONTEND_BUILD, FRONTEND_VERSION } from "./version";

const ASSETS =
  "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";

const RAW = (() => {
  const text = atob(ASSETS);
  const bytes = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
  return bytes;
})();

function fold(values: ArrayLike<number>, seed: number): number {
  let h = seed >>> 0;
  for (let i = 0; i < values.length; i++) h = Math.imul(h ^ values[i], 16777619) >>> 0;
  return h;
}

function word32(bytes: Uint8Array, at: number): number {
  return (
    ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0
  );
}

function part(index: number): Uint8Array {
  let at = 0;
  for (let i = 0; at + 4 <= RAW.length; i++) {
    const size = word32(RAW, at);
    at += 4;
    if (i === index) return RAW.subarray(at, at + size);
    at += size;
  }
  return new Uint8Array(0);
}

function open(index: number, key: number): Uint8Array | null {
  const cipher = part(index);
  if (cipher.length < 4) return null;
  const plain = new Uint8Array(cipher.length);
  let k = key >>> 0;
  for (let i = 0; i < cipher.length; i++) {
    k = Math.imul(k ^ i, 16777619) >>> 0;
    plain[i] = cipher[i] ^ ((k >>> 24) & 255);
  }
  const body = plain.subarray(4);
  return fold(body, 2166136261) === word32(plain, 0) ? body : null;
}

function reader(bytes: Uint8Array) {
  let at = 0;
  const decoder = new TextDecoder();
  return {
    byte: () => bytes[at++],
    long: () => {
      const value = word32(bytes, at);
      at += 4;
      return value;
    },
    span: (size: number) => {
      const slice = bytes.subarray(at, at + size);
      at += size;
      return slice;
    },
    text: () => {
      const size = (bytes[at] << 8) | bytes[at + 1];
      at += 2;
      return decoder.decode(bytes.subarray(at, (at += size)));
    },
  };
}

function lines(body: Uint8Array): string[] {
  const read = reader(body);
  const count = read.byte();
  const found: string[] = [];
  for (let i = 0; i < count; i++) found.push(read.text());
  return found;
}

interface Sheet {
  text: string;
  note: string;
  clip: Uint8Array | null;
}

function sheet(body: Uint8Array): Sheet {
  const read = reader(body);
  const cols = read.byte();
  const rows = read.byte();
  const shades = Array.from(read.span(10), (code) => String.fromCharCode(code));
  const cells = read.span((cols * rows + 1) >> 1);
  const drawn: string[] = [];
  for (let y = 0; y < rows; y++) {
    let line = "";
    for (let x = 0; x < cols; x++) {
      const cell = y * cols + x;
      const byte = cells[cell >> 1];
      line += shades[cell % 2 === 0 ? byte >> 4 : byte & 15];
    }
    drawn.push(line);
  }
  const note = read.text();
  const size = read.long();
  const clip = size > 0 ? new Uint8Array(read.span(size)) : null;
  return { text: drawn.join("\n"), note, clip };
}

const IDLE = 2200;

const OWED: readonly (readonly [string, string])[] = [
  ["libretro", "cores and metadata"],
  ["SteamGridDB", "artwork"],
  ["RetroAchievements", "achievements"],
  ["rclone", "cloud saves"],
  ["SteamDeckGyroDSU", "motion"],
  ["Decky Loader", "plugins"],
];

const NAME: CSSProperties = { fontSize: "26px", letterSpacing: "0.01em" };
const HEADING: CSSProperties = {
  fontSize: "11px",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  opacity: 0.6,
  marginTop: "22px",
};
const ROW: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: "12px",
  marginTop: "8px",
  fontSize: "15px",
};

interface Props {
  closeModal?: () => void;
}

export function AboutModal({ closeModal }: Props) {
  const [said, setSaid] = useState<readonly string[] | null>(null);
  const [shown, setShown] = useState<Sheet | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const marks = useRef<number[]>([]);
  const seed = useRef(0);
  const pressed = useRef<number[]>([]);
  const last = useRef({ button: -1, at: 0 });

  useEffect(() => {
    box.current?.focus();
  }, []);

  useEffect(() => {
    if (!shown?.clip) return;
    const ctx = new AudioContext();
    let source: AudioBufferSourceNode | null = null;
    ctx
      .decodeAudioData(shown.clip.buffer.slice(0) as ArrayBuffer)
      .then((buffer) => {
        source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        source.start();
      })
      .catch(() => undefined);
    return () => {
      source?.stop();
      void ctx.close();
    };
  }, [shown]);

  const onStamp = useCallback(() => {
    const now = Date.now();
    const since = now - (marks.current[marks.current.length - 1] ?? 0);
    const run = since > IDLE ? [now] : [...marks.current, now];
    marks.current = run.slice(-12);
    const gaps = run.slice(1).map((at, i) => at - run[i]);
    if (gaps.length < 3) return;
    const mid = [...gaps].sort((a, b) => a - b)[(gaps.length - 1) >> 1] || 1;
    const key = fold(
      gaps.map((gap) => (gap < mid * 0.75 ? 0 : gap > mid * 1.6 ? 2 : 1)),
      2166136261,
    );
    const body = open(0, key);
    if (!body) return;
    marks.current = [];
    seed.current = key;
    setSaid(lines(body));
  }, []);

  const feed = useCallback((button: number) => {
    const now = Date.now();
    const since = now - last.current.at;
    if (button === last.current.button && since < 40) return;
    last.current = { button, at: now };
    const run = since > IDLE ? [button] : [...pressed.current, button];
    pressed.current = run.slice(-16);
    const body = open(1, fold(run, seed.current));
    if (body) setShown(sheet(body));
  }, []);

  const waiting = said !== null && shown === null;

  const onButtonDown = useCallback(
    (evt: GamepadEvent) => {
      if (!waiting || evt.detail.is_repeat) return;
      feed(evt.detail.button);
    },
    [waiting, feed],
  );

  const onActivate = useCallback(() => {
    if (waiting) feed(GamepadButton.OK);
  }, [waiting, feed]);

  const onCancelButton = useCallback(() => {
    if (!waiting) {
      closeModal?.();
      return;
    }
    feed(GamepadButton.CANCEL);
  }, [waiting, feed, closeModal]);

  return (
    <ModalRoot closeModal={closeModal}>
      <Focusable
        ref={box}
        noFocusRing
        preferredFocus
        onActivate={onActivate}
        onButtonDown={onButtonDown}
        onCancelButton={onCancelButton}
        style={{ outline: "none" }}
      >
        {shown ? (
          <>
            <div style={{ display: "flex", justifyContent: "center", overflow: "clip" }}>
              <pre
                style={{
                  margin: 0,
                  fontFamily: "monospace",
                  fontSize: "0.97vh",
                  lineHeight: 1.2,
                  letterSpacing: 0,
                  whiteSpace: "pre",
                }}
              >
                {shown.text}
              </pre>
            </div>
            <div style={{ ...MUTED, marginTop: "10px", textAlign: "center" }}>{shown.note}</div>
          </>
        ) : said ? (
          <div style={{ padding: "22px 8px 6px", textAlign: "center" }}>
            <div style={{ fontSize: "21px", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
              {said[0]}
            </div>
            <div style={{ ...MUTED, marginTop: "18px", fontSize: "12px" }}>{said[1]}</div>
          </div>
        ) : (
          <div style={{ padding: "4px 2px" }}>
            <div style={{ ...ROW, marginTop: 0, alignItems: "baseline" }}>
              <div style={NAME}>DeckyEmu</div>
              <div style={MUTED} onClick={onStamp}>
                {describe(FRONTEND_VERSION, FRONTEND_BUILD)}
              </div>
            </div>
            <div style={HEADING}>Built on work by</div>
            {OWED.map(([who, what]) => (
              <div key={who} style={ROW}>
                <div>{who}</div>
                <div style={{ ...MUTED, textAlign: "right" }}>{what}</div>
              </div>
            ))}
            <div style={{ ...MUTED, marginTop: "20px" }}>github.com/elpendor/deckyemu</div>
          </div>
        )}
      </Focusable>
    </ModalRoot>
  );
}
