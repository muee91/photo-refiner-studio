"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const smokeHome = fs.mkdtempSync(path.join(os.tmpdir(), "photo-refiner-smoke-"));
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

// A dead server must fail the smoke loudly, never pass it vacuously.
let finished = false;
server.on("exit", (code) => {
  if (!finished) {
    console.error(`server exited prematurely with code ${code}`);
    process.exit(1);
  }
});
function rpc(method, params = {}, timeoutMs = 15000) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve, reject});
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(`rpc timeout waiting for ${method}`));
      }
    }, timeoutMs);
    server.stdin.write(`${JSON.stringify({jsonrpc: "2.0", id, method, params})}\n`);
  });
}

(async () => {
  // A user-authored prompt containing `$&`-style sequences must survive the
  // Widget payload serialization verbatim instead of being interpreted as a
  // String.replace replacement pattern.
  fs.mkdirSync(path.join(smokeHome, ".codex", "photo-refiner"), {recursive: true});
  fs.writeFileSync(
    path.join(smokeHome, ".codex", "photo-refiner", "preferences.json"),
    `${JSON.stringify({customPrompts: [{id: "dollar-guard", kind: "custom", label: "dollar guard", prompt: "keep $& and $' and $$ intact", avoid: "old text stays $` put", savedAt: "2026-01-01T00:00:00.000Z"}]})}\n`,
  );

  const initialized = await rpc("initialize", {protocolVersion: "2024-11-05"});
  assert.equal(initialized.serverInfo.name, "photo-refiner-studio");

  const listed = await rpc("tools/list");
  assert.deepEqual(listed.tools.map((item) => item.name), ["open_photo_refiner_settings", "submit_photo_refiner_settings", "delete_photo_refiner_prompt", "get_photo_refiner_recipe_preview", "set_photo_refiner_recipe_preview"]);
  assert.deepEqual(listed.tools[0].inputSchema.required, ["sourceCount"]);
  assert.equal(listed.tools[0].inputSchema.properties.sourceCount.minimum, 1);
  // Broker-envelope tolerance: widget-originated calls must accept extra
  // fields some Codex brokers add, so no const/additionalProperties:false.
  assert.equal(listed.tools[1].inputSchema.properties.userConfirmed.type, "boolean");
  assert.equal(listed.tools[1].inputSchema.properties.userConfirmed.const, undefined);
  assert.equal(listed.tools[1].inputSchema.additionalProperties, true);
  assert.equal(listed.tools[2].inputSchema.additionalProperties, true);
  assert.deepEqual(listed.tools[1].outputSchema.required, ["ok", "kind", "confirmationId", "confirmationPath", "confirmedAt"]);

  const noSource = await rpc("tools/call", {name: "open_photo_refiner_settings", arguments: {sourceCount: 0}});
  assert.equal(noSource.isError, true);
  assert.match(noSource.structuredContent.error, /source photograph is required/);

  const opened = await rpc("tools/call", {name: "open_photo_refiner_settings", arguments: {sourceCount: 2}});
  assert.equal(opened.structuredContent.schemaVersion, 3);
  assert.equal(opened.structuredContent.defaults.workflow, "batch");
  assert.equal(opened.structuredContent.defaults.sourceCount, 2);
  assert.equal(opened.structuredContent.defaults.creativeRecipe, "none");
  assert.equal(opened.structuredContent.defaults.creativeAssemblyMode, "direct-effect");
  assert.equal(opened.structuredContent.defaults.creativeFromBase, false);
  assert.equal(opened.structuredContent.defaults.creativeHdChain, false);
  assert.equal(opened.structuredContent.defaults.creativeUpscale, true);
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
    name: "open_photo_refiner_settings",
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
  assert.match(resourceHtml, /使用此配方/);
  assert.match(resourceHtml, /高清创意链/);
  assert.match(resourceHtml, /4X-UltraSharp/);
  assert.match(resourceHtml, /替换效果图/);
  assert.match(resourceHtml, /恢复默认图/);
  assert.match(resourceHtml, /lightbox/);
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
  // interactive wiring must exist for every control group — a dropped wiring
  // leaves controls dead while the panel still renders (0.7.0 regression)
  for (const wiring of ["querySelectorAll\\('#recipeFilters \\.chip'\\)", "querySelectorAll\\('.chip\\[data-frag\\]'\\)", "querySelectorAll\\('.opt-card\\[data-delivery\\]'\\)", "querySelectorAll\\('#resSeg \\.chip'\\)", "getElementById\\('resApply'\\)", "querySelectorAll\\('#proTabs button'\\)", "querySelectorAll\\('.row-btn\\[data-pick\\]'\\)"]) {
    assert.match(resourceHtml, new RegExp(wiring), `missing wiring: ${wiring}`);
  }
  assert.match(resourceHtml, /未收到初始设置/);
  assert.match(resourceHtml, /不要再次打开设置面板/);
  assert.match(resourceHtml, /PHOTO_REFINER_PANEL_SUBMITTED/);
  assert.match(resourceHtml, /creativeRecipe/);
  // Every element id the Widget script resolves must exist in the markup — a
  // missing id throws during load() and leaves the panel stuck on "loading".
  const mainScript = resourceHtml.slice(resourceHtml.indexOf("<script>", resourcePayloadMatch.index));
  for (const match of mainScript.matchAll(/getElementById\('([^']+)'\)/g)) {
    const id = match[1];
    if (!id || id.includes("+")) continue;
    assert.ok(resourceHtml.includes(`id="${id}"`), `Widget script references missing element id: ${id}`);
  }

  const defaults = recommended.structuredContent.defaults;
  defaults.clothing.wrinkleReduction = 35;
  const submitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
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

  const creativeOpened = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1, suggestedCreativeRecipe: "s001-abstract-quartet"},
  });
  assert.equal(creativeOpened.structuredContent.defaults.creativeRecipe, "s001-abstract-quartet");
  const creativeConfig = JSON.parse(JSON.stringify(creativeOpened.structuredContent.defaults));
  creativeConfig.uiMode = "pro";
  creativeConfig.creativeFromBase = true;
  const creativeSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: creativeConfig},
  });
  assert.equal(creativeSubmitted.structuredContent.ok, true);
  assert.equal(creativeSubmitted.structuredContent.summary.executionMode, "creative-translation");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeRecipe, "s001-abstract-quartet");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeAssemblyMode, "direct-effect");
  assert.equal(creativeSubmitted.structuredContent.summary.creativeFromBase, true);
  assert.equal(creativeSubmitted.structuredContent.summary.creativeHdChain, false);
  assert.equal(creativeSubmitted.structuredContent.summary.creativeUpscale, true);
  assert.match(creativeSubmitted.structuredContent.confirmationHash, /^[0-9a-f]{64}$/);
  const creativeConfirmation = JSON.parse(fs.readFileSync(creativeSubmitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(creativeConfirmation.resolvedCreativeRecipe.sourceCommit, "b71ad7b187d00a72378a15f32181b655907d32a9");
  assert.equal(creativeConfirmation.config.creativeAssemblyMode, "direct-effect");
  assert.equal(creativeConfirmation.config.creativeFromBase, true);
  assert.equal(creativeConfirmation.creativeOutput.mode, "direct-effect");
  assert.equal(creativeConfirmation.schemaVersion, 4);
  assert.match(creativeConfirmation.confirmationHash, /^[0-9a-f]{64}$/);

  // Cross-layer contract: a real Studio confirmation (including uiMode=pro and
  // the canonical confirmationHash) must be accepted unchanged by init_job.py.
  const python = process.env.PYTHON || "python3";
  const smokeSource = path.join(smokeHome, "source.jpg");
  const makeSource = childProcess.spawnSync(
    python,
    ["-c", "from PIL import Image; import sys; Image.new('RGB',(1200,1800),(90,120,150)).save(sys.argv[1], quality=95)", smokeSource],
    {encoding: "utf8"},
  );
  assert.equal(makeSource.status, 0, makeSource.stdout + makeSource.stderr);
  const initResult = childProcess.spawnSync(
    python,
    [
      path.resolve(ROOT, "..", "skill", "scripts", "init_job.py"),
      smokeSource,
      "--confirmation-file", creativeSubmitted.structuredContent.confirmationPath,
      "--output-root", path.join(smokeHome, "jobs"),
    ],
    {encoding: "utf8", env: {...process.env, HOME: smokeHome}},
  );
  assert.equal(initResult.status, 0, initResult.stdout + initResult.stderr);
  const crossJobDir = initResult.stdout.trim().split(/\r?\n/).at(-1);
  const crossJob = JSON.parse(fs.readFileSync(path.join(crossJobDir, "job.json"), "utf8"));
  assert.equal(crossJob.ui_mode, "pro");
  assert.equal(crossJob.creative_output.upstream_binding, "look-master");

  const invalidHdOneClick = JSON.parse(JSON.stringify(creativeConfig));
  invalidHdOneClick.creativeFromBase = false;
  invalidHdOneClick.creativeHdChain = true;
  invalidHdOneClick.deliveryMode = "one-click";
  const invalidHdSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: invalidHdOneClick},
  });
  assert.equal(invalidHdSubmitted.isError, true);
  assert.match(invalidHdSubmitted.structuredContent.error, /preview-first/);

  const validHd = JSON.parse(JSON.stringify(invalidHdOneClick));
  validHd.deliveryMode = "preview-first";
  const validHdSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: validHd},
  });
  assert.equal(validHdSubmitted.structuredContent.ok, true);
  assert.equal(validHdSubmitted.structuredContent.summary.creativeHdChain, true);
  assert.equal(validHdSubmitted.structuredContent.summary.deliveryMode, "preview-first");
  assert.match(validHdSubmitted.structuredContent.confirmationHash, /^[0-9a-f]{64}$/);

  const originalAssembly = JSON.parse(JSON.stringify(creativeConfig));
  originalAssembly.creativeAssemblyMode = "original-assembly";
  const originalSubmitted = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: originalAssembly},
  });
  assert.equal(originalSubmitted.structuredContent.summary.creativeAssemblyMode, "original-assembly");
  const originalConfirmation = JSON.parse(fs.readFileSync(originalSubmitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(originalConfirmation.creativeOutput.originalAssembly, true);

  // A completed collage must not become the next job's implicit output mode.
  const freshAfterAssembly = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 1},
  });
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeRecipe, "none");
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeAssemblyMode, "direct-effect");
  assert.equal(freshAfterAssembly.structuredContent.defaults.creativeFromBase, false);

  const incompatible = JSON.parse(JSON.stringify(creativeConfig));
  incompatible.creativeRecipe = "s008-logo";
  const incompatibleResult = await rpc("tools/call", {
    name: "submit_photo_refiner_settings",
    arguments: {userConfirmed: true, config: incompatible},
  });
  assert.equal(incompatibleResult.isError, true);
  assert.match(incompatibleResult.structuredContent.error, /requires 2-5 source photographs/);

  const vesak = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 3, suggestedCreativeRecipe: "s013-vesak"},
  });
  const mix = await rpc("tools/call", {
    name: "open_photo_refiner_settings",
    arguments: {sourceCount: 3, suggestedCreativeRecipe: "s014-mix"},
  });
  assert.equal(vesak.structuredContent.defaults.creativeRecipe, "s013-vesak");
  assert.equal(mix.structuredContent.defaults.creativeRecipe, "s014-mix");

  // recipe lightbox tooling: large fetch, user replacement, reset-to-default
  const previewGet = await rpc("tools/call", {name: "get_photo_refiner_recipe_preview", arguments: {recipeId: "s001-abstract-quartet"}});
  assert.equal(previewGet.structuredContent.ok, true);
  assert.equal(previewGet.structuredContent.source, "original");
  const inlineLen = opened.structuredContent.creativeRecipes.recipes.find((item) => item.id === "s001-abstract-quartet").preview.dataUri.length;
  assert.ok(previewGet.structuredContent.dataUri.length > inlineLen, "large preview must exceed the inline thumbnail");
  const tinyPng = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  const previewSet = await rpc("tools/call", {name: "set_photo_refiner_recipe_preview", arguments: {recipeId: "s001-abstract-quartet", dataUri: tinyPng}});
  assert.equal(previewSet.structuredContent.ok, true);
  assert.equal(previewSet.structuredContent.source, "user");
  const afterOverride = await rpc("tools/call", {name: "open_photo_refiner_settings", arguments: {sourceCount: 1}});
  assert.equal(afterOverride.structuredContent.creativeRecipes.recipes.find((item) => item.id === "s001-abstract-quartet").preview.overridden, true);
  const previewGetUser = await rpc("tools/call", {name: "get_photo_refiner_recipe_preview", arguments: {recipeId: "s001-abstract-quartet"}});
  assert.equal(previewGetUser.structuredContent.source, "user");
  const previewReset = await rpc("tools/call", {name: "set_photo_refiner_recipe_preview", arguments: {recipeId: "s001-abstract-quartet", reset: true}});
  assert.equal(previewReset.structuredContent.reset, true);
  assert.equal(previewReset.structuredContent.source, "bundled");
  const invalidSet = await rpc("tools/call", {name: "set_photo_refiner_recipe_preview", arguments: {recipeId: "s001-abstract-quartet", dataUri: "data:text/html;base64,PGI+"}});
  assert.equal(invalidSet.isError, true);

  finished = true;
  server.stdin.end();
  fs.rmSync(smokeHome, {recursive: true, force: true});
  console.log(JSON.stringify({ok: true, confirmationPath: submitted.structuredContent.confirmationPath}));
})().catch((error) => {
  server.kill();
  fs.rmSync(smokeHome, {recursive: true, force: true});
  console.error(error);
  process.exitCode = 1;
});
