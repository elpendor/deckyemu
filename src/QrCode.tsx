import { useMemo } from "react";
import qrcode from "qrcode-generator";

/**
 * A QR code, for handing a URL to a phone that has a camera and a keyboard.
 *
 * Both directions of the file server -- sending files in, reading a report out
 * -- put the same kind of token URL on screen, and nobody types 22 characters
 * of random text into a phone. Same component, so the two stay scannable alike.
 */
export function QrCode({ text, size = 190 }: { text: string; size?: number }) {
  const svg = useMemo(() => {
    // Type 0 lets the library pick the smallest version that fits; "M" is the
    // usual balance of density against damage tolerance.
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    // createSvgTag scales to the requested size and needs no canvas.
    return qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true });
  }, [text]);

  return (
    <div
      style={{
        width: size,
        height: size,
        // A quiet zone is part of the spec; white behind it keeps the contrast
        // a camera needs whatever the surrounding theme is doing.
        background: "#ffffff",
        borderRadius: "8px",
        padding: "8px",
        boxSizing: "border-box",
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
