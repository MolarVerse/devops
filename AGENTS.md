# Copilot Agent Instructions

## Pull Request Base Branch Policy

When creating a new Pull Request:

- **Always use `dev` as the base branch by default**
- Do **not** use `main`, `master`, or any other branch unless explicitly instructed
- If the user mentions a different base branch, follow that instruction exactly
- Create **all** following pull requests to the previously used base branch

### Summary Rule

> **Default base branch = `dev`**  
> **Override only when explicitly requested**

This rule applies to:
- New feature branches
- Bug fixes
- Refactors
- Documentation changes
- Any automated or suggested pull request creation

## Documentation

The project's Sphinx documentation lives under `docs/source` and is built with the `docs` extra (`pip install -e ".[docs]"`).

- The API reference under `docs/source/api/` is generated automatically via `autosummary --recursive` from docstrings (NumPy style, per `ruff.toml`'s `pydocstyle` convention) — new/removed modules require no manual edits there.
- The version shown on the docs landing page is pulled automatically from the installed package's metadata (`setuptools_scm`), so it never needs to be updated by hand.
- Explanatory guide pages go under `docs/source/sections/`.
- Build locally with `sphinx-build -b html -W docs/source docs/build/html`; treat any warning as a build failure, matching CI.
- `.github/workflows/docs.yml` builds the docs on push/PR to `main`/`dev` and deploys to GitHub Pages on push to `main`.

## Changelog

Pull requests do **not** edit `CHANGELOG.md`. Each one adds a fragment `changes/<category>.<slug>.md` with one or more `- ...` bullets (one per line, no blank lines, ending with a newline), e.g. `changes/feature.no-unit-alias.md`.

- Categories (`devops.toml`): `feature` (Features), `fix` (Bug Fixes), `performance`, `docs` (Documentation), `ci` (CI), `internal`.
- CI checks this with `devops_changelog check-pr`; PRs that need no entry get the `skip-changelog` label.
- On release, `create-tag.yml` runs `devops_changelog stamp <version>`, which moves all fragments under the new version heading in `CHANGELOG.md` and deletes them (`changes/.gitkeep` stays).

