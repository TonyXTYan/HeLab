# Setting up Maestri for HeLab (human guide)

2026-10-15. How Tony (or anyone running HeLab's agents) sets up Maestri so a
coordinator can run workers on floors, following the rules in
[roadmaps/agent-workflow.md](../roadmaps/agent-workflow.md). Written from the
[Maestri docs](https://www.themaestri.app/en/docs/floors) (Floors, Maestro Mode,
Terminals & Agents, Connections, Notes) and HeLab's needs. Steps marked
**(check)** haven't been tried with this repo yet. Floors, reviews and landing
have run since 2026-10-19.

## What you get

- **Ground**: your own checkout (`HeLab/`), on the current dev branch (the
  roadmap's *Now*, e.g. `dev/v0.0.7`). You and the coordinator live here.
  Agents never commit here without asking.
- **Floors**: one per task. Each is a git worktree of HeLab on its own branch,
  in `.maestri/floors` next to the project, with its own canvas and terminals.
  On APFS, Ground's files (including `venv.nosync/` and other gitignored
  files) are copy-on-write cloned in, so creation is near-instant.
- **Coordinator**: one terminal with Maestro Mode. It proposes tasks, creates
  floors, recruits workers, reviews and integrates. It asks you before starting
  a worker, and before landing or opening a PR.

## 0. A new computer, from nothing

For a Mac with nothing installed (2026-10-19). Steps marked **(check)**
haven't been done on a second machine yet. Then continue with sections 1–4.

1. **Command-line tools and Homebrew**: `xcode-select --install` (gives
   `git`), then [Homebrew](https://brew.sh) and `brew install gh node`
   (`node` for the npm tools below).
2. **Git identity**: `git config --global user.name "…"` and
   `git config --global user.email "…"`.
3. **GitHub**: `gh auth login` with the account that can push to
   `TonyXTYan/HeLab`; `gh auth setup-git` lets `git push` use it.
4. **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new
   terminal.
5. **Clone** outside iCloud Drive if you can (inside it, keep the venv in
   `venv.nosync/` with a `venv` symlink, see AGENTS.md):

   ```bash
   git clone --recurse-submodules https://github.com/TonyXTYan/HeLab.git
   cd HeLab && git switch dev/v0.0.7   # the current dev branch: the roadmap's "Now"
   ```

6. **Python and packages** (the README's "Setup (any machine)"):

   ```bash
   uv python install 3.13
   uv venv --seed --python 3.13 venv && source venv/bin/activate
   uv pip install -r requirements.lock -e .
   pytest -n 4 --reruns 5 --reruns-delay 1   # should pass; report any RERUN
   ```

7. **Agents**: Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`)
   and Codex (`npm install -g @openai/codex`); run `claude` and `codex` once
   each to sign in.
8. **Claude's global instructions**: none are needed. The repo's `CLAUDE.md`
   loads `AGENTS.md`, and the CodeGraph rules are in `.cursor/rules/codegraph.mdc`
   (2026-10-28: `~/.claude/CLAUDE.md` isn't used on Tony's Mac either).
9. **CodeGraph** (optional; AGENTS.md uses it only when its tools are there):
   `npm install -g @colbymchenry/codegraph`, register it for Claude Code with
   `claude mcp add --scope user codegraph -- codegraph serve --mcp`, then run
   `codegraph init -i` in the repo (`.codegraph/` is gitignored).
10. **Project memory**: Claude keeps memory per checkout path, in
    `~/.claude/projects/<encoded path>/memory`. HeLab's lives in the repo
    (`.ai/memory`), so link it. Start `claude` once in the repo and quit, then:

    ```bash
    dir=$(ls -d ~/.claude/projects/*HeLab | head -1)   # the encoded repo path
    [ -d "$dir/memory" ] && [ ! -L "$dir/memory" ] && mv "$dir/memory" "$dir/memory.local"
    ln -s "$PWD/.ai/memory" "$dir/memory"
    ```

    Without the link, Claude on this Mac starts with an empty memory.
11. **Maestri**: install the app from [themaestri.app](https://www.themaestri.app),
    open it and sign in. It provides the `maestri` CLI inside its terminals
    (`$MAESTRI_CLI`) and installs its agent skills (`maestri`,
    `maestri-chat`, `maestri-manager`, … in `~/.claude/skills/`).
12. **Maestri settings don't sync**: `.maestri/` (roles, floors) is gitignored
    and hooks live in the app. Redo sections 1–4 here: workspace,
    notifications, presets, the coordinator terminal and role (the role text
    is in section 2), the register note and the floor setup hook.
13. **HeLab's own state is per machine**: settings (QSettings plist) and the
    cache in `~/Library/Caches/HeLab` start empty. Data roots are found again
    from their `.helab-root` markers. A drive this Mac reaches at a new
    location asks "same folder or a copy?" once.

**Two computers at once.** Run one coordinator on each. Both branch
`agent/<task>` from the current dev branch and land back into it. Before
landing, pull that branch first: `git pull` on Ground, or **Sync** in the land
dialog. Keep the two machines on different roadmap items, and say in the
register note which machine owns which task.

## 1. One-time setup

1. **Install the agents** Maestri will run: Claude Code and Codex, signed in
   (`claude`, `codex`). Maestri expects them installed already. Codex trusts
   only the projects listed in `~/.codex/config.toml` (on Tony's Mac, Ground
   alone); floors live in `.maestri/floors` beside the project, so a Codex
   recruit there starts in an untrusted project. Found 2026-10-29: a Codex
   Reviewer on a floor stalled on its first approval prompt (`maestri list`)
   and waited there unattended, until it was replaced by a Claude one. Two
   likely causes: the floors folder isn't trusted, and the roles' commands
   all start with `cd … && source …`, which Codex's `prefix_rule(["maestri"])`
   doesn't match. Tony decided (Q24.1, 2026-10-29): Claude Reviewers for
   unattended runs, Codex only while he is at the screen.
2. **GitHub CLI**: `gh auth status` should show the account that can push to
   `TonyXTYan/HeLab`. Floors use `gh` for pull requests; without it Maestri
   opens the PR page in the browser.
3. **Workspace**: one Maestri workspace rooted at the HeLab checkout (sidebar
   → new workspace, or `maestri workspace create "HeLab" --dir <path>` from a
   Maestro terminal).
4. **Notifications**: Settings → General → *Notify when a floor needs you*
   (blocked, ready for review, PR conflicts) and Settings → Notifications →
   *Notify when an agent needs attention*.
5. **Presets** (optional): Settings → Terminal → Quick Start, one preset each
   for Claude Code and Codex, so the coordinator can recruit either. Extra
   accounts: Settings → Agents → Accounts. Claude recruits ran all night on
   2026-10-29 without a permission prompt, although the "Claude Code" preset
   runs a bare `claude` and `~/.claude/settings.json` sets no `permissions`
   or `defaultMode`: they run in Claude Code's auto mode, which Tony's
   account opted into once (recorded in `~/.claude.json`, not in a settings
   file). On a new machine, accept auto mode when Claude Code first offers
   it, or recruits will stop at prompts **(check)**: confirm where the
   default comes from on a second machine.
6. **Gitignore**: `.maestri/` (role folders, `.maestri/roles/<id>/`) is in
   `.gitignore`.

## 2. Coordinator terminal

1. Draw a terminal on Ground (Terminal tool), choose Claude Code or Codex, and
   give it any name (Tony's is **CoCo**); the role is what makes it the
   Coordinator.
2. Right-click → **Edit Terminal** → **Details** → tick **Maestro** → Save.
   Only a Maestro (or you) can create floors and recruit agents.
3. Optional role (Settings → Agents → roles), name **Coordinator**, with
   instructions such as:

   > You coordinate parallel HeLab work. Your shell starts in a Maestri role
   > folder (`.maestri/roles/<id>/`): run every command from the repo root
   > (`cd "$(git rev-parse --show-toplevel)"` first, then `source
   > venv/bin/activate`; Claude Code resets the shell to the start folder
   > after every command, so prefix each one). Read `AGENTS.md`,
   > `roadmaps/agent-workflow.md` and `.ai/maestri-setup.md` first and follow
   > them. Don't edit feature code. Propose tasks with a brief; ask Tony
   > before creating a floor or recruiting, and before landing a floor or
   > opening a PR. Keep the "Active work" note current. Apply workers'
   > proposed doc changes when landing (`AGENTS.md`, `.ai/architecture/`,
   > roadmaps, known-issues, MANUAL_TODO), and their provisional items
   > (`Q~1`, `A~1`, `M~1`): give them the next block in `.ai/ID_BLOCKS.md`
   > and copy them into `.ai/DECISIONS_TODO.md`, `.ai/AI_TODO.md` and
   > `.ai/MANUAL_TODO.md` with their final IDs. Never delete agent branches,
   > locally or on GitHub: delete a floor only with `maestri floor delete
   > --keep-branch`, and never pass `--delete-branch` to `floor land`. Tony
   > and other agents may edit Ground for small
   > urgent changes: before landing a floor, applying doc changes or choosing
   > a base commit, check Ground's `git status` and recent log, and ask Tony
   > about changes you didn't make. Never stash, reset, check out over or
   > discard them. Base commits are always committed (`HEAD` or a hash).
   > Tony's Assistant terminal on Ground may report his decisions and Ground
   > commits to you: treat them as Tony's. Tony reads Maestri Chat, not your
   > terminal: post a short `maestri say --progress '…'` when you start a
   > task, at each milestone (a floor or recruit, a review back, a landing,
   > CI's result), when you need his decision and when you reply in the
   > terminal with something he'd want to know (to anyone, FYIs included),
   > also during work another agent asked for. One line each, without your
   > name or role (Chat shows which terminal it came from); skip routine
   > steps and acknowledgements. If `maestri say` fails, report to the
   > Assistant instead.

   A role starts the agent in `.maestri/roles/<id>/`, where Maestri writes
   the role's own `AGENTS.md`, `CLAUDE.md` and `role.json` (gitignored via
   `.maestri/`). Don't symlink or edit them: Maestri regenerates them from the
   role. The repo's instructions still load, because Claude Code reads every
   `CLAUDE.md` from the start folder up and Codex reads every `AGENTS.md` from
   the git root down. What breaks is anything relative to the start folder:
   `source venv/bin/activate`, `pytest` (collects nothing), `mypy helab/`.
   Hence the "repo root first" line. Claude Code may also ask permission to
   edit files above its start folder; the alternative is a terminal without a
   role, started in the repo root, with this text as its first prompt.
4. In the first prompt, mention **@Maestro** so the agent loads the
   `maestri-manager` skill.
5. Two more roles (Settings → Agents → roles), for the Coordinator to recruit
   with `--role` (section 5). Don't tick Maestro for either. The brief adds
   the task itself; these hold the rules every task shares.

   **Worker**:

   > You do one HeLab task on a Maestri floor. Your shell starts in a Maestri
   > role folder (`.maestri/roles/<id>/`): run every command from the floor's
   > root (`cd "$(git rev-parse --show-toplevel)"` first, then `source
   > venv/bin/activate` and `source .ai/local/floor-env.sh`; Claude Code
   > resets the shell to the start folder after every command, so prefix each
   > one). Check that the root is the floor (under `.maestri/floors`), not
   > Ground; if it is Ground, stop and tell the Coordinator. Read
   > `AGENTS.md`, `roadmaps/agent-workflow.md`, your brief and the
   > `.ai/architecture/` file of each area you change first, and follow them.
   > Work on your floor's `agent/<task>` branch, from the base commit in the
   > brief; commit freely there, and push it to `TonyXTYan/HeLab` only, at
   > checkpoints only (when the work is done, after review fixes, or when a
   > CI run on all three OSes is worth it), never with every commit. Change
   > only the brief's
   > owned paths. Write documentation only in your own
   > `.ai/sessions/<date>-<tool>-<task>/` (brief, notes, handoff with
   > proposed doc changes); never edit `AGENTS.md`, `.ai/architecture/`,
   > `roadmaps/`, `.ai/MANUAL_TODO.md`, `.ai/DECISIONS_TODO.md`,
   > `.ai/AI_TODO.md` or `.ai/memory/`; put questions for Tony, follow-ups
   > and manual checks in your handoff instead, numbered provisionally
   > (`Q~1`, `A~1`, `M~1`). Run tests with `pytest -n 4 --reruns 5
   > --reruns-delay 1 --basetemp=.ai/temp/pytest` plus strict mypy and
   > pyright, and report any RERUN. Launch the HeLab GUI only when
   > `$HELAB_TEST_SETTINGS_FILE` is set (floor-env.sh). Ask the
   > Coordinator (`maestri ask`) when blocked or when the brief is unclear;
   > keep `maestri floor status` current, and when done post `--state review`
   > and send the Coordinator your handoff's summary.

   **Reviewer**:

   > You review one HeLab branch on a Maestri floor, read-only. Your shell
   > starts in a Maestri role folder (`.maestri/roles/<id>/`): run every
   > command from the floor's root (`cd "$(git rev-parse --show-toplevel)"`
   > first, then `source venv/bin/activate` and `source
   > .ai/local/floor-env.sh`; prefix each command). Check that the root is
   > the floor (under `.maestri/floors`), not Ground; if it is Ground, stop
   > and tell the Coordinator. Read `AGENTS.md`,
   > `roadmaps/agent-workflow.md`, the brief and the worker's handoff. Review
   > the actual diff against the brief's base commit (`git diff
   > <base>...HEAD`), not the handoff's account of it: correctness, the
   > brief's acceptance criteria, the rules in `AGENTS.md` and the changed
   > areas' `.ai/architecture/` files, tests that prove the change, and doc
   > changes the handoff should propose. Rerun the critical checks yourself
   > (the full suite with `pytest -n 4 --reruns 5 --reruns-delay 1
   > --basetemp=.ai/temp/pytest-review`, strict mypy, pyright). Don't edit,
   > commit or push. Send your findings to the Coordinator (`maestri ask`),
   > most severe first, each with file and line, and say plainly when you
   > found no blocker.

   Recruit the Reviewer with the other model from the worker's (Codex
   reviews Claude's work, Claude reviews Codex's). **Today's limit:** a
   Codex Reviewer stalls unattended on approval prompts, even for
   `maestri` (section 1, step 1), so it reviews only while Tony is at the
   screen. Unattended, recruit a Claude Reviewer: a fresh terminal, never
   the author (Q24.1, Tony 2026-10-29).

   **Quick Fixer** (small, well-scoped jobs one at a time: flaky or crashing tests, CI
   failures, small bugs; a brief can hold several jobs):

   > You take small, well-scoped HeLab jobs one at a time on a Maestri floor:
   > flaky or crashing tests and CI failures from `roadmaps/known-issues.md`,
   > and small bugs. Your shell starts in a Maestri role folder
   > (`.maestri/roles/<id>/`): run every command from the floor's root (`cd
   > "$(git rev-parse --show-toplevel)"` first, then `source
   > venv/bin/activate` and `source .ai/local/floor-env.sh`; Claude Code
   > resets the shell to the start folder after every command, so prefix each
   > one). Check that the root is the floor (under `.maestri/floors`), not
   > Ground; if it is Ground, stop and tell the Coordinator. Read
   > `AGENTS.md`, `roadmaps/agent-workflow.md`, your brief and the
   > `.ai/architecture/` file of each area you change first, and follow them.
   > Run `maestri list` to see the team; take names from your brief, never
   > from memory.
   >
   > How you work:
   > - Work on your floor's `agent/…` branch, from the base commit in the
   >   brief. One job = one or a few commits there, each with a subject and a
   >   body saying the cause, the fix and the checks.
   > - Find the cause before changing code: read the failing test and the
   >   code it exercises, the CI logs (`gh api
   >   repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`; quote the "rerun
   >   reasons"), and reproduce locally (repeated runs under load, `-p xdist`
   >   with other modules, `PYTHONFAULTHANDLER=1`, `QT_FATAL_WARNINGS`, a
   >   stress loop). "Flaky" is not a cause; a longer timeout is a fix only
   >   when the cause is timing and you say why. When you can't reproduce it,
   >   say what you tried and add diagnostics that will name the cause at the
   >   next CI failure, rather than guessing.
   > - Change only what the job needs, in the style of the surrounding code:
   >   fix the test when the test is wrong, the code when the code is. If a
   >   job turns out not to be small (a design change, more than a few files,
   >   behaviour users see), stop and ask the Coordinator.
   > - Before each report: the full suite (`pytest -n 4 --reruns 5
   >   --reruns-delay 1 --basetemp=.ai/temp/pytest`), `mypy helab/ --strict`,
   >   `mypy tests --strict`, `pyright helab tests`; report any RERUN with
   >   its reason.
   > - Push your branch only at checkpoints, never with every commit (each
   >   push runs the full CI matrix): when the brief's jobs are done, or
   >   earlier when a CI run is worth it, e.g. to check a fix on Windows and
   >   Ubuntu, or when the Coordinator asks.
   > - Write documentation only in your session folder
   >   (`.ai/sessions/<date>-<tool>-<task>/`): a notes.md with a section per
   >   job (cause, evidence, fix, checks, a proposed
   >   `roadmaps/known-issues.md` line). Never edit `AGENTS.md`,
   >   `.ai/architecture/`, `roadmaps/`, `.ai/MANUAL_TODO.md`,
   >   `.ai/DECISIONS_TODO.md`, `.ai/AI_TODO.md` or `.ai/memory/`; put
   >   questions for Tony and follow-ups in your handoff (notes.md), numbered
   >   provisionally (`Q~1`, `A~1`, `M~1`). Launch the HeLab GUI only when
   >   `$HELAB_TEST_SETTINGS_FILE` is set (floor-env.sh).
   > - Keep `maestri floor status` current (a line per job; `--state review`
   >   when the batch is done). Report each job to whoever gave it with
   >   `maestri ask "<name>" "<job, cause, commits, files, checks with
   >   RERUNs, proposed known-issues line>"`, then go on to the next job in
   >   the brief.
6. **Assistant terminal** (optional): a second Ground terminal for Tony's
   questions, ideas and small urgent changes, so the Coordinator's context
   stays on the floors. Tick **Maestro** on it only so it can manage roles
   and talk to the Coordinator; it leaves floors and recruiting to the
   Coordinator. Connect it to the Coordinator (Ctrl L). Role
   **Assistant**:

   > You are Tony's assistant on Ground, beside the Coordinator. Your shell
   > starts in a Maestri role folder (`.maestri/roles/<id>/`): run every
   > command from the repo root (`cd "$(git rev-parse --show-toplevel)"`
   > first, then `source venv/bin/activate`; Claude Code resets the shell to
   > the start folder after every command, so prefix each one). Read
   > `AGENTS.md`, `roadmaps/agent-workflow.md` and `.ai/maestri-setup.md`
   > first and follow them. Answer Tony's questions, make small urgent
   > changes and quick features on Ground (the current dev branch, see the
   > roadmap's "Now"; "Work on Ground" in the guide: small, outside floors'
   > owned paths, tested and typed, then handed to the Coordinator with what
   > is left to harden), edit docs and `.ai/maestri-setup.md`, keep
   > `.ai/DECISIONS_TODO.md` current (write Tony's answers in and carry
   > decided items to where they live; take a block in `.ai/ID_BLOCKS.md`
   > before adding items, and merge floors' provisional items when the
   > Coordinator doesn't), manage Maestri roles when Tony asks, and check on
   > the Coordinator and floors (`maestri ask`, `maestri check`). Ask Tony
   > before committing unless he has asked for the commit. Leave floors,
   > workers, briefs, reviews and landing to the Coordinator: don't create
   > floors or recruit unless Tony asks, even though your terminal is a
   > Maestro. Never stash, reset or discard changes you didn't make. When a
   > chat with Tony ends in a decision that changes the plan or a floor's
   > task, or you commit on Ground, tell the Coordinator in one short
   > message; other chat stays here. Tony reads Maestri Chat, not your
   > terminal: post a short `maestri say --progress '…'` when you start a
   > task, at each milestone and when you reply in the terminal with
   > something he'd want to know, and pass the Coordinator's reports and
   > questions on there with `maestri say`. One line each, without your name
   > or role (Chat shows which terminal it came from); skip routine steps and
   > acknowledgements.

## 3. Register note

1. Draw a Note on Ground (Note tool), rename it **Active work**.
2. Connect it to the Coordinator: select the terminal, press **Ctrl L** (or the
   Connection tool), click the note.
3. Starting content:

   | Task | Floor / branch | Base commit | Agent | Owned paths | Status | Blocked on |
   |---|---|---|---|---|---|---|

Note ropes stay on one floor, so workers on floors don't see this note; they
report to the Coordinator (`maestri ask`) and post their floor status instead.
The Coordinator updates a floor's row at each landing (the landed commit,
pushed or not, floor kept, unloaded or deleted), the Ground line's commit
when it moves, and the kept-branches list when it pushes a new `agent/*`
branch. A line that holds only for a while (an overnight mandate, "no floors
until …") goes when that ends.
Keep the note in Maestri's own storage: if you *Move to…* a file inside the
repo, floors would copy a stale version of it.

## 4. Floor setup hook

Right-click the floor button (bottom right, next to the minimap) →
**Configure Hooks…** → **Setup**, tick **Auto-run**, and add each command
below as its own entry, in this order, so each can be switched on or off.
Maestri provides `$MAESTRI_FLOOR_PATH`, `$MAESTRI_ROOT_PATH`,
`$MAESTRI_BRANCH_NAME`, `$MAESTRI_FLOOR_NAME` and `$MAESTRI_PROJECT_NAME`.
Every command starts from the floor's folder itself and the venv and bytecode
ones refuse to run on Ground, so none relies on an earlier one's working directory.

**Python.** The cloned venv has the right packages but is wired to Ground by
absolute paths (script shebangs, `activate`, and the editable install of
`helab`). `pytest.ini` (`pythonpath = .`, 2026-10-22) now makes pytest test the
floor's checkout whatever the venv, but the `helab` entry point and anything
else that imports `helab` would still get **Ground's** code, so give each floor
a fresh venv (about 16 s with uv's cache). Keep 1 and 2 both on or both off.

1. Fresh venv:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && case "$(cd -P venv 2>/dev/null && pwd || pwd -P)/" in "$(pwd -P)"/*) uv venv --clear --seed --python 3.13 venv;; *) echo "venv resolves outside the floor; not clearing it" >&2; false;; esac
   ```

   `uv venv --clear` follows a `venv` symlink and empties its target, so the
   `case` refuses when `venv` resolves outside the floor (an absolute link to
   Ground's `venv.nosync`). The README's relative `ln -s venv.nosync venv`
   resolves inside the floor and passes. Added 2026-10-28 (checked under sh,
   zsh and bash on scratch folders); update the hook entry in the app to match.

2. Packages and the floor's own editable `helab`:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && uv pip install -q --python venv/bin/python -r requirements.lock -e .
   ```

**Private app folders and settings**, for tests and any manual run. Command 3
starts `.ai/local/floor-env.sh` afresh; 4, 5 and 5b add a line each. Command 3 also makes `.ai/temp`,
where `pytest --basetemp=.ai/temp/pytest` needs it.

3. App folder (locks, `cache-move.json`) and the floor's `.ai/temp`:

   ```bash
   mkdir -p "$MAESTRI_FLOOR_PATH/.ai/local" "$MAESTRI_FLOOR_PATH/.ai/temp" && echo "export HELAB_APP_DIR_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/app\"" > "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

   **A floor copies Ground as it is.** `maestri floor create` clones Ground's
   files, uncommitted and untracked ones included, and has no way to exclude
   a folder (Excluded folders, below, is only in the app's create dialog).
   So every floor made from the command line carries Ground's `.ai/temp`
   (2.8 GB on 2026-10-29: old briefs, `pytest-*` folders with copies of the
   docs that turn up in a `grep -r`) and anything left uncommitted on Ground
   (hence "Ground clean" in section 5).

   **Proposed hook 3, for Tony to paste into the app** (2026-10-29), in place
   of the one above: it first empties the floor's own `.ai/temp`, then does
   what hook 3 does now.

   ```bash
   { [ -n "$MAESTRI_FLOOR_PATH" ] && [ -n "$MAESTRI_ROOT_PATH" ] && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && root="$(cd -P "$MAESTRI_ROOT_PATH" && pwd -P)" && [ -n "$root" ] && cd -P "$MAESTRI_FLOOR_PATH" && [ "$(pwd -P)" != "$root" ] && [ ! -L .ai ] && rm -rf .ai/temp; } || echo "hook 3: not emptying .ai/temp" >&2; mkdir -p "$MAESTRI_FLOOR_PATH/.ai/local" "$MAESTRI_FLOOR_PATH/.ai/temp" && echo "export HELAB_APP_DIR_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/app\"" > "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

   The removal runs only inside `$MAESTRI_FLOOR_PATH`, and never when either
   variable is empty, when the two are equal as text, when the floor's real
   path (symlinks resolved) is Ground's, or when `.ai` is a symlink (it could
   point at Ground's). A `.ai/temp` that is itself a symlink loses only the
   link. When the guard refuses, the step says so and still writes
   `floor-env.sh`. The guard was checked under sh, zsh and bash on scratch
   folders, with `echo` in place of the removal: it refused every case above
   (and a missing floor or Ground folder) and passed a floor path with a
   space in it. The removal itself
   hasn't run on a floor yet **(check)**. Ground's own `.ai/temp` stays
   (Q2.1.2).

4. Cache folder:

   ```bash
   echo "export HELAB_DIR_CACHES_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/caches\"" >> "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

5. Temp folder:

   ```bash
   echo "export HELAB_DIR_TEMPS_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/temps\"" >> "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

5b. Settings file (Q2.5, 2026-10-28): `app_settings()` opens this ini instead of
   the real settings store, so the GUI or a script run from the floor never
   touches Tony's settings. pytest still gives each test its own.

   ```bash
   echo "export HELAB_TEST_SETTINGS_FILE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/settings.ini\"" >> "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

**Stale bytecode.** The clone copies Ground's `__pycache__` folders, which
carry Ground's paths into tracebacks (seen on the CI Robustness floor: a
traceback naming `../../../HeLab/tests/…`). Delete them outside `venv/` and
`legacy/`:

6. Bytecode:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && find . \( -path ./venv -o -path ./venv.nosync -o -path ./legacy -o -path ./.git \) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
   ```

   Added 2026-10-22. Works on real floors (checked 2026-10-29 on TXY ship):
   folders under `.ai/temp` that Ground had before the floor was made were
   copied, but their `__pycache__` folders were gone.

**Optional**, added but switched off; switch it on (or run the command in the
brief) when a task needs the 2019 MATLAB converter. Since Q6.4 it is the only
submodule, and its folder starts empty on a floor. The hand-cloned
`legacy/DLD_front_panel` and `legacy/Momentum_Bells_test` are gitignored, so
they come with the clone of Ground's ignored files.

7. Converter submodule:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && git submodule update --init legacy/tdc_autoconverter
   ```

**Teardown** (runs on Delete Floor): remove that floor's private folders. The
name check stops an empty `$MAESTRI_FLOOR_NAME` from removing every floor's
folders.

1. Floor folders:

   ```bash
   [ -n "$MAESTRI_FLOOR_NAME" ] && rm -rf "$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME"
   ```

Checked 2026-10-22 on a test floor named "Hook Test": setup runs by itself
when a floor is created, in order, in under a minute; `floor-env.sh` quotes a
name with spaces correctly; the floor's venv imports the floor's `helab`; and
the Worker's pytest command runs with no manual steps. Pasting a command from
this guide can bring its closing ```` ``` ```` along on a second line the hook
editor may not show: the step then exits with an error (under zsh it writes
nothing). **(check)** Whether Maestri stops or carries on after a failing step.

When creating a floor in the app's dialog (not from the command line, which
has no such option) you can add **Excluded folders**; `build` and `dist` are
excluded by default. Worth adding: `htmlcov`, `.ai/temp`, `.pytest_cache`. Check that `.codegraph/` works on a floor or re-run
`codegraph init -i` there **(check)**.

## 5. Running a task

1. **Choose the base commit** (you or the Coordinator). First check that
   Ground is clean (`git status --short` prints nothing): the new floor
   copies Ground's working tree, uncommitted and untracked files included
   (section 4). If it isn't, ask whoever made the change (the Assistant or
   Tony) to commit it or keep it out of the tree; never stash or discard it.
   To start from a commit other than Ground's current one, make the branch
   first, then use it:

   ```bash
   git branch agent/<task> <commit>
   maestri floor create "<Task>" --branch agent/<task> --existing-branch
   ```

   Otherwise `maestri floor create "<Task>" --branch agent/<task>`, or type
   `@New Floor` in the Coordinator's composer with the task.

   After a release, base floors only on the new dev branch. v0.0.6 went to
   `main` as a squash (`9c477c2`), so `dev/v0.0.7` shares no history with
   `dev/v0.0.6`, and earlier `agent/*` branches are records, not bases.
   `floor create --copy` makes an independent APFS copy of the repository
   instead of a git worktree (Mac only, `maestri help floor`); floors here
   are worktrees, so don't pass it. `--copy-ground` is still explained
   nowhere, neither in `maestri help floor` nor here; don't use it until it
   is known **(check)**.
2. **Recruit the worker** on that floor (the Coordinator asks you first):

   ```bash
   maestri recruit "<Codename>" --floor "<Task>" --preset "Claude Code" --role "Worker"
   ```

   A Claude worker or reviewer runs Opus 5.5 at the effort the Coordinator
   picks (low, medium, high, xhigh, max), set in the new terminal with
   `/model` and `/effort` if it didn't start that way. Fable only with
   Tony's approval (agent workflow, Models).

   then `maestri ask` it the brief (objective, acceptance, base commit, owned
   paths and paths not to touch, checks, handoff). For review, recruit the
   other model on the same floor (`--preset "Codex" --role "Reviewer"`),
   but only while Tony is at the screen: a Codex Reviewer stalls unattended
   on approval prompts, even for `maestri` (section 1, step 1; Q24.1, Tony
   2026-10-29). Unattended, recruit a Claude
   Reviewer (`--preset "Claude Code" --role "Reviewer"`): a fresh terminal,
   never the author.

   Before sending the brief, `maestri check` the new terminal: a recruit can
   hang at start, showing only its typed `claude …` command and no Claude UI,
   so a brief sent then never arrives (RAM Worker, 2026-10-20; Ctrl-C didn't
   help). Restart it in place with
   `maestri recruit "<Codename>" --preset "Claude Code" --replace "<Codename>"`
   (same node, floor and role), check again, then send the brief. It happened
   once with an explicit `--command`, which other recruits used without
   trouble, so the flag isn't known to be the cause.
3. **The worker**:
   - works from the floor's root: a worker recruited with `--role` starts in
     `.maestri/roles/<id>/`, so it runs `cd "$(git rev-parse --show-toplevel)"`
     first and confirms that path is the floor, not Ground;
   - runs `source .ai/local/floor-env.sh` before tests or a manual run;
   - runs tests with its own `--basetemp=.ai/temp/pytest` and about `-n 4`
     when several workers are busy, and the type checks for Windows too
     (`mypy --platform win32` and `pyright --pythonplatform Windows`, as
     well as the usual ones: Windows-only typing errors have reached CI);
   - installs packages only into the floor's venv: when a task needs one that
     `requirements.lock` lacks (a spike's numba or Cython), it first checks that
     `venv/bin/python -c "import sys; print(sys.prefix)"` prints a path under
     the floor, then runs `uv pip install --python venv/bin/python <pkg>`.
     Never a bare `pip install` or an activated `uv pip install`: with hooks
     1–2 off or failed, those install into Ground's venv. Such packages are
     listed in the session folder (or a `requirements-bench.txt`), never in
     `requirements.txt` or the lock unless Tony decides. Briefs that add
     packages repeat this rule;
   - commits freely on its branch; writes only its own
     `.ai/sessions/<date>-<tool>-<task>/` (brief, notes, handoff with proposed
     doc changes);
   - when done, pushes the branch (pushes only at checkpoints), runs
     `maestri floor status "<summary>" --state review`, and reports to the
     Coordinator, naming the push's CI run ID and its result once it is in.

   **Two agents on one floor** (e.g. a builder and a cross-checker, TXY
   Reference 2026-10-29): give each its own `--basetemp`
   (`.ai/temp/pytest-<name>`), since pytest empties its basetemp and two runs
   sharing one clear each other. The second agent writes in its own
   subfolder of the session folder (the cross-checker used
   `.ai/sessions/<date>-<tool>-<task>/crosscheck/`), and the brief says
   which paths each may commit.
4. **The HeLab GUI may run from a floor** once `floor-env.sh` is sourced: hooks
   3–5b give it its own app, cache and temp folders and settings file (Q2.5).
   Check `echo $HELAB_TEST_SETTINGS_FILE` first; if it is empty, the hook
   wasn't run, so don't launch it. Tests are safe either way.

## Work on Ground

Tony (or his Assistant terminal, section 2) may make small urgent changes on
Ground, on the current dev branch, while floors run. The Coordinator doesn't
make them: it doesn't edit feature code. The Assistant tells the Coordinator
about each Ground commit.

- Add a **Ground** row to Active work (task, terminal, files, status) and
  clear it when the change is committed; the Coordinator warns a floor whose
  owned paths overlap.
- **Keep Ground clean**: commit a change (after asking Tony) or keep it out
  of the tree before a floor lands or a new floor is made. Maestri's Merge
  Locally refuses uncommitted work, but the `git merge` the Coordinator uses
  doesn't, and a new floor copies whatever is in the tree (section 4). On
  2026-10-29 an uncommitted Assistant log and a DECISIONS_TODO edit were
  swept into landing commits. Logs and drafts written during a run go in
  `.ai/local/` or a Maestri note, or are committed at once. With Maestri's
  land, **Sync** then brings a committed change into the floor before the
  merge.
- **ID blocks**: an agent reserves its block in `.ai/ID_BLOCKS.md` (a
  committed row) before writing any item with that block's number; a
  subagent gets its block from its parent. An ID that has been pushed is
  never renamed (`f405de0` moved an A19.1 that was already on GitHub).
- A change that overlaps a floor's owned paths and isn't small goes to that
  floor's worker instead. Anything bigger becomes its own floor.

**Quick features.** Tony may ask the Assistant for a small feature he can use
at once, then have the Coordinator send a floor to harden it (edge cases,
slow drives, Windows, tests):

- Keep it small: about a day's work, a few files, outside every floor's owned
  paths. Anything bigger starts as a floor.
- Run the tests and typing before committing; commit (after asking Tony) as
  soon as he has tried it and is happy, so it doesn't block landing.
- After the commit, send the Coordinator one message: the commit, what the
  feature does and what it doesn't cover yet. The Coordinator decides on a
  hardening floor based on that commit.
- Add a roadmap line marked "quick version on Ground, hardening pending", and
  keep that list short: harden before adding more.

## 6. Landing

You land floors (or approve the Coordinator doing it from Ground).

**Landing conditions** (Tony, Q24.4, 2026-10-29). A floor lands only when all of these hold (from the
2026-10-29 overnight run, where helab-core landed with its own branch CI red
on Windows and turned the dev branch red):

- [ ] The Reviewer has no open findings.
- [ ] The branch contains the current dev branch (`git merge-base
      --is-ancestor dev/v0.0.7 agent/<task>`), so what was tested is what
      lands.
- [ ] The branch's latest CI run, on the commit that lands, is green on
      macOS, Windows and Ubuntu: every job, both test groups ("Tests (1/2)",
      "Tests (2/2)"), "Converter backends" and "Build". Check it by run ID
      and quote the ID when asking Tony:
      `gh run list --workflow "CI CD" --branch agent/<task> --limit 1 --json databaseId,headSha,conclusion`
      (its `headSha` is `git rev-parse agent/<task>`), then
      `gh run view <id> --json jobs --jq '.jobs[] | select(.name | test("py3.13")) | [.name, .conclusion] | @tsv'`.
- [ ] The full suite passes on the merged tree, with its output kept whole
      (`… > .ai/temp/<name>.txt 2>&1`, never filtered: a filter once dropped
      a RERUN's name and reason), and every RERUN is named and explained or
      filed in `roadmaps/known-issues.md`.
- [ ] The type checks pass, for Windows too: `mypy helab/ --strict`,
      `mypy tests --strict`, the same two with `--platform win32`,
      `pyright helab tests` and `pyright --pythonplatform Windows helab tests`.
- [ ] Ground is clean before the merge (`git status --short` prints
      nothing): `git merge` doesn't refuse uncommitted work, and anything
      left there ends up in a landing commit or in the next floor ("Work on
      Ground").

**How floors land today: `git merge` on Ground.** All 16 landings of
2026-10-29 were a plain merge from a Ground terminal, which leaves the floor
and its status in place:

```bash
git status --short                       # must print nothing
git merge agent/<task>                   # a fast-forward when the branch contains the dev branch
maestri floor status --floor "<Task>" "Landed <sha>" --state done
```

Then run the suite and type checks on Ground and update the register note's
row. Without the `floor status` line the floor keeps saying "review" in the
sidebar.

**Maestri's own landing**, in the app or from the CLI:

- Click the airplane button beside the floor, or **Land Floor** in its menu.
- **Merge Locally**: pick the target branch (the current dev branch, e.g.
  `dev/v0.0.7`). **Sync** first pulls the target's latest changes into the
  floor. A merge is refused when the floor or the target's checkout has
  uncommitted work, or lists the conflicting files and stops.
- **Pull Request**: pick **Into**; title and description come from the commit
  and PR template. Maestri then tracks reviews and CI, offers *Ask an Agent to
  Fix the Checks* and the like, and lands the floor after **Merge…**.
- The floor is removed after landing unless **Keep this floor after landing**
  is ticked. The branch stays in the repo.
- CLI equivalent, from a Ground terminal only:
  `maestri floor land "<Task>" --into dev/v0.0.7 --keep-floor` (the current
  dev branch). Without `--keep-floor` the floor is deleted. Never pass
  `--delete-branch`.

After landing, the Coordinator applies the worker's proposed doc changes
(`AGENTS.md`, `.ai/architecture/`, `roadmaps/` with known-issues,
`.ai/MANUAL_TODO.md`, `.ai/memory/`) on Ground, merges its provisional items
(`Q~1`, `A~1`, `M~1`) into the `.ai/*_TODO.md` lists under a block it has
reserved in `.ai/ID_BLOCKS.md` ("Work on Ground"), and asks you before
committing them.

### Supervised runs (mandate mode)

Tony may hand his approvals to the Assistant while he is away (Q24.2, 2026-10-29), as on the
night of 2026-10-29 ([mandate](sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md)).
**Only Tony starts it**: an agent may suggest a supervised run, never begin one. Then:

1. The Assistant writes the mandate in `.ai/sessions/<date>-claude-<task>-supervised/mandate.md`
   before any floor starts: the scope (which plan stages); what it approves for Tony (floors and
   recruits on default models, landings into the dev branch under the landing conditions above,
   pushes at checkpoints, reversible choices the plan leaves open); what never happens without
   him (a PR to `main`, a version bump, a release or tag, deleting branches, data, caches or
   settings, writing to lab shares or sample copies, machine-wide installs, answering any agent's
   permission prompt); and a decisions log.
2. The Coordinator reports to the Assistant, not Tony's Chat, and asks it what the plan doesn't
   answer. The Assistant logs each decision it makes for Tony as "for Tony to confirm", keeps its
   log out of Ground's tree until a checkpoint commit, and runs a heartbeat (every ~30 min) that
   checks the floors and CI.
3. Anything outside the mandate, or a test that keeps failing after a cause hunt, stops that
   piece and waits for Tony.
4. The mode ends when Tony says so, or comes back: the Assistant sends a report (stages, every
   decision for him to confirm, RERUNs, what waits for him), the decisions go to
   `.ai/DECISIONS_TODO.md`, and the Coordinator's note drops the mandate lines.

The roles will say this once Tony updates them (until then, the mandate itself says it).

## 7. Clean-up

**Delete Floor** removes the floor folder including uncommitted changes;
commits stay unless **Also remove the branch** is ticked: never tick it. From
the CLI, `maestri floor delete "<Task>" --keep-branch`: without the flag it
deletes the branch. Agent branches are kept, locally and on GitHub, for the
record (AGENTS.md). Unload idle floors to free memory: the floor's menu, or
`maestri floor unload "<Task>"` from a Maestro terminal. `maestri floor
list` doesn't say which floors are unloaded, so note it in the register.

After deleting a floor, check that `~/Library/Caches/HeLab/floors/` no longer
holds its folder: the teardown hook hasn't always run (two empty folders were
left on 2026-10-28). Remove a leftover only after confirming its floor is gone.

## Not yet in place

- Settings profiles (`HELAB_SETTINGS_OVERRIDE`, share/isolated per checkout;
  the hard-coded defaults table landed 2026-10-22). Floors are isolated by
  hook 5b meanwhile.
- The floor review items marked **(check)**.
