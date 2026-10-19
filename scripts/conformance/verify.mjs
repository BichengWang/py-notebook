#!/usr/bin/env node
// Usage: node verify.mjs [repository-root]
// Checks every ai-workflows/*/conformance/manifest.json under the repository root (default: the
// repository containing this script). Exits 1 when any schema or digest check disagrees with a
// manifest, 2 on usage or unexpected errors.

import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkRepository } from "./checks/conformance.mjs";

const args = process.argv.slice(2);
if (args.length > 1 || args[0] === "--help" || args[0] === "-h") {
  console.error("usage: node verify.mjs [repository-root]");
  process.exit(args.length > 1 ? 2 : 0);
}
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(args[0] ?? path.join(here, "..", ".."));

try {
  const result = await checkRepository(root, (line) => console.log(line));
  const summary = `${result.manifests} manifests, ${result.vectors} vectors, ${result.checks} checks, ${result.failures.length} failures`;
  if (result.failures.length > 0) {
    console.error(`\nconformance FAILED: ${summary}`);
    for (const failure of result.failures) console.error(`  - ${failure}`);
    process.exit(1);
  }
  console.log(result.manifests === 0 ? `conformance: 0 manifests found under ai-workflows/*/conformance/, nothing to check` : `\nconformance OK: ${summary}`);
} catch (error) {
  console.error(`conformance: unexpected error: ${error.stack ?? error}`);
  process.exit(2);
}
