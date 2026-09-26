// Release JS decode timing and isolated renderer memory measurements.
// Install the checked-in tools/browser-test package lock under target/browser-test first.
// node tools/benchmark_browser.mjs [--browser PATH] [--output target/performance-browser]
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const playwrightPath = path.resolve(root, process.env.PLAYWRIGHT_CORE_PATH ??
  "target/browser-test/node_modules/playwright-core");
const { chromium } = require(playwrightPath);
const playwrightVersion = require(path.join(playwrightPath, "package.json")).version;
const options = { output: "target/performance-browser", browser: process.env.BROWSER_PATH ??
  process.env.EDGE_PATH ?? (process.platform === "win32"
    ? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" : "/usr/bin/chromium") };
for (let i = 2; i < process.argv.length; i += 2) {
  const name = process.argv[i].replace(/^--/, "");
  assert(name in options && process.argv[i + 1], `Unknown or incomplete option: ${process.argv[i]}`);
  options[name] = process.argv[i + 1];
}
const output = path.resolve(root, options.output);
// Benchmark products must stay under the ignored target directory.
assert(output.startsWith(path.join(root, "target") + path.sep), "Output must be under target/");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const run = (command, args) => execFileSync(command, args, {
  cwd: root, encoding: "utf8", windowsHide: true,
}).trim();
const moonVersion = run("moon", ["version"]).split(/\r?\n/)[0];
const toolchainBytes = await readFile(path.join(root, "tools/toolchain.lock.json"));
assert.equal(moonVersion, JSON.parse(toolchainBytes).tools.moon.version, "MoonBit version differs from pinned toolchain");
const manifest = JSON.parse(await readFile(path.join(root, "tests/corpus/manifest.json")));
const policy = JSON.parse(await readFile(path.join(root, "tests/reference_policy.json")));
const caseIds = ["l3-he_32khz", "M2L3_compl24", "generated-8000-2ch-cbr"];
const cases = [];
for (const id of caseIds) {
  const entry = manifest.cases.find((item) => item.id === id);
  assert(entry, `Missing case: ${id}`);
  const bytes = await readFile(path.join(root, entry.path));
  assert.equal(sha256(bytes), entry.sha256, `Corpus hash changed: ${id}`);
  const metadata = policy.expected[id].metadata;
  cases.push({ id, bytes, sha256: entry.sha256, metadata,
    audioSeconds: metadata.sample_count / metadata.channels / metadata.sample_rate });
}
execFileSync("moon", ["build", "examples/browser", "--target", "js", "--release", "--deny-warn"],
  { cwd: root, stdio: "inherit", windowsHide: true });
const source = await readFile(path.join(root, "_build/js/release/build/examples/browser/browser.js"));
await mkdir(output, { recursive: true });

// Serve only the built module and verified corpus, never arbitrary workspace files.
const resources = new Map([
  ["/", { mime: "text/html", body: "<!doctype html><title>MP3 decode benchmark</title>" }],
  ["/decoder.js", { mime: "text/javascript", body: source }],
  ...cases.map((item) => [`/${item.id}.bit`, { mime: "application/octet-stream", body: item.bytes }]),
]);
const server = createServer((req, res) => {
  const resource = resources.get(req.url);
  if (!resource) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": resource.mime, "Cache-Control": "no-store" });
  res.end(resource.body);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const url = `http://127.0.0.1:${server.address().port}`;
const launch = () => chromium.launch({ executablePath: options.browser, headless: true,
  args: ["--enable-precise-memory-info", "--renderer-process-limit=1",
    "--disable-features=SpareRendererForSitePerProcess"] });

async function setup(browser, item) {
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: "load" });
  await page.evaluate(async ({ id, metadata }) => {
    const { decode_mp3 } = await import("/decoder.js");
    const input = new Uint8Array(await (await fetch(`/${id}.bit`)).arrayBuffer());
    globalThis.bench = { decode_mp3, input, metadata, audio: null, error: null };
    globalThis.mp3Demo = {
      receiveAudio(rate, channels, samples) { bench.audio = { rate, channels, samples }; },
      receiveError(message) { bench.error = message; },
    };
    bench.decode = () => {
      bench.audio = null;
      bench.error = null;
      decode_mp3(input, 10000000);
    };
    bench.check = () => {
      if (bench.error) throw new Error(bench.error);
      const audio = bench.audio;
      if (!audio || audio.rate !== metadata.sample_rate || audio.channels !== metadata.channels ||
          audio.samples.length !== metadata.sample_count) throw new Error("Decoded metadata mismatch");
      let checksum = 0;
      for (let i = 0; i < audio.samples.length; i++) {
        if (!Number.isFinite(audio.samples[i])) throw new Error(`Non-finite sample ${i}`);
        if (i % 257 === 0) checksum += audio.samples[i];
      }
      return checksum;
    };
  }, { id: item.id, metadata: item.metadata });
  return page;
}

async function rendererMemory(browser) {
  const cdp = await browser.newBrowserCDPSession();
  try {
    const { processInfo } = await cdp.send("SystemInfo.getProcessInfo");
    const pids = processInfo.filter((p) => p.type === "renderer").map((p) => p.id);
    assert(pids.length > 0, "No browser renderer process found");
    if (process.platform === "win32") {
      // OS counters include V8, native backing stores, and renderer startup, but not other browser processes.
      const script = `$rows = @(Get-Process -Id ${pids.join(",")} | ForEach-Object { ` +
        `$_.Refresh(); [pscustomobject]@{pid=$_.Id; residentBytes=$_.WorkingSet64; ` +
        `peakResidentBytes=$_.PeakWorkingSet64} }); ConvertTo-Json -Compress -InputObject $rows`;
      return { method: "Windows Get-Process WorkingSet64 / PeakWorkingSet64", processes:
        JSON.parse(run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script])) };
    }
    if (process.platform === "linux") {
      const processes = [];
      for (const pid of pids) {
        const status = await readFile(`/proc/${pid}/status`, "utf8");
        const value = (key) => {
          const match = status.match(new RegExp(`^${key}:\\s+(\\d+) kB$`, "m"));
          assert(match, `Missing ${key} for renderer ${pid}`);
          return Number(match[1]) * 1024;
        };
        processes.push({ pid, residentBytes: value("VmRSS"), peakResidentBytes: value("VmHWM") });
      }
      return { method: "Linux /proc/<pid>/status VmRSS / VmHWM", processes };
    }
    throw new Error(`OS peak resident memory is not implemented on ${process.platform}`);
  } finally { await cdp.detach(); }
}

const report = {
  dateUtc: new Date().toISOString(), system: `${os.type()} ${os.release()} ${os.arch()}`,
  cpu: os.cpus()[0]?.model, logicalCpus: os.cpus().length,
  gitCommit: run("git", ["rev-parse", "HEAD"]),
  gitDirty: run("git", ["status", "--porcelain"]).length > 0,
  moon: moonVersion, toolchainLockSha256: sha256(toolchainBytes),
  node: process.version, playwright: playwrightVersion,
  browserExecutable: path.basename(options.browser), browserVersion: null,
  builtModuleSha256: sha256(source),
  method: {
    timing: "Release JS browser bridge decode_mp3; 3 warmups; 7 batches of 5; per-call performance.now; no fetch, validation, Web Audio, drawing, or playback in timer. Includes PCM bridge copy. All 35 calls and 7 batch means reported.",
    memory: "Separate fresh browser per corpus case; one decode, output retained. OS renderer process lifetime peak RSS/working set includes startup and input; it is not a decoder-only allocation peak. CDP heap snapshots before decode, after decode, and after explicit GC distinguish transient and retained heap. Not mixed into timing run.",
    gate: "Each timing median must exceed 1x realtime, metadata must match frozen policy, and all output samples must be finite. This is not a PCM differential conformance test or a portable performance guarantee.",
  },
  results: [],
};
try {
  const browser = await launch();
  try {
    report.browserVersion = browser.version();
    for (const item of cases) {
      const page = await setup(browser, item);
      const timing = await page.evaluate(() => {
        for (let i = 0; i < 3; i++) { bench.decode(); bench.check(); }
        const batchMeanMs = [];
        const callMs = [];
        let checksum = 0;
        for (let batch = 0; batch < 7; batch++) {
          let elapsed = 0;
          const calls = [];
          for (let repeat = 0; repeat < 5; repeat++) {
            const start = performance.now();
            bench.decode();
            const duration = performance.now() - start;
            elapsed += duration;
            calls.push(duration);
            checksum += bench.check();
          }
          batchMeanMs.push(elapsed / 5);
          callMs.push(calls);
        }
        return { batchMeanMs, callMs, checksum, userAgent: navigator.userAgent };
      });
      const sorted = [...timing.batchMeanMs].sort((a, b) => a - b);
      const medianMs = sorted[3];
      const slowestBatchMs = sorted.at(-1);
      const row = { id: item.id, inputSha256: item.sha256, inputBytes: item.bytes.length,
        metadata: item.metadata, audioSeconds: item.audioSeconds, ...timing,
        medianMs, slowestBatchMs, medianRealtime: item.audioSeconds * 1000 / medianMs,
        slowestBatchRealtime: item.audioSeconds * 1000 / slowestBatchMs };
      row.passed = Number.isFinite(row.medianRealtime) && row.medianRealtime >= 1;
      report.results.push(row);
      console.log(`${item.id}: ${medianMs.toFixed(3)} ms, ${row.medianRealtime.toFixed(1)}x realtime`);
      await page.close();
    }
  } finally { await browser.close(); }
  for (let i = 0; i < cases.length; i++) {
    const memoryBrowser = await launch();
    try {
      const page = await setup(memoryBrowser, cases[i]);
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("HeapProfiler.collectGarbage");
      const before = await cdp.send("Runtime.getHeapUsage");
      const residentBefore = await rendererMemory(memoryBrowser);
      const checksum = await page.evaluate(() => { bench.decode(); return bench.check(); });
      const afterDecode = await cdp.send("Runtime.getHeapUsage");
      const residentAfter = await rendererMemory(memoryBrowser);
      await cdp.send("HeapProfiler.collectGarbage");
      const retained = await cdp.send("Runtime.getHeapUsage");
      const residentRetained = await rendererMemory(memoryBrowser);
      report.results[i].memory = { before, afterDecode, retained, residentBefore,
        residentAfter, residentRetained, checksum,
        rendererPeakResidentBytes: Math.max(...residentAfter.processes.map((p) => p.peakResidentBytes)),
        rendererCount: residentAfter.processes.length };
      // Reporting a single renderer peak is unambiguous only with one renderer.
      assert.equal(residentAfter.processes.length, 1, "Expected one renderer for isolated memory measurement");
      console.log(`${cases[i].id}: renderer lifetime peak ${(report.results[i].memory.rendererPeakResidentBytes / 1048576).toFixed(2)} MiB`);
      await cdp.detach();
    } finally { await memoryBrowser.close(); }
  }
  report.allPassed = report.results.every((row) => row.passed);
  await writeFile(path.join(output, "results.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(`Report: ${path.relative(root, path.join(output, "results.json"))}`);
  assert(report.allPassed, "Browser realtime target failed");
} finally { await new Promise((resolve) => server.close(resolve)); }
