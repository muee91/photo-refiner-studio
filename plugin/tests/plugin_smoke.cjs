"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const testHome = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-smoke-"));
const server = childProcess.spawn(process.execPath, [path.join(ROOT, "mcp", "server.cjs"), "--stdio"], {
  stdio: ["pipe", "pipe", "inherit"],
  env: {...process.env, HOME: testHome},
});
const lines = readline.createInterface({input: server.stdout});
const pending = new Map();
let nextId = 0;
lines.on("line", (line) => {
  const message = JSON.parse(line);
  const callbacks = pending.get(message.id);
  if (!callbacks) return;
  pending.delete(message.id);
  message.error ? callbacks.reject(new Error(message.error.message)) : callbacks.resolve(message.result);
});

function rpc(method, params = {}) {
  const id = ++nextId;
  server.stdin.write(`${JSON.stringify({jsonrpc: "2.0", id, method, params})}\n`);
  return new Promise((resolve, reject) => pending.set(id, {resolve, reject}));
}

(async () => {
  const initialized = await rpc("initialize", {protocolVersion: "2024-11-05"});
  assert.equal(initialized.serverInfo.name, "photo-refiner-studio");

  const listed = await rpc("tools/list");
  assert.deepEqual(listed.tools.map((item) => item.name), ["open_photo_refiner_settings", "submit_photo_refiner_settings", "delete_photo_refiner_prompt"]);
  assert.deepEqual(listed.tools[0].inputSchema.required, ["sourceCount"]);
  assert.equal(listed.tools[0].inputSchema.properties.sourceCount.minimum, 1);
  assert.match(listed.tools[0].description, /native\/top-level tool call/);
  assert.match(listed.tools[0].description, /never call it through functions\.exec/);

  const noSource = await rpc("tools/call", {name: "open_photo_refiner_settings", arguments: {sourceCount: 0}});
  assert.equal(noSource.isError, true);
  assert.match(noSource.structuredContent.error, /source photograph is required/);

  const opened = await rpc("tools/call", {name: "open_photo_refiner_settings", arguments: {sourceCount: 2}});
  assert.equal(opened.structuredContent.schemaVersion, 2);
  assert.equal(opened.structuredContent.defaults.workflow, "batch");
  assert.equal(opened.structuredContent.defaults.preset, "natural-cinematic");
  assert.equal(opened.structuredContent.defaults.styleStrength, 45);
  assert.equal(opened.structuredContent.presets.presets["natural-cinematic"].defaultStrength, 45);
  assert.ok(["simple", "pro"].includes(opened.structuredContent.defaults.uiMode));
  assert.equal(opened.structuredContent.defaults.detail.patchScope, "head-and-face");
  assert.equal(opened.structuredContent.defaults.deliveryMode, "preview-first");
  assert.ok(["jpg", "png", "both"].includes(opened.structuredContent.defaults.outputFormat));
  assert.ok(opened.structuredContent.promptLibrary);
  assert.ok(Array.isArray(opened.structuredContent.promptLibrary.custom));
  assert.equal(opened.structuredContent.recommendation, "");
  assert.match(
    opened.structuredContent.presets.presets["eastern-twilight"].prompt,
    /visibly transformed cinematic twilight grade/,
  );
  assert.match(
    opened.structuredContent.presets.presets["eastern-twilight"].promptZh,
    /电影感暮光成片/,
  );
  assert.ok(opened.structuredContent.presets.presets["natural-landscape"]);
  assert.match(opened._meta["openai/outputTemplate"], /^ui:\/\/widget\//);
  assert.deepEqual(opened._meta.ui.visibility, ["model", "app"]);

  const recommended = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1, suggestedPreset: "natural-landscape"},
  });
  assert.equal(recommended.structuredContent.defaults.preset, "natural-landscape");
  assert.equal(recommended.structuredContent.defaults.styleStrength, 35);
  assert.equal(recommended.structuredContent.presets.presets["natural-landscape"].defaultStrength, 35);

  const resources = await rpc("resources/list");
  assert.equal(resources.resources[0]._meta.ui.prefersBorder, true);
  assert.match(resources.resources[0].uri, /^ui:\/\/widget\/photo-refiner-settings\//);
  assert.doesNotMatch(resources.resources[0].uri, /%/);
  const resource = await rpc("resources/read", {uri: resources.resources[0].uri});
  assert.equal(resource.contents[0].mimeType, "text/html;profile=mcp-app");
  assert.equal(resource.contents[0]._meta.ui.prefersBorder, true);
  assert.match(resource.contents[0].text, /去衣服褶皱/);
  assert.match(resource.contents[0].text, /中文提示词/);
  assert.match(resource.contents[0].text, /确认并开始/);
  assert.match(resource.contents[0].text, /先看效果图/);
  assert.match(resource.contents[0].text, /简单模式（推荐）/);
  assert.match(resource.contents[0].text, /专业模式/);
  assert.match(resource.contents[0].text, /ui\/initialize/);
  assert.match(resource.contents[0].text, /ui\/notifications\/initialized/);
  assert.match(resource.contents[0].text, /提示词库/);
  assert.match(resource.contents[0].text, /内置可直接使用/);
  assert.match(resource.contents[0].text, /根据照片的建议/);
  assert.match(resource.contents[0].text, /preset-list/);
  assert.match(resource.contents[0].text, /默认只需选择风格/);
  assert.ok(resource.contents[0].text.includes("头部 + 人脸"));

  const defaults = recommended.structuredContent.defaults;
  defaults.clothing.wrinkleReduction = 35;
  const submitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: defaults},
  });
  assert.equal(submitted.structuredContent.ok, true);
  assert.ok(fs.existsSync(submitted.structuredContent.confirmationPath));
  const confirmation = JSON.parse(fs.readFileSync(submitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(confirmation.schemaVersion, 2);
  assert.equal(confirmation.config.preset, "natural-landscape");
  assert.equal(confirmation.config.styleStrength, 35);
  assert.equal(confirmation.resolvedPrompt.defaultStrength, 35);
  assert.equal(confirmation.config.clothing.wrinkleReduction, 35);
  assert.equal(confirmation.config.portrait.enabled, false);
  assert.equal(confirmation.config.body.enabled, false);

  // Same-preset saved user tuning must win over the catalog default.
  const tuned = JSON.parse(JSON.stringify(defaults));
  tuned.styleStrength = 42;
  await rpc("tools/call", {name: "submit_photo_refiner_settings", arguments: {userConfirmed: true, config: tuned}});
  const reopened = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1, suggestedPreset: "natural-landscape"},
  });
  assert.equal(reopened.structuredContent.defaults.styleStrength, 42);

  // A different recommendation must adopt that preset's own default strength.
  const switched = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1, suggestedPreset: "clean-architecture"},
  });
  assert.equal(switched.structuredContent.defaults.preset, "clean-architecture");
  assert.equal(switched.structuredContent.defaults.styleStrength, 30);

  const unsafe = JSON.parse(JSON.stringify(defaults));
  unsafe.body.enabled = true;
  unsafe.body.waistSlim = 80;
  const rejected = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: unsafe},
  });
  assert.equal(rejected.isError, true);
  assert.match(rejected.structuredContent.error, /0 to 40/);

  server.stdin.end();
  fs.rmSync(testHome, {recursive: true, force: true});
  console.log(JSON.stringify({ok: true, confirmationPath: submitted.structuredContent.confirmationPath, temp: os.tmpdir()}));
})().catch((error) => {
  server.kill();
  fs.rmSync(testHome, {recursive: true, force: true});
  console.error(error);
  process.exitCode = 1;
});
