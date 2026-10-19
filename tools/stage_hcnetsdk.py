#!/usr/bin/env python3
"""Stage an official HCNetSDK Linux64 ZIP without distributing vendor binaries.

The resulting directory is an *opt-in local build input*. Never replace SDK
libraries in a running container or mix components from different releases.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SDK_VERSION = "6.1.11.40"
MAX_ARCHIVE_ENTRIES = 1200
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
REQUIRED = {
    "lib/libhcnetsdk.so", "lib/libHCCore.so", "lib/libhpr.so",
    "lib/libcrypto.so.3", "lib/libssl.so.3", "lib/libPlayCtrl.so",
    "lib/HCNetSDKCom/libHCPreview.so", "lib/HCNetSDKCom/libHCAlarm.so",
    "include/HCNetSDK.h", "include/DataType.h",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sdk_entry(name):
    if "\\" in name or name.startswith("/"):
        raise ValueError("unsafe ZIP member path")
    parts = PurePosixPath(name).parts
    if any(p == ".." for p in parts):
        raise ValueError("unsafe ZIP member path")
    if len(parts) < 3:
        return None
    # Official ZIP contains a single top-level versioned SDK directory.
    if not re.fullmatch(r"EN-HCNetSDKV6\.1\.11\.40_build[0-9]{8}_linux64", parts[0]):
        raise ValueError("unexpected SDK archive root")
    if parts[1] == "lib":
        relative = PurePosixPath(*parts[1:])
        if not (name.endswith(".so") or ".so." in name or name.endswith(".xml")):
            return None
        return relative
    if parts[1] == "incEn" and len(parts) == 3 and parts[2] in {"HCNetSDK.h", "DataType.h"}:
        return PurePosixPath("include", parts[2])
    return None


def _check_elf(data, filename):
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError("non-ELF SDK library: " + filename)
    # ELF64 little-endian x86_64, ET_DYN.
    if data[4:6] != b"\x02\x01" or data[18:20] != b"\x3e\x00":
        raise ValueError("SDK library is not Linux x86-64: " + filename)


def stage_archive(archive, destination, expected_sha256=None):
    archive = Path(archive)
    destination = Path(destination)
    digest = sha256_file(archive)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError("SDK archive SHA-256 mismatch")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be absent or empty; refusing to replace libraries")
    if destination.exists() and not destination.is_dir():
        raise ValueError("destination is not a directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".hcnetsdk-stage-", dir=destination.parent))
    seen = set()
    manifest = {"sdk_version": SDK_VERSION, "architecture": "linux/amd64",
                "archive_sha256": digest, "files": {}}
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES or sum(z.file_size for z in entries) > MAX_EXPANDED_BYTES:
                raise ValueError("SDK archive exceeds safety limits")
            for entry in entries:
                if entry.is_dir():
                    continue
                # Reject symlink and special-file entries, never follow paths.
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise ValueError("ZIP archive contains a special file")
                relative = _sdk_entry(entry.filename)
                if relative is None:
                    continue
                name = relative.as_posix()
                if name in seen or entry.file_size == 0 or entry.file_size > MAX_ENTRY_BYTES:
                    raise ValueError("duplicate or invalid SDK library/header: " + name)
                seen.add(name)
                with bundle.open(entry, "r") as source:
                    data = source.read(MAX_ENTRY_BYTES + 1)
                if len(data) != entry.file_size:
                    raise ValueError("truncated SDK library/header: " + name)
                if name.startswith("lib/") and ".so" in name:
                    _check_elf(data, name)
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(),
                                            "bytes": len(data)}
        missing = REQUIRED - seen
        if missing:
            raise ValueError("SDK archive missing components: " + ", ".join(sorted(missing)))
        library = (temp / "lib/libhcnetsdk.so").read_bytes()
        if b"The HCNetSDK version is 6.1.11.40" not in library:
            raise ValueError("libhcnetsdk.so version is not 6.1.11.40")
        header = (temp / "include/HCNetSDK.h").read_bytes()
        if b"cbLoginResultV40" not in header or b"NET_DVR_Login_V40" not in header:
            raise ValueError("SDK header lacks required V40 ABI definitions")
        (temp / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if destination.exists():
            destination.rmdir()
        os.replace(temp, destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Official Hikvision Linux64 SDK ZIP")
    parser.add_argument("--output", required=True, help="New staging directory")
    parser.add_argument("--sha256", help="Expected SHA-256 of original vendor ZIP")
    args = parser.parse_args()
    try:
        result = stage_archive(args.archive, args.output, args.sha256)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        parser.exit(2, "HCNetSDK import refused: " + str(exc) + "\n")
    print("HCNetSDK %s staged: %d files, original SHA-256 %s" %
          (result["sdk_version"], len(result["files"]), result["archive_sha256"]))


if __name__ == "__main__":
    main()
