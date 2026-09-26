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
const input = new Uint8Array(bytes);
const defaultLimit = 10000000;
decode_mp3(input, defaultLimit);
assert.equal(error, undefined);
assert.equal(audio.rate, 22050);
assert.equal(audio.channels, 2);
assert.equal(audio.samples.length, 444672);
assert(audio.samples.every(Number.isFinite));
console.log(`JS bridge: ${audio.rate} Hz, ${audio.channels} channels, ${audio.samples.length} samples`);

const sampleCount = audio.samples.length;
for (const limit of [sampleCount, sampleCount - 1, defaultLimit]) {
  audio = undefined;
  error = undefined;
  decode_mp3(input, limit);
  if (limit < sampleCount) {
    assert.equal(audio, undefined);
    assert.match(error, /OutputLimit/);
  } else {
    assert.equal(error, undefined);
    assert.equal(audio.samples.length, sampleCount);
  }
}
console.log(`JS bridge PCM limit: ${sampleCount} succeeds, ${sampleCount - 1} rejects, higher limit restores decoding`);

const repetitions = 23;
const longInput = new Uint8Array(input.length * repetitions);
for (let i = 0; i < repetitions; i++) longInput.set(input, i * input.length);
const longSampleCount = sampleCount * repetitions;
assert(longSampleCount > defaultLimit);
audio = undefined;
error = undefined;
decode_mp3(longInput, defaultLimit);
assert.equal(audio, undefined);
assert.match(error, /OutputLimit/);
error = undefined;
decode_mp3(longInput, longSampleCount);
assert.equal(error, undefined);
assert.equal(audio.rate, 22050);
assert.equal(audio.channels, 2);
assert.equal(audio.samples.length, longSampleCount);
console.log(`JS bridge raised PCM limit: ${defaultLimit} rejects, ${longSampleCount} succeeds`);

for (const limit of [undefined, null, "10000000", true, 0, -1, 1.5, NaN, Infinity, -Infinity, 2147483648, 4294967297]) {
  audio = undefined;
  error = undefined;
  decode_mp3(input, limit);
  assert.equal(audio, undefined);
  assert.match(error, /InvalidLimits/);
}
console.log("JS bridge rejects invalid, fractional, and out-of-range PCM limits");

audio = undefined;
error = undefined;
decode_mp3(new Uint8Array([1, 2, 3, 4]), defaultLimit);
assert.equal(audio, undefined);
assert.match(error, /NoAudio|InvalidHeader/);
console.log(`JS bridge rejects malformed input: ${error}`);
