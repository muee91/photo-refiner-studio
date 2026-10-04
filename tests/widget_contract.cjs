"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "assets", "settings.html"), "utf8");
const style = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1] || "";
const script = (html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/) || [])[1] || "";

assert.match(html, /<title>[^<\s][^<]*<\/title>/, "Studio needs a non-empty document title");
assert.ok(style.length > 1000, "Studio must ship its design system inline");
assert.ok(script.length > 1000, "Studio controller script is missing");
assert.doesNotMatch(html, /V0\.\d/, "Studio must not hard-code an obsolete panel version");
assert.match(script, /payload\.widgetVersion/, "Studio version must come from the MCP payload");

assert.match(html, /id="lightbox"[^>]*role="dialog"/, "recipe preview needs dialog semantics");
assert.match(html, /id="lightbox"[^>]*aria-modal="true"/, "recipe preview must be modal");
assert.match(html, /id="status"[^>]*role="status"/, "Studio status line must be a live region");
assert.match(html, /aria-pressed=/, "toggle selection must be exposed to assistive technology");
assert.match(script, /setAttribute\(['"]aria-pressed['"]/, "Studio must update aria-pressed dynamically");
assert.match(script, /setAttribute\(['"]aria-expanded['"]/, "Studio must expose disclosure state");
assert.match(script, /event\.source===window\.parent/, "inbound postMessage must validate its source");

assert.doesNotMatch(html, /2048²/, "tile size must not be presented as a fixed ChatGPT client limit");
assert.doesNotMatch(html, /想要更大就给它更大/, "delivery controls must not imply requested size equals returned native size");
assert.match(html, /自动高清底座/, "Studio must describe the automatic honest-HD router");
assert.match(html, /客户端实测可用 Patch 尺寸|实际生成尺寸/, "Studio must describe empirical returned patch dimensions");
assert.match(script, /creativeHdChain/, "HD creative chain state is missing");
assert.match(script, /preview-first/, "HD creative chain must retain preview-first semantics");

const rootBlock = (style.match(/:root\s*\{([^}]*)\}/) || [])[1] || "";
const declared = new Set([...rootBlock.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]));
const used = new Set([...style.matchAll(/var\((--[\w-]+)/g)].map((match) => match[1]));
const missing = [...used].filter((token) => !declared.has(token));
assert.deepEqual(missing, [], `undefined CSS custom properties: ${missing.join(", ")}`);

assert.match(html, /<input type="file" id="lightboxFile" class="sr-only"/, "preview replacement file input must remain keyboard-focusable");
assert.doesNotMatch(html, /id="lightboxFile"[^>]*\shidden/, "preview replacement input must not be hidden from keyboard users");

console.log("widget contract OK");
