"""Fetch and verify pinned Windows binaries required by the PyInstaller build."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_SET = "ffmpeg-9.0.2-deno-2.9.5"
ASSET_ROOT = PROJECT_ROOT / ".build-assets"
OUTPUT_ROOT = ASSET_ROOT / ASSET_SET

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip"
FFMPEG_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
DENO_URL = "https://dl.deno.land/release/v2.9.5/deno-x86_64-pc-windows-msvc.zip"
DENO_SHA256 = "171efab55ac6b9881fd53ee4c20f8bf3bb1340ffc618483746909014db12216a"
FFMPEG_LICENSE_URL = "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n9.0.2/COPYING.GPLv3"
DENO_LICENSE_URL = "https://raw.githubusercontent.com/denoland/deno/v2.9.5/LICENSE.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, expected_sha256: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Logovo-Downloads-build-assets"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as file:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                file.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    actual_sha256 = digest.hexdigest()
    if actual_sha256.lower() != expected_sha256.lower():
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual_sha256}"
        )


def download_text(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Logovo-Downloads-build-assets"})
    with urllib.request.urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


def extract_zip_member(
    archive_path: Path,
    expected_name: str,
    destination: Path,
    *,
    parent_name: str | None = None,
) -> None:
    """Copy one uniquely matching ZIP member without extracting arbitrary paths."""
    with zipfile.ZipFile(archive_path) as archive:
        matches = []
        for name in archive.namelist():
            member_path = PurePosixPath(name)
            if member_path.name.casefold() != expected_name.casefold():
                continue
            if parent_name and (len(member_path.parts) < 2 or member_path.parent.name.casefold() != parent_name.casefold()):
                continue
            matches.append(name)

        if len(matches) != 1:
            raise RuntimeError(
                f"Expected exactly one {expected_name} in {archive_path.name}; found {len(matches)}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(matches[0]) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def _existing_assets_are_valid() -> bool:
    manifest_path = OUTPUT_ROOT / "licenses" / "asset-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return all(
            sha256_file(OUTPUT_ROOT / relative_path) == expected_hash
            for relative_path, expected_hash in manifest["files"].items()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare_assets() -> Path:
    if OUTPUT_ROOT.exists():
        if _existing_assets_are_valid():
            print(f"Verified build assets already exist: {OUTPUT_ROOT}")
            return OUTPUT_ROOT
        raise RuntimeError(
            f"Build asset directory exists but is incomplete or modified: {OUTPUT_ROOT}. "
            "Move it aside before preparing a fresh copy; it was not overwritten."
        )

    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="logovo-assets-", dir=ASSET_ROOT) as temp_name:
        temp_root = Path(temp_name)
        ffmpeg_archive = temp_root / "ffmpeg.zip"
        deno_archive = temp_root / "deno.zip"
        stage_root = temp_root / ASSET_SET
        binary_dir = stage_root / "bin"
        license_dir = stage_root / "licenses"
        binary_dir.mkdir(parents=True)
        license_dir.mkdir(parents=True)

        print("Downloading FFmpeg 9.0.2 Essentials archive...")
        download_verified(FFMPEG_URL, FFMPEG_SHA256, ffmpeg_archive)
        print("Downloading Deno 2.9.5 archive...")
        download_verified(DENO_URL, DENO_SHA256, deno_archive)

        extract_zip_member(ffmpeg_archive, "ffmpeg.exe", binary_dir / "ffmpeg.exe", parent_name="bin")
        extract_zip_member(ffmpeg_archive, "ffprobe.exe", binary_dir / "ffprobe.exe", parent_name="bin")
        extract_zip_member(deno_archive, "deno.exe", binary_dir / "deno.exe")

        download_text(FFMPEG_LICENSE_URL, license_dir / "FFmpeg-GPLv3.txt")
        download_text(DENO_LICENSE_URL, license_dir / "Deno-MIT.txt")

        # Preserve the vendor's build details when included in its archive.
        with zipfile.ZipFile(ffmpeg_archive) as archive:
            readmes = [name for name in archive.namelist() if PurePosixPath(name).name.casefold() == "readme.txt"]
            if len(readmes) == 1:
                with archive.open(readmes[0]) as source, (license_dir / "FFmpeg-Build-README.txt").open("wb") as output:
                    shutil.copyfileobj(source, output)

        files = {}
        for relative_path in (Path("bin") / name for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe")):
            files[relative_path.as_posix()] = sha256_file(stage_root / relative_path)
        for license_file in license_dir.iterdir():
            files[license_file.relative_to(stage_root).as_posix()] = sha256_file(license_file)

        manifest = {
            "asset_set": ASSET_SET,
            "archives": {
                "ffmpeg": {"url": FFMPEG_URL, "sha256": FFMPEG_SHA256},
                "deno": {"url": DENO_URL, "sha256": DENO_SHA256},
            },
            "files": files,
        }
        (license_dir / "asset-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        stage_root.rename(OUTPUT_ROOT)

    print(f"Verified build assets prepared in: {OUTPUT_ROOT}")
    return OUTPUT_ROOT


if __name__ == "__main__":
    try:
        prepare_assets()
    except Exception as error:
        raise SystemExit(f"Could not prepare build assets: {error}") from error
