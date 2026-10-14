"""CI version validation and release selection: python -m helab.release."""

import argparse
import ast
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from packaging.version import InvalidVersion, Version

from helab._version import __version__
from helab.release_draft import Draft, GitHubReleases, read_manifest, release_complete


@dataclass(frozen=True)
class ReleaseDecision:
    tag: str
    should_release: bool
    prerelease: bool


def decide_release(version: str, tags: list[str], ref: str, *, completed: bool = False) -> ReleaseDecision:
    current = Version(version)
    if str(current) != version or current.local is not None or current.epoch:
        raise ValueError("Use a canonical public PEP 440 version, without a v prefix or local suffix")
    previous: list[Version] = []
    for tag in tags:
        if tag.startswith("v"):
            try:
                previous.append(Version(tag[1:]))
            except InvalidVersion:
                continue
    if previous and current < max(previous):
        raise ValueError(f"Version {version} is lower than latest tagged version {max(previous)}")
    # Do not create a second spelling of a legacy tag. A canonical existing tag,
    # however, is not proof that its draft/assets finished uploading.
    tag = f"v{version}"
    legacy = current in previous and tag not in tags
    return ReleaseDecision(tag, ref == "refs/heads/main" and not legacy and not completed,
                           current.is_prerelease or current.is_devrelease)


@dataclass(frozen=True)
class ReleasePlan:
    decision: ReleaseDecision
    release_sha: str
    build_sha: str
    build_ref: str
    build_branch: str


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def validate_release_commit(root: Path, commit: str, head: str, version: str) -> None:
    """An old tag is recoverable only from its own version on the current main lineage."""
    try:
        _git(root, "merge-base", "--is-ancestor", commit, head)
        source = ast.parse(_git(root, "show", f"{commit}:helab/_version.py"))
        values = [ast.literal_eval(node.value) for node in source.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
        if values != [version]:
            raise ValueError("Tagged commit has a different package version")
    except (subprocess.SubprocessError, SyntaxError) as exc:
        raise ValueError("Release commit/version is unavailable or outside the main lineage") from exc


def plan_release(root: Path, version: str, ref: str, release: Draft | None) -> ReleasePlan:
    tags = _git(root, "tag", "-l").splitlines()
    head = _git(root, "rev-parse", "HEAD")
    tag = f"v{version}"
    commit = _git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}") if tag in tags else head
    if release is not None:
        manifest = read_manifest(release.body)
        if manifest is not None and manifest.commit != commit:
            raise ValueError("Draft manifest and tag commit disagree; refusing recovery")
    decision = decide_release(version, tags, ref, completed=release_complete(release, commit))
    if decision.should_release:
        validate_release_commit(root, commit, head, version)
    recovering = decision.should_release and commit != head
    build_ref = f"refs/tags/{tag}" if recovering else ref
    branch = "detached"
    if not recovering:
        if os.environ.get("GITHUB_HEAD_REF"):
            branch = os.environ["GITHUB_HEAD_REF"]
        elif ref.startswith("refs/heads/"):
            branch = ref.removeprefix("refs/heads/")
    return ReleasePlan(decision, commit, commit if decision.should_release else head, build_ref, branch)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    parser.add_argument("--output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    release = (GitHubReleases(args.repository).get_release(f"v{__version__}")
               if args.ref == "refs/heads/main" and args.repository else None)
    plan = plan_release(root, __version__, args.ref, release)
    decision = plan.decision
    values = (f"tag_name={decision.tag}\n"
              f"should_release={str(decision.should_release).lower()}\n"
              f"prerelease={str(decision.prerelease).lower()}\n"
              f"release_sha={plan.release_sha}\nbuild_sha={plan.build_sha}\n"
              f"build_ref={plan.build_ref}\nbuild_branch={plan.build_branch}\n")
    print(f"Package version: {__version__}\n{values}", end="")
    if args.output is not None:
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(values)


if __name__ == "__main__":
    main()
