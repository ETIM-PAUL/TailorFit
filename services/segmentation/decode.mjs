// Decodes SAM masks with Meta's @meta-sam/parser (installed dependency, not copied code).
// stdin:  JSON array of {encoding: "one_bit"|"lossless", payload, width, height}
// stdout: JSON array of base64 strings, each a row-major width*height raster of 0/1 bytes.
import { decodeMaskToRaster } from "@meta-sam/parser";

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const masks = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const out = masks.map((m) => Buffer.from(decodeMaskToRaster(m)).toString("base64"));
process.stdout.write(JSON.stringify(out));
