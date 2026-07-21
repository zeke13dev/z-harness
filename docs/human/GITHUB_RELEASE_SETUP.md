# GitHub release setup

This document records the repository settings required before z-harness is made public or a release is published. The workflows enforce candidate integrity in code; these GitHub settings supply the administrative protection around those workflows.

## Current publication order

1. Push the reviewed `main` history while the repository is still private.
2. Let all `main` CI jobs complete successfully.
3. Protect `main` using the exact successful check names reported by GitHub.
4. Create the protected `release-evidence` environment and add its release-only secrets.
5. Register a repository-owned self-hosted runner carrying the `z-harness-release-evidence` label.
6. Run release evidence, conformance, and publication against one exact SHA at the freshly fetched `origin/main` tip.
7. Make the repository public only after the public-page and secret-history checks pass.

Do not create a release tag or make the repository public merely to test the setup.

## Protect `main`

Use a branch ruleset or classic branch protection with these properties:

- target: the `main` branch;
- block force pushes and branch deletion;
- require a pull request before future merges;
- require conversation resolution;
- require branches to be up to date before merging;
- require every successful `main` CI check that is intended to remain blocking; and
- include administrators after the initial private `main` push is complete.

For a single-maintainer repository, requiring a pull request with zero mandatory approving reviews prevents direct pushes without creating an impossible self-approval requirement. Increase the approval count when another maintainer is available.

Do not guess required-check context names from workflow YAML. Push first, let CI create the checks, and select the exact names GitHub reports for the successful commit.

## Protect release evidence

Create an Actions environment named exactly `release-evidence`. The workflow contract validates this exact name.

Configure the environment to:

- allow deployment only from protected branches;
- require an explicit approval before the evidence job starts, if the repository plan and maintainer topology support a non-deadlocking reviewer rule; and
- store the following environment secrets, never repository variables or committed files:
  - `Z_HARNESS_RELEASE_ANTHROPIC_API_KEY`
  - `Z_HARNESS_RELEASE_CODEX_OPENAI_API_KEY`
  - `Z_HARNESS_RELEASE_OMP_OPENAI_API_KEY`

The evidence runner must be repository-owned and carry all labels required by `.github/workflows/release-evidence.yml`:

```text
self-hosted
linux
x64
z-harness-release-evidence
```

Use a dedicated runner account or machine with no persistent provider credentials. The workflow supplies release-only credentials through the protected environment and creates isolated host homes for execution.

## Authorize one protected-main candidate

Before running release evidence, confirm the reviewed candidate is the exact `origin/main` tip and stop further mutation until publication completes. Evidence, conformance, and publication independently fetch `origin/main`, require a clean detached checkout at that exact SHA, and reject stale or mismatched bindings. Publication refreshes `origin/main` again immediately before publication, creates the canonical tag with a non-force push that fails if the tag already exists, verifies the remote tag resolves to the authorized candidate SHA, and only then creates the release.

These workflows verify Git identities and immutable evidence; they do not query or prove GitHub ruleset configuration. Branch protection is the administrative prerequisite described above and must be checked in repository settings.

Protect the canonical release-tag namespace (`v*`) with a repository ruleset that permits the release workflow to create tags but prevents tag updates and deletion. The non-force tag push closes competing-creation races; the ruleset keeps the verified tag immutable afterward.

## Public visibility checklist

Before changing repository visibility from private to public, confirm:

- `README.md`, `LICENSE`, repository description, and topics render correctly;
- the default branch is `main` and its protection is active;
- CI is green at the public tip;
- a full-history credential and privacy scan has passed, and any benign historical plan metadata or maintainer-local path strings retained for provenance have been explicitly reviewed and accepted;
- Actions has read-only default token permissions;
- no release-only secret is stored outside the protected environment;
- Issues and any intentionally enabled community features have appropriate templates or are disabled; and
- the first public release remains unpublished until protected exact-candidate evidence succeeds.

Visibility changes and release publication are separate decisions. A repository may be public while the first release is still pending.

## Release workflow order

For a canonical version and exact protected `main` candidate SHA:

1. Run `Produce exact release evidence` with `candidate_version` and `candidate_sha`.
2. Record the successful immutable evidence run ID.
3. Run `Exact release-candidate conformance` with the same version, SHA, and evidence run ID.
4. Run `Release protected main candidate` with the same version, candidate SHA, and evidence run ID.

Publication creates the canonical tag and release at `candidate_sha` only after all exact-candidate and freshness checks pass.
