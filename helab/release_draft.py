"""Validate release archives and resume owned assets on an unpublished GitHub draft."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Protocol, cast
from urllib.parse import quote
import zipfile

ASSET_NAMES = ("HeLab-macos.zip", "HeLab-windows.zip", "HeLab-ubuntu.zip")


def release_name(tag: str) -> str:
    """The name CI gives a release (how ``get_release`` knows its draft, listed as "untagged-…")."""
    return f"Automated Release {tag}"
MARKER = re.compile(r"<!-- helab-release-manifest:(.*?) -->", re.DOTALL)


@dataclass(frozen=True)
class Asset:
    id: int
    name: str
    size: int
    state: str
    digest: str | None


@dataclass(frozen=True)
class Draft:
    id: int
    draft: bool
    body: str
    assets: tuple[Asset, ...]


@dataclass(frozen=True)
class Fingerprint:
    size: int
    digest: str


@dataclass(frozen=True)
class Manifest:
    commit: str
    assets: dict[str, Fingerprint]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, object], value)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Expected an integer")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def read_manifest(body: str) -> Manifest | None:
    match = MARKER.search(body)
    if match is None:
        return None
    data = _object(json.loads(match.group(1)))
    commit = _string(data.get("commit"))
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("Invalid release commit in manifest")
    entries = _object(data.get("assets"))
    assets: dict[str, Fingerprint] = {}
    for name, value in entries.items():
        entry = _object(value)
        size, digest = _integer(entry.get("size")), _string(entry.get("digest"))
        if name not in ASSET_NAMES or size <= 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Invalid release asset manifest")
        assets[name] = Fingerprint(size, digest)
    return Manifest(commit, assets)


def manifest_body(body: str, manifest: Manifest) -> str:
    data = {"commit": manifest.commit, "assets": {
        name: {"size": item.size, "digest": item.digest} for name, item in manifest.assets.items()
    }}
    return MARKER.sub("", body).rstrip() + "\n\n<!-- helab-release-manifest:" + json.dumps(data, sort_keys=True) + " -->\n"


def asset_matches(asset: Asset, expected: Fingerprint) -> bool:
    return (asset.state == "uploaded" and asset.size == expected.size and asset.size > 0
            and asset.digest == expected.digest)


def release_complete(release: Draft | None, commit: str) -> bool:
    if release is None:
        return False
    # Published releases are immutable to this workflow, including published alphas.
    if not release.draft:
        return True
    manifest = read_manifest(release.body)
    if manifest is None or manifest.commit != commit:
        return False
    for name in ASSET_NAMES:
        assets = [asset for asset in release.assets if asset.name == name]
        if name not in manifest.assets or len(assets) != 1 or not asset_matches(assets[0], manifest.assets[name]):
            return False
    return True


def validate_archives(artifacts: dict[str, Path], tag: str, commit: str) -> dict[str, Fingerprint]:
    if set(artifacts) != set(ASSET_NAMES):
        raise ValueError("All three platform archives are required")
    result: dict[str, Fingerprint] = {}
    for name, path in artifacts.items():
        with zipfile.ZipFile(path) as archive:
            stamps = [item for item in archive.namelist() if item.endswith("/helab/_build_info.json")]
            if not stamps:
                raise ValueError(f"{name} has no packaged build stamp")
            for stamp in stamps:
                data = _object(json.loads(archive.read(stamp)))
                if data.get("version") != tag.removeprefix("v") or data.get("commit") != commit or data.get("dirty") is not False:
                    raise ValueError(f"{name} was not built cleanly from the release version/commit")
        with path.open("rb") as stream:
            digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        result[name] = Fingerprint(path.stat().st_size, digest)
    return result


class ReleaseAPI(Protocol):
    def get_release(self, tag: str) -> Draft | None: ...
    def verify_tag(self, tag: str, commit: str) -> None: ...
    def create(self, tag: str, commit: str, prerelease: bool, body: str) -> Draft: ...
    def save_body(self, release_id: int, body: str, prerelease: bool) -> None: ...
    def delete_asset(self, asset_id: int) -> None: ...
    def upload(self, release_id: int, name: str, path: Path) -> None: ...


def _guard(api: ReleaseAPI, tag: str, commit: str, release_id: int) -> Draft:
    api.verify_tag(tag, commit)
    release = api.get_release(tag)
    if release is None or release.id != release_id or not release.draft:
        raise ValueError("Draft was replaced, removed or published; refusing to modify it")
    manifest = read_manifest(release.body)
    if manifest is not None and manifest.commit != commit:
        raise ValueError("Draft manifest and tag commit disagree")
    return release


def publish_draft(api: ReleaseAPI, tag: str, commit: str, prerelease: bool,
                  artifacts: dict[str, Path], body: str) -> None:
    fingerprints = validate_archives(artifacts, tag, commit)
    api.verify_tag(tag, commit)
    release = api.get_release(tag)
    if release is not None and not release.draft:
        return
    if release is None:
        release = api.create(tag, commit, prerelease, manifest_body(body, Manifest(commit, fingerprints)))
    for name in ASSET_NAMES:
        release = _guard(api, tag, commit, release.id)
        manifest = read_manifest(release.body)
        existing = [asset for asset in release.assets if asset.name == name]
        if manifest is not None and name in manifest.assets and len(existing) == 1 and asset_matches(existing[0], manifest.assets[name]):
            continue  # Preserve verified assets from an earlier attempt, even after a rebuild.
        entries = {} if manifest is None else dict(manifest.assets)
        entries[name] = fingerprints[name]
        api.save_body(release.id, manifest_body(release.body, Manifest(commit, entries)), prerelease)
        for asset in existing:
            _guard(api, tag, commit, release.id)
            api.delete_asset(asset.id)
        _guard(api, tag, commit, release.id)
        api.upload(release.id, name, artifacts[name])
        verified = _guard(api, tag, commit, release.id)
        if not any(asset.name == name and asset_matches(asset, fingerprints[name]) for asset in verified.assets):
            raise ValueError(f"Uploaded {name} did not match its expected size/digest")
    if not release_complete(_guard(api, tag, commit, release.id), commit):
        raise ValueError("Draft upload remains incomplete")


class GitHubReleases:
    """GitHub CLI handles archive uploads; API/read failures never mean missing release."""

    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected owner/repository")
        self.repository = repository

    def _request(self, method: str, endpoint: str, payload: dict[str, object] | None = None,
                 file: Path | None = None) -> object:
        command = ["gh", "api", "--method", method, endpoint]
        if payload is not None:
            command += ["--input", "-"]
        if file is not None:
            command += ["--input", str(file), "--header", "Content-Type: application/zip"]
        response = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                  text=True, capture_output=True, check=True, timeout=300)
        return json.loads(response.stdout) if response.stdout.strip() else None

    def _pages(self, endpoint: str) -> list[object]:
        entries: list[object] = []
        page = 1
        while True:
            result = self._request("GET", f"{endpoint}?per_page=100&page={page}")
            if not isinstance(result, list):
                raise ValueError("Expected paginated API list")
            entries.extend(result)
            if len(result) < 100:
                return entries
            page += 1

    def _draft(self, value: object) -> Draft:
        data = _object(value)
        release_id = _integer(data.get("id"))
        draft = data.get("draft")
        if not isinstance(draft, bool):
            raise ValueError("Missing release draft state")
        assets: list[Asset] = []
        for entry in self._pages(f"repos/{self.repository}/releases/{release_id}/assets"):
            item = _object(entry)
            digest = item.get("digest")
            if digest is not None and not isinstance(digest, str):
                raise ValueError("Invalid asset digest")
            assets.append(Asset(_integer(item.get("id")), _string(item.get("name")),
                                _integer(item.get("size")), _string(item.get("state")), digest))
        return Draft(release_id, draft, _string(data.get("body") or ""), tuple(assets))

    def get_release(self, tag: str) -> Draft | None:
        # Listing with push-capable authentication includes drafts; by-tag lookup
        # is documented for published releases and must not be used as an absence test.
        # GitHub lists a draft under "untagged-<hash>" rather than its tag (v0.0.5a1 and
        # v0.0.6a1 stopped right after creating theirs), so a draft also matches by its name.
        def ours(item: object) -> bool:
            data = _object(item)
            if data.get("tag_name") == tag:
                return True
            return (data.get("draft") is True and str(data.get("tag_name", "")).startswith("untagged-")
                    and data.get("name") == release_name(tag))
        matches = [item for item in self._pages(f"repos/{self.repository}/releases") if ours(item)]
        if len(matches) > 1:
            raise ValueError("Multiple releases use this tag; resolve them manually")
        return self._draft(matches[0]) if matches else None

    def verify_tag(self, tag: str, commit: str) -> None:
        data = _object(self._request("GET", f"repos/{self.repository}/git/ref/tags/{quote(tag, safe='')}"))
        obj = _object(data.get("object"))
        for _ in range(8):
            if obj.get("type") == "commit":
                if obj.get("sha") != commit:
                    raise ValueError("Remote tag points to another commit")
                return
            if obj.get("type") != "tag":
                break
            data = _object(self._request("GET", f"repos/{self.repository}/git/tags/{_string(obj.get('sha'))}"))
            obj = _object(data.get("object"))
        raise ValueError("Release tag does not resolve to a commit")

    def create(self, tag: str, commit: str, prerelease: bool, body: str) -> Draft:
        return self._draft(self._request("POST", f"repos/{self.repository}/releases", {
            "tag_name": tag, "target_commitish": commit, "draft": True,
            "prerelease": prerelease, "name": release_name(tag), "body": body,
        }))

    def save_body(self, release_id: int, body: str, prerelease: bool) -> None:
        self._request("PATCH", f"repos/{self.repository}/releases/{release_id}",
                      {"body": body, "prerelease": prerelease})

    def delete_asset(self, asset_id: int) -> None:
        self._request("DELETE", f"repos/{self.repository}/releases/assets/{asset_id}")

    def upload(self, release_id: int, name: str, path: Path) -> None:
        endpoint = f"https://uploads.github.com/repos/{self.repository}/releases/{release_id}/assets?name={quote(name, safe='')}"
        self._request("POST", endpoint, file=path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--prerelease", choices=["true", "false"], default="true")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--body", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    artifacts = {name: args.artifacts / name for name in ASSET_NAMES}
    if args.validate_only:
        validate_archives(artifacts, args.tag, args.commit)
    else:
        if not args.repository or args.body is None:
            parser.error("--repository and --body are required when uploading")
        publish_draft(GitHubReleases(args.repository), args.tag, args.commit,
                      args.prerelease == "true", artifacts, args.body.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
