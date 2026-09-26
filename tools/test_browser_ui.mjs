// Optional Edge/Playwright smoke test; install playwright-core under target/browser-test first.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { chromium } = require("../target/browser-test/node_modules/playwright-core");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const url = process.argv[2] ?? "http://127.0.0.1:9010/examples/browser/";
const edge = process.env.EDGE_PATH ??
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

const browser = await chromium.launch({ executablePath: edge, headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(url, { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(root, "target/browser-test/desktop.png") });
  assert.equal(await page.locator("#state-badge").textContent(), "Idle");
  const pcmLimit = page.locator("#pcm-sample-limit");
  assert.equal(await pcmLimit.inputValue(), "10000000");
  assert.match(await page.locator("#pcm-limit-summary").textContent(), /1:53.*38\.1 MiB/);
  await pcmLimit.fill("172799");
  await page.locator("#file-input").setInputFiles(
    path.join(root, "tests/corpus/upstream/l3-he_32khz.bit"),
  );
  await page.waitForFunction(() => document.querySelector("#state-badge").textContent === "Error");
  assert.match(await page.locator("#message").textContent(), /PCM sample limit/);
  assert.equal(await page.locator("#play").isDisabled(), true);
  for (const invalid of ["", "0", "-1", "1.5", "2147483648"]) {
    await pcmLimit.fill(invalid);
    await page.locator("#file-input").setInputFiles(
      path.join(root, "tests/corpus/upstream/l3-he_32khz.bit"),
    );
    assert.equal(await pcmLimit.evaluate((input) => input.validity.valid), false);
  }
  await pcmLimit.fill("172800");
  await page.locator("#file-input").setInputFiles(
    path.join(root, "tests/corpus/upstream/l3-he_32khz.bit"),
  );
  await page.waitForFunction(() => document.querySelector("#state-badge").textContent === "Ready");
  assert.equal(await pcmLimit.evaluate((input) => input.validity.valid), true);
  await pcmLimit.fill("10000000");
  assert.match(await page.locator("#track-meta").textContent(), /32,000 Hz.*Mono.*0:05/);
  const painted = await page.locator("#waveform").evaluate((canvas) => {
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let colored = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] > 0) colored++;
    }
    return colored;
  });
  assert(painted > 100, `waveform pixels: ${painted}`);
  await page.locator("#play").click();
  await page.waitForFunction(() => document.querySelector("#state-badge").textContent === "Playing");
  await page.locator("#play").click();
  await page.waitForFunction(() => document.querySelector("#state-badge").textContent === "Paused");
  await page.locator("#seek").evaluate((input) => {
    input.value = "500";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  assert.notEqual(await page.locator("#current-time").textContent(), "0:00");
  await page.screenshot({ path: path.join(root, "target/browser-test/loaded.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(root, "target/browser-test/mobile.png") });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  assert.equal(overflow, false, "mobile horizontal overflow");
  await page.setViewportSize({ width: 320, height: 720 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

  await page.locator("#file-input").setInputFiles({
    name: "invalid.mp3", mimeType: "audio/mpeg", buffer: Buffer.from([1, 2, 3, 4]),
  });
  await page.waitForFunction(() => document.querySelector("#state-badge").textContent === "Error");
  assert.equal(await page.locator("#play").isDisabled(), true);
  assert.deepEqual(errors, []);
  console.log("Browser UI: adjustable PCM limit, exact sample boundary, invalid-value recovery, load, waveform, play/pause, seek, error, desktop/mobile passed");
} finally {
  await browser.close();
}
