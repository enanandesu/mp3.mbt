import { decode_mp3 } from "../../_build/js/release/build/examples/browser/browser.js";

const $ = (id) => document.getElementById(id);
const ui = {
  dropZone: $("drop-zone"), fileInput: $("file-input"), choose: $("choose-button"), fileName: $("file-name"),
  trackMeta: $("track-meta"), badge: $("state-badge"), waveform: $("waveform"),
  seek: $("seek"), currentTime: $("current-time"), duration: $("duration"),
  play: $("play"), restart: $("restart"), volume: $("volume"), message: $("message"),
  fileSizeLimit: $("file-size-limit"), demo: $("demo-button"),
  pcmSampleLimit: $("pcm-sample-limit"), pcmLimitSummary: $("pcm-limit-summary"),
};

let context;
let gain;
let buffer;
let source;
let sourceId = 0;
let startedAt = 0;
let position = 0;
let playing = false;
let loadingId = 0;
let envelope = [];

function timeLabel(seconds) {
  const total = Math.floor(Math.max(0, seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function validPcmLimit(samples) {
  return Number.isInteger(samples) && samples >= 1 && samples <= 2147483647;
}

function updatePcmLimitSummary() {
  const samples = ui.pcmSampleLimit.valueAsNumber;
  ui.pcmLimitSummary.textContent = validPcmLimit(samples)
    ? `About ${timeLabel(samples / (44100 * 2))} at 44.1 kHz stereo · ${(samples * 4 / 1024 / 1024).toFixed(1)} MiB of PCM. Playback uses additional memory.`
    : "Enter a whole number from 1 to 2,147,483,647 samples.";
}

function setState(state, message, error = false) {
  ui.badge.textContent = state;
  ui.badge.dataset.state = state.toLowerCase();
  ui.message.textContent = message;
  ui.message.classList.toggle("error", error);
}

function currentPosition() {
  return playing ? Math.min(buffer.duration, context.currentTime - startedAt) : position;
}

function stopSource() {
  sourceId++;
  if (source) {
    source.stop();
    source.disconnect();
    source = null;
  }
  playing = false;
}

function updateTimeline() {
  const duration = buffer?.duration ?? 0;
  const at = currentPosition();
  ui.currentTime.textContent = timeLabel(at);
  ui.duration.textContent = timeLabel(duration);
  ui.seek.value = duration ? String(Math.round(at / duration * 1000)) : "0";
  drawWaveform(at);
}

function drawWaveform(at = 0) {
  const canvas = ui.waveform;
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(bounds.width * ratio));
  const height = Math.max(1, Math.round(bounds.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const paint = canvas.getContext("2d");
  paint.clearRect(0, 0, width, height);
  if (!envelope.length) {
    paint.fillStyle = "#dbe5e2";
    for (let i = 0; i < 90; i++) {
      const x = (i + .5) * width / 90;
      paint.fillRect(x, height * .39, Math.max(2, width / 190), height * .22);
    }
    return;
  }
  const progress = buffer?.duration ? at / buffer.duration : 0;
  const step = width / envelope.length;
  for (let i = 0; i < envelope.length; i++) {
    const bar = Math.max(height * .04, envelope[i] * height * .82);
    paint.fillStyle = i / envelope.length <= progress ? "#21816b" : "#b5d1c8";
    paint.fillRect(i * step, (height - bar) / 2, Math.max(1, step * .62), bar);
  }
}

function animationTick() {
  if (!playing) return;
  updateTimeline();
  requestAnimationFrame(animationTick);
}

async function playFrom(at) {
  if (!buffer) return;
  if (!context) {
    context = new AudioContext();
    gain = context.createGain();
    gain.gain.value = Number(ui.volume.value) / 100;
    gain.connect(context.destination);
  }
  await context.resume();
  stopSource();
  position = Math.min(Math.max(0, at), buffer.duration);
  if (position >= buffer.duration) position = 0;
  const id = ++sourceId;
  source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(gain);
  source.onended = () => {
    if (id !== sourceId) return;
    source = null;
    playing = false;
    position = buffer.duration;
    ui.play.textContent = "Play";
    setState("Finished", "Playback complete.");
    updateTimeline();
  };
  startedAt = context.currentTime - position;
  source.start(0, position);
  playing = true;
  ui.play.textContent = "Pause";
  setState("Playing", "Playing local audio.");
  requestAnimationFrame(animationTick);
}

function pause() {
  position = currentPosition();
  stopSource();
  ui.play.textContent = "Play";
  setState("Paused", "Playback paused.");
  updateTimeline();
}

globalThis.mp3Demo = {
  receiveAudio(rate, channels, samples) {
    if (!Number.isInteger(rate) || ![1, 2].includes(channels) ||
        samples.length === 0 || samples.length % channels !== 0) {
      this.receiveError("Invalid decoded PCM metadata");
      return;
    }
    const frames = samples.length / channels;
    buffer = new AudioBuffer({ length: frames, numberOfChannels: channels, sampleRate: rate });
    for (let channel = 0; channel < channels; channel++) {
      const output = buffer.getChannelData(channel);
      for (let frame = 0; frame < frames; frame++) {
        output[frame] = samples[frame * channels + channel];
      }
    }
    const channelData = Array.from({ length: channels }, (_, channel) => buffer.getChannelData(channel));
    const bins = Math.min(500, frames);
    const peaks = Array.from({ length: bins }, (_, i) => {
      const first = Math.floor(i * frames / bins);
      const last = Math.max(first + 1, Math.floor((i + 1) * frames / bins));
      let peak = 0;
      for (let frame = first; frame < last; frame++) {
        for (const data of channelData) peak = Math.max(peak, Math.abs(data[frame]));
      }
      return peak;
    });
    const maximum = Math.max(...peaks, 0.001);
    envelope = peaks.map((peak) => Math.sqrt(peak / maximum));
    position = 0;
    ui.trackMeta.textContent = `${rate.toLocaleString()} Hz · ${channels === 1 ? "Mono" : "Stereo"} · ${timeLabel(buffer.duration)}`;
    ui.play.disabled = false;
    ui.restart.disabled = false;
    ui.seek.disabled = false;
    ui.play.textContent = "Play";
    setState("Ready", "Decoded and ready to play.");
    updateTimeline();
  },
  receiveError(message) {
    buffer = null;
    envelope = [];
    position = 0;
    ui.play.disabled = true;
    ui.restart.disabled = true;
    ui.seek.disabled = true;
    ui.trackMeta.textContent = "No playable audio";
    setState("Error", message === "OutputLimit"
      ? "Decoded audio exceeds your PCM sample limit. Increase the decoded PCM limit and load the audio again."
      : message, true);
    updateTimeline();
  },
};

async function loadAudio(name, readFile) {
  const limitMiB = ui.fileSizeLimit.valueAsNumber;
  const limitBytes = limitMiB * 1024 * 1024;
  if (!ui.fileSizeLimit.checkValidity() || !Number.isSafeInteger(limitBytes)) {
    ui.fileSizeLimit.setCustomValidity("Enter a positive whole number of MiB.");
    ui.fileSizeLimit.reportValidity();
    return;
  }
  const maxOutputSamples = ui.pcmSampleLimit.valueAsNumber;
  if (!ui.pcmSampleLimit.checkValidity() || !validPcmLimit(maxOutputSamples)) {
    ui.pcmSampleLimit.setCustomValidity("Enter a whole number from 1 to 2,147,483,647 samples.");
    ui.pcmSampleLimit.reportValidity();
    return;
  }
  const id = ++loadingId;
  stopSource();
  buffer = null;
  envelope = [];
  position = 0;
  ui.fileName.textContent = name;
  ui.trackMeta.textContent = "Reading audio...";
  ui.play.disabled = true;
  ui.restart.disabled = true;
  ui.seek.disabled = true;
  ui.play.textContent = "Play";
  setState("Loading", "Reading and decoding file...");
  updateTimeline();
  try {
    const file = await readFile();
    if (id !== loadingId) return;
    ui.trackMeta.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MiB`;
    if (file.size > limitBytes) {
      globalThis.mp3Demo.receiveError(`This file exceeds your ${limitMiB} MiB limit. Increase the file size limit and load it again.`);
      return;
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (id !== loadingId) return;
    await new Promise(requestAnimationFrame);
    if (id !== loadingId) return;
    decode_mp3(bytes, maxOutputSamples);
  } catch (error) {
    if (id === loadingId) globalThis.mp3Demo.receiveError(String(error));
  }
}

function loadFile(file) {
  if (file) return loadAudio(file.name, async () => file);
}

ui.demo.addEventListener("click", () => loadAudio("sample.mp3", async () => {
  // Request bytes from the beginning; this also avoids media-download interception
  // by download helpers that otherwise replace this MP3 response with an empty 204.
  const response = await fetch(new URL("sample.mp3", import.meta.url), {
    headers: { Range: "bytes=0-" },
  });
  if (!response.ok) throw new Error(`Could not load demo audio (HTTP ${response.status}).`);
  const file = await response.blob();
  if (!file.size) throw new Error("No demo audio received. Use Choose MP3 to open examples/browser/sample.mp3.");
  return file;
}));

ui.fileSizeLimit.addEventListener("input", () => ui.fileSizeLimit.setCustomValidity(""));
ui.pcmSampleLimit.addEventListener("input", () => {
  ui.pcmSampleLimit.setCustomValidity("");
  updatePcmLimitSummary();
});
ui.choose.addEventListener("click", () => ui.fileInput.click());
ui.fileInput.addEventListener("change", (event) => {
  loadFile(event.target.files[0]);
  event.target.value = "";
});
for (const eventName of ["dragenter", "dragover"]) {
  ui.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    ui.dropZone.classList.add("drag-over");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  ui.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    ui.dropZone.classList.remove("drag-over");
  });
}
ui.dropZone.addEventListener("drop", (event) => loadFile(event.dataTransfer.files[0]));
ui.play.addEventListener("click", () => {
  if (playing) pause();
  else playFrom(position).catch((error) => globalThis.mp3Demo.receiveError(String(error)));
});
ui.restart.addEventListener("click", () => {
  if (playing) playFrom(0).catch((error) => globalThis.mp3Demo.receiveError(String(error)));
  else { position = 0; updateTimeline(); }
});
ui.seek.addEventListener("input", () => {
  if (!buffer) return;
  position = Number(ui.seek.value) / 1000 * buffer.duration;
  ui.currentTime.textContent = timeLabel(position);
  drawWaveform(position);
});
ui.seek.addEventListener("change", () => {
  if (playing) playFrom(position).catch((error) => globalThis.mp3Demo.receiveError(String(error)));
});
ui.volume.addEventListener("input", () => {
  if (gain) gain.gain.value = Number(ui.volume.value) / 100;
});
ui.waveform.addEventListener("click", (event) => {
  if (!buffer) return;
  const box = ui.waveform.getBoundingClientRect();
  const at = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) * buffer.duration;
  if (playing) playFrom(at).catch((error) => globalThis.mp3Demo.receiveError(String(error)));
  else { position = at; updateTimeline(); }
});
new ResizeObserver(() => drawWaveform(currentPosition())).observe(ui.waveform);
updatePcmLimitSummary();
updateTimeline();
