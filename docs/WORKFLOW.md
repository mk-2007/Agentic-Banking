# How we work: branches, commits, pull requests

One rule: **every change is a short branch, a few small commits, and a pull request that gets merged.**
That keeps history readable, CI honest, and the tracker true.

## The loop

On Windows, call the tools as `python -m ruff`, `python -m mypy` and `python -m pytest`: pip puts the plain
`ruff` and `mypy` commands in a folder that is often not on PATH.

```powershell
git switch main; git pull
git switch -c feat/<short-name>          # fix/, docs/, test/, chore/ also fine
# ... work in small steps; after each step that passes the checks:
cd backend; python -m ruff check .; python -m ruff format --check .; python -m mypy; python -m pytest -q; cd ..
git add <the files of that step>
git commit -m "feat(scope): what changed"
# ... repeat, then:
git push -u origin HEAD
gh pr create --fill                      # or open it on github.com; the template appears
# wait for CI, read your own diff once, then merge on GitHub (use "Create a merge commit")
git switch main; git pull
```

Before opening the PR, update `docs/TRACKER.md`, `docs/PROJECT_LOG.md` and `docs/context/STATE.md`.

## Commits
- One logical step per commit, and **every commit passes the checks** (so any commit can be reverted or bisected).
- Format: `type(scope): imperative summary`, with type one of `feat fix test docs refactor chore`.
- Commit when a step is done, not on a timer. A day of real work is usually 5 to 12 commits. Do not pad
  history with empty or trivial commits; reviewers can tell, and it hides the real work.
- Never commit `.env`, keys or real personal data.

## Pull requests
- One PR per tracker line (6a, 6b, ...). Small PRs get merged the same day and keep `main` green.
- Merge with **"Create a merge commit"** (or rebase), not squash: squashing collapses your commits into
  one on `main`, so the work shows up as a single commit.
- Make sure your commit email is one of the verified emails on your GitHub account
  (`git config user.email`), otherwise GitHub does not credit the commits to you.
- The repo must be **public** (or private contributions enabled on your profile) for activity to count
  towards profile achievements.
