"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const MANIFEST = JSON.parse(fs.readFileSync(path.join(ROOT, ".codex-plugin", "plugin.json"), "utf8"));
const PRESETS = JSON.parse(fs.readFileSync(path.join(ROOT, "config", "presets.json"), "utf8"));
const CREATIVE_RECIPES = JSON.parse(fs.readFileSync(path.join(ROOT, "config", "creative-recipes.json"), "utf8"));
const CREATIVE_RECIPE_BY_ID = Object.fromEntries(CREATIVE_RECIPES.recipes.map((recipe) => [recipe.id, recipe]));
const WIDGET_TEMPLATE_HTML = fs.readFileSync(path.join(ROOT, "assets", "settings.html"), "utf8");
const NODE_CANVAS_ROOT = path.join(ROOT, "assets", "node-canvas");
const NODE_CANVAS_INDEX_HTML = fs.readFileSync(path.join(NODE_CANVAS_ROOT, "index.html"), "utf8");
const NODE_CANVAS_STYLES = fs.readFileSync(path.join(NODE_CANVAS_ROOT, "styles.css"), "utf8");
const NODE_CANVAS_SCRIPT = fs.readFileSync(path.join(NODE_CANVAS_ROOT, "app.js"), "utf8");
// Use the slash-scoped URI shape accepted by Codex MCP App hosts. A flat URI
// containing an encoded `+` can return a successful tool call while failing to
// resolve and mount the Widget resource.
const WIDGET_VERSION = String(MANIFEST.version).replace(/[^A-Za-z0-9._-]+/g, "-");
const WIDGET_URI = `ui://widget/photo-refiner-flow-settings/${WIDGET_VERSION}.html`;
const NODE_CANVAS_URI = `ui://widget/photo-refiner-flow/${WIDGET_VERSION}.html`;
const WIDGET_MIME = "text/html;profile=mcp-app";
const INITIAL_PAYLOAD_TOKEN = "__PHOTO_REFINER_INITIAL_PAYLOAD__";
// Respect an injected HOME for isolated plugin sessions and smoke tests. macOS
// os.homedir() resolves from the account database and can ignore HOME.
const USER_HOME = process.env.HOME || os.homedir();
const CONFIRMATION_DIR = path.join(USER_HOME, ".codex", "photo-refiner-flow", "confirmed");
const GRAPH_DIR = path.join(USER_HOME, ".codex", "photo-refiner-flow", "graphs");
const PREFERENCES_PATH = path.join(USER_HOME, ".codex", "photo-refiner-flow", "preferences.json");

const DEFAULTS = {
  sourceCount: 1,
  uiMode: "simple",
  workflow: "auto",
  creativeRecipe: "none",
  // Starryear recipes default to a complete effect image. The source-evidence
  // collage remains available as an explicit, recipe-faithful alternative.
  creativeAssemblyMode: "direct-effect",
  // Opt-in two-stage flow: render the confirmed preset as an approved main
  // image first, then translate creatively with that image as look reference.
  creativeFromBase: false,
  // Neutral fallback only; normal jobs pass a subject-aware suggestedPreset.
  preset: "natural-cinematic",
  customPrompt: "",
  customAvoid: "",
  promptFavorite: false,
  aspectRatio: "original",
  framing: "preserve",
  resolution: "source-width",
  // The preview is intentionally the default: Image 2.5 establishes the look
  // first, then the user decides whether the high-resolution recovery pass is warranted.
  deliveryMode: "preview-first",
  outputFormat: "jpg",
  keepIntermediates: false,
  // Neutral fallback. Subject-aware recommendations use each preset's defaultStrength.
  styleStrength: 45,
  global: {
    exposure: 0,
    contrast: 0,
    highlights: 0,
    shadows: 0,
    temperature: 0,
    tint: 0,
    saturation: 0,
    vibrance: 0,
    clarity: 0,
    dehaze: 0,
    denoise: 15,
    sharpen: 15,
    grain: 10,
  },
  portrait: {
    enabled: false,
    skinSmoothing: 0,
    blemishRemoval: 0,
    skinToneEven: 0,
    eyeEnhance: 0,
    teethWhiten: 0,
    faceSlim: 0,
    jawline: 0,
    eyeSize: 0,
  },
  body: {
    enabled: false,
    waistSlim: 0,
    armSlim: 0,
    legSlim: 0,
    legLength: 0,
    shoulderAdjust: 0,
  },
  clothing: {
    wrinkleReduction: 0,
    preserveTexture: 90,
    lintRemoval: 0,
    stainRemoval: 0,
    silhouetteCleanup: 0,
  },
  background: {
    cleanup: 0,
    removeDistractors: 0,
    bokeh: 0,
    skyEnhance: 0,
    foliageEnhance: 0,
    architectureLines: 0,
  },
  detail: {
    mode: "adaptive",
    strength: 60,
    regions: "",
    patchScope: "head-and-face",
    headPatch: true,
  },
  batch: {
    consistency: "balanced",
  },
};

// resources/read has no per-call tool arguments. Keep a usable baseline in
// the static Widget resource so hosts that mount the resource before exposing
// window.openai.toolOutput do not leave every control disabled. The panel
// detects this marker and keeps watching for the real call's source count,
// recommendation, and saved preferences to replace the baseline.
const FALLBACK_WIDGET_PAYLOAD = {
  ok: true,
  kind: "photo-refiner-settings",
  schemaVersion: 3,
  _photoRefinerFallback: true,
  presets: PRESETS,
  creativeRecipes: CREATIVE_RECIPES,
  defaults: clone(DEFAULTS),
  promptLibrary: {custom: []},
  recommendation: "",
  creativeDirections: [],
};

const FALLBACK_NODE_CANVAS_PAYLOAD = {
  ok: true,
  kind: "photo-refiner-flow",
  schemaVersion: 1,
  _photoRefinerFallback: true,
  presets: PRESETS,
  creativeRecipes: CREATIVE_RECIPES,
  defaults: clone(DEFAULTS),
};

function loadPreferences() {
  try {
    const value = JSON.parse(fs.readFileSync(PREFERENCES_PATH, "utf8"));
    if (!isObject(value)) return {};
    const migrated = [
      ...(Array.isArray(value.customPrompts) ? value.customPrompts : []),
      ...(Array.isArray(value.history) ? value.history.filter((item) => item?.kind === "custom") : []),
      ...(Array.isArray(value.favorites) ? value.favorites.filter((item) => item?.kind === "custom") : []),
    ];
    value.customPrompts = migrated.map((item) => ({
      ...item,
      id: item.id || crypto.randomUUID(),
      kind: "custom",
    })).filter((item, index, all) => index === all.findIndex((candidate) => candidate.prompt === item.prompt && candidate.avoid === item.avoid)).slice(0, 30);
    return value;
  } catch (_) {
    return {};
  }
}

function savePreferences(value) {
  fs.mkdirSync(path.dirname(PREFERENCES_PATH), {recursive: true, mode: 0o700});
  fs.writeFileSync(PREFERENCES_PATH, `${JSON.stringify(value, null, 2)}\n`, {encoding: "utf8", mode: 0o600});
}

function promptLibrary(preferences) {
  return {
    custom: Array.isArray(preferences.customPrompts) ? preferences.customPrompts.slice(0, 30) : [],
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function numberIn(value, min, max, field) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${field} must be a number from ${min} to ${max}`);
  }
  return value;
}

function integerIn(value, min, max, field) {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${field} must be an integer from ${min} to ${max}`);
  }
  return value;
}

function enumValue(value, allowed, field) {
  if (!allowed.includes(value)) throw new Error(`${field} must be one of: ${allowed.join(", ")}`);
  return value;
}

function booleanValue(value, field) {
  if (typeof value !== "boolean") throw new Error(`${field} must be true or false`);
  return value;
}

function cleanText(value, maxLength, field) {
  if (typeof value !== "string") throw new Error(`${field} must be text`);
  const cleaned = value.trim();
  if (cleaned.length > maxLength) throw new Error(`${field} exceeds ${maxLength} characters`);
  return cleaned;
}

function mergeDefaults(config) {
  const merged = clone(DEFAULTS);
  for (const [key, value] of Object.entries(config || {})) {
    if (isObject(value) && isObject(merged[key])) Object.assign(merged[key], value);
    else merged[key] = value;
  }
  return merged;
}

function validateConfig(raw) {
  if (!isObject(raw)) throw new Error("config must be an object");
  const config = mergeDefaults(raw);
  config.sourceCount = integerIn(config.sourceCount, 1, 100, "sourceCount");
  config.uiMode = enumValue(config.uiMode, ["simple", "pro"], "uiMode");
  config.workflow = enumValue(config.workflow, ["auto", "single", "batch"], "workflow");
  config.creativeRecipe = cleanText(config.creativeRecipe, 80, "creativeRecipe") || "none";
  config.creativeAssemblyMode = enumValue(config.creativeAssemblyMode, ["direct-effect", "original-assembly"], "creativeAssemblyMode");
  config.creativeFromBase = booleanValue(config.creativeFromBase, "creativeFromBase");
  if (config.creativeRecipe !== "none") {
    const recipe = CREATIVE_RECIPE_BY_ID[config.creativeRecipe];
    if (!recipe) throw new Error(`Unknown creative recipe: ${config.creativeRecipe}`);
    if (config.sourceCount < recipe.sourceCount.min || config.sourceCount > recipe.sourceCount.max) {
      throw new Error(`${recipe.titleZh} requires ${recipe.sourceCount.min === recipe.sourceCount.max ? recipe.sourceCount.min : `${recipe.sourceCount.min}-${recipe.sourceCount.max}`} source photographs`);
    }
  }
  config.preset = cleanText(config.preset, 80, "preset");
  if (config.preset !== "custom" && !PRESETS.presets[config.preset]) {
    throw new Error(`Unknown preset: ${config.preset}`);
  }
  config.customPrompt = cleanText(config.customPrompt, 8000, "customPrompt");
  config.customAvoid = cleanText(config.customAvoid, 4000, "customAvoid");
  config.promptFavorite = booleanValue(config.promptFavorite, "promptFavorite");
  if (config.preset === "custom" && !config.customPrompt) throw new Error("Custom prompt is required");
  config.aspectRatio = enumValue(config.aspectRatio, ["original", "16:9", "3:2", "4:5", "1:1", "9:16"], "aspectRatio");
  config.framing = enumValue(config.framing, ["preserve", "crop", "outpaint", "contain"], "framing");
  if (config.aspectRatio !== "original" && config.framing === "preserve") {
    throw new Error("Changing aspect ratio requires crop, outpaint, or contain");
  }
  const customResolution = /^(\d{3,4})x(\d{3,4})$/i.exec(String(config.resolution));
  if (customResolution) {
    const w = Number(customResolution[1]);
    const h = Number(customResolution[2]);
    if (w < 320 || w > 8192 || h < 320 || h > 8192) {
      throw new Error("Custom resolution must be 320-8192 pixels per side");
    }
    config.resolution = `${w}x${h}`;
  } else {
    config.resolution = enumValue(config.resolution, ["preview", "4k", "source-width"], "resolution");
  }
  config.deliveryMode = enumValue(config.deliveryMode, ["preview-first", "one-click"], "deliveryMode");
  config.outputFormat = enumValue(config.outputFormat, ["png", "jpg", "both"], "outputFormat");
  config.keepIntermediates = booleanValue(config.keepIntermediates, "keepIntermediates");
  config.styleStrength = numberIn(config.styleStrength, 0, 100, "styleStrength");

  for (const key of ["exposure"]) numberIn(config.global[key], -2, 2, `global.${key}`);
  for (const key of ["contrast", "highlights", "shadows", "temperature", "tint", "saturation", "vibrance", "clarity", "dehaze"]) {
    numberIn(config.global[key], -100, 100, `global.${key}`);
  }
  for (const key of ["denoise", "sharpen", "grain"]) numberIn(config.global[key], 0, 100, `global.${key}`);

  config.portrait.enabled = booleanValue(config.portrait.enabled, "portrait.enabled");
  for (const key of ["skinSmoothing", "blemishRemoval", "skinToneEven", "eyeEnhance", "teethWhiten"]) {
    numberIn(config.portrait[key], 0, 100, `portrait.${key}`);
  }
  for (const key of ["faceSlim", "jawline", "eyeSize"]) numberIn(config.portrait[key], 0, 40, `portrait.${key}`);
  config.body.enabled = booleanValue(config.body.enabled, "body.enabled");
  for (const key of ["waistSlim", "armSlim", "legSlim", "legLength", "shoulderAdjust"]) {
    numberIn(config.body[key], 0, 40, `body.${key}`);
  }
  for (const key of ["wrinkleReduction", "preserveTexture", "lintRemoval", "stainRemoval", "silhouetteCleanup"]) {
    numberIn(config.clothing[key], 0, 100, `clothing.${key}`);
  }
  for (const key of ["cleanup", "removeDistractors", "bokeh", "skyEnhance", "foliageEnhance", "architectureLines"]) {
    numberIn(config.background[key], 0, 100, `background.${key}`);
  }
  config.detail.mode = enumValue(config.detail.mode, ["base-only", "face", "adaptive", "explicit"], "detail.mode");
  config.detail.strength = numberIn(config.detail.strength, 0, 100, "detail.strength");
  config.detail.regions = cleanText(config.detail.regions, 1000, "detail.regions");
  config.detail.patchScope = enumValue(config.detail.patchScope, ["head-and-face", "face-only", "custom"], "detail.patchScope");
  config.detail.headPatch = booleanValue(config.detail.headPatch, "detail.headPatch");
  if (config.detail.patchScope === "head-and-face") config.detail.headPatch = true;
  if (config.detail.patchScope === "face-only") config.detail.headPatch = false;
  if (config.detail.mode === "explicit" && !config.detail.regions) throw new Error("Explicit detail mode requires regions");
  config.batch.consistency = enumValue(config.batch.consistency, ["strict", "balanced", "creative"], "batch.consistency");

  if (!config.portrait.enabled) {
    for (const key of Object.keys(config.portrait)) if (key !== "enabled") config.portrait[key] = 0;
  }
  if (!config.body.enabled) {
    for (const key of Object.keys(config.body)) if (key !== "enabled") config.body[key] = 0;
  }
  return config;
}

function resolvedPrompt(config) {
  if (config.preset === "custom") {
    return {label: "自定义", summary: "用户自定义提示词", prompt: config.customPrompt, avoid: config.customAvoid};
  }
  return PRESETS.presets[config.preset];
}

function resolvedCreativeRecipe(config) {
  if (config.creativeRecipe === "none") return null;
  const recipe = CREATIVE_RECIPE_BY_ID[config.creativeRecipe];
  return {
    id: recipe.id,
    number: recipe.number,
    titleZh: recipe.titleZh,
    titleEn: recipe.titleEn,
    summaryZh: recipe.summaryZh,
    sourceCount: recipe.sourceCount,
    output: recipe.output,
    sourceUrl: recipe.sourceUrl,
    sourceCommit: recipe.sourceCommit,
    creativeAssemblyMode: config.creativeAssemblyMode,
    creativeAssemblyLabelZh: config.creativeAssemblyMode === "original-assembly" ? "原版拼接" : "直接效果图",
    ...(recipe.sharedWorkflowWith ? {sharedWorkflowWith: recipe.sharedWorkflowWith} : {}),
  };
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function uiMeta(resourceUri = WIDGET_URI) {
  return {
    // Codex Apps hosts mount widgets from the tool descriptor metadata.
    ui: {resourceUri, visibility: ["model", "app"]},
    "ui/resourceUri": resourceUri,
    // Keep the legacy Apps SDK binding for hosts that still read this alias.
    "openai/outputTemplate": resourceUri,
    "openai/widgetAccessible": true,
  };
}

function widgetResourceMeta() {
  return {
    ui: {prefersBorder: true},
    "openai/widgetDescription": "Interactive Photo Refiner Flow settings panel for confirming a photo refinement workflow before generation.",
    "openai/widgetPrefersBorder": true,
    "openai/widgetCSP": {
      connect_domains: [],
      resource_domains: [],
    },
  };
}

function nodeCanvasResourceMeta() {
  return {
    ui: {prefersBorder: false},
    "openai/widgetDescription": "Interactive Photo Refiner node workflow canvas. It edits a high-level graph while keeping the existing processing backend independent from the UI.",
    "openai/widgetPrefersBorder": false,
    "openai/widgetCSP": {
      connect_domains: [],
      resource_domains: [],
    },
  };
}

function nodeCanvasHtmlWithInitialPayload(payload) {
  const serialized = JSON.stringify(payload)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
  let html = NODE_CANVAS_INDEX_HTML;
  html = html.replace('<link rel="stylesheet" href="styles.css">', () => `<style>${NODE_CANVAS_STYLES}</style>`);
  html = html.replace('<script src="app.js"></script>', () => `<script>window.__PHOTO_REFINER_NODE_PAYLOAD__=${serialized};</script><script>${NODE_CANVAS_SCRIPT}</script>`);
  if (html === NODE_CANVAS_INDEX_HTML) throw new Error("Photo Refiner Flow could not inline its assets");
  return html;
}

function validateSubmittedGraph(raw) {
  if (!isObject(raw) || raw.version !== 1 || typeof raw.graphId !== "string" || !raw.graphId.trim()) {
    throw new Error("Invalid node graph header");
  }
  if (!Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) throw new Error("Node graph requires nodes and edges arrays");
  const ids = new Set();
  const enabled = [];
  for (const node of raw.nodes) {
    if (!isObject(node) || typeof node.id !== "string" || !node.id || typeof node.type !== "string" || typeof node.enabled !== "boolean" || !isObject(node.config)) {
      throw new Error("Node graph contains a malformed node");
    }
    if (ids.has(node.id)) throw new Error(`Duplicate node id: ${node.id}`);
    ids.add(node.id);
    if (node.enabled) enabled.push(node);
  }
  const allowed = ["source", "look", "creative-effect", "approval", "recovery", "delivery"];
  const types = enabled.map((node) => node.type);
  if (types.some((type) => !allowed.includes(type))) throw new Error("Node graph contains an unknown node type");
  const creative = enabled.find((node) => node.type === "creative-effect");
  const recovery = enabled.find((node) => node.type === "recovery");
  const expected = ["source", "look", ...(creative ? ["creative-effect"] : []), "approval", ...(recovery ? ["recovery"] : []), "delivery"];
  if (JSON.stringify(types) !== JSON.stringify(expected)) throw new Error(`Enabled node order must be: ${expected.join(" -> ")}`);
  const source = enabled.find((node) => node.type === "source");
  const look = enabled.find((node) => node.type === "look");
  if (!source || !Number.isInteger(source.config.sourceCount) || source.config.sourceCount < 1 || source.config.sourceCount > 100) throw new Error("Source node requires sourceCount 1-100");
  if (!look || !["direction-only", "look-master"].includes(look.config.renderMode || "look-master")) throw new Error("Look node has invalid renderMode");
  if (creative) {
    const recipe = CREATIVE_RECIPE_BY_ID[creative.config.recipeId];
    if (!recipe) throw new Error(`Unknown creative recipe: ${creative.config.recipeId}`);
    if (source.config.sourceCount < recipe.sourceCount.min || source.config.sourceCount > recipe.sourceCount.max) throw new Error(`${recipe.titleZh} does not accept ${source.config.sourceCount} source photographs`);
    if (creative.config.sourceCommit && creative.config.sourceCommit !== recipe.sourceCommit) throw new Error("Creative recipe sourceCommit does not match installed catalog");
    if (!["direct-effect", "original-assembly"].includes(creative.config.mode || "direct-effect")) throw new Error("Creative node has invalid mode");
    if (creative.config.mode === "original-assembly" && look.config.renderMode === "look-master") throw new Error("original-assembly cannot consume a rendered LOOK_A");
  }
  if (recovery) {
    const mode = recovery.config.mode || "normal";
    if (!["normal", "creative-safe", "disabled"].includes(mode)) throw new Error("Recovery node has invalid mode");
    if (creative?.config.mode === "original-assembly") throw new Error("Recovery must be disabled for original-assembly");
    if (mode === "creative-safe" && (!creative || source.config.sourceCount > 1)) throw new Error("creative-safe recovery requires a single-source creative effect");
  }
  const expectedEdges = enabled.slice(0, -1).map((node, index) => `${node.id}->${enabled[index + 1].id}`);
  const actualEdges = raw.edges
    .filter((edge) => isObject(edge) && (edge.kind || "flow") === "flow")
    .map((edge) => `${edge.from}->${edge.to}`);
  if (JSON.stringify(actualEdges) !== JSON.stringify(expectedEdges)) throw new Error("Enabled flow must be one continuous controlled chain");
  return clone(raw);
}

function widgetHtmlWithInitialPayload(payload) {
  // Some Codex brokers mount the embedded resource but do not expose the
  // originating tool result through window.openai.toolOutput. Keep the
  // structured content available in that compatibility path as inert JSON.
  const serialized = JSON.stringify(payload)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
  // A string replacement argument would interpret `$&`, `$'`, and similar
  // sequences inside user-authored prompt text as replacement patterns and
  // corrupt the Widget HTML. Pass a function so the payload is inert.
  const html = WIDGET_TEMPLATE_HTML.replace(INITIAL_PAYLOAD_TOKEN, () => serialized);
  if (html === WIDGET_TEMPLATE_HTML) throw new Error("Photo Refiner Widget is missing its initial-payload slot");
  return html;
}

function toolDefinitions() {
  return [
    {
      name: "open_photo_refiner_flow_settings",
      title: "Open Photo Refiner Flow settings",
      description: "Optional compact fallback settings panel for Photo Refiner Flow. Use it only when the user explicitly asks for the compact settings surface or the Flow canvas cannot mount. The normal Flow entry is open_photo_refiner_flow.",
      inputSchema: {
        type: "object",
        required: ["sourceCount"],
        properties: {
          sourceCount: {type: "integer", minimum: 1, description: "Positive number of attached or existing source photos"},
          suggestedPreset: {type: "string", description: "Optional preset id inferred from the request"},
          suggestedCreativeRecipe: {type: "string", description: "Optional Starryear creative recipe id inferred from the source photos and request"},
          recommendation: {type: "string", description: "Optional concise subject-aware recommendation shown above the settings"},
          creativeDirections: {type: "array", maxItems: 3, description: "Optional editable creative directions inferred from the photo", items: {type: "object", additionalProperties: false, properties: {label: {type: "string"}, summary: {type: "string"}, prompt: {type: "string"}, avoid: {type: "string"}, preset: {type: "string"}, styleStrength: {type: "number", minimum: 0, maximum: 100}}}},
        },
        additionalProperties: false,
      },
      annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      outputSchema: {
        type: "object",
        required: ["ok", "kind", "schemaVersion", "presets", "creativeRecipes", "defaults"],
        additionalProperties: true,
        properties: {
          ok: {type: "boolean"},
          kind: {type: "string"},
          schemaVersion: {type: "integer"},
          presets: {type: "object"},
          creativeRecipes: {type: "object"},
          defaults: {type: "object"},
          promptLibrary: {type: "object"},
          recommendation: {type: "string"},
          creativeDirections: {type: "array"},
        },
      },
      _meta: uiMeta(),
    },
    {
      name: "open_photo_refiner_flow",
      title: "Open Photo Refiner Flow",
      description: "Primary Photo Refiner Flow entry. Open the node workflow canvas for Source → Look A → Effect B → Approval → Recovery → Delivery after at least one source photograph is known.",
      inputSchema: {
        type: "object",
        required: ["sourceCount"],
        properties: {
          sourceCount: {type: "integer", minimum: 1},
          suggestedPreset: {type: "string"},
          suggestedCreativeRecipe: {type: "string"},
        },
        additionalProperties: false,
      },
      annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      outputSchema: {
        type: "object",
        required: ["ok", "kind", "schemaVersion", "creativeRecipes", "defaults"],
        additionalProperties: true,
        properties: {
          ok: {type: "boolean"},
          kind: {type: "string"},
          schemaVersion: {type: "integer"},
          creativeRecipes: {type: "object"},
          defaults: {type: "object"},
        },
      },
      _meta: uiMeta(NODE_CANVAS_URI),
    },
    {
      name: "submit_photo_refiner_flow_graph",
      title: "Confirm Photo Refiner Flow graph",
      description: "Validate and freeze a graph explicitly submitted from the Photo Refiner Flow. Do not call this on the user's behalf.",
      inputSchema: {
        type: "object",
        required: ["userConfirmed", "graph"],
        properties: {
          userConfirmed: {type: "boolean"},
          graph: {type: "object", additionalProperties: true},
        },
        additionalProperties: true,
      },
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false},
      outputSchema: {
        type: "object",
        required: ["ok", "kind", "graphId", "graphPath", "confirmedAt"],
        additionalProperties: true,
      },
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
    {
      name: "submit_photo_refiner_flow_settings",
      title: "Confirm Photo Refiner Flow settings",
      description: "Validate and freeze settings submitted by the compact Photo Refiner Flow fallback panel. Do not call this on the user's behalf; it represents an explicit panel submission. After success, the returned confirmationPath is authoritative: continue from it without reopening the panel or asking the user to confirm the same settings again.",
      inputSchema: {
        type: "object",
        required: ["userConfirmed", "config"],
        properties: {
          // No `const` and no additionalProperties:false here: some Codex
          // brokers wrap widget-originated calls with extra envelope fields
          // and reject strict schemas as "Invalid MCP tool call params"
          // before the request ever reaches this server. The server itself
          // enforces userConfirmed === true and validates every config field.
          userConfirmed: {type: "boolean"},
          config: {type: "object", additionalProperties: true},
        },
        additionalProperties: true,
      },
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false},
      outputSchema: {
        type: "object",
        required: ["ok", "kind", "confirmationId", "confirmationPath", "confirmedAt"],
        additionalProperties: true,
        properties: {
          ok: {type: "boolean"},
          kind: {type: "string"},
          confirmationId: {type: "string"},
          confirmationPath: {type: "string"},
          confirmedAt: {type: "string"},
          promptHash: {type: "string"},
          summary: {type: "object"},
        },
      },
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
    {
      name: "delete_photo_refiner_flow_prompt",
      title: "Delete saved Photo Refiner Flow prompt",
      description: "Delete one user-authored prompt after an explicit action in the settings panel. Built-in presets are not deletable.",
      inputSchema: {
        type: "object",
        required: ["collection", "entryId"],
        properties: {
          collection: {type: "string", enum: ["custom"]},
          entryId: {type: "string", minLength: 1},
        },
        // Same broker-envelope tolerance as submit_photo_refiner_flow_settings.
        additionalProperties: true,
      },
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
  ];
}

function nodeCanvasToolResult(payload) {
  const html = nodeCanvasHtmlWithInitialPayload(payload);
  return {
    content: [
      {type: "text", text: "Photo Refiner Flow is ready."},
      {type: "resource", resource: {uri: NODE_CANVAS_URI, mimeType: WIDGET_MIME, text: html, _meta: nodeCanvasResourceMeta()}},
      {type: "resource_link", uri: NODE_CANVAS_URI, name: "Photo Refiner Flow", title: "Photo Refiner Flow", mimeType: WIDGET_MIME, _meta: nodeCanvasResourceMeta()},
    ],
    structuredContent: payload,
    isError: false,
    _meta: uiMeta(NODE_CANVAS_URI),
  };
}

function toolResult(payload, withWidget = false) {
  const result = {
    content: [{type: "text", text: withWidget ? "Photo Refiner Flow settings are ready." : JSON.stringify(payload)}],
    structuredContent: payload,
    isError: false,
  };
  if (withWidget) {
    const widgetHtml = widgetHtmlWithInitialPayload(payload);
    result._meta = uiMeta();
    // Code Mode brokers in some Codex builds flatten result metadata. Include
    // the MCP Apps resource as an embedded resource as a compatibility path;
    // native MCP Apps hosts ignore this duplicate and use ui.resourceUri.
    result.content.push({
      type: "resource",
      resource: {
        uri: WIDGET_URI,
        mimeType: WIDGET_MIME,
        text: widgetHtml,
        _meta: widgetResourceMeta(),
      },
    });
    result.content.push({
      type: "resource_link",
      uri: WIDGET_URI,
      name: "Photo Refiner Flow settings",
      title: "Photo Refiner Flow settings",
      mimeType: WIDGET_MIME,
      _meta: widgetResourceMeta(),
    });
  }
  return result;
}

function toolError(message) {
  const payload = {ok: false, error: message};
  return {content: [{type: "text", text: JSON.stringify(payload)}], structuredContent: payload, isError: true};
}

function callTool(name, args) {
  if (name === "open_photo_refiner_flow") {
    if (!Number.isInteger(args.sourceCount) || args.sourceCount < 1) throw new Error("At least one source photograph is required before opening Node Canvas");
    const preferences = loadPreferences();
    const savedConfig = isObject(preferences.lastConfig) ? preferences.lastConfig : {};
    const defaults = mergeDefaults(savedConfig);
    defaults.sourceCount = args.sourceCount;
    defaults.workflow = args.sourceCount > 1 ? "batch" : "single";
    defaults.creativeRecipe = "none";
    defaults.creativeAssemblyMode = "direct-effect";
    defaults.creativeFromBase = false;
    if (typeof args.suggestedPreset === "string" && PRESETS.presets[args.suggestedPreset]) {
      defaults.preset = args.suggestedPreset;
      const presetDefault = PRESETS.presets[args.suggestedPreset].defaultStrength;
      if (typeof presetDefault === "number") defaults.styleStrength = presetDefault;
    }
    if (typeof args.suggestedCreativeRecipe === "string") {
      const recipe = CREATIVE_RECIPE_BY_ID[args.suggestedCreativeRecipe];
      if (recipe && args.sourceCount >= recipe.sourceCount.min && args.sourceCount <= recipe.sourceCount.max) defaults.creativeRecipe = recipe.id;
    }
    return nodeCanvasToolResult({ok: true, kind: "photo-refiner-flow", schemaVersion: 1, presets: PRESETS, creativeRecipes: CREATIVE_RECIPES, defaults});
  }
  if (name === "submit_photo_refiner_flow_graph") {
    if (args.userConfirmed !== true) throw new Error("Explicit user confirmation is required");
    const graph = validateSubmittedGraph(args.graph);
    const now = new Date().toISOString();
    const graphId = graph.graphId || crypto.randomUUID();
    fs.mkdirSync(GRAPH_DIR, {recursive: true, mode: 0o700});
    const graphPath = path.join(GRAPH_DIR, `${graphId}.json`);
    const record = {schemaVersion: 1, graphId, confirmedAt: now, confirmedBy: "photo-refiner-flow-studio", graph};
    fs.writeFileSync(graphPath, `${JSON.stringify(record, null, 2)}\n`, {encoding: "utf8", mode: 0o600});
    return toolResult({ok: true, kind: "photo-refiner-node-graph", graphId, graphPath, confirmedAt: now});
  }
  if (name === "open_photo_refiner_flow_settings") {
    if (!Number.isInteger(args.sourceCount) || args.sourceCount < 1) {
      throw new Error("At least one source photograph is required before opening Photo Refiner Flow settings");
    }
    const preferences = loadPreferences();
    const savedConfig = isObject(preferences.lastConfig) ? preferences.lastConfig : {};
    const defaults = mergeDefaults(savedConfig);
    defaults.sourceCount = args.sourceCount;
    defaults.workflow = args.sourceCount > 1 ? "batch" : "single";
    // Starryear is an opt-in second stage after the normal preset. Do not
    // revive a previously selected recipe or collage mode for a new job.
    defaults.creativeRecipe = "none";
    defaults.creativeAssemblyMode = "direct-effect";
    defaults.creativeFromBase = false;
    if (typeof args.suggestedPreset === "string" && PRESETS.presets[args.suggestedPreset]) {
      defaults.preset = args.suggestedPreset;
      const presetDefault = PRESETS.presets[args.suggestedPreset].defaultStrength;
      const preserveSavedStrength = savedConfig.preset === args.suggestedPreset && typeof savedConfig.styleStrength === "number";
      if (!preserveSavedStrength && typeof presetDefault === "number") defaults.styleStrength = presetDefault;
    }
    if (typeof args.suggestedCreativeRecipe === "string") {
      const suggestedRecipe = CREATIVE_RECIPE_BY_ID[args.suggestedCreativeRecipe];
      if (suggestedRecipe && args.sourceCount >= suggestedRecipe.sourceCount.min && args.sourceCount <= suggestedRecipe.sourceCount.max) {
        defaults.creativeRecipe = suggestedRecipe.id;
      }
    }
    const creativeDirections = Array.isArray(args.creativeDirections) ? args.creativeDirections.slice(0, 3).map((item) => ({
      label: cleanText(String(item?.label || "灵感方向"), 80, "creativeDirections.label"),
      summary: cleanText(String(item?.summary || ""), 240, "creativeDirections.summary"),
      prompt: cleanText(String(item?.prompt || ""), 1800, "creativeDirections.prompt"),
      avoid: cleanText(String(item?.avoid || ""), 600, "creativeDirections.avoid"),
      ...(typeof item?.preset === "string" && PRESETS.presets[item.preset] ? {preset: item.preset} : {}),
      ...(typeof item?.styleStrength === "number" && item.styleStrength >= 0 && item.styleStrength <= 100 ? {styleStrength: item.styleStrength} : {}),
    })).filter((item) => item.prompt) : [];
    return toolResult({ok: true, kind: "photo-refiner-settings", schemaVersion: 3, presets: PRESETS, creativeRecipes: CREATIVE_RECIPES, defaults, promptLibrary: promptLibrary(preferences), recommendation: typeof args.recommendation === "string" ? args.recommendation.trim().slice(0, 500) : "", creativeDirections}, true);
  }
  if (name === "submit_photo_refiner_flow_settings") {
    if (args.userConfirmed !== true) throw new Error("Explicit user confirmation is required");
    const config = validateConfig(args.config);
    const prompt = resolvedPrompt(config);
    const creativeRecipe = resolvedCreativeRecipe(config);
    const now = new Date().toISOString();
    const id = crypto.randomUUID();
    const record = {
      schemaVersion: 3,
      confirmationId: id,
      confirmedAt: now,
      confirmedBy: "photo-refiner-flow-studio",
      config,
      executionMode: creativeRecipe ? "creative-translation" : "photo-refinement",
      resolvedCreativeRecipe: creativeRecipe,
      creativeOutput: creativeRecipe ? {
        mode: creativeRecipe.creativeAssemblyMode,
        labelZh: creativeRecipe.creativeAssemblyLabelZh,
        originalAssembly: creativeRecipe.creativeAssemblyMode === "original-assembly",
      } : null,
      resolvedPrompt: {
        preset: config.preset,
        label: prompt.label,
        summary: prompt.summary,
        prompt: prompt.prompt,
        avoid: prompt.avoid,
        defaultStrength: typeof prompt.defaultStrength === "number" ? prompt.defaultStrength : config.styleStrength,
        presetVersion: PRESETS.version,
      },
    };
    const preferences = loadPreferences();
    const entry = {id: crypto.randomUUID(), kind: config.preset === "custom" ? "custom" : "preset", label: prompt.label, preset: config.preset, prompt: prompt.prompt, avoid: prompt.avoid, savedAt: now};
    preferences.lastConfig = config;
    if (entry.kind === "custom") preferences.customPrompts = [entry, ...(Array.isArray(preferences.customPrompts) ? preferences.customPrompts : [])]
      .filter((item, index, all) => index === all.findIndex((candidate) => candidate.prompt === item.prompt && candidate.avoid === item.avoid))
      .slice(0, 30);
    savePreferences(preferences);
    record.promptHash = sha256(JSON.stringify(record.resolvedPrompt));
    fs.mkdirSync(CONFIRMATION_DIR, {recursive: true, mode: 0o700});
    const confirmationPath = path.join(CONFIRMATION_DIR, `${id}.json`);
    fs.writeFileSync(confirmationPath, `${JSON.stringify(record, null, 2)}\n`, {encoding: "utf8", mode: 0o600, flag: "wx"});
    return toolResult({
      ok: true,
      kind: "photo-refiner-confirmation",
      confirmationId: id,
      confirmationPath,
      confirmedAt: now,
      preset: config.preset,
      promptHash: record.promptHash,
      summary: {
        workflow: config.workflow,
        executionMode: creativeRecipe ? "creative-translation" : "photo-refinement",
        creativeRecipe: creativeRecipe ? creativeRecipe.id : "none",
        creativeRecipeTitle: creativeRecipe ? creativeRecipe.titleZh : null,
        creativeAssemblyMode: creativeRecipe ? creativeRecipe.creativeAssemblyMode : null,
        creativeAssemblyLabelZh: creativeRecipe ? creativeRecipe.creativeAssemblyLabelZh : null,
        creativeFromBase: config.creativeFromBase,
        aspectRatio: config.aspectRatio,
        resolution: config.resolution,
        deliveryMode: config.deliveryMode,
        detailMode: config.detail.mode,
        portraitEnabled: config.portrait.enabled,
        bodyEnabled: config.body.enabled,
        wrinkleReduction: config.clothing.wrinkleReduction,
      },
    });
  }
  if (name === "delete_photo_refiner_flow_prompt") {
    const collection = enumValue(args.collection, ["custom"], "collection");
    const entryId = cleanText(args.entryId, 120, "entryId");
    const preferences = loadPreferences();
    const before = Array.isArray(preferences.customPrompts) ? preferences.customPrompts : [];
    preferences.customPrompts = before.filter((item) => item.id !== entryId);
    savePreferences(preferences);
    return toolResult({ok: true, kind: "photo-refiner-prompt-library", promptLibrary: promptLibrary(preferences)});
  }
  throw new Error(`Unknown tool: ${name}`);
}

function rpcResponse(id, result) {
  return {jsonrpc: "2.0", id, result};
}

function rpcError(id, code, message) {
  return {jsonrpc: "2.0", id, error: {code, message}};
}

async function handleRpc(message) {
  if (!isObject(message)) return rpcError(null, -32600, "Invalid Request");
  const id = message.id;
  const params = isObject(message.params) ? message.params : {};
  if (typeof message.method !== "string") return id == null ? null : rpcError(id, -32600, "Invalid Request");
  if (message.method.startsWith("notifications/") || message.method === "$/cancelRequest") return null;
  try {
    if (message.method === "initialize") {
      return rpcResponse(id, {
        protocolVersion: params.protocolVersion || "2024-11-05",
        capabilities: {
          tools: {listChanged: false},
          resources: {subscribe: false, listChanged: false},
          // Advertise the MCP Apps UI extension explicitly. Codex hosts use
          // this capability during initialization to decide whether a tool's
          // ui/resourceUri should be mounted as an in-chat Widget.
          extensions: {"io.modelcontextprotocol/ui": {}},
        },
        serverInfo: {name: "photo-refiner-flow-studio", title: "Photo Refiner Flow", version: MANIFEST.version},
        instructions: "For $photo-refiner-flow or Photo Refiner Flow requests with at least one attached or existing source photo, invoke the native top-level open_photo_refiner_flow tool by default. Use open_photo_refiner_flow_settings only if the user explicitly asks for the compact settings panel or the Flow canvas is unavailable. Either UI-opening tool call must be the final visible action of the turn; do not append text after it or wrap it through functions.exec. If no source photo is supplied, ask for one. PHOTO_REFINER_FLOW_GRAPH_SUBMITTED with graphPath is explicit graph confirmation; PHOTO_REFINER_FLOW_SETTINGS_SUBMITTED with confirmationPath is explicit fallback-settings confirmation. After either handoff, do not reopen a UI or ask the user to confirm the same configuration again.",
      });
    }
    if (message.method === "ping") return rpcResponse(id, {});
    if (message.method === "tools/list") return rpcResponse(id, {tools: toolDefinitions()});
    if (message.method === "tools/call") {
      const name = params.name;
      const args = isObject(params.arguments) ? params.arguments : {};
      try {
        return rpcResponse(id, callTool(name, args));
      } catch (error) {
        return rpcResponse(id, toolError(error && error.message ? error.message : String(error)));
      }
    }
    if (message.method === "resources/list") {
      return rpcResponse(id, {resources: [
        {uri: WIDGET_URI, name: "Photo Refiner Flow settings", mimeType: WIDGET_MIME, _meta: widgetResourceMeta()},
        {uri: NODE_CANVAS_URI, name: "Photo Refiner Flow", mimeType: WIDGET_MIME, _meta: nodeCanvasResourceMeta()},
      ]});
    }
    if (message.method === "resources/read") {
      if (params.uri === WIDGET_URI) {
        return rpcResponse(id, {contents: [{uri: WIDGET_URI, mimeType: WIDGET_MIME, text: widgetHtmlWithInitialPayload(FALLBACK_WIDGET_PAYLOAD), _meta: widgetResourceMeta()}]});
      }
      if (params.uri === NODE_CANVAS_URI) {
        return rpcResponse(id, {contents: [{uri: NODE_CANVAS_URI, mimeType: WIDGET_MIME, text: nodeCanvasHtmlWithInitialPayload(FALLBACK_NODE_CANVAS_PAYLOAD), _meta: nodeCanvasResourceMeta()}]});
      }
      return rpcError(id, -32602, `Unknown resource: ${params.uri}`);
    }
    if (message.method === "resources/templates/list") return rpcResponse(id, {resourceTemplates: []});
    if (message.method === "prompts/list") return rpcResponse(id, {prompts: []});
    return rpcError(id, -32601, `Method not found: ${message.method}`);
  } catch (error) {
    return rpcError(id, -32000, error && error.message ? error.message : String(error));
  }
}

function writeRpc(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

const input = readline.createInterface({input: process.stdin});
input.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  try {
    const request = JSON.parse(trimmed);
    const response = await handleRpc(request);
    if (response) writeRpc(response);
  } catch (error) {
    writeRpc(rpcError(null, -32700, error && error.message ? error.message : String(error)));
  }
});
