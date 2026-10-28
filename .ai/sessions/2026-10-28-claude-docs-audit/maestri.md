# Audit of the Maestri setup (2026-10-28, evening)

Read-only. Done on Ground at `dev/v0.0.7` `7b82c9d`. The working tree had uncommitted
`.ai/DECISIONS_TODO.md` and `.ai/ID_BLOCKS.md`, and the untracked
`.ai/sessions/2026-10-28-claude-txy-converter-plan/`. Maestri 0.56.1.

Only read-only `maestri` commands were used: `list`, `role list` and `role show` (all five),
`floor list`, `preset list` and `preset show`, `note read "Active work"`, and `help`. No
Maestri state was changed and no agent was messaged. The one experiment ran in the
scratchpad (finding 4) and was deleted.

Tags: **[AI]** marks mechanical work. **[Tony]** marks a decision.

**What checks out:**
- **Live roles match the guide.** The live prompts of Coordinator, Worker, Reviewer, Assistant
  and Quick Fixer match `.ai/maestri-setup.md` §2 word for word (compared after joining
  whitespace).
- **Role folders match the live roles.** The two role folders, `19b8…` (Assistant) and
  `3b67…` (Coordinator), have `CLAUDE.md` = `AGENTS.md` = `role.json` = the live prompt.
- **Every `maestri` command and flag the guide uses exists in 0.56.1:**
  - `floor create --branch --existing-branch`
  - `floor land --into`
  - `floor status --state`
  - `recruit --floor --preset --role --replace`
  - `workspace create --dir`
  - `ask`, `check`, `say --progress`
- **Presets match the guide.** "Claude Code" runs a bare `claude`, and the global settings
  make that `opus` at effort high, as the guide's Models line says. "Codex" runs
  `codex --no-daemon`. A "Claude Fable" preset exists; the guide already restricts Fable
  to Tony's approval.
- **The Maestri skills are installed** in `~/.claude/skills/`.
- **Nothing left over on the git side.** `git worktree list` shows only Ground, there is no
  `.git/worktrees`, and no HeLab floor folders remain.
- **AGENTS.md** is 15.9 KB, within Codex's 32 KiB.

## Findings

1. **Deleting a floor from the command line deletes its branch by default.** [AI]
   - **The guide:** `.ai/maestri-setup.md:526-528` (§7) covers only the UI ("never tick
     *Also remove the branch*").
   - **The CLI:** `maestri help floor` says:
     - `floor delete "Name" [--keep-branch]` "Remove the floor, its clone and, **unless
       --keep-branch, its branch**";
     - `floor land` has a `--delete-branch` flag.
   - **The rule it breaks:** the Coordinator, the only role that deletes floors, has
     "Never delete agent branches" (AGENTS.md:26, the Coordinator role). Neither the guide nor
     the role gives the safe CLI form.
   - **Fix:** in §7 add "From the CLI: `maestri floor delete "<Task>" --keep-branch`; never
     pass `--delete-branch` to `floor land`". Optionally add the same clause to the
     Coordinator role.

2. **The setup guide still names `dev/v0.0.6` in seven places.** [AI]
   - **Where:** `.ai/maestri-setup.md`:
     - :13 "currently `dev/v0.0.6`";
     - :42 `git switch dev/v0.0.6`;
     - :89-90 Two computers;
     - :476 Work on Ground;
     - :508 Merge Locally;
     - :518 `floor land … --into dev/v0.0.6`.
   - **What's current:** the roadmap's "Now" (`roadmaps/_readme.md:23`) and the "Active work"
     note both say `dev/v0.0.7`.
   - **Fix:** write "the current dev branch (roadmap's *Now*)", with `dev/v0.0.7` only as the
     example, as the Assistant role already does.

   Related, unwritten:
   - **v0.0.6 went to `main` as a squash.** `9c477c2` has a single parent. `dev/v0.0.7` was
     cut from it, so it shares no history with `dev/v0.0.6`:
     `git rev-list --left-right --count dev/v0.0.6...dev/v0.0.7` gives `447 3`.
   - **Old agent branches can't be landed into `dev/v0.0.7`.** That is every local
     `agent/*`: each is an ancestor of `dev/v0.0.6` and not of `dev/v0.0.7`.
   - **Only two places say so.** The README (:184) and the "Active work" note do. The guide and
     `agent-workflow.md` don't.
   - **Fix:** add one line to §5 step 1: "after a release, base floors only on the new dev
     branch; earlier `agent/*` branches are records, not bases".

3. **The Ground floor's status is stale.** [AI, for the Coordinator]
   - **What it says:** `maestri floor list` shows `Ground … branch 'dev/v0.0.7'`, with the
     status "[working] dev/v0.0.6 at 927de44, CI 40604007433 green; no floors active · by CoCo".
   - **What's true:** Ground is `dev/v0.0.7` at `7b82c9d`.
   - **Fix:** the Coordinator reposts the status.

4. **Nothing says how a floor adds packages, and the wrong way installs into Ground's venv.**
   [AI; the Rust toolchain is Tony's]
   - **What the guide covers:** `roadmaps/agent-workflow.md:77-81` covers only a branch that
     changes `requirements.txt`. AGENTS.md and the guide say nothing about a spike adding
     packages such as numba, Cython, maturin or mlx to a floor's venv.
   - **Ground's venv is wired to Ground by absolute paths:**
     - `venv/bin/pytest` starts `#!/Users/tonyyan/GitHub-Local/HeLab/venv/bin/python`;
     - `venv/bin/activate:81` sets `VIRTUAL_ENV='/Users/tonyyan/GitHub-Local/HeLab/venv'`.
   - **Where that bites:** on a floor whose fresh-venv hooks (§4, 1–2) are off or failed,
     `pip install` or an activated `uv pip install` installs into **Ground's** venv.
   - **Hook 1 can wipe Ground's venv.** Tested in the scratchpad: `uv venv --clear` follows an
     absolute `venv` symlink and wipes the target. The target's contents were replaced by a
     fresh venv. On a machine where `venv` is an absolute link to Ground's `venv.nosync`,
     hook 1 would empty Ground's venv. The README's `ln -s venv.nosync venv` is relative and
     therefore safe, so this is hardening only.
   - **Fix:**
     - Add a "Floor-only packages" rule to the guide §5 and the Worker brief template:
       `uv pip install --python venv/bin/python <pkg>`, after checking that
       `venv/bin/python -c "import sys; print(sys.prefix)"` is under the floor. List spike-only
       packages in the session folder or a `requirements-bench.txt`, never in
       `requirements.txt` or the lock unless Tony decides.
     - Make hook 1 refuse when `venv` is a symlink that resolves outside the floor.
   - **The machine** (`which` and `--version`):
     - present: Apple clang 21.0.0 (`cc`/`gcc`/`clang`, Xcode CLT) and uv 0.12.21;
     - missing: `rustc`, `cargo`, `rustup` and `maturin` (no `~/.cargo`); `cython`; Homebrew
       `libomp`, needed for OpenMP with Apple clang; CUDA (an Apple M4 Max with 16 cores);
     - Ground's venv has numpy 2.5.4, scipy and setuptools, but no numba, Cython, maturin, mlx
       or pybind11.
   - **Rust (PyO3) needs Tony's OK.** `rustup` installs per user, outside any floor.

5. **TXY converter spike: the X share is mounted read-write, and its path depends on mount
   order.** [Tony]
   - **The mount** (`mount`; the share itself was not touched):
     `//Xintong@192.168.137.1/X on /Volumes/192.168.137.1-4 (smbfs, nodev, nosuid, …)`.
     It has no `read-only` flag.
   - **The path suffix is mount order:** C, D, E, R and X are mounted as `…1`, `…1-1` …
     `…1-4`. A remount in another order renumbers them, yet DECISIONS_TODO Q6.3.1 and the
     findings hard-code `-4`.
   - **What protects the share today:**
     - `HELAB_TEST_SOURCE_GUARD` exists only under pytest, and `floor-env.sh` rightly doesn't
       set it;
     - the findings say MATLAB's `dld_raw_to_txy_counts` "writes beside its input".

     So nothing technical stops a floor agent from writing to the lab archive. The guide has
     no section on real data for floors.
   - **Proposed:**
     - copy the two sample folders once to a local folder outside every checkout, e.g.
       `~/Library/Caches/HeLab/samples/` (the `20241107…` folder is about 0.96 GB: 679 MB raw
       and 279 MB TXY);
     - have floors read only those copies;
     - find X with `mount | grep '/X on'` rather than `-4`;
     - add a short "Real data on floors" paragraph to §5.

6. **TXY spike: what MATLAB needs on a floor.** [AI]
   - **The 2019 converter isn't there by default.** It is the byte-identical reference, and it
     lives in the submodule `legacy/tdc_autoconverter`. Submodule folders start empty on a
     floor (guide :390), and hook 7 that fills them is **off by default**.
   - **Hook 7 is out of date.** The command is `git submodule update --init --recursive`.
     Since Q6.4 (`7b82c9d`), `.gitmodules` holds only `tdc_autoconverter`, which has no nested
     submodules, so `--recursive` is moot. The guide's "submodule folders" wording predates Q6.4.
   - **The 2023 variant comes along by another route.** It lives in
     `legacy/DLD_front_panel/…`, which is now a gitignored hand clone (28 MB on Ground). A
     floor gets it only through the copy-on-write clone of Ground's ignored files. It is
     present on Ground today.
   - **Running MATLAB headless isn't documented.**
     `/Applications/MATLAB_R2025b.app/bin/matlab` exists, but nothing in the guide says how to
     run it. Whether several MATLAB sessions may run at once (one per builder) under the
     licence wasn't checked.
   - **Fix:** a spike brief:
     - switches hook 7 on, or runs `git submodule update --init legacy/tdc_autoconverter`;
     - runs MATLAB only on local copies, with `-nodisplay -batch`.

     In the guide, reword hook 7 and drop `--recursive`.

7. **TXY spike: the Reviewer role is read-only, but Q6.5 has the reviewer co-write the
   reference.** [Tony]
   - **The plan:** Q6.5 (DECISIONS_TODO, "Decided"): "The builder and a reviewer write the
     reference first (the reviewer cross-checks, also against MATLAB run headless), then one
     builder per backend, all connected to the reviewer."
   - **The role:** "You review one HeLab branch on a Maestri floor, read-only … Don't edit,
     commit or push". It also has every check run the full suite (`pytest -n 4 …
     --basetemp=.ai/temp/pytest-review`), which a benchmark spike doesn't need.
   - **Choices:**
     - (a) the brief overrides the role for this task, to allow MATLAB runs and scratch output
       under `.ai/temp`;
     - (b) recruit the cross-checker as a Worker;
     - (c) add a "Verifier" role.

     Proposed: (b) for the reference stage, with the Reviewer used as written for the final
     review.

8. **TXY spike: the guide assumes one worker per floor, but Q6.5 plans one builder per
   backend.** [Tony]
   - **The guide's model:** one floor, one branch, one worker, with
     `--basetemp=.ai/temp/pytest` (Worker role), and the reviewer on `pytest-review`.
   - **Five builders on one floor would share the working tree and the branch.** NumPy, Numba,
     Cython/C, Rust and MLX would:
     - commit over each other;
     - clear each other's `.ai/temp/pytest`, since pytest wipes its basetemp.
   - **Five floors are clean but cost more.** Each takes a fresh venv (about 16 s) and a branch.
     Wiring builders to a reviewer on another floor needs `maestri connect` (Maestro only).
     Whether cross-floor agent links work wasn't checked; note links stay on one floor (guide
     :319).
   - **Benchmark noise:**
     - parallel builders and their `-n 4` pytest runs compete for the 16 cores;
     - the idle HeLab GUI (pid 77000, `venv/bin/helab`) runs at **32 % CPU**, 30 h after it
       started (audit #18, A2.3, still open).
   - **Proposed:** one floor per backend, each branched from the reference commit. Timings are
     taken serially by one agent at the end, on an otherwise idle machine, after quitting
     pid 77000.

9. **Settings isolation on floors (audit #5, Q2.5): still open, and the guide still says it
   can't be done.** [Tony, Q2.5]
   - **The guide:** `.ai/maestri-setup.md:353` "QSettings is **not** yet isolated", :469-471
     "Don't launch the HeLab GUI from a floor yet" and :533-535.
   - **The code:** `helab/utils/settings_store.py:25-27`. `app_settings()` opens
     `HELAB_TEST_SETTINGS_FILE` as an ini file whenever it is set, so one more `floor-env.sh`
     line would isolate a floor.
   - **What a floor gets today, per the guide:**
     - a fresh venv (hooks 1–2);
     - private app, cache and temp folders (hooks 3–5);
     - `.ai/temp` for `--basetemp`;
     - pytest itself isolated, since conftest overrides all of these
       (`tests/conftest.py:44-46,148`).
   - **What it lacks:** any non-pytest run (the GUI, or a benchmark script that imports
     `helab`) reads and writes Tony's real settings store.
   - **Fix:** once Q2.5 is answered, add hook 3b, `echo "export
     HELAB_TEST_SETTINGS_FILE=…/floors/$MAESTRI_FLOOR_NAME/settings.ini" >> …/floor-env.sh`.
     Then drop the three "not isolated" passages and the roles' "Don't launch the HeLab GUI".

10. **The setup hooks can't be audited from the repo.** [Tony]
    - **Where they live:** in the Maestri app. Searching `~/Library` (Application Support,
      Preferences, Containers, Spotlight) found no `floor-env` or `MAESTRI_FLOOR_PATH` text,
      so the guide's copy is the only record and whether each hook is on can't be checked.
    - **Proposed:** move the commands into a tracked script (e.g. `tools/floor-setup.sh` and
      `tools/floor-teardown.sh`), called by a single hook entry, so changes such as findings 4,
      6 and 9 are versioned and reviewed. `agent-workflow.md:67` already says "a script to
      write".

11. **The guide contradicts itself on whether floors get Ground's ignored files.** [AI]
    - **Two sides:**
      - :17-18 says Ground's files, "including `venv.nosync/` and other gitignored files", are
        cloned in;
      - :355-356 says `.ai/temp` is something "a floor doesn't get (it is gitignored)".
    - **Evidence:** the surviving PencilMaps floor has Ground's ignored `.ai/local/`,
      `Packages/PencilMapsCore/.build/` and `.swiftpm/` (`git status --ignored`).
    - **Probably:** `.ai/temp` is missing only when it is excluded at floor creation, which
      :417 recommends.
    - **Fix:** reword :355 as "`.ai/temp`, which is excluded from the clone (see Excluded
      folders)". This also matters for finding 6: the hand-cloned legacy folders reach floors
      only because ignored files are cloned.

12. **The Coordinator role and guide §6 list different docs to apply at landing.** [AI]
    - **The Coordinator role:** "`AGENTS.md`, `.ai/architecture/`, roadmaps, known-issues,
      MANUAL_TODO" plus the provisional IDs.
    - **Guide :520-522:** "AGENTS.md, `roadmaps/`, MANUAL_TODO, memory". That has no
      `.ai/architecture/` and no ID lists, and the role has no memory.
    - **`agent-workflow.md:41-42`:** "the coordinator updates those".
    - **Fix:** make §6 the same list as the role, plus `.ai/memory/`, and add memory to the
      role.

13. **AGENTS.md's push rule has no exceptions.** [AI]
    - **AGENTS.md:22:** "It pushes that branch once, when its work is done".
    - **The exceptions elsewhere:**
      - `agent-workflow.md:95` "A further push after review fixes is fine";
      - Q2.2.2 and the Quick Fixer role "push earlier only when the Coordinator asks".
    - **Fix:** "… once, when its work is done (again after review fixes, or when the
      Coordinator asks)".

14. **The Quick Fixer and Reviewer roles drift from the rules.** [AI]
    - **Quick Fixer:**
      - its provisional IDs are "(`Q~1`, `A~1`)", with no `M~1`, where Worker and AGENTS.md:61
        have all three;
      - it writes them in `notes.md`, where AGENTS.md:61 says "in your handoff".
    - **Reviewer:** it lacks the "Check that the root is the floor (under `.maestri/floors`),
      not Ground" guard that Worker and Quick Fixer have.
    - **Fix:** two `maestri role edit`s and the matching §2 text.

15. **Items from the earlier audits that are still unresolved.**
    - **Six local agent branches are still one handoff commit ahead of GitHub** (#6, Q2.2.3):
      - `agent/cache-only` `398e8ee`;
      - `codebase-review-2` `797cd02`;
      - `presets-reopen` `b3021b8`;
      - `quick-fixes-2` `3eb0fbf`;
      - `quick-fixes-3` `4a63827`;
      - `windows-store-test` `8a4049d`.

      Their content is on GitHub through `dev/v0.0.6` (`3d9bf31` = origin), but the branch
      tips aren't, although the "Active work" note lists them as "kept on GitHub". [Tony,
      Q2.2.3]
    - **The orphaned pytest is still alive** (#17, Q2.1.1): pid 15027, started Oct 23, 153 MB,
      0 % CPU now. Its floor folder `.maestri/floors/HeLab--agentresult-cache-r2` no longer
      exists. [Tony]
    - **`.ai/temp` is still 386 MB** (#26, Q2.1.2). [Tony]
    - **The floor pilot is still described as future** (#8, A2.1):
      - `agent-workflow.md:3-4` "settings profiles … nothing implemented", although the
        defaults table and `app_settings()` landed;
      - :67 "a script to write";
      - :70 "ground's `venv.nosync/bin/python3.13`": this Mac's Ground `venv` is a real
        folder and there is no `venv.nosync`;
      - :97-100 "before the pilot";
      - `roadmaps/_readme.md:38` "pilot the first floor".

      [AI, A2.1]
    - **`.ai/coding-workspace.md` is still a symlink into `ai-common`** (#4, Q2.4). It resolves
      on this Mac. [Tony]
    - **Earlier items now fixed, not re-reported:**
      - Quick Fixer documented, with its push rule and session folder (#1, #16);
      - the branch-keeping rule in AGENTS.md and guide §7 (#2, #18);
      - CodeGraph optional, with no `~/.claude/CLAUDE.md` step (#3, #9, #14);
      - the Assistant role names "the current dev branch" and `.ai/maestri-setup.md`
        (#19, #20);
      - the new lists are in the roles (#17).

16. **Small points.** [AI]
    - **`(check)` markers:**
      - guide :78 (Maestri skills) can lose it: `~/.claude/skills/` has `maestri`,
        `maestri-chat`, `maestri-manager`, `maestri-portal`, `maestri-portal-devices`,
        `maestri-routines` and `maestri-workspace`;
      - :387 (bytecode hook "not yet on a floor") should be confirmed or removed, since about
        8 floors have run since Oct 22.
    - **Two leftover floor folders.** `~/Library/Caches/HeLab/floors/` still holds empty
      `Result Cache/` and `Codebase Review 2/` (only `caches/` and `temps/`). The teardown hook
      didn't run for those two. It's harmless, but worth a line in §7: "check this folder
      after deleting a floor".
    - **Codex trusts only Ground.** `~/.codex/config.toml` marks only
      `/Users/tonyyan/GitHub-Local/HeLab` as trusted. Floors live in
      `/Users/tonyyan/GitHub-Local/.maestri/floors/HeLab--…`, so a Codex recruit there starts
      in an untrusted project. The effect on a Codex builder (approval prompts, sandbox) wasn't
      tested. Worth a note in §1, or adding the floors folder as trusted.
    - **One CLI flag is undocumented.** `maestri floor create` has a `--copy-ground` flag that
      the guide doesn't mention and `help` doesn't explain. Find out what it does before
      relying on the default clone behaviour.
