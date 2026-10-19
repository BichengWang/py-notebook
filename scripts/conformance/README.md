# Conformance cross-check

A Node program, with no Python in the loop, that re-checks every conformance
manifest under `ai-workflows/<project>/conformance/manifest.json`:

1. the manifest matches [`manifest.schema.json`](manifest.schema.json);
2. every `documents` entry validates (or fails, as declared by `schema_valid`)
   against its JSON Schema with Ajv 2020-12 (strict mode, `ajv-formats`);
3. for every `valid` vector, every `digests` entry is recomputed from the vector
   and compared with the recorded digest, using a JavaScript canonicalizer that
   shares no code with the Python packages.

It exists so that a second implementation, in another language, disagrees loudly
if a Python canonicalizer, a schema, or a vector drifts. It checks internal
consistency of committed vectors. It does not run the Python verifiers (each
project's own tests do that), authenticate anything, or show adoption.

```sh
cd scripts/conformance
npm ci                      # pinned: package.json + package-lock.json
node --test                 # self-tests: a wrong digest, a schema violation and a
                            # non-canonical file are each caught
node verify.mjs             # all manifests in this checkout (exit 1 on any discrepancy)
node verify.mjs /path/to/checkout
```

With no manifests, `verify.mjs` prints `0 manifests found` and exits 0. CI runs
this as the `conformance (node)` check of
[`.github/workflows/conformance.yml`](../../.github/workflows/conformance.yml) on
every change to a manifest, vector, package `schema/` directory or this folder.

## Manifest rules

The format is specified in [DECISION_RECORDS](../../docs/DECISION_RECORDS.md#conformance-vectors).
Beyond the JSON Schema, the checker enforces:

- `path` and `canonical_file` are relative to `conformance/`. `documents[].path`,
  `digests[].document` and `covers_file` are relative to the vector path: `.` for
  a file vector, a file inside it for a directory vector. `schema` is relative to
  `ai-workflows/<project>/`. Nothing may leave its base directory.
- A vector lives under the directory named by its `expect` (`valid/`, `tampered/`,
  `invalid/`) and `verify.exit_code` is 0, 1 or 2 accordingly.
- Every file under `valid/`, `tampered/` and `invalid/` is referenced by a vector,
  digest `canonical_file` or `covers_file`, so no vector goes unchecked.
- Every schema file under `ai-workflows/<project>/*/schema/` has a string `$id`
  and loads into one Ajv instance, so `$ref` between files resolves.
- Digests of `tampered` and `invalid` vectors are not recomputed; they are
  expected to disagree with their content.

## Digest recomputation

Documents are read with a strict JSON reader (`checks/json.mjs`): duplicate object
keys are an error, and an integer literal outside +-(2^53-1) is kept exactly as a
BigInt instead of being rounded.

| `canonicalization` | Check |
| --- | --- |
| `rfc8785` | Re-canonicalize the covered value (after removing `exclude` members; each must exist) per RFC 8785 and compare byte for byte with `canonical_file`; SHA-256 of those bytes must equal the recorded digest. Integers outside the I-JSON range, non-finite numbers and lone surrogates fail. |
| `python-json-v1` | SHA-256 of `canonical_file` must equal the recorded digest; `canonical_file` must parse to a value deep-equal to the covered value (after `exclude`); and re-serializing it with sorted keys (by code point), compact separators, unescaped non-ASCII and its own number literals must reproduce it byte for byte. Float formatting is not re-derived. |
| `bytes` | SHA-256 of the exact bytes of `covers_file` must equal the recorded digest. |

Schema validation reads documents with `JSON.parse`, like any JSON Schema
consumer, so a duplicate key is not a schema violation; duplicate keys are caught
by the digest reader and by each package's own verifier.

## Dependencies

`ajv` and `ajv-formats` are the only dependencies, pinned to exact versions in
`package.json` and `package-lock.json`; CI installs with `npm ci`. The checker
uses the Ajv library rather than `ajv-cli` so that one process can resolve
`$ref` between the schema files of a project and report failures per vector.
Update both pins together, run `node --test`, and commit the lockfile.
`test/jcs_vectors.json` is the shared RFC 8785 vector file also committed in each
package's tests.
