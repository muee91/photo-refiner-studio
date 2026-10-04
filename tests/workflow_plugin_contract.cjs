"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const pluginData = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-workflow-data-"));
const jobRoot = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-job-"));
const jobPath = path.join(jobRoot, "job.json");
const artifactPath = path.join(jobRoot, "preview.png");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.json"), "utf8"));

// Tiny valid 1x1 PNG; update_job.py/delivery_gate.measure only needs a readable image.
fs.writeFileSync(artifactPath, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nYkAAAAASUVORK5CYII=", "base64"));
fs.writeFileSync(jobPath, JSON.stringify({
  status: "base_generated",
  workflow: "single",
  execution_mode: "photo-refinement",
  delivery_mode: "preview-first",
  sources: [path.join(jobRoot, "source.jpg")],
  resolved_prompt: {label: "自然电影感"},
  resolution: "source-width",
  base_preview: {required: true, approved: false},
  creative_preview: {required: false, approved: false},
  creative_output: null,
  detail: {mode: "adaptive"},
  hd_working_canvas_policy: {mode: "automatic", routes: ["native-detail", "source-backed-detail", "ultrasharp-detail", "full-canvas-tile-redraw"]},
  patch_observations: [],
  detail_blend_receipts: [],
  tile_blend_receipts: [],
  artifacts: [],
  history: [{status: "base_generated", at: new Date().toISOString()}],
  created_at: new Date().toISOString(),
}, null, 2));

const server = childProcess.spawn(process.execPath, [path.join(ROOT, "mcp", "workflow.cjs"), "--stdio"], {
  stdio: ["pipe", "pipe", "inherit"],
  env: {...process.env, HOME: pluginData, PLUGIN_ROOT: ROOT, PLUGIN_DATA: pluginData, PYTHON: process.env.PYTHON || "python3"},
});
const lines = readline.createInterface({input: server.stdout});
const pending = new Map();
let nextId = 0;
let finished = false;
server.on("exit", (code) => { if (!finished) { console.error(`Workflow MCP exited prematurely with code ${code}`); process.exit(1); } });
lines.on("line", (line) => {
  const message = JSON.parse(line);
  const callbacks = pending.get(message.id);
  if (!callbacks) return;
  pending.delete(message.id);
  clearTimeout(callbacks.timer);
  message.error ? callbacks.reject(new Error(message.error.message)) : callbacks.resolve(message.result);
});
function rpc(method, params = {}, timeoutMs = 15000) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`timeout waiting for ${method}`)); }, timeoutMs);
    pending.set(id, {resolve, reject, timer});
    server.stdin.write(`${JSON.stringify({jsonrpc: "2.0", id, method, params})}\n`);
  });
}

(async () => {
  const init = await rpc("initialize", {protocolVersion: "2024-11-05"});
  assert.equal(init.serverInfo.name, "photo-refiner-workflow");
  assert.equal(init.serverInfo.version, manifest.version);

  const tools = await rpc("tools/list");
  assert.deepEqual(tools.tools.map((item) => item.name), [
    "register_photo_refiner_job",
    "open_photo_refiner_review",
    "submit_photo_refiner_review",
    "open_photo_refiner_recent_jobs",
    "resume_photo_refiner_job",
  ]);

  const registered = await rpc("tools/call", {name: "register_photo_refiner_job", arguments: {jobPath}});
  assert.equal(registered.isError, false);
  assert.equal(registered.structuredContent.summary.status, "base_generated");

  const review = await rpc("tools/call", {name: "open_photo_refiner_review", arguments: {jobPath, checkpoint: "base", artifactPath}});
  assert.equal(review.isError, false);
  assert.equal(review.structuredContent.kind, "photo-refiner-review");
  assert.ok(review._meta?.ui?.resourceUri);
  assert.match(review.content.find((item) => item.type === "resource").resource.text, /使用这版并继续/);

  const approved = await rpc("tools/call", {name: "submit_photo_refiner_review", arguments: {jobPath, checkpoint: "base", artifactPath, event: "approve"}});
  assert.equal(approved.isError, false, JSON.stringify(approved));
  assert.equal(approved.structuredContent.decision.next_action, "prepare_hd_working_canvas");
  const job = JSON.parse(fs.readFileSync(jobPath, "utf8"));
  assert.equal(job.base_preview.approved, true);
  assert.equal(job.approved_preview.path, path.resolve(artifactPath));

  const recent = await rpc("tools/call", {name: "open_photo_refiner_recent_jobs", arguments: {limit: 5}});
  assert.equal(recent.isError, false);
  assert.equal(recent.structuredContent.jobs.length, 1);
  assert.equal(recent.structuredContent.jobs[0].jobPath, path.resolve(jobPath));
  assert.match(recent.content.find((item) => item.type === "resource").resource.text, /继续最近任务/);

  const resumed = await rpc("tools/call", {name: "resume_photo_refiner_job", arguments: {jobPath}});
  assert.equal(resumed.isError, false);
  assert.equal(resumed.structuredContent.decision.next_action, "prepare_hd_working_canvas");

  const resources = await rpc("resources/list");
  assert.equal(resources.resources.length, 2);
  for (const resource of resources.resources) {
    const rendered = await rpc("resources/read", {uri: resource.uri});
    assert.equal(rendered.contents.length, 1);
    assert.doesNotMatch(rendered.contents[0].text, /__PHOTO_REFINER_(REVIEW|JOBS)_PAYLOAD__/);
  }

  finished = true;
  lines.close();
  server.kill("SIGTERM");
  fs.rmSync(pluginData, {recursive: true, force: true});
  fs.rmSync(jobRoot, {recursive: true, force: true});
  console.log("workflow plugin contract OK");
})().catch((error) => {
  finished = true;
  lines.close();
  server.kill("SIGTERM");
  fs.rmSync(pluginData, {recursive: true, force: true});
  fs.rmSync(jobRoot, {recursive: true, force: true});
  console.error(error);
  process.exit(1);
});
