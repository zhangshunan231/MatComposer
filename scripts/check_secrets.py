# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors
"""Reject recognizable credentials without printing their values."""

import argparse
import re
import subprocess


PATTERN = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    rb"github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,}|"
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def candidates(all_history):
    if all_history:
        rows = subprocess.check_output(["git", "rev-list", "--objects", "--all"])
        for row in rows.splitlines():
            oid, _, path = row.partition(b" ")
            yield oid, path.decode("utf-8", errors="replace") or "commit/tag metadata"
    else:
        rows = subprocess.check_output(["git", "ls-files", "--stage", "-z"])
        for row in rows.split(b"\0"):
            if not row:
                continue
            info, path = row.split(b"\t", 1)
            mode, oid, stage = info.split()
            if mode != b"160000":
                yield oid, path.decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-history", action="store_true", help="Scan all reachable Git history")
    parser.add_argument("--staged", action="store_true", help="Scan the index (default)")
    args = parser.parse_args()
    if args.staged and args.all_history:
        parser.error("choose either --staged or --all-history")
    objects = dict(candidates(args.all_history))
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    failures = []
    try:
        for oid, label in objects.items():
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3:
                raise RuntimeError("Could not read Git object during credential scan")
            _, kind, size = header
            data = process.stdout.read(int(size))
            if process.stdout.read(1) != b"\n":
                raise RuntimeError("Incomplete Git object during credential scan")
            if kind in (b"blob", b"commit", b"tag") and PATTERN.search(data):
                failures.append(label)
    finally:
        process.stdin.close()
        process.stdout.close()
        result = process.wait()
    if result:
        raise SystemExit("Git object scan failed")
    if failures:
        for label in sorted(set(failures)):
            print(f"BLOCKED: possible credential in {label}")
        raise SystemExit(1)
    print(f"Credential scan passed ({len(objects)} objects).")


if __name__ == "__main__":
    main()
