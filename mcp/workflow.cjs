"use strict";

const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const ROOT = path.resolve(__dirname, "..");
const MANIFEST = JSON.parse(fs.readFileSync(path.join(ROOT, "plugin.json"), "utf8"));
const VERSION = String(MANIFEST.version).replace(/[^A-Za-z0-9._-]+/g, "-");
const REVIEW_URI = `ui://widget/photo-refiner-review/${VERSION}.html`;
const JOBS_URI = `ui://widget/photo-refiner-jobs/${VERSION}.html`;
const MIME = "text/html;profile=mcp-app";
const REVIEW_TOKEN = "__PHOTO_REFINER_REVIEW_PAYLOAD__";
const JOBS_TOKEN = "__PHOTO_REFINER_JOBS_PAYLOAD__";
const REVIEW_TEMPLATE = fs.readFileSync(path.join(ROOT, "assets", "review.html"), "utf8");
const JOBS_TEMPLATE = fs.readFileSync(path.join(ROOT, "assets", "recent-jobs.html"), "utf8");
const USER_HOME = process.env.HOME || os.homedir();
const STATE_ROOT = path.join(USER_HOME, ".codex", "photo-refiner");
const JOBS_PATH = path.join(STATE_ROOT, "jobs.json");
const PYTHON = process.env.PYTHON || "python3";
const SCRIPTS = path.join(ROOT, "skills", "photo-refiner", "scripts");

function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function nowIso() { return new Date().toISOString(); }
function cleanText(value, max, name) {
  if (typeof value !== "string") throw new Error(`${name} must be text`);
  const cleaned = value.trim();
  if (!cleaned || cleaned.length > max) throw new Error(`${name} must be 1-${max} characters`);
  return cleaned;
}
function enumValue(value, allowed, name) {
  if (!allowed.includes(value)) throw new Error(`${name} must be one of: ${allowed.join(", ")}`);
  return value;
}
function readJson(file, fallback = null) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch (_) { return fallback; }
}
function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
  const temp = `${file}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, {encoding: "utf8", mode: 0o600});
  fs.renameSync(temp, file);
}
function normalizeJobPath(raw) {
  const jobPath = path.resolve(cleanText(raw, 4096, "jobPath"));
  if (path.basename(jobPath) !== "job.json" || !fs.existsSync(jobPath) || !fs.statSync(jobPath).isFile()) {
    throw new Error(`Missing job manifest: ${jobPath}`);
  }
  return jobPath;
}
function readJob(jobPath) {
  const job = readJson(jobPath);
  if (!isObject(job)) throw new Error(`Invalid job manifest: ${jobPath}`);
  return job;
}
function runPython(script, args) {
  const scriptPath = path.join(SCRIPTS, script);
  const result = childProcess.spawnSync(PYTHON, [scriptPath, ...args.map(String)], {
    cwd: ROOT,
    env: {...process.env},
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || `${script} failed`).trim();
    throw new Error(detail.slice(-4000));
  }
  const text = String(result.stdout || "").trim();
  if (!text) return {};
  try { return JSON.parse(text); } catch (_) { throw new Error(`${script} returned invalid JSON`); }
}
function controller(jobPath, event = "inspect") {
  return runPython("workflow_controller.py", [jobPath, "--event", event]);
}

function registry() {
  const value = readJson(JOBS_PATH, {version: 1, jobs: []});
  return isObject(value) && Array.isArray(value.jobs) ? value : {version: 1, jobs: []};
}
function canonicalParentJob(jobPath, job) {
  const parent = job.batch_frame?.parent_job;
  if (typeof parent === "string" && parent.trim()) {
    const candidate = path.resolve(parent);
    if (fs.existsSync(candidate) && path.basename(candidate) === "job.json") return candidate;
  }
  return jobPath;
}
function registerJob(rawPath, {opened = false} = {}) {
  let jobPath = normalizeJobPath(rawPath);
  let job = readJob(jobPath);
  jobPath = canonicalParentJob(jobPath, job);
  job = readJob(jobPath);
  const data = registry();
  const stamp = nowIso();
  const existing = data.jobs.find((item) => item.jobPath === jobPath) || {};
  const entry = {
    jobPath,
    registeredAt: existing.registeredAt || stamp,
    lastSeenAt: stamp,
    lastOpenedAt: opened ? stamp : existing.lastOpenedAt || null,
  };
  data.jobs = [entry, ...data.jobs.filter((item) => item.jobPath !== jobPath)].slice(0, 50);
  writeJsonAtomic(JOBS_PATH, data);
  return {jobPath, job};
}
function jobSummary(jobPath, job) {
  const sources = Array.isArray(job.sources) ? job.sources : [];
  const isBatch = job.workflow === "batch";
  const batch = isObject(job.batch) ? job.batch : {};
  const title = isBatch
    ? `批量任务 · ${batch.frame_count || sources.length} 张`
    : (sources[0] ? path.basename(sources[0]) : path.basename(path.dirname(jobPath)));
  const updatedAt = job.updated_at || job.created_at || "";
  const finalPath = job.delivery_gate?.final?.path || null;
  return {
    jobPath,
    title,
    status: String(job.status || "unknown"),
    workflow: String(job.workflow || "single"),
    active: !["completed", "failed"].includes(job.status),
    updatedAt,
    frameCount: isBatch ? (batch.frame_count || sources.length) : 1,
    completedFrames: isBatch ? (batch.completed_frames || 0) : undefined,
    failedFrames: isBatch ? (batch.failed_frames || 0) : undefined,
    preset: job.resolved_prompt?.label || job.preset || "",
    resolution: job.resolution || "",
    finalPath,
  };
}
function recentJobs(limit = 12) {
  const data = registry();
  const valid = [];
  const seen = new Set();
  for (const entry of data.jobs) {
    if (!entry || typeof entry.jobPath !== "string" || seen.has(entry.jobPath)) continue;
    seen.add(entry.jobPath);
    try {
      const jobPath = normalizeJobPath(entry.jobPath);
      const job = readJob(jobPath);
      valid.push({...entry, summary: jobSummary(jobPath, job)});
    } catch (_) {}
  }
  data.jobs = valid.map(({summary, ...entry}) => entry).slice(0, 50);
  writeJsonAtomic(JOBS_PATH, data);
  valid.sort((a, b) => Number(b.summary.active) - Number(a.summary.active) || String(b.summary.updatedAt).localeCompare(String(a.summary.updatedAt)));
  return valid.slice(0, Math.max(1, Math.min(20, limit))).map((item) => item.summary);
}

function render(template, token, payload) {
  const serialized = JSON.stringify(payload).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
  const html = template.replace(token, () => serialized);
  if (html === template) throw new Error("Widget payload token missing");
  return html;
}
function widgetMeta(uri, description) {
  return {
    ui: {resourceUri: uri, visibility: ["model", "app"]},
    "ui/resourceUri": uri,
    "openai/outputTemplate": uri,
    "openai/widgetAccessible": true,
    "openai/widgetDescription": description,
  };
}
function resourceMeta(description) {
  return {ui: {prefersBorder: true}, "openai/widgetDescription": description, "openai/widgetPrefersBorder": true};
}
function toolResult(payload, widget = null) {
  const result = {content: [{type: "text", text: JSON.stringify(payload)}], structuredContent: payload, isError: false};
  if (widget) {
    result._meta = widgetMeta(widget.uri, widget.description);
    const html = render(widget.template, widget.token, payload);
    result.content.push({type: "resource", resource: {uri: widget.uri, mimeType: MIME, text: html, _meta: resourceMeta(widget.description)}});
    result.content.push({type: "resource_link", uri: widget.uri, name: widget.name, title: widget.name, mimeType: MIME, _meta: resourceMeta(widget.description)});
  }
  return result;
}
function toolError(message) {
  const payload = {ok: false, error: message};
  return {content: [{type: "text", text: JSON.stringify(payload)}], structuredContent: payload, isError: true};
}

const REVIEW_WIDGET = {uri: REVIEW_URI, template: REVIEW_TEMPLATE, token: REVIEW_TOKEN, name: "Photo Refiner review", description: "Approve, redo, or adjust the exact Photo Refiner checkpoint without typing workflow commands."};
const JOBS_WIDGET = {uri: JOBS_URI, template: JOBS_TEMPLATE, token: JOBS_TOKEN, name: "Photo Refiner recent jobs", description: "Resume recent Photo Refiner jobs from durable job state."};

function toolDefinitions() {
  return [
    {
      name: "register_photo_refiner_job",
      title: "Register Photo Refiner job",
      description: "Register a newly created Photo Refiner job.json in the durable recent-jobs index. Call immediately after init_job.py creates a job. Child batch-frame jobs are automatically collapsed to their parent batch job.",
      inputSchema: {type: "object", required: ["jobPath"], properties: {jobPath: {type: "string"}}, additionalProperties: false},
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false},
    },
    {
      name: "open_photo_refiner_review",
      title: "Open Photo Refiner review",
      description: "Open the button-based review card for an exact generated checkpoint. Use instead of asking the user to type continue/redo/adjust. artifactPath must be the exact image currently shown to the user.",
      inputSchema: {type: "object", required: ["jobPath", "checkpoint", "artifactPath"], properties: {jobPath: {type: "string"}, checkpoint: {type: "string", enum: ["base", "creative", "batch-master"]}, artifactPath: {type: "string"}}, additionalProperties: false},
      annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: widgetMeta(REVIEW_URI, REVIEW_WIDGET.description),
    },
    {
      name: "submit_photo_refiner_review",
      title: "Submit Photo Refiner review",
      description: "Handle an explicit review-button action. Approve binds the exact displayed image via update_job.py; redo/adjust are converted to deterministic Workflow Controller events.",
      inputSchema: {type: "object", required: ["jobPath", "checkpoint", "artifactPath", "event"], properties: {jobPath: {type: "string"}, checkpoint: {type: "string", enum: ["base", "creative", "batch-master"]}, artifactPath: {type: "string"}, event: {type: "string", enum: ["approve", "redo", "adjust"]}}, additionalProperties: false},
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false},
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["app"]}},
    },
    {
      name: "open_photo_refiner_recent_jobs",
      title: "Open recent Photo Refiner jobs",
      description: "Open recent Photo Refiner jobs when the user asks to continue, resume, reopen, or see recent work. Resume from job.json rather than conversation memory.",
      inputSchema: {type: "object", properties: {limit: {type: "integer", minimum: 1, maximum: 20}}, additionalProperties: false},
      annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: widgetMeta(JOBS_URI, JOBS_WIDGET.description),
    },
    {
      name: "resume_photo_refiner_job",
      title: "Resume Photo Refiner job",
      description: "Inspect one registered job and return the Workflow Controller's exact next action. Does not regenerate completed stages.",
      inputSchema: {type: "object", required: ["jobPath"], properties: {jobPath: {type: "string"}}, additionalProperties: false},
      annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false},
      _meta: {"openai/widgetAccessible": true, ui: {visibility: ["model", "app"]}},
    },
  ];
}

function validateArtifact(jobPath, rawArtifact) {
  const artifact = path.resolve(cleanText(rawArtifact, 4096, "artifactPath"));
  const jobDir = path.dirname(jobPath);
  if (!fs.existsSync(artifact) || !fs.statSync(artifact).isFile()) throw new Error(`Missing review artifact: ${artifact}`);
  const relative = path.relative(jobDir, artifact);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Review artifact must be inside the job directory");
  return artifact;
}
function checkpointExpected(job, checkpoint) {
  if (checkpoint === "base") return job.status === "base_generated" && job.base_preview?.required && !job.base_preview?.approved;
  if (checkpoint === "creative") return job.status === "creative_generated" && job.creative_preview?.required && !job.creative_preview?.approved;
  if (checkpoint === "batch-master") return job.workflow === "batch" && job.status === "base_generated" && !job.batch?.master_frame_approved;
  return false;
}

function callTool(name, args) {
  if (name === "register_photo_refiner_job") {
    const {jobPath, job} = registerJob(args.jobPath);
    return toolResult({ok: true, kind: "photo-refiner-job-registered", jobPath, summary: jobSummary(jobPath, job)});
  }
  if (name === "open_photo_refiner_review") {
    const jobPath = normalizeJobPath(args.jobPath);
    const job = readJob(jobPath);
    const checkpoint = enumValue(args.checkpoint, ["base", "creative", "batch-master"], "checkpoint");
    const artifactPath = validateArtifact(jobPath, args.artifactPath);
    if (!checkpointExpected(job, checkpoint)) throw new Error(`Job is not waiting at the ${checkpoint} review checkpoint`);
    registerJob(jobPath);
    return toolResult({ok: true, kind: "photo-refiner-review", widgetVersion: MANIFEST.version, jobPath, checkpoint, artifactPath, decision: controller(jobPath, "inspect")}, REVIEW_WIDGET);
  }
  if (name === "submit_photo_refiner_review") {
    const jobPath = normalizeJobPath(args.jobPath);
    const checkpoint = enumValue(args.checkpoint, ["base", "creative", "batch-master"], "checkpoint");
    const event = enumValue(args.event, ["approve", "redo", "adjust"], "event");
    const artifactPath = validateArtifact(jobPath, args.artifactPath);
    const job = readJob(jobPath);
    if (!checkpointExpected(job, checkpoint)) throw new Error(`Job is no longer waiting at the ${checkpoint} review checkpoint`);
    let decision;
    if (event === "approve") {
      if (checkpoint === "base") runPython("update_job.py", [jobPath, "--approve-base-preview", "--artifact", `base_preview=${artifactPath}`]);
      else if (checkpoint === "creative") runPython("update_job.py", [jobPath, "--approve-creative-preview", "--artifact", `creative_preview=${artifactPath}`]);
      else runPython("update_job.py", [jobPath, "--approve-master", "--master-frame", artifactPath]);
      decision = controller(jobPath, "inspect");
    } else {
      decision = controller(jobPath, event);
    }
    registerJob(jobPath, {opened: true});
    return toolResult({ok: true, kind: "photo-refiner-review-result", jobPath, checkpoint, event, decision});
  }
  if (name === "open_photo_refiner_recent_jobs") {
    const limit = Number.isInteger(args.limit) ? args.limit : 12;
    return toolResult({ok: true, kind: "photo-refiner-recent-jobs", widgetVersion: MANIFEST.version, jobs: recentJobs(limit)}, JOBS_WIDGET);
  }
  if (name === "resume_photo_refiner_job") {
    const {jobPath, job} = registerJob(args.jobPath, {opened: true});
    return toolResult({ok: true, kind: "photo-refiner-resume", jobPath, summary: jobSummary(jobPath, job), decision: controller(jobPath, "inspect")});
  }
  throw new Error(`Unknown tool: ${name}`);
}

function rpcResponse(id, result) { return {jsonrpc: "2.0", id, result}; }
function rpcError(id, code, message) { return {jsonrpc: "2.0", id, error: {code, message}}; }
async function handleRpc(message) {
  if (!isObject(message)) return rpcError(null, -32600, "Invalid Request");
  const id = message.id;
  const params = isObject(message.params) ? message.params : {};
  if (typeof message.method !== "string") return id == null ? null : rpcError(id, -32600, "Invalid Request");
  if (message.method.startsWith("notifications/") || message.method === "$/cancelRequest") return null;
  try {
    if (message.method === "initialize") return rpcResponse(id, {protocolVersion: params.protocolVersion || "2024-11-05", capabilities: {tools: {listChanged: false}, resources: {subscribe: false, listChanged: false}, extensions: {"io.modelcontextprotocol/ui": {}}}, serverInfo: {name: "photo-refiner-workflow", title: "Photo Refiner Workflow", version: MANIFEST.version}, instructions: "Use this server for durable Photo Refiner review buttons, recent-job resume, and workflow state. Register every newly initialized parent job. Use review widgets instead of asking users to type workflow commands."});
    if (message.method === "ping") return rpcResponse(id, {});
    if (message.method === "tools/list") return rpcResponse(id, {tools: toolDefinitions()});
    if (message.method === "tools/call") {
      try { return rpcResponse(id, callTool(params.name, isObject(params.arguments) ? params.arguments : {})); }
      catch (error) { return rpcResponse(id, toolError(error?.message || String(error))); }
    }
    if (message.method === "resources/list") return rpcResponse(id, {resources: [
      {uri: REVIEW_URI, name: "Photo Refiner review", mimeType: MIME, _meta: resourceMeta(REVIEW_WIDGET.description)},
      {uri: JOBS_URI, name: "Photo Refiner recent jobs", mimeType: MIME, _meta: resourceMeta(JOBS_WIDGET.description)},
    ]});
    if (message.method === "resources/read") {
      if (params.uri === REVIEW_URI) return rpcResponse(id, {contents: [{uri: REVIEW_URI, mimeType: MIME, text: render(REVIEW_TEMPLATE, REVIEW_TOKEN, {ok: true, kind: "photo-refiner-review", jobPath: "", checkpoint: "base", artifactPath: ""}), _meta: resourceMeta(REVIEW_WIDGET.description)}]});
      if (params.uri === JOBS_URI) return rpcResponse(id, {contents: [{uri: JOBS_URI, mimeType: MIME, text: render(JOBS_TEMPLATE, JOBS_TOKEN, {ok: true, kind: "photo-refiner-recent-jobs", jobs: []}), _meta: resourceMeta(JOBS_WIDGET.description)}]});
      return rpcError(id, -32602, `Unknown resource: ${params.uri}`);
    }
    if (message.method === "resources/templates/list") return rpcResponse(id, {resourceTemplates: []});
    if (message.method === "prompts/list") return rpcResponse(id, {prompts: []});
    return rpcError(id, -32601, `Method not found: ${message.method}`);
  } catch (error) { return rpcError(id, -32000, error?.message || String(error)); }
}
function writeRpc(message) { process.stdout.write(`${JSON.stringify(message)}\n`); }
const input = readline.createInterface({input: process.stdin});
input.on("line", async (line) => {
  const trimmed = line.trim(); if (!trimmed) return;
  try { const request = JSON.parse(trimmed); const response = await handleRpc(request); if (response) writeRpc(response); }
  catch (error) { writeRpc(rpcError(null, -32700, error?.message || String(error))); }
});
