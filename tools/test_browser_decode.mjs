// Exercise the generated MoonBit JS export without a browser MP3 decoder.
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
execFileSync("moon", ["build", "examples/browser", "--target", "js", "--release", "--deny-warn"], {
  cwd: root, stdio: "inherit",
});
const built = path.join(root, "_build/js/release/build/examples/browser/browser.js");
const source = await readFile(built);
const { decode_mp3 } = await import(`data:text/javascript;base64,${source.toString("base64")}`);

let audio;
let error;
globalThis.mp3Demo = {
  receiveAudio(rate, channels, samples) { audio = { rate, channels, samples }; },
  receiveError(message) { error = message; },
};

const bytes = await readFile(path.join(root, "tests/corpus/upstream/M2L3_noise.bit"));
decode_mp3(new Uint8Array(bytes));
assert.equal(error, undefined);
assert.equal(audio.rate, 22050);
assert.equal(audio.channels, 2);
assert.equal(audio.samples.length, 444672);
assert(audio.samples.every(Number.isFinite));
console.log(`JS bridge: ${audio.rate} Hz, ${audio.channels} channels, ${audio.samples.length} samples`);

audio = undefined;
decode_mp3(new Uint8Array([1, 2, 3, 4]));
assert.equal(audio, undefined);
assert.match(error, /NoAudio|InvalidHeader/);
console.log(`JS bridge rejects malformed input: ${error}`);
