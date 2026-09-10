"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const MANIFEST = JSON.parse(fs.readFileSync(path.join(ROOT, ".codex-plugin", "plugin.json"), "utf8"));
const PRESETS = JSON.parse(fs.readFileSync(path.join(ROOT, "config", "presets.json"), "utf8"));
const WIDGET_HTML = fs.readFileSync(path.join(ROOT, "assets", "settings.html"), "utf8");
const WIDGET_URI = `ui://widget/photo-refiner-settings-${encodeURIComponent(MANIFEST.version)}.html`;
const WIDGET_MIME = "text/html;profile=mcp-app";
const CONFIRMATION_DIR = path.join(os.homedir(), ".codex", "photo-refiner", "confirmed");
const PREFERENCES_PATH = path.join(os.homedir(), ".codex", "photo-refiner", "preferences.json");

const DEFAULTS = {
  uiMode: "simple",
  workflow: "auto",
  preset: "eastern-twilight",
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
  // 80 is the visible, strong-but-controlled cinematic default. 100 remains
  // an opt-in extreme where identity, texture, and scene drift become likelier.
  styleStrength: 80,
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
  config.uiMode = enumValue(config.uiMode, ["simple", "pro"], "uiMode");
  config.workflow = enumValue(config.workflow, ["auto", "single", "batch"], "workflow");
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
  config.resolution = enumValue(config.resolution, ["preview", "4k", "source-width"], "resolution");
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

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function uiMeta() {
  return {
    ui: {resourceUri: WIDGET_URI},
    "ui/resourceUri": WIDGET_URI,
    "openai/outputTemplate": WIDGET_URI,
    "openai/widgetAccessible": true,
  };
}

function toolDefinitions() {
  return [
    {
      name: "open_photo_refiner_settings",
      title: "Open Photo Refiner settings",
      description: "MANDATORY only after at least one source photograph is attached or an existing local image path is known: open the interactive settings panel before replying with settings or starting image generation, unless this conversation already contains a submitted confirmationPath. Do not open this panel when no source photograph is known. Do not print a text settings menu when this tool is available.",
      inputSchema: {
        type: "object",
        required: ["sourceCount"],
        properties: {
          sourceCount: {type: "integer", minimum: 1, description: "Positive number of attached or existing source photos"},
          suggestedPreset: {type: "string", description: "Optional preset id inferred from the request"},
          recommendation: {type: "string", description: "Optional concise subject-aware recommendation shown above the settings"},
          creativeDirections: {type: "array", maxItems: 3, description: "Optional editable creative directions inferred from the photo", items: {type: "object", additionalProperties: false, properties: {label: {type: "string"}, summary: {type: "string"}, prompt: {type: "string"}, avoid: {type: "string"}}}},
        },
        additionalProperties: false,
      },
      annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: uiMeta(),
    },
    {
      name: "submit_photo_refiner_settings",
      title: "Confirm Photo Refiner settings",
      description: "Validate and freeze settings submitted by the interactive Photo Refiner panel. Do not call this on the user's behalf; it represents an explicit panel submission.",
      inputSchema: {
        type: "object",
        required: ["userConfirmed", "config"],
        properties: {
          userConfirmed: {type: "boolean", const: true},
          config: {type: "object", additionalProperties: true},
        },
        additionalProperties: false,
      },
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false},
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
    {
      name: "delete_photo_refiner_prompt",
      title: "Delete saved Photo Refiner prompt",
      description: "Delete one user-authored prompt after an explicit action in the settings panel. Built-in presets are not deletable.",
      inputSchema: {
        type: "object",
        required: ["collection", "entryId"],
        properties: {
          collection: {type: "string", enum: ["custom"]},
          entryId: {type: "string", minLength: 1},
        },
        additionalProperties: false,
      },
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
  ];
}

function toolResult(payload, withWidget = false) {
  const result = {
    content: [{type: "text", text: JSON.stringify(payload)}],
    structuredContent: payload,
    isError: false,
  };
  if (withWidget) result._meta = uiMeta();
  return result;
}

function toolError(message) {
  const payload = {ok: false, error: message};
  return {content: [{type: "text", text: JSON.stringify(payload)}], structuredContent: payload, isError: true};
}

function callTool(name, args) {
  if (name === "open_photo_refiner_settings") {
    if (!Number.isInteger(args.sourceCount) || args.sourceCount < 1) {
      throw new Error("At least one source photograph is required before opening Photo Refiner settings");
    }
    const preferences = loadPreferences();
    const defaults = mergeDefaults(preferences.lastConfig || {});
    defaults.workflow = args.sourceCount > 1 ? "batch" : "single";
    if (typeof args.suggestedPreset === "string" && PRESETS.presets[args.suggestedPreset]) defaults.preset = args.suggestedPreset;
    const creativeDirections = Array.isArray(args.creativeDirections) ? args.creativeDirections.slice(0, 3).map((item) => ({
      label: cleanText(String(item?.label || "灵感方向"), 80, "creativeDirections.label"),
      summary: cleanText(String(item?.summary || ""), 240, "creativeDirections.summary"),
      prompt: cleanText(String(item?.prompt || ""), 1800, "creativeDirections.prompt"),
      avoid: cleanText(String(item?.avoid || ""), 600, "creativeDirections.avoid"),
    })).filter((item) => item.prompt) : [];
    return toolResult({ok: true, kind: "photo-refiner-settings", schemaVersion: 1, presets: PRESETS, defaults, promptLibrary: promptLibrary(preferences), recommendation: typeof args.recommendation === "string" ? args.recommendation.trim().slice(0, 500) : "", creativeDirections}, true);
  }
  if (name === "submit_photo_refiner_settings") {
    if (args.userConfirmed !== true) throw new Error("Explicit user confirmation is required");
    const config = validateConfig(args.config);
    const prompt = resolvedPrompt(config);
    const now = new Date().toISOString();
    const id = crypto.randomUUID();
    const record = {
      schemaVersion: 1,
      confirmationId: id,
      confirmedAt: now,
      confirmedBy: "photo-refiner-studio",
      config,
      resolvedPrompt: {
        preset: config.preset,
        label: prompt.label,
        summary: prompt.summary,
        prompt: prompt.prompt,
        avoid: prompt.avoid,
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
  if (name === "delete_photo_refiner_prompt") {
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
        capabilities: {tools: {listChanged: false}, resources: {subscribe: false, listChanged: false}},
        serverInfo: {name: "photo-refiner-studio", title: "Photo Refiner Studio", version: MANIFEST.version},
        instructions: "For every Photo Refiner or $photo-refiner request with at least one attached or existing source photo, call open_photo_refiner_settings before replying with settings or starting image generation. If no source photo is supplied, ask for one and do not open the panel. Never replace the panel with a text menu while this tool is available. Continue only from a user-submitted confirmationPath.",
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
      return rpcResponse(id, {resources: [{uri: WIDGET_URI, name: "Photo Refiner settings", mimeType: WIDGET_MIME}]});
    }
    if (message.method === "resources/read") {
      if (params.uri !== WIDGET_URI) return rpcError(id, -32602, `Unknown resource: ${params.uri}`);
      return rpcResponse(id, {contents: [{uri: WIDGET_URI, mimeType: WIDGET_MIME, text: WIDGET_HTML, _meta: {"openai/widgetPrefersBorder": true}}]});
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
