// Cross-language conformance check for ai-workflows/<project>/conformance/manifest.json.
//
// For every manifest: validate its shape, validate each declared document against its JSON
// Schema (Ajv, draft 2020-12), and recompute every digest of every valid vector without any
// Python code. Path and digest semantics are documented in scripts/conformance/README.md.

import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020Module from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";
import { canonicalizeRfc8785, serializePythonJsonV1 } from "./canonical.mjs";
import { decodeUtf8, deepEqual, parseJson, rawNumber, resolvePointer, JsonSyntaxError } from "./json.mjs";

const Ajv2020 = Ajv2020Module.default ?? Ajv2020Module;
const addFormats = addFormatsModule.default ?? addFormatsModule;

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const MANIFEST_SCHEMA_PATH = path.resolve(HERE, "..", "manifest.schema.json");
const PROJECTS_DIR = "ai-workflows";
const VECTOR_DIRS = ["valid", "tampered", "invalid"];
const SHA256_HEX = /^[0-9a-f]{64}$/;

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

function newAjv() {
  // Strict mode rejects unknown keywords and formats (typos). The type-hygiene checks are off:
  // conditional branches, tuples and `required` across branches are valid JSON Schema.
  const ajv = new Ajv2020({ strict: true, strictTypes: false, strictTuples: false, strictRequired: false, allErrors: true });
  addFormats(ajv);
  return ajv;
}

function describeErrors(errors, limit = 4) {
  const lines = (errors ?? []).slice(0, limit).map((error) => `${error.instancePath || "/"} ${error.message}`);
  if ((errors ?? []).length > limit) lines.push(`... ${errors.length - limit} more`);
  return lines.join("; ");
}

function describeError(error) {
  return error instanceof Error ? error.message : String(error);
}

function firstDifference(expected, actual) {
  const length = Math.min(expected.length, actual.length);
  let offset = 0;
  while (offset < length && expected[offset] === actual[offset]) offset += 1;
  const show = (bytes) => JSON.stringify(bytes.subarray(offset, offset + 24).toString("utf8"));
  return `first difference at byte ${offset} (file ${expected.length} bytes ${show(expected)}, recomputed ${actual.length} bytes ${show(actual)})`;
}

/** Counts and prints checks; `sink` receives one line at a time. */
export class Recorder {
  constructor(sink = () => {}) {
    this.sink = sink;
    this.checks = 0;
    this.failures = [];
    this.scope = "";
  }

  ok(kind, message) {
    this.checks += 1;
    this.sink(`    ok    ${kind.padEnd(9)} ${message}`);
  }

  fail(kind, message) {
    this.checks += 1;
    this.failures.push(`${this.scope}: ${kind}: ${message}`);
    this.sink(`    FAIL  ${kind.padEnd(9)} ${message}`);
  }
}

class PathError extends Error {}

function contained(base, relative, what) {
  const full = path.resolve(base, relative);
  if (full !== base && !full.startsWith(base + path.sep)) {
    throw new PathError(`${what} ${JSON.stringify(relative)} leaves ${path.basename(base)}/`);
  }
  return full;
}

async function discoverManifests(root) {
  const projects = path.join(root, PROJECTS_DIR);
  let entries;
  try {
    entries = await fs.readdir(projects, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
  const found = [];
  for (const entry of entries.filter((item) => item.isDirectory()).sort((a, b) => (a.name < b.name ? -1 : 1))) {
    const manifest = path.join(projects, entry.name, "conformance", "manifest.json");
    if (await fs.stat(manifest).then((stat) => stat.isFile(), () => false)) found.push(manifest);
  }
  return found;
}

// One Ajv instance per project holding every schema file in the project's package schema
// directories, so a $ref by $id resolves across files.
async function loadProjectSchemas(projectDir) {
  const ajv = newAjv();
  const loaded = new Map(); // absolute file -> { id } | { error }
  const files = [];
  for (const entry of await fs.readdir(projectDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const schemaDir = path.join(projectDir, entry.name, "schema");
    const names = await fs.readdir(schemaDir).catch(() => []);
    for (const name of names.filter((item) => item.endsWith(".json")).sort()) files.push(path.join(schemaDir, name));
  }
  const load = async (file) => {
    if (loaded.has(file)) return;
    try {
      const schema = JSON.parse(decodeUtf8(await fs.readFile(file)));
      if (typeof schema.$id !== "string") throw new Error("schema has no string $id");
      ajv.addSchema(schema);
      loaded.set(file, { id: schema.$id });
    } catch (error) {
      loaded.set(file, { error: describeError(error) });
    }
  };
  for (const file of files) await load(file);
  return { load, validatorFor: (file) => {
    const entry = loaded.get(file);
    if (entry?.error) throw new Error(`schema ${path.basename(file)} cannot be loaded: ${entry.error}`);
    const validate = ajv.getSchema(entry.id);
    if (!validate) throw new Error(`schema ${path.basename(file)} is not registered`);
    return validate;
  } };
}

/** Check one manifest. Returns the recorder so callers can inspect counts and failures. */
export async function checkManifest(manifestFile, { root, recorder, validateManifest }) {
  const conformanceDir = path.dirname(manifestFile);
  const projectDir = path.dirname(conformanceDir);
  const label = path.relative(root, manifestFile).split(path.sep).join("/");
  recorder.scope = label;
  recorder.sink(`${label}`);

  let manifest;
  try {
    manifest = parseJson(decodeUtf8(await fs.readFile(manifestFile)));
  } catch (error) {
    recorder.fail("manifest", `not readable as strict JSON: ${describeError(error)}`);
    return 0;
  }
  if (!validateManifest(manifest)) {
    recorder.fail("manifest", `does not match manifest.schema.json: ${describeErrors(validateManifest.errors)}`);
    return 0;
  }
  recorder.ok("manifest", `format 1, package ${manifest.package}, ${manifest.vectors.length} vectors`);

  const schemas = await loadProjectSchemas(projectDir);
  const referenced = new Set();
  const documentCache = new Map();
  const readBytes = async (file) => {
    if (!documentCache.has(file)) documentCache.set(file, fs.readFile(file));
    return documentCache.get(file);
  };
  const seenPaths = new Set();

  for (const vector of manifest.vectors) {
    recorder.scope = `${label} ${vector.path}`;
    recorder.sink(`  ${vector.path} [${vector.expect}]`);
    if (seenPaths.has(vector.path)) recorder.fail("vector", "listed more than once");
    seenPaths.add(vector.path);
    if (vector.path.split("/")[0] !== vector.expect) {
      recorder.fail("vector", `a ${vector.expect} vector must live under ${vector.expect}/`);
    }
    let vectorFile;
    let isDirectory;
    try {
      vectorFile = contained(conformanceDir, vector.path, "path");
      isDirectory = (await fs.stat(vectorFile)).isDirectory();
    } catch (error) {
      recorder.fail("vector", error instanceof PathError ? error.message : `vector path does not exist: ${vector.path}`);
      continue;
    }
    referenced.add(vectorFile);
    const base = isDirectory ? vectorFile : path.dirname(vectorFile);
    const inside = (relative, what) => {
      if (!isDirectory && relative !== ".") throw new PathError(`${what} ${JSON.stringify(relative)} must be "." for a file vector`);
      return isDirectory ? contained(vectorFile, relative, what) : vectorFile;
    };

    for (const document of vector.documents ?? []) {
      try {
        const file = inside(document.path, "document path");
        const schemaFile = contained(projectDir, document.schema, "schema");
        await schemas.load(schemaFile);
        const validate = schemas.validatorFor(schemaFile);
        let data;
        let parseProblem = null;
        try {
          data = JSON.parse(decodeUtf8(await readBytes(file)));
        } catch (error) {
          parseProblem = `is not parseable JSON: ${describeError(error)}`;
        }
        const valid = parseProblem === null && validate(data);
        const where = `${document.path} against ${document.schema}`;
        if (valid === document.schema_valid) {
          recorder.ok("schema", `${where}: ${valid ? "valid" : `invalid as declared (${parseProblem ?? describeErrors(validate.errors, 2)})`}`);
        } else if (valid) {
          recorder.fail("schema", `${where}: declared schema_valid=false but the document validates`);
        } else {
          recorder.fail("schema", `${where}: declared schema_valid=true but ${parseProblem ?? describeErrors(validate.errors)}`);
        }
      } catch (error) {
        recorder.fail("schema", `${document.path} against ${document.schema}: ${describeError(error)}`);
      }
    }

    for (const digest of vector.digests ?? []) {
      // Digests of tampered and invalid vectors are not recomputed: those vectors are expected to disagree.
      if (vector.expect !== "valid") continue;
      const kind = "digest";
      const name = `${digest.document}#${digest.value} (${digest.canonicalization})`;
      try {
        const documentFile = inside(digest.document, "digest document");
        if (digest.canonicalization === "bytes") {
          const coveredFile = contained(base, digest.covers_file, "covers_file");
          referenced.add(coveredFile);
          const actual = sha256(await readBytes(coveredFile));
          const recorded = readDigest(await readStrict(readBytes, documentFile), digest.value);
          report(recorder, kind, name, recorded, actual, `SHA-256 of ${digest.covers_file}`);
          continue;
        }
        const document = await readStrict(readBytes, documentFile);
        const recorded = readDigest(document, digest.value);
        const value = withoutMembers(resolvePointer(document, digest.covers), digest.exclude ?? []);
        const canonicalFile = contained(conformanceDir, digest.canonical_file, "canonical_file");
        referenced.add(canonicalFile);
        const canonicalBytes = await readBytes(canonicalFile);
        if (digest.canonicalization === "rfc8785") {
          const recomputed = canonicalizeRfc8785(value);
          if (!recomputed.equals(canonicalBytes)) {
            throw new Error(`${digest.canonical_file} is not the RFC 8785 form of ${digest.covers || "the document"}: ${firstDifference(canonicalBytes, recomputed)}`);
          }
          report(recorder, kind, name, recorded, sha256(recomputed), `SHA-256 of RFC 8785 form of ${digest.covers || "document"}; ${digest.canonical_file} matches byte for byte`);
        } else {
          const text = decodeUtf8(canonicalBytes);
          if (!deepEqual(parseJson(text), value)) {
            throw new Error(`${digest.canonical_file} parses to a different value than ${digest.covers || "the document"}`);
          }
          const recomputed = serializePythonJsonV1(parseJson(text, { number: rawNumber }));
          if (!recomputed.equals(canonicalBytes)) {
            throw new Error(`${digest.canonical_file} is not in python-json-v1 form: ${firstDifference(canonicalBytes, recomputed)}`);
          }
          report(recorder, kind, name, recorded, sha256(canonicalBytes), `SHA-256 of ${digest.canonical_file}; it is the python-json-v1 form of ${digest.covers || "document"}`);
        }
      } catch (error) {
        recorder.fail(kind, `${name}: ${describeError(error)}`);
      }
    }
    if (vector.expect === "valid" && (vector.digests ?? []).length === 0) recorder.fail("digest", "a valid vector must carry digests");
  }

  recorder.scope = label;
  for (const dir of VECTOR_DIRS) {
    for (const file of await listFiles(path.join(conformanceDir, dir))) {
      if (![...referenced].some((used) => file === used || file.startsWith(used + path.sep))) {
        recorder.fail("coverage", `${path.relative(conformanceDir, file).split(path.sep).join("/")} is not referenced by any vector`);
      }
    }
  }
  return manifest.vectors.length;
}

async function readStrict(readBytes, file) {
  try {
    return parseJson(decodeUtf8(await readBytes(file)));
  } catch (error) {
    if (error instanceof JsonSyntaxError || error instanceof TypeError) {
      throw new Error(`${path.basename(file)} is not strict JSON: ${error.message}`);
    }
    throw error;
  }
}

function readDigest(document, pointer) {
  const recorded = resolvePointer(document, pointer);
  if (typeof recorded !== "string" || !SHA256_HEX.test(recorded)) {
    throw new Error(`${pointer} is not a 64-character lowercase hex digest`);
  }
  return recorded;
}

function withoutMembers(value, names) {
  if (names.length === 0) return value;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("exclude needs the covered value to be an object");
  }
  for (const name of names) {
    if (!Object.hasOwn(value, name)) throw new Error(`excluded member ${JSON.stringify(name)} is not in the covered object`);
  }
  const copy = {};
  for (const key of Object.keys(value)) {
    if (!names.includes(key)) Object.defineProperty(copy, key, { value: value[key], enumerable: true, writable: true, configurable: true });
  }
  return copy;
}

function report(recorder, kind, name, recorded, recomputed, how) {
  if (recorded === recomputed) {
    recorder.ok(kind, `${name}: ${recorded.slice(0, 12)}... ${how}`);
  } else {
    recorder.fail(kind, `${name}: recorded ${recorded}, recomputed ${recomputed} (${how})`);
  }
}

async function listFiles(dir) {
  const found = [];
  for (const entry of await fs.readdir(dir, { withFileTypes: true }).catch(() => [])) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await listFiles(full)));
    else found.push(full);
  }
  return found.sort();
}

// Check every manifest under <root>/ai-workflows/<project>/conformance/.
export async function checkRepository(root, sink = () => {}) {
  const ajv = newAjv();
  const manifestSchema = JSON.parse(await fs.readFile(MANIFEST_SCHEMA_PATH, "utf8"));
  const validateManifest = ajv.compile(manifestSchema);
  const recorder = new Recorder(sink);
  const manifests = await discoverManifests(root);
  let vectors = 0;
  for (const manifest of manifests) vectors += await checkManifest(manifest, { root, recorder, validateManifest });
  return { manifests: manifests.length, vectors, checks: recorder.checks, failures: recorder.failures };
}
