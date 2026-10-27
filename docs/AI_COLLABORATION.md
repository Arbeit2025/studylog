# Studylog AI collaboration policy (public-safe)

Status: proposed policy. This repository is **public**. Do not put unpublished patent-related techniques, draft claims, private development records, secrets, credentials, or personal data here.

## Working branches

- ChatGPT: `ai/chatgpt`
- Meta Muse: `ai/muse`
- Anthropic Claude: `ai/claude`
- Integration target: `main`

Each assistant uses **only its own branch or namespaced task branches** (`ai/<assistant>/<task>`) for code changes. Check the latest `main` and existing open PRs before starting. Do not push directly to `main` or overwrite another assistant's branch. Never force-push shared branches.

## Change and review flow

1. Check issue/task scope, file ownership, changed files, and open PRs. Flag concurrent edits to the same files.
2. Implement the smallest coherent change on the relevant assistant branch. Avoid destructive DB/schema migrations.
3. Run available tests repeatedly (aim for 3 runs when practical). Report commands, results, and **untested** behavior separately. Never invent tests.
4. Open a pull request targeting `main` with the purpose, changed files, compatibility impacts, security/privacy review, test evidence, and rollback steps. Do not self-merge.
5. Owner reviews and explicitly approves merging and any production deploy. Rebase/update from current `main` as needed; re-test after resolving conflicts.
6. After a verified merge/deploy, update the authoritative development record. Distinguish code written, tests run, PR opened, merge completed, and production verified.

## Confidential information

The intended confidential record repository is `Arbeit2025/studylog-dev-private` (must be created as **Private**, and access individually verified for each service). Do not assume it exists or is connected. Do not transfer confidential material until its private visibility and access permissions have been checked.

Do not paste private repo content into this public repo, public issue/PR, commit messages, Actions logs, or AI outputs intended for publication. A private GitHub repository restricts access but does not by itself establish confidentiality obligations for external AI providers; review each provider's data handling and permissions.

## Authority and safety

AI outputs are proposals pending human review. Only the owner can approve merges/deploys. Keep tests non-destructive and do not alter production data without a verified backup and explicit authorization. Secrets belong in dedicated secret-management controls, not in Git history.

_Last policy draft: 2026-10-26._
