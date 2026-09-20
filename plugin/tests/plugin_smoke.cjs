"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const smokeHome = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-flow-smoke-"));
const server = childProcess.spawn(process.execPath, [path.join(ROOT, "mcp", "server.cjs"), "--stdio"], {
  stdio: ["pipe", "pipe", "inherit"],
  env: {...process.env, HOME: smokeHome},
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
  // A user-authored prompt containing `$&`-style sequences must survive the
  // Widget payload serialization verbatim instead of being interpreted as a
  // String.replace replacement pattern.
  fs.mkdirSync(path.join(smokeHome, ".codex", "photo-refiner-flow"), {recursive: true});
  fs.writeFileSync(
    path.join(smokeHome, ".codex", "photo-refiner-flow", "preferences.json"),
    `${JSON.stringify({customPrompts: [{id: "dollar-guard", kind: "custom", label: "dollar guard", prompt: "keep $& and $' and $$ intact", avoid: "old text stays $` put", savedAt: "2026-01-01T00:00:00.000Z"}]})}\n`,
  );

  const initialized = await rpc("initialize", {protocolVersion: "2024-11-05"});
  assert.equal(initialized.serverInfo.name, "photo-refiner-flow-studio");

  const listed = await rpc("tools/list");
  assert.deepEqual(listed.tools.map((item) => item.name), [
    "open_photo_refiner_flow_settings",
    "open_photo_refiner_flow",
    "submit_photo_refiner_flow_graph",
    "submit_photo_refiner_flow_settings",
    "delete_photo_refiner_flow_prompt",
  ]);
  assert.deepEqual(listed.tools[0].inputSchema.required, ["sourceCount"]);
  assert.equal(listed.tools[0].inputSchema.properties.sourceCount.minimum, 1);
  assert.deepEqual(listed.tools[1].inputSchema.required, ["sourceCount"]);
  assert.equal(listed.tools[1].inputSchema.properties.sourceCount.minimum, 1);
  // Broker-envelope tolerance: widget-originated calls must accept extra
  // fields some Codex brokers add, so no const/additionalProperties:false.
  assert.equal(listed.tools[2].inputSchema.properties.userConfirmed.type, "boolean");
  assert.equal(listed.tools[2].inputSchema.properties.userConfirmed.const, undefined);
  assert.equal(listed.tools[2].inputSchema.additionalProperties, true);
  assert.equal(listed.tools[3].inputSchema.properties.userConfirmed.type, "boolean");
  assert.equal(listed.tools[3].inputSchema.properties.userConfirmed.const, undefined);
  assert.equal(listed.tools[3].inputSchema.additionalProperties, true);
  assert.equal(listed.tools[4].inputSchema.additionalProperties, true);
  assert.deepEqual(listed.tools[2].outputSchema.required, ["ok", "kind", "graphId", "graphPath", "confirmedAt"]);
  assert.deepEqual(listed.tools[3].outputSchema.required, ["ok", "kind", "confirmationId", "confirmationPath", "confirmedAt"]);

  const noSource = await rpc("tools/call", {name: "open_photo_refiner_flow_settings", arguments: {sourceCount: 0}});
  assert.equal(noSource.isError, true);
  assert.match(noSource.structuredContent.error, /source photograph is required/);

  const opened = await rpc("tools/call", {name: "open_photo_refiner_flow_settings", arguments: {sourceCount: 2}});
  assert.equal(opened.structuredContent.schemaVersion, 3);
  assert.equal(opened.structuredContent.defaults.workflow, "batch");
  assert.equal(opened.structuredContent.defaults.sourceCount, 2);
  assert.equal(opened.structuredContent.defaults.creativeRecipe, "none");
  assert.equal(opened.structuredContent.defaults.creativeAssemblyMode, "direct-effect");
  assert.equal(opened.structuredContent.defaults.creativeFromBase, false);
  assert.equal(opened.structuredContent.defaults.preset, "natural-cinematic");
  assert.equal(opened.structuredContent.defaults.styleStrength, 45);
  assert.equal(opened.structuredContent.presets.presets["natural-cinematic"].defaultStrength, 45);
  assert.ok(["simple", "pro"].includes(opened.structuredContent.defaults.uiMode));
  assert.equal(opened.structuredContent.defaults.detail.patchScope, "head-and-face");
  assert.equal(opened.structuredContent.defaults.deliveryMode, "preview-first");
  assert.ok(["jpg", "png", "both"].includes(opened.structuredContent.defaults.outputFormat));
  assert.ok(opened.structuredContent.promptLibrary);
  assert.ok(Array.isArray(opened.structuredContent.promptLibrary.custom));
  assert.equal(opened.structuredContent.creativeRecipes.recipes.length, 15);
  assert.equal(opened.structuredContent.creativeRecipes.recipes.filter((item) => item.preview.status === "available").length, 14);
  assert.ok(opened.structuredContent.creativeRecipes.recipes.find((item) => item.id === "s013-vesak"));
  assert.ok(opened.structuredContent.creativeRecipes.recipes.find((item) => item.id === "s014-mix"));
  assert.equal(opened.structuredContent.recommendation, "");
  assert.match(
    opened.structuredContent.presets.presets["eastern-twilight"].prompt,
    /visibly transformed cinematic twilight grade/,
  );
  assert.match(
    opened.structuredContent.presets.presets["eastern-twilight"].promptZh,
    /电影感暮光成片/,
  );
  assert.equal(opened.structuredContent.presets.presets["eastern-twilight"].labelZh, "东方暮光");
  assert.equal(opened.structuredContent.presets.presets["portra-soft-editorial"].labelZh, "柔和胶片人像");
  assert.ok(opened.structuredContent.presets.presets["natural-landscape"]);
  assert.equal(Object.keys(opened.structuredContent.presets.presets).length, 15);
  assert.ok(opened.structuredContent.presets.presets["portra-soft-editorial"]);
  assert.ok(opened.structuredContent.presets.presets["fine-art-chiaroscuro"]);
  assert.match(opened._meta.ui.resourceUri, /^ui:\/\/widget\//);
  assert.match(opened._meta["openai/outputTemplate"], /^ui:\/\/widget\//);
  assert.equal(opened.content[1].type, "resource");
  assert.equal(opened.content[1].resource.mimeType, "text/html;profile=mcp-app");
  const openedPayloadMatch = opened.content[1].resource.text.match(/<script id="photoRefinerInitialPayload" type="application\/json">([\s\S]*?)<\/script>/);
  assert.ok(openedPayloadMatch, "tool-result Widget must contain an initial payload");
  const openedPayload = JSON.parse(openedPayloadMatch[1]);
  assert.equal(openedPayload.promptLibrary.custom[0].prompt, "keep $& and $' and $$ intact");
  assert.equal(openedPayload._photoRefinerFallback, undefined);

  const recommended = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {
      sourceCount: 1,
      suggestedPreset: "natural-landscape",
      creativeDirections: [{label: "暖金古风", summary: "应用暖金光线", prompt: "preserve identity", avoid: "plastic skin", preset: "warm-gold-ancient", styleStrength: 68}],
    },
  });
  assert.equal(recommended.structuredContent.defaults.preset, "natural-landscape");
  assert.equal(recommended.structuredContent.defaults.styleStrength, 35);
  assert.equal(recommended.structuredContent.presets.presets["natural-landscape"].defaultStrength, 35);
  assert.equal(recommended.structuredContent.creativeDirections[0].preset, "warm-gold-ancient");
  assert.equal(recommended.structuredContent.creativeDirections[0].styleStrength, 68);
  const embeddedPayload = recommended.content[1].resource.text.match(/<script id="photoRefinerInitialPayload" type="application\/json">([\s\S]*?)<\/script>/);
  assert.ok(embeddedPayload, "embedded Widget must contain an initial payload");
  assert.deepEqual(JSON.parse(embeddedPayload[1]), recommended.structuredContent);

  const resources = await rpc("resources/list");
  assert.equal(resources.resources.length, 2);
  assert.match(resources.resources[0].uri, /photo-refiner-flow-settings/);
  assert.match(resources.resources[1].uri, /photo-refiner-flow/);
  const resource = await rpc("resources/read", {uri: resources.resources[0].uri});
  assert.equal(resource.contents[0].mimeType, "text/html;profile=mcp-app");
  const resourceHtml = resource.contents[0].text;
  // Proposal-sheet structure: three rows, accordion pickers, pro drawer
  assert.match(resourceHtml, /data-pick/);
  assert.match(resourceHtml, /建议方案|proposal/);
  assert.match(resourceHtml, /Starryear 二次创作/);
  assert.match(resourceHtml, /高清出图是灵魂/);
  assert.match(resourceHtml, /专业参数/);
  assert.match(resourceHtml, /本次将执行：/);
  assert.match(resourceHtml, /提示词工作台/);
  assert.match(resourceHtml, /提示词库/);
  assert.match(resourceHtml, /自定义宽高/);
  assert.match(resourceHtml, /recipe-grid/);
  assert.match(resourceHtml, /preset-list/);
  assert.match(resourceHtml, /先选择风格和强度/);
  assert.match(resourceHtml, /先看效果图（推荐）/);
  assert.match(resourceHtml, /确认并开始/);
  assert.match(resourceHtml, /确认开跑/);
  assert.match(resourceHtml, /单张直接效果图（默认，不拼接）/);
  assert.match(resourceHtml, /待补效果图/);
  assert.match(resourceHtml, /先出主图/);
  assert.match(resourceHtml, /输出画幅继承画幅设置/);
  assert.ok(resourceHtml.includes("头部 + 人脸"));
  assert.match(resourceHtml, /内置可直接使用/);
  assert.match(resourceHtml, /根据照片的建议/);
  assert.match(resourceHtml, /已应用到本次设置/);
  assert.match(resourceHtml, /direction\.preset/);
  assert.match(resourceHtml, /labelZh\|\|p\.label/);
  assert.ok(resourceHtml.indexOf('id="rowCreative"') > resourceHtml.indexOf('id="rowLook"'));
  assert.ok(resourceHtml.indexOf('id="rowShip"') > resourceHtml.indexOf('id="rowCreative"'));
  // Payload hygiene: token substituted, fallback flagged, previews bounded
  assert.doesNotMatch(resourceHtml, /__PHOTO_REFINER_INITIAL_PAYLOAD__/);
  const resourcePayloadMatch = resourceHtml.match(/<script id="photoRefinerInitialPayload" type="application\/json">([\s\S]*?)<\/script>/);
  assert.ok(resourcePayloadMatch, "resource Widget must contain a baseline payload");
  const resourcePayload = JSON.parse(resourcePayloadMatch[1]);
  assert.equal(resourcePayload._photoRefinerFallback, true);
  assert.equal(resourcePayload.defaults.creativeRecipe, "none");
  assert.match(resourceHtml, /自然电影/);
  const dataUriBytes = resourcePayload.creativeRecipes.recipes.reduce((total, item) => total + (item.preview?.dataUri?.length || 0), 0);
  assert.ok(dataUriBytes > 0 && dataUriBytes < 600000, `selector previews must stay small, got ${dataUriBytes} chars`);
  // Widget behavior wiring must survive the redesign
  assert.match(resourceHtml, /watchRealPayload/);
  assert.match(resourceHtml, /__prcBound/);
  assert.match(resourceHtml, /sharedWorkflowWith/);
  assert.match(resourceHtml, /window\.openai\.callTool\(\{name:params\.name,arguments:params\.arguments\}\)/);
  assert.match(resourceHtml, /bridgeRequest/);
  assert.doesNotMatch(resourceHtml, /callTool\.length/);
  assert.match(resourceHtml, /addEventListener\('change',handleFieldChange\)/);
  assert.match(resourceHtml, /未收到初始设置/);
  assert.match(resourceHtml, /不要再次打开设置面板/);
  assert.match(resourceHtml, /PHOTO_REFINER_FLOW_SETTINGS_SUBMITTED/);
  assert.match(resourceHtml, /creativeRecipe/);
  // Every element id the Widget script resolves must exist in the markup — a
  // missing id throws during load() and leaves the panel stuck on "loading".
  const mainScript = resourceHtml.slice(resourceHtml.indexOf("<script>", resourcePayloadMatch.index));
  for (const match of mainScript.matchAll(/getElementById\('([^']+)'\)/g)) {
    const id = match[1];
    if (!id || id.includes("+")) continue;
    assert.ok(resourceHtml.includes(`id="${id}"`), `Widget script references missing element id: ${id}`);
  }

  const nodeOpened = await rpc("tools/call", {
    name: "open_photo_refiner_flow",
    arguments: {sourceCount: 1, suggestedPreset: "natural-landscape", suggestedCreativeRecipe: "s001-abstract-quartet"},
  });
  assert.equal(nodeOpened.structuredContent.kind, "photo-refiner-flow");
  assert.equal(nodeOpened.structuredContent.schemaVersion, 1);
  assert.equal(nodeOpened.structuredContent.defaults.sourceCount, 1);
  assert.equal(nodeOpened.structuredContent.defaults.preset, "natural-landscape");
  assert.equal(nodeOpened.structuredContent.defaults.creativeRecipe, "s001-abstract-quartet");
  assert.match(nodeOpened._meta.ui.resourceUri, /photo-refiner-flow/);
  assert.equal(nodeOpened.content[1].type, "resource");
  assert.match(nodeOpened.content[1].resource.text, /Photo Refiner · Node Canvas/);
  assert.match(nodeOpened.content[1].resource.text, /submit_photo_refiner_flow_graph/);
  assert.match(nodeOpened.content[1].resource.text, /PHOTO_REFINER_FLOW_GRAPH_SUBMITTED/);
  assert.doesNotMatch(nodeOpened.content[1].resource.text, /href="styles\.css"/);
  assert.doesNotMatch(nodeOpened.content[1].resource.text, /src="app\.js"/);

  const nodeResource = await rpc("resources/read", {uri: resources.resources[1].uri});
  assert.equal(nodeResource.contents[0].mimeType, "text/html;profile=mcp-app");
  assert.match(nodeResource.contents[0].text, /__PHOTO_REFINER_NODE_PAYLOAD__/);
  assert.match(nodeResource.contents[0].text, /openai\.callTool/);
  assert.match(nodeResource.contents[0].text, /Effect B|效果 B/);

  const graph = {
    version: 1,
    graphId: "smoke-node-graph",
    createdFrom: "node-canvas",
    nodes: [
      {id: "source", type: "source", enabled: true, config: {sourceCount: 1}, position: {x: 0, y: 0}},
      {id: "look_a", type: "look", enabled: true, config: {preset: "natural-landscape", styleStrength: 35, renderMode: "look-master"}, position: {x: 1, y: 0}},
      {id: "effect_b", type: "creative-effect", enabled: false, config: {recipeId: "s001-abstract-quartet", mode: "direct-effect", sourceCommit: ""}, position: {x: 2, y: 0}},
      {id: "approval", type: "approval", enabled: true, config: {deliveryMode: "preview-first"}, position: {x: 3, y: 0}},
      {id: "recovery", type: "recovery", enabled: true, config: {mode: "normal", generationBudget: "balanced"}, position: {x: 4, y: 0}},
      {id: "delivery", type: "delivery", enabled: true, config: {resolution: "source-width", outputFormat: "jpg"}, position: {x: 5, y: 0}},
    ],
    edges: [
      {from: "source", to: "look_a", kind: "flow"},
      {from: "look_a", to: "approval", kind: "flow"},
      {from: "approval", to: "recovery", kind: "flow"},
      {from: "recovery", to: "delivery", kind: "flow"},
    ],
  };
  const submittedGraph = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_graph",
    arguments: {userConfirmed: true, graph},
  });
  assert.equal(submittedGraph.structuredContent.ok, true);
  assert.equal(submittedGraph.structuredContent.graphId, "smoke-node-graph");
  assert.ok(fs.existsSync(submittedGraph.structuredContent.graphPath));
  const graphRecord = JSON.parse(fs.readFileSync(submittedGraph.structuredContent.graphPath, "utf8"));
  assert.equal(graphRecord.confirmedBy, "photo-refiner-flow-studio");
  assert.equal(graphRecord.graph.graphId, "smoke-node-graph");

  const defaults = recommended.structuredContent.defaults;
  defaults.clothing.wrinkleReduction = 35;
  const submitted = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_settings",
    arguments: {userConfirmed: true, config: defaults},
  });
  assert.equal(submitted.structuredContent.ok, true);
  assert.ok(fs.existsSync(submitted.structuredContent.confirmationPath));
  const confirmation = JSON.parse(fs.readFileSync(submitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(confirmation.schemaVersion, 3);
  assert.equal(confirmation.executionMode, "photo-refinement");
  assert.equal(confirmation.resolvedCreativeRecipe, null);
  assert.equal(confirmation.config.preset, "natural-landscape");
  assert.equal(confirmation.config.styleStrength, 35);
  assert.equal(confirmation.resolvedPrompt.defaultStrength, 35);
  assert.equal(confirmation.config.clothing.wrinkleReduction, 35);
  assert.equal(confirmation.config.portrait.enabled, false);
  assert.equal(confirmation.config.body.enabled, false);

  // Same-preset saved user tuning must win over the catalog default.
  const tuned = JSON.parse(JSON.stringify(defaults));
  tuned.styleStrength = 42;
  await rpc("tools/call", {name: "submit_photo_refiner_flow_settings", arguments: {userConfirmed: true, config: tuned}});
  const reopened = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 1, suggestedPreset: "natural-landscape"},
  });
  assert.equal(reopened.structuredContent.defaults.styleStrength, 42);

  // A different recommendation must adopt that preset's own default strength.
  const switched = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 1, suggestedPreset: "clean-architecture"},
  });
  assert.equal(switched.structuredContent.defaults.preset, "clean-architecture");
  assert.equal(switched.structuredContent.defaults.styleStrength, 30);

  const unsafe = JSON.parse(JSON.stringify(defaults));
  unsafe.body.enabled = true;
  unsafe.body.waistSlim = 80;
  const rejected = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_settings",
    arguments: {userConfirmed: true, config: unsafe},
  });
  assert.equal(rejected.isError, true);
  assert.match(rejected.structuredContent.error, /0 to 40/);

  const creativeOpened = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 1, suggestedCreativeRecipe: "s001-abstract-quartet"},
  });
  assert.equal(creativeOpened.structuredContent.defaults.creativeRecipe, "s001-abstract-quartet");
  const creativeConfig = JSON.parse(JSON.stringify(creativeOpened.structuredContent.defaults));
  creativeConfig.uiMode = "pro";
  creativeConfig.creativeFromBase = true;
  const creativeSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_settings",
    arguments: {userConfirmed: true, config: creativeConfig},
  });
  assert.equal(creativeSubmitted.structuredContent.ok, true);
  assert.equal(creativeSubmitted.structuredContent.summary.executionMode, "creative-translation");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeRecipe, "s001-abstract-quartet");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeAssemblyMode, "direct-effect");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeFromBase, true);
  const creativeConfirmation = JSON.parse(fs.readFileSync(creativeSubmitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(creativeConfirmation.resolvedCreativeRecipe.sourceCommit, "b71ad7b187d00a72378a15f32181b655907d32a9");
  assert.equal(creativeConfirmation.config.creativeAssemblyMode, "direct-effect");
  assert.equal(creativeConfirmation.config.creativeFromBase, true);
  assert.equal(creativeConfirmation.creativeOutput.mode, "direct-effect");

  const originalAssembly = JSON.parse(JSON.stringify(creativeConfig));
  originalAssembly.creativeAssemblyMode = "original-assembly";
  const originalSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_settings",
    arguments: {userConfirmed: true, config: originalAssembly},
  });
  assert.equal(originalSubmitted.structuredContent.summary.creativeAssemblyMode, "original-assembly");
  const originalConfirmation = JSON.parse(fs.readFileSync(originalSubmitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(originalConfirmation.creativeOutput.originalAssembly, true);

  // A completed collage must not become the next job's implicit output mode.
  const freshAfterAssembly = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 1},
  });
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeRecipe, "none");
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeAssemblyMode, "direct-effect");
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeFromBase, false);

  const incompatible = JSON.parse(JSON.stringify(creativeConfig));
  incompatible.creativeRecipe = "s008-logo";
  const incompatibleResult = await rpc("tools/call", {
    name: "submit_photo_refiner_flow_settings",
    arguments: {userConfirmed: true, config: incompatible},
  });
  assert.equal(incompatibleResult.isError, true);
  assert.match(incompatibleResult.structuredContent.error, /requires 2-5 source photographs/);

  const vesak = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 3, suggestedCreativeRecipe: "s013-vesak"},
  });
  const mix = await rpc("tools/call", {
    name: "open_photo_refiner_flow_settings",
    arguments: {sourceCount: 3, suggestedCreativeRecipe: "s014-mix"},
  });
  assert.equal(vesak.structuredContent.defaults.creativeRecipe, "s013-vesak");
  assert.equal(mix.structuredContent.defaults.creativeRecipe, "s014-mix");

  server.stdin.end();
  fs.rmSync(smokeHome, {recursive: true, force: true});
  console.log(JSON.stringify({ok: true, confirmationPath: submitted.structuredContent.confirmationPath}));
})().catch((error) => {
  server.kill();
  fs.rmSync(smokeHome, {recursive: true, force: true});
  console.error(error);
  process.exitCode = 1;
});
