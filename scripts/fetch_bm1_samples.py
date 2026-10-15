"""Fetch the BM1 real-malware samples as encrypted zips (never extracted).

    python scripts/fetch_bm1_samples.py [DEST] [--dry-run] [--list-members]

DEST defaults to BENCH_MALWARE_DIR and must be outside the repo. Each sample in
tests/bench/fixtures/bm1-samples.json is downloaded from the DataDog dataset at
the pinned commit, checked against its git blob hash and written unchanged: the
zips stay encrypted (password "infected"), so nothing malicious is readable on
disk until the BM1 adapter decrypts one into a scratch dir for a scan. Nothing
is installed or run. --list-members prints each zip's file names, which zip
keeps unencrypted, without decrypting anything.
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_FILE = REPO_ROOT / "tests" / "bench" / "fixtures" / "bm1-samples.json"
TIMEOUT_S = 60


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _sample_url(source: dict, sample: dict) -> str:
    package_dir = sample["name"].replace("/", "@")
    return (
        f"https://raw.githubusercontent.com/{source['repo']}/{source['commit']}"
        f"/samples/npm/{sample['kind']}/{package_dir}/{sample['version']}/{sample['file']}"
    )


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _fetch_one(source: dict, sample: dict, dest: Path) -> str:
    target = dest / sample["file"]
    if target.exists() and _git_blob_sha(target.read_bytes()) == sample["git_sha"]:
        return "cached"
    response = httpx.get(_sample_url(source, sample), timeout=TIMEOUT_S)
    response.raise_for_status()
    data = response.content
    actual = _git_blob_sha(data)
    if actual != sample["git_sha"]:
        raise ValueError(f"hash mismatch for {sample['file']}: {actual} != {sample['git_sha']}")
    target.write_bytes(data)
    return "fetched"


def _list_members(path: Path) -> None:
    # Reads the central directory only; encrypted member contents are never touched.
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        encrypted = sum(1 for info in archive.infolist() if info.flag_bits & 0x1)
    print(f"  {len(names)} members ({encrypted} encrypted); first: {', '.join(names[:5])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "dest", type=Path, nargs="?", default=os.environ.get("BENCH_MALWARE_DIR") or None
    )
    parser.add_argument("--dry-run", action="store_true", help="print the URLs, download nothing")
    parser.add_argument(
        "--list-members", action="store_true", help="list file names inside each fetched zip"
    )
    args = parser.parse_args()

    if args.dest is None:
        parser.error("pass DEST or set BENCH_MALWARE_DIR")
    dest = Path(args.dest).resolve()
    if _is_inside(dest, REPO_ROOT):
        parser.error(f"{dest} is inside the repo; malware samples must live outside it")

    corpus = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    source, samples = corpus["source"], corpus["samples"]
    if args.dry_run:
        for sample in samples:
            print(_sample_url(source, sample))
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    failures = 0
    for sample in samples:
        label = f"{sample['kind']:<16} {sample['name']}@{sample['version']}"
        try:
            status = _fetch_one(source, sample, dest)
        except (OSError, ValueError, httpx.HTTPError) as exc:
            failures += 1
            print(f"FAIL {label}: {exc}", file=sys.stderr)
            continue
        print(f"{status:<7} {label}")
        if args.list_members:
            _list_members(dest / sample["file"])

    # Copy the labels next to the samples so BENCH_MALWARE_DIR is self-describing.
    (dest / "manifest.json").write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    print(f"{len(samples) - failures}/{len(samples)} samples in {dest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
