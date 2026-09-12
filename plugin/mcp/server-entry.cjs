"use strict";

const fs = require("node:fs");
const path = require("node:path");

// Keep the large settings.html source stable while synchronizing the v2.2 adaptive
// budget wording at runtime. This avoids rewriting/minifying the whole widget for a
// three-string policy change and guarantees cached clients receive the new copy once
// the plugin version changes.
const originalReadFileSync = fs.readFileSync.bind(fs);
const settingsSuffix = path.join("assets", "settings.html");
const replacements = [
  ["平衡模式 · 最多 3 次局部生成", "平衡模式 · 通常 1–3 次 · 复杂场景 ≤6"],
  ["“最多 3 次”是上限，不是配额；低价值区域会直接跳过。", "3 次是软预算；只有高价值且通过 Pixel Budget 的复杂区域才会自动扩展，平衡模式硬上限 6 次。"],
  ["智能细节 · 按需 ≤3 次", "智能细节 · 通常 ≤3 / 复杂 ≤6"],
];

fs.readFileSync = function patchedReadFileSync(file, ...args) {
  const value = originalReadFileSync(file, ...args);
  if (!String(file).endsWith(settingsSuffix)) return value;
  const asBuffer = Buffer.isBuffer(value);
  let text = asBuffer ? value.toString("utf8") : String(value);
  for (const [from, to] of replacements) text = text.split(from).join(to);
  return asBuffer ? Buffer.from(text, "utf8") : text;
};

require("./server.cjs");
