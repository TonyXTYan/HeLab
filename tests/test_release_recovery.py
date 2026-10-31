from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from helab import release as selection
from helab.build_info import checkout_build_info, read_build_info, write_build_info
from helab.release import decide_release, plan_release
from helab.release_draft import (
    ASSET_NAMES, Asset, Draft, GitHubReleases, Manifest, manifest_body, publish_draft,
    read_manifest, release_complete, validate_archives,
)

SHA = "a" * 40
LATER_SHA = "b" * 40
TAG = "v0.0.5a1"
ROOT = Path(__file__).resolve().parent.parent


def archives(root: Path, *, commit: str = SHA, dirty: bool = False, extra: str = "first") -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name in ASSET_NAMES:
        path = root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("HeLab/_internal/helab/_build_info.json", json.dumps({
                "version": "0.0.5a1", "commit": commit, "dirty": dirty,
            }))
            archive.writestr("HeLab/payload.txt", extra)
        result[name] = path
    return result


class MemoryReleases:
    def __init__(self) -> None:
        self.release: Draft | None = None
        self.tag_sha = SHA
        self.uploads: list[str] = []
        self.deleted: list[int] = []
        self.creations = 0
        self.body_updates = 0
        self.fail_before: str | None = None
        self.fail_after: str | None = None

    def get_release(self, tag: str) -> Draft | None:
        assert tag == TAG
        return self.release

    def verify_tag(self, tag: str, commit: str) -> None:
        assert tag == TAG
        if self.tag_sha != commit:
            raise ValueError("Remote tag points to another commit")

    def create(self, tag: str, commit: str, prerelease: bool, body: str) -> Draft:
        assert self.release is None and tag == TAG and commit == SHA and prerelease
        self.creations += 1
        self.release = Draft(1, True, body, ())
        return self.release

    def save_body(self, release_id: int, body: str, prerelease: bool) -> None:
        assert self.release is not None and self.release.id == release_id and self.release.draft
        self.body_updates += 1
        self.release = replace(self.release, body=body)

    def delete_asset(self, asset_id: int) -> None:
        assert self.release is not None and self.release.draft
        self.deleted.append(asset_id)
        self.release = replace(self.release, assets=tuple(a for a in self.release.assets if a.id != asset_id))

    def upload(self, release_id: int, name: str, path: Path) -> None:
        assert self.release is not None and self.release.id == release_id and self.release.draft
        if self.fail_before == name:
            raise RuntimeError("Upload failed before completion")
        self.uploads.append(name)
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        asset = Asset(100 + len(self.uploads), name, path.stat().st_size, "uploaded", digest)
        self.release = replace(self.release, assets=self.release.assets + (asset,))
        if self.fail_after == name:
            raise RuntimeError("Response lost after successful upload")


@pytest.mark.parametrize("response_lost", [False, True])
def test_full_rerun_recovers_tagged_partial_draft_and_preserves_completed_assets(
    tmp_path: Path, response_lost: bool,
) -> None:
    files = archives(tmp_path / "first")
    api = MemoryReleases()
    if response_lost:
        api.fail_after = ASSET_NAMES[0]
    else:
        api.fail_before = ASSET_NAMES[1]
    with pytest.raises(RuntimeError):
        publish_draft(api, TAG, SHA, True, files, "Release notes")
    assert not release_complete(api.release, SHA)
    assert decide_release("0.0.5a1", [TAG], "refs/heads/main",
                          completed=release_complete(api.release, SHA)).should_release
    api.fail_before = api.fail_after = None
    rebuilt = archives(tmp_path / "rebuilt", extra="rebuilt with different bytes/date")
    publish_draft(api, TAG, SHA, True, rebuilt, "New workflow notes")
    assert api.creations == 1
    assert api.uploads == list(ASSET_NAMES)
    assert api.deleted == []
    assert release_complete(api.release, SHA)
    assert not decide_release("0.0.5a1", [TAG], "refs/heads/main", completed=True).should_release
    publish_draft(api, TAG, SHA, True, rebuilt, "Retry again")
    assert api.uploads == list(ASSET_NAMES)


def test_existing_tag_without_draft_is_recoverable(tmp_path: Path) -> None:
    api = MemoryReleases()
    assert decide_release("0.0.5a1", [TAG], "refs/heads/main").should_release
    publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.creations == 1 and release_complete(api.release, SHA)


def test_starter_or_wrong_digest_is_replaced_but_manual_assets_survive(tmp_path: Path) -> None:
    files = archives(tmp_path)
    fingerprints = validate_archives(files, TAG, SHA)
    api = MemoryReleases()
    api.release = Draft(1, True, manifest_body("Human notes", Manifest(SHA, fingerprints)), (
        Asset(1, ASSET_NAMES[0], 0, "starter", None),
        Asset(2, ASSET_NAMES[1], fingerprints[ASSET_NAMES[1]].size, "uploaded", "sha256:" + "0" * 64),
        Asset(3, "manual-notes.txt", 15, "uploaded", None),
    ))
    assert not release_complete(api.release, SHA)
    publish_draft(api, TAG, SHA, True, files, "Ignored replacement notes")
    assert api.deleted == [1, 2]
    assert api.release is not None and "Human notes" in api.release.body
    assert any(asset.name == "manual-notes.txt" for asset in api.release.assets)
    assert release_complete(api.release, SHA)


def test_legacy_incomplete_draft_is_rebuilt_from_verified_tag(tmp_path: Path) -> None:
    api = MemoryReleases()
    api.release = Draft(1, True, "Older notes without a manifest", (
        Asset(1, ASSET_NAMES[0], 99, "uploaded", None),
    ))
    publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.creations == 0 and api.deleted == [1]
    assert release_complete(api.release, SHA)


def test_published_release_is_not_updated_even_if_assets_are_missing(tmp_path: Path) -> None:
    api = MemoryReleases()
    original = Draft(1, False, "Published alpha", ())
    api.release = original
    assert release_complete(original, SHA)
    publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.release == original
    assert not api.uploads and not api.deleted and api.body_updates == 0


@pytest.mark.parametrize("wrong_tag,wrong_manifest", [(True, False), (False, True)])
def test_commit_collision_refuses_any_release_mutation(tmp_path: Path, wrong_tag: bool, wrong_manifest: bool) -> None:
    api = MemoryReleases()
    if wrong_tag:
        api.tag_sha = LATER_SHA
    if wrong_manifest:
        api.release = Draft(1, True, manifest_body("Notes", Manifest(LATER_SHA, {})), ())
    with pytest.raises(ValueError):
        publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.creations == api.body_updates == 0 and not api.uploads and not api.deleted


def add_link(archive: Path, name: str, target: str) -> None:
    """A symlink entry as ``zip -y`` stores one (the macOS zip keeps HeLab.app's links)."""
    info = zipfile.ZipInfo(name)
    info.external_attr = (0o120755 << 16)
    with zipfile.ZipFile(archive, "a") as stream:
        stream.writestr(info, target)


def test_a_stamp_linked_to_the_packaged_one_is_checked_through_it(tmp_path: Path) -> None:
    # 0.0.7a1's macOS zip (run 41110274554): Contents/Frameworks/helab/_build_info.json links to
    # Contents/Resources/helab/_build_info.json, and reading the link as JSON stopped the release.
    files = archives(tmp_path)
    add_link(files[ASSET_NAMES[0]], "HeLab/Frameworks/helab/_build_info.json", "../../_internal/helab/_build_info.json")
    assert set(validate_archives(files, TAG, SHA)) == set(ASSET_NAMES)


@pytest.mark.parametrize("target", ["../../payload.txt", "../../_internal/helab/missing/_build_info.json"])
def test_a_linked_stamp_must_lead_to_a_packaged_stamp(tmp_path: Path, target: str) -> None:
    files = archives(tmp_path)
    add_link(files[ASSET_NAMES[0]], "HeLab/Frameworks/helab/_build_info.json", target)
    with pytest.raises(ValueError, match="links outside the stamps"):
        validate_archives(files, TAG, SHA)


def test_an_archive_with_only_a_linked_stamp_has_none(tmp_path: Path) -> None:
    files = archives(tmp_path)
    only_link = tmp_path / "only-link.zip"
    with zipfile.ZipFile(only_link, "w") as archive:
        archive.writestr("HeLab/payload.txt", "first")
    add_link(only_link, "HeLab/Frameworks/helab/_build_info.json", "../../payload.txt")
    files[ASSET_NAMES[0]] = only_link
    with pytest.raises(ValueError, match="no packaged build stamp"):
        validate_archives(files, TAG, SHA)


@pytest.mark.parametrize("commit,dirty", [(LATER_SHA, False), (SHA, True)])
def test_wrong_commit_or_dirty_archives_are_rejected_before_mutation(tmp_path: Path, commit: str, dirty: bool) -> None:
    api = MemoryReleases()
    with pytest.raises(ValueError):
        publish_draft(api, TAG, SHA, True, archives(tmp_path, commit=commit, dirty=dirty), "Notes")
    assert api.creations == api.body_updates == 0 and api.uploads == []


def built(root: Path, name: str, *, version: str, commit: str = SHA, dirty: bool = False) -> Path:
    """One platform's archive as its build job zips it, its stamp saying ``version``."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HeLab/_internal/helab/_build_info.json",
                         json.dumps({"version": version, "commit": commit, "dirty": dirty}))
    return path


@pytest.mark.parametrize("name", ASSET_NAMES)
def test_a_build_checks_its_own_archive_without_a_tag(tmp_path: Path, name: str,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """A39.1: each PR build runs ``release_draft --check`` on its archive against its build commit and the
    checkout's version: the release's stamp check, with no tag and no draft, before any merge."""
    from helab._version import __version__
    from helab.release_draft import main
    main(["--check", str(built(tmp_path, name, version=__version__)), "--commit", SHA])
    assert capsys.readouterr().out == f"{name}: built cleanly from {__version__} at {SHA}\n"
    linked = built(tmp_path / "linked", name, version=__version__)
    add_link(linked, "HeLab/Frameworks/helab/_build_info.json", "../../_internal/helab/_build_info.json")
    main(["--check", str(linked), "--commit", SHA])  # (0.0.7a1's macOS zip: a linked stamp.)
    for wrong in (built(tmp_path / "commit", name, version=__version__, commit=LATER_SHA),
                  built(tmp_path / "dirty", name, version=__version__, dirty=True),
                  built(tmp_path / "version", name, version="0.0.1")):
        with pytest.raises(ValueError, match="not built cleanly"):
            main(["--check", str(wrong), "--commit", SHA])
    add_link(linked, "HeLab/Other/helab/_build_info.json", "../../payload.txt")
    with pytest.raises(ValueError, match="links outside the stamps"):
        main(["--check", str(linked), "--commit", SHA])


def test_the_release_still_needs_its_tag_and_the_three_archives(tmp_path: Path) -> None:
    from helab.release_draft import main
    with pytest.raises(SystemExit):
        main(["--validate-only", "--commit", SHA, "--artifacts", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["--validate-only", "--commit", SHA, "--tag", TAG])
    files = archives(tmp_path)
    main(["--validate-only", "--commit", SHA, "--tag", TAG, "--artifacts", str(tmp_path)])
    files[ASSET_NAMES[1]].unlink()
    with pytest.raises(FileNotFoundError):
        main(["--validate-only", "--commit", SHA, "--tag", TAG, "--artifacts", str(tmp_path)])


def test_each_python_3_13_build_checks_its_archive_against_its_commit() -> None:
    """A39.1: the build job's step (ci-build.yml) runs the check on what it built, for every OS."""
    workflow = (ROOT / ".github" / "workflows" / "ci-build.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Check the build's stamps against its commit", 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.python-minor == '13' && inputs.build-sha == github.sha" in step
    assert 'python -m helab.release_draft --check "$archive" --commit "$BUILD_SHA"' in step
    assert "BUILD_SHA: ${{ inputs.build-sha }}" in step
    assert workflow.index("Zip the macOS app") < workflow.index("Check the build's stamps") < workflow.index(
        "Archive build artifacts")
    assert "if: inputs.os == 'macos' && (inputs.upload || inputs.python-minor == '13')" in workflow


def test_publication_during_recovery_stops_further_writes(tmp_path: Path) -> None:
    class PublishedDuringUpload(MemoryReleases):
        def upload(self, release_id: int, name: str, path: Path) -> None:
            super().upload(release_id, name, path)
            assert self.release is not None
            self.release = replace(self.release, draft=False)
    api = PublishedDuringUpload()
    with pytest.raises(ValueError, match="published"):
        publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.uploads == [ASSET_NAMES[0]]


def mock_git(monkeypatch: pytest.MonkeyPatch, *, version: str = "0.0.5a1", ancestor: bool = True) -> None:
    def git(root: Path, *args: str) -> str:
        if args == ("tag", "-l"):
            return TAG
        if args == ("rev-parse", "HEAD"):
            return LATER_SHA
        if args == ("rev-parse", f"refs/tags/{TAG}^{{commit}}"):
            return SHA
        if args[0] == "merge-base":
            assert args[-2:] == (SHA, LATER_SHA)
            if not ancestor:
                raise subprocess.CalledProcessError(1, "git merge-base")
            return ""
        if args == ("show", f"{SHA}:helab/_version.py"):
            return f'__version__ = "{version}"'
        raise AssertionError(args)
    monkeypatch.setattr(selection, "_git", git)


def test_later_main_push_rebuilds_tagged_sha_instead_of_uploading_new_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_git(monkeypatch)
    plan = plan_release(tmp_path, "0.0.5a1", "refs/heads/main", None)
    assert plan.decision.should_release
    assert plan.release_sha == plan.build_sha == SHA
    assert plan.build_sha != LATER_SHA
    assert plan.build_ref == f"refs/tags/{TAG}" and plan.build_branch == "detached"
    complete = plan_release(tmp_path, "0.0.5a1", "refs/heads/main", Draft(1, False, "Published", ()))
    assert not complete.decision.should_release and complete.build_sha == LATER_SHA


@pytest.mark.parametrize("version,ancestor", [("0.0.4a1", True), ("0.0.5a1", False)])
def test_tag_version_or_lineage_mismatch_blocks_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       version: str, ancestor: bool) -> None:
    mock_git(monkeypatch, version=version, ancestor=ancestor)
    with pytest.raises(ValueError):
        plan_release(tmp_path, "0.0.5a1", "refs/heads/main", None)


def test_manifest_tag_collision_is_rejected_even_for_published_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_git(monkeypatch)
    release = Draft(1, False, manifest_body("Published", Manifest(LATER_SHA, {})), ())
    with pytest.raises(ValueError, match="disagree"):
        plan_release(tmp_path, "0.0.5a1", "refs/heads/main", release)


def test_detached_pr_stamp_records_source_branch_and_merge_ref_without_replacing_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(ROOT), str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "HEAD"], check=True)
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    assert checkout_build_info(checkout).branch == "detached"
    monkeypatch.delenv("HELAB_BUILD_BRANCH", raising=False)
    monkeypatch.delenv("HELAB_BUILD_REF", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_HEAD_REF", "feature/versioning")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/17/merge")
    monkeypatch.setenv("GITHUB_SHA", LATER_SHA)  # Context cannot replace the actual checked-out SHA.
    path = tmp_path / "stamp.json"
    info = write_build_info(checkout, path)
    assert info.commit == commit and info.commit != LATER_SHA
    assert info.branch == "feature/versioning" and info.build_ref == "refs/pull/17/merge"
    assert read_build_info(path) == info
    monkeypatch.setenv("HELAB_BUILD_BRANCH", "detached")
    monkeypatch.setenv("HELAB_BUILD_REF", f"refs/tags/{TAG}")
    recovery = write_build_info(checkout, path)
    assert recovery.commit == commit and recovery.build_ref == f"refs/tags/{TAG}"
    assert recovery.branch == "detached"


def test_api_errors_are_not_treated_as_a_missing_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, "gh api", stderr="HTTP 403")
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        GitHubReleases("owner/repo").get_release(TAG)


def test_api_lists_drafts_across_pages_and_peels_annotated_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    api = GitHubReleases("owner/repo")
    calls: list[str] = []
    def request(method: str, endpoint: str, payload: dict[str, object] | None = None,
                file: Path | None = None) -> object:
        calls.append(endpoint)
        if endpoint.endswith("releases?per_page=100&page=1"):
            return [{"tag_name": "other"}] * 100
        if endpoint.endswith("releases?per_page=100&page=2"):
            return [{"tag_name": TAG, "id": 1, "draft": True, "body": "Notes"}]
        if endpoint.endswith("assets?per_page=100&page=1"):
            return []
        if "git/ref/tags" in endpoint:
            return {"object": {"type": "tag", "sha": "annotated"}}
        if "git/tags/annotated" in endpoint:
            return {"object": {"type": "commit", "sha": SHA}}
        raise AssertionError(endpoint)
    monkeypatch.setattr(api, "_request", request)
    assert api.get_release(TAG) == Draft(1, True, "Notes", ())
    api.verify_tag(TAG, SHA)
    with pytest.raises(ValueError, match="another commit"):
        api.verify_tag(TAG, LATER_SHA)
    assert any("page=2" in call for call in calls)


def test_a_draft_listed_as_untagged_is_found_by_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub lists a draft as "untagged-<hash>", not its tag: v0.0.5a1's and v0.0.6a1's CI created
    their draft, failed to find it again and stopped before uploading. Another draft or a
    published release with that name isn't taken for it."""
    api = GitHubReleases("owner/repo")
    listed = [{"tag_name": "untagged-0855e2edbc65d73ef84f", "id": 7, "draft": True, "body": "Notes",
               "name": f"Automated Release {TAG}"},
              {"tag_name": "untagged-1111", "id": 8, "draft": True, "name": "Automated Release v0.0.4a"},
              {"tag_name": "v0.0.3b", "id": 9, "draft": False, "name": f"Automated Release {TAG}"}]

    def request(method: str, endpoint: str, payload: dict[str, object] | None = None,
                file: Path | None = None) -> object:
        if endpoint.endswith("releases?per_page=100&page=1"):
            return listed
        if endpoint.endswith("assets?per_page=100&page=1"):
            return []
        raise AssertionError(endpoint)
    monkeypatch.setattr(api, "_request", request)
    assert api.get_release(TAG) == Draft(7, True, "Notes", ())
    listed.append(dict(listed[0], id=10))
    with pytest.raises(ValueError, match="Multiple releases"):
        api.get_release(TAG)


def test_duplicate_or_missing_digest_assets_do_not_count_as_complete(tmp_path: Path) -> None:
    api = MemoryReleases()
    publish_draft(api, TAG, SHA, True, archives(tmp_path), "Notes")
    assert api.release is not None
    snapshot = api.release
    assert read_manifest(snapshot.body) is not None
    duplicate = replace(snapshot, assets=snapshot.assets + (replace(snapshot.assets[0], id=500, state="starter"),))
    assert not release_complete(duplicate, SHA)
    missing_digest = replace(snapshot, assets=(replace(snapshot.assets[0], digest=None),) + snapshot.assets[1:])
    assert not release_complete(missing_digest, SHA)
