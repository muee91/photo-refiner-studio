"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const pluginData = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-plugin-data-"));
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.json"), "utf8"));

const server = childProcess.spawn(process.execPath, [path.join(ROOT, "mcp", "server.cjs"), "--stdio"], {
  stdio: ["pipe", "pipe", "inherit"],
  env: {...process.env, HOME: pluginData, PLUGIN_ROOT: ROOT, PLUGIN_DATA: pluginData},
});
const lines = readline.createInterface({input: server.stdout});
const pending = new Map();
let nextId = 0;
let finished = false;

server.on("exit", (code) => {
  if (!finished) {
    console.error(`Studio MCP exited prematurely with code ${code}`);
    process.exit(1);
  }
});

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
    const timer = setTimeout(() => {
      if (!pending.has(id)) return;
      pending.delete(id);
      reject(new Error(`timeout waiting for ${method}`));
    }, timeoutMs);
    pending.set(id, {resolve, reject, timer});
    server.stdin.write(`${JSON.stringify({jsonrpc: "2.0", id, method, params})}\n`);
  });
}

(async () => {
  assert.equal(manifest.name, "photo-refiner-studio");
  assert.equal(manifest.version, "1.0.0");

  const initialized = await rpc("initialize", {protocolVersion: "2024-11-05"});
  assert.equal(initialized.serverInfo.name, "photo-refiner-studio");
  assert.equal(initialized.serverInfo.version, manifest.version);
  assert.ok(initialized.capabilities.tools);
  assert.ok(initialized.capabilities.resources);

  const listed = await rpc("tools/list");
  assert.deepEqual(listed.tools.map((item) => item.name), [
    "open_photo_refiner_settings",
    "submit_photo_refiner_settings",
    "delete_photo_refiner_prompt",
    "get_photo_refiner_recipe_preview",
    "set_photo_refiner_recipe_preview",
  ]);

  const opened = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1, suggestedPreset: "natural-cinematic"},
  });
  assert.equal(opened.isError, false);
  assert.equal(opened.structuredContent.kind, "photo-refiner-settings");
  assert.equal(opened.structuredContent.widgetVersion, manifest.version);
  assert.equal(opened.structuredContent.defaults.sourceCount, 1);
  assert.equal(opened.structuredContent.defaults.workflow, "single");
  assert.equal(opened.structuredContent.defaults.creativeRecipe, "none");
  assert.ok(opened.structuredContent.creativeRecipes.recipes.length >= 15);
  assert.ok(opened._meta?.ui?.resourceUri);

  const submitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: opened.structuredContent.defaults},
  });
  assert.equal(submitted.isError, false);
  assert.equal(submitted.structuredContent.kind, "photo-refiner-confirmation");
  assert.match(submitted.structuredContent.confirmationHash, /^[0-9a-f]{64}$/);
  const confirmationPath = path.resolve(submitted.structuredContent.confirmationPath);
  assert.ok(confirmationPath.startsWith(path.resolve(pluginData) + path.sep));
  const confirmation = JSON.parse(fs.readFileSync(confirmationPath, "utf8"));
  assert.equal(confirmation.schemaVersion, 4);
  assert.equal(confirmation.config.sourceCount, 1);
  assert.equal(confirmation.config.uiMode, opened.structuredContent.defaults.uiMode);
  assert.equal(confirmation.confirmationHash, submitted.structuredContent.confirmationHash);

  const resources = await rpc("resources/list");
  assert.equal(resources.resources.length, 1);
  const widget = await rpc("resources/read", {uri: resources.resources[0].uri});
  assert.equal(widget.contents.length, 1);
  assert.match(widget.contents[0].mimeType, /text\/html/);
  assert.match(widget.contents[0].text, /Photo Refiner/i);

  finished = true;
  lines.close();
  server.kill("SIGTERM");
  fs.rmSync(pluginData, {recursive: true, force: true});
  console.log("plugin contract OK");
})().catch((error) => {
  finished = true;
  lines.close();
  server.kill("SIGTERM");
  fs.rmSync(pluginData, {recursive: true, force: true});
  console.error(error);
  process.exit(1);
});
