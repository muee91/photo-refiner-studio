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

// ── Widget HTML quality gates ──────────────────────────────────────────────
// These are the defects an audit found in the shipped panel; each one is now a
// gate so a future edit cannot reintroduce it silently.
const WCAG_SRGB = (channel) => {
  const s = channel / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
function contrastRatio(rgbA, rgbB) {
  const lum = ([r, g, b]) => 0.2126 * WCAG_SRGB(r) + 0.7152 * WCAG_SRGB(g) + 0.0722 * WCAG_SRGB(b);
  const [hi, lo] = [lum(rgbA), lum(rgbB)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function parseColor(value) {
  const hex = value.trim().match(/^#([0-9a-f]{6})$/i);
  if (hex) return [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16));
  const rgb = value.match(/rgba?\(([^)]+)\)/);
  if (rgb) {
    const parts = rgb[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return parts.slice(0, 3);
  }
  return null;
}
function rootTokens(styleBlock) {
  const declaration = styleBlock.match(/:root\s*\{([^}]*)\}/);
  if (!declaration) throw new Error("gate: no :root block");
  const tokens = {};
  for (const [, name, value] of declaration[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) tokens[name] = value.trim();
  return tokens;
}
function widgetHtmlInvariants(html) {
  const styleBlock = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1];
  assert.ok(styleBlock, "gate: Widget must ship one inline <style> block");
  const scriptBlock = (html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/) || [])[1];
  assert.ok(scriptBlock, "gate: Widget script not found");
  const tokens = rootTokens(styleBlock);
  // Collect every violation: a fail-fast gate hides all but the first defect.
  const problems = [];
  const need = (condition, message) => {
    if (!condition) problems.push(message);
  };

  need(/<title>[^<\s][^<]*<\/title>/.test(html), "Widget needs a non-empty <title> (WCAG 2.4.2)");

  // Every custom property referenced in CSS must be declared in :root. The blue
  // leftovers from the pre-darkroom theme rendered the lightbox CTA invisible.
  const undefinedTokens = [...new Set([...styleBlock.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]))].filter((name) => !(name in tokens));
  need(undefinedTokens.length === 0, `CSS references tokens that :root never declares: ${undefinedTokens.join(", ")}`);

  // Contrast floors for the text roles that carry decisions. A missing token is
  // itself a failure, and must report as one instead of crashing the gate.
  const colorOf = (name) => {
    if (!(name in tokens)) {
      problems.push(`${name} is not declared in :root`);
      return null;
    }
    const parsed = parseColor(tokens[name]);
    if (!parsed) {
      problems.push(`${name} is not a plain hex/rgb color, so the gate cannot check it`);
      return null;
    }
    return parsed;
  };
  const bg = colorOf("--bg");
  if (bg) {
    for (const role of ["--ink", "--muted", "--faint"]) {
      const fg = colorOf(role);
      if (!fg) continue;
      const ratio = contrastRatio(fg, bg);
      need(ratio >= 4.5, `${role} on --bg is ${ratio.toFixed(2)}:1, needs 4.5:1`);
    }
  }
  const ctaInk = colorOf("--cta-ink");
  for (const stop of ["--cta-top", "--cta-bottom"]) {
    const color = colorOf(stop);
    if (!ctaInk || !color) continue;
    const ratio = contrastRatio(ctaInk, color);
    need(ratio >= 4.5, `--cta-ink on ${stop} is ${ratio.toFixed(2)}:1, needs 4.5:1`);
  }

  // No hard-coded panel version: the manifest is the only version source.
  need(!/V0\.\d/.test(html), "Widget must not hard-code its own version label");
  need(/payload\.widgetVersion/.test(scriptBlock), "Widget should render the version from the payload");

  // Strings from stored preferences and synced recipe text may only reach
  // innerHTML through esc().
  for (const [, template] of scriptBlock.matchAll(/innerHTML=`([^`]*)`/g)) {
    for (const [, expr] of template.matchAll(/\$\{([^}]*)\}/g)) {
      need(/^esc\(/.test(expr.trim()), `unescaped \${${expr}} interpolated into innerHTML`);
    }
  }

  // Selection and disclosure state must be exposed, not painted.
  need((html.match(/aria-pressed=/g) || []).length >= 12, "toggle controls need aria-pressed in markup");
  need((scriptBlock.match(/setAttribute\(['"]aria-pressed['"]/g) || []).length >= 5, "JS must keep aria-pressed in sync");
  need(/setAttribute\(['"]aria-expanded['"]/.test(scriptBlock), "pickers must expose aria-expanded");
  need(/id="lightbox"[^>]*role="dialog"/.test(html), "recipe lightbox needs dialog semantics");
  need(/id="lightbox"[^>]*aria-modal="true"/.test(html), "recipe lightbox needs aria-modal");
  need(/id="status"[^>]*role="status"/.test(html), "the status line must be a live region");
  need(!/<label>([^<]*)<\/label>/.test(html), "bare <label> without a control cannot name anything");
  // The pro-drawer "已调整"回显 is a data attribute written purely to be styled;
  // without a CSS consumer the affordance silently never appears.
  if (/dataset\.tuned\s*=/.test(scriptBlock)) {
    need(/\[data-tuned/.test(styleBlock), "dataset.tuned is written but no CSS reads [data-tuned]");
  }

  // Keyboard contract: Enter must not steal a focused control's activation.
  need(/ACTIVATABLE/.test(scriptBlock), "Enter handler has to skip controls that activate on Enter");
  need(/event\.source===window\.parent/.test(scriptBlock), "inbound postMessage must be source-checked");
  need(/entry\.timer=setTimeout/.test(scriptBlock), "bridge requests need a timeout so submit cannot hang");

  // The preview picker was a display:none file input, unreachable by keyboard.
  need(/<input type="file" id="lightboxFile" class="sr-only"/.test(html), "file input must stay focusable");
  need(!/id="lightboxFile"[^>]*\shidden/.test(html), "file input must not be hidden");

  // Touch-target floor on the dense controls (WCAG 2.5.8).
  const rules = new Map();
  for (const [, selectorText, bodyText] of styleBlock.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    for (const selector of selectorText.split(",").map((part) => part.trim())) {
      if (!rules.has(selector)) rules.set(selector, bodyText);
    }
  }
  for (const selector of [".row-btn", ".chip", ".btn", ".tabs button", ".recipe-detail", ".library-item button", "#submit", ".mode-card", ".opt-card", ".preset-row"]) {
    const body = rules.get(selector);
    if (body === undefined) {
      problems.push(`no CSS rule for ${selector}`);
      continue;
    }
    const px = [...body.matchAll(/(?:min-height|height|width|min-width):\s*(\d+)px/g)].map((m) => Number(m[1]));
    if (/min-height:\s*var\(--tap/.test(body)) px.push(32);
    need(px.length > 0 && Math.min(...px) >= 24, `${selector} has a hit area under 24px`);
  }
  need(/@media\(max-width:5\d\dpx\)\{[\s\S]{0,40}\.lightbox-panel\{grid-template-columns:1fr/.test(styleBlock), "lightbox needs a single-column breakpoint");

  // Markup nesting: an unclosed wrapper silently relies on the parser.
  const body = html.slice(html.indexOf("<body>") + "<body>".length, html.indexOf("<script id="));
  const voids = new Set(["img", "input", "br", "hr", "meta", "link", "source"]);
  const stack = [];
  let nesting = "";
  for (const [, kind, name] of body.matchAll(/<(\/?)([a-z0-9]+)[^>]*?>/gi)) {
    const tag = name.toLowerCase();
    if (voids.has(tag)) continue;
    if (kind === "/") {
      const open = stack.pop();
      if (open !== tag) nesting += `</${tag}> does not close <${open || "nothing"}>; `;
    } else stack.push(tag);
  }
  if (stack.length) nesting += `unclosed <${stack.join(">, <")}>; `;
  need(nesting === "", `body markup nesting is malformed: ${nesting}`);

  if (problems.length) assert.fail(`Widget quality gates failed:\n  - ${problems.join("\n  - ")}`);
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
  widgetHtmlInvariants(opened.content[1].resource.text);
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
  for (const wiring of ["querySelectorAll\\('#recipeFilters \\.chip'\\)", "querySelectorAll\\('.chip\\[data-frag\\]'\\)", "querySelectorAll\\('.opt-card\\[data-delivery\\]'\\)", "querySelectorAll\\('#resSeg \\.chip'\\)", "getElementById\\('resApply'\\)", "querySelectorAll\\('#proTabs \\[role=\\\"tab\\\"\\]'\\)", "querySelectorAll\\('.row-btn\\[data-pick\\]'\\)"]) {
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
  const creativeConfirmation = JSON.parse(fs.readFileSync(creativeSubmitted.structuredContent.confirmationPath, "utf8"));
  assert.equal(creativeConfirmation.resolvedCreativeRecipe.sourceCommit, "b71ad7b187d00a72378a15f32181b655907d32a9");
  assert.equal(creativeConfirmation.config.creativeAssemblyMode, "direct-effect");
  assert.equal(creativeConfirmation.config.creativeFromBase, true);
  assert.equal(creativeConfirmation.creativeOutput.mode, "direct-effect");

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
