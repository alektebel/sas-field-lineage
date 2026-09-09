#!/usr/bin/env python3
"""
Fetch real-world SAS program files from public GitHub repos for stress testing.

Uses the GitHub API (via the authenticated `gh` CLI) to list *.sas files in a
set of public repos, then downloads the largest files as a corpus. Meant for
local stress-testing the lineage explorer against realistic, non-trivial SAS —
clinical/regulatory, public-health and analytics SAS that model real data flow.

Output: files under <out_dir>, plus a JSON summary.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# owner/repo -> (max_files, note)
REPOS = {
    "HHS-AHRQ/MEPS": (8, "US medical expenditure public-health SAS (real health data analysis)"),
    "phuse-org/phuse-scripts": (8, "Clinical trial / CDISC SDTM-ADaM SAS (regulatory data lineage)"),
    "wyp1125/SAS-Clinical-Trials-Toolkit": (6, "Clinical trials SAS scripts"),
    "friendly/SAS-macros": (5, "SAS statistical/graphics macros"),
    "sassoftware/enlighten-apply": (5, "SAS Viya applied analytics examples"),
    "sascommunities/sas-prog-for-r-users": (4, "SAS-for-R teaching programs"),
}


def gh_json(args: list[str]) -> dict:
    res = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh api failed: {res.stderr.strip()}")
    return json.loads(res.stdout)


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def fetch_repo(owner_repo: str, max_files: int, out_dir: Path, summary: list) -> int:
    owner, repo = owner_repo.split("/")
    tree = gh_json([f"/repos/{owner_repo}/git/trees/HEAD?recursive=1"])
    blobs = [t for t in tree.get("tree", []) if t.get("type") == "blob" and t["path"].lower().endswith(".sas")]
    # Prefer bigger programs: they exercise deeper lineage and more fields.
    blobs.sort(key=lambda b: b.get("size", 0), reverse=True)
    blobs = blobs[:max_files]
    saved = 0
    for b in blobs:
        path = b["path"]
        fname = sanitize(owner + "__" + repo + "__" + path.replace("/", "_"))
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
        dest = out_dir / fname
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sas-lineage-stress"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            dest.write_bytes(data)
            saved += 1
            summary.append({
                "repo": owner_repo, "path": path, "file": fname,
                "bytes": len(data), "lines": data.count(b"\n"),
                "url": f"https://github.com/{owner}/{repo}/blob/{path}",
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {path}: {exc}", file=sys.stderr)
    print(f"  {owner_repo}: saved {saved}/{len(blobs)} .sas files")
    return saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/opencode/sas_corpus", help="Output directory")
    ap.add_argument("--repo", action="append", help="Override repos (owner/repo[:max])")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repos = dict(REPOS)
    if args.repo:
        repos = {}
        for spec in args.repo:
            owner_repo, _, mx = spec.rpartition(":")
            repos[owner_repo or spec] = (int(mx) if mx else 5, "user-specified")

    summary = []
    total = 0
    for owner_repo, (max_files, note) in repos.items():
        print(f"== {owner_repo}  ({note})")
        try:
            total += fetch_repo(owner_repo, max_files, out_dir, summary)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {owner_repo}: {exc}", file=sys.stderr)

    meta = {"count": len(summary), "bytes": sum(s["bytes"] for s in summary), "files": summary}
    (out_dir / "index.json").write_text(json.dumps(meta, indent=2))
    print(f"\nFetched {len(summary)} files, {meta['bytes']:,} bytes total -> {out_dir}")


if __name__ == "__main__":
    main()
