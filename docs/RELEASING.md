# Releasing the three small packages

`experiment-gate` (distribution `expgate`), `jev-decision` (`jevdecision`) and
`decision-control` (`decisioncontrol`) are independent release candidates.
RELIA is excluded; follow [RELIA_RELEASE.md](RELIA_RELEASE.md).
Use Python 3.11+ from the repository root. The [release tool](../scripts/release.py)
never commits, tags or publishes.

## Prepare and tag

```sh
python3.11 scripts/release.py status
python3.11 scripts/release.py check --component experiment-gate
python3.11 scripts/release.py prepare experiment-gate --date YYYY-MM-DD
python3.11 scripts/release.py check --tag experiment-gate/v0.1.0
```

Substitute `jev-decision` or `decision-control` as appropriate. Review the changed
changelog, single-source version, license and metadata; run both Python suites,
build/twine validation and installed-wheel console smoke before committing.
`check --tag` validates the candidate metadata and dated notes; it does not create
a tag or attest to a clean/reviewed working tree.

```sh
git add ai-workflows/experiment-gate/CHANGELOG.md
git commit -m "chore(release): prepare experiment-gate 0.1.0"
git tag -a experiment-gate/v0.1.0 -m "experiment-gate 0.1.0"
git push origin HEAD
git push origin experiment-gate/v0.1.0
```

Include other reviewed version changes in the commit when applicable. Tags use
`<component>/vX.Y.Z`, not the distribution name. Never move an already published
tag or reuse a published PyPI version.

## What automation does

On a matching tag push, [release.yml](../.github/workflows/release.yml) checks out
that tag, validates its component/version/dated changelog/license, runs its tests
on Python 3.11, builds sdist and wheel, runs `twine check --strict`, and imports the
installed wheel from outside the source tree to check its version. The component
CI workflows separately run console scripts against source examples from outside
the source tree on Python 3.11 and 3.13; release.yml's wheel smoke is import-only.
Build artifacts are uploaded. Two jobs then independently follow the build:
GitHub Release creation attaches distributions with dated changelog notes (and
leaves an existing release unchanged); PyPI publishing runs only when repository
variable `PYPI_PUBLISH` equals `true`, and skips files already on PyPI.

## One-time publishing setup

For **each** distribution (`expgate`, `jevdecision`, `decisioncontrol`), register a
PyPI pending trusted publisher (or a publisher on the existing project): owner
`BichengWang`, repository `ai-decision-system`, workflow filename `release.yml`,
environment `pypi`. See [PyPI setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

PyPI permits only one **pending** publisher per (owner, repository, workflow,
environment) configuration. For the 0.1.0 releases, register and publish one
project at a time: `expgate`, then `decisioncontrol`, then `jevdecision`. Each
first upload converts that pending entry into an active project publisher,
freeing the configuration for the next pending project. Future new packages
using this same workflow and environment must follow the same sequence;
existing projects use their active publishers.

Create GitHub environment `pypi` with a required reviewer and selected deployment
tag patterns `experiment-gate/v*`, `jev-decision/v*`, `decision-control/v*`.
Configure these controls before setting repository variable `PYPI_PUBLISH=true`.
See [GitHub environment rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
Trusted publishing uses short-lived OIDC credentials, not a stored PyPI API token.
See [PyPI security model](https://docs.pypi.org/trusted-publishers/security-model/).

## Existing tag: publish later or retry

Fix publisher/environment configuration first, then dispatch the workflow **on the
tag ref** with `publish=true`:

```sh
gh workflow run release.yml --ref experiment-gate/v0.1.0 \
  -f tag=experiment-gate/v0.1.0 -f publish=true
```

The build job refuses a publishing dispatch whose run ref is not `refs/tags/<tag>`,
so the `pypi` environment's tag rule applies to exactly the tag being published.
The run rebuilds from the tag, creates the GitHub Release only if it is missing, and
uploads to PyPI only when `PYPI_PUBLISH=true`, skipping files that already exist.
A dispatch without `publish` is a build-only diagnostic. Never move or recreate a
published tag, and never reuse a published PyPI version.
