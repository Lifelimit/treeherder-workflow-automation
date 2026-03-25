#!/usr/bin/env python3
"""
mock_lando.py — realistic Lando CLI simulator for local testing.

Supports: push-commits, push-merge
Validates required arguments and prints realistic output with delays.

Set LANDO_MOCK_FAIL=1 in the environment to simulate a failure (tests error handling).
"""
import sys
import time
import os

SEP   = "=" * 60
FAIL  = os.environ.get("LANDO_MOCK_FAIL", "0") == "1"

def step(msg, delay=0.4):
    print(msg, flush=True)
    time.sleep(delay)

def err(msg):
    print(f"\n[lando] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)

def parse_args(argv):
    """Return a dict of --key value pairs from argv."""
    args = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:]
            val = argv[i + 1] if i + 1 < len(argv) and not argv[i+1].startswith("--") else True
            args[key] = val
            i += 2 if val is not True else 1
        else:
            i += 1
    return args

def cmd_push_commits(args):
    repo = args.get("lando-repo")
    if not repo:
        err("--lando-repo is required for push-commits")

    print(f"\n{SEP}")
    print(f"[lando] push-commits → {repo}")
    print(SEP)
    step("[lando] Authenticating with Lando server...")
    step("[lando] Fetching commit stack from local repo...")
    step("[lando] Linting commit messages...")
    step("[lando] Checking for merge conflicts with remote...")

    if FAIL:
        print("[lando] ERROR: Commit stack has conflicts with remote tip.", file=sys.stderr)
        sys.exit(1)

    step("[lando] All checks passed.")
    step("[lando] Submitting patch to Phabricator...")
    step("[lando] Triggering CI pipeline on Treeherder...")
    print(f"[lando] ✓ Successfully pushed commits to {repo}!")
    print(f"[lando]   Treeherder: https://treeherder.mozilla.org/#/jobs?repo={repo.replace('firefox-', '')}")
    print(SEP + "\n")

def cmd_push_merge(args):
    repo   = args.get("lando-repo")
    commit = args.get("target-commit")
    msg    = args.get("commit-message")

    if not repo:
        err("--lando-repo is required for push-merge")
    if not commit:
        err("--target-commit is required for push-merge")
    if not msg:
        err("--commit-message is required for push-merge")

    print(f"\n{SEP}")
    print(f"[lando] push-merge → {repo}")
    print(SEP)
    step(f"[lando] Authenticating with Lando server...")
    step(f"[lando] Resolving target commit: {commit}")
    step(f"[lando] Verifying commit exists in source branch...")
    step(f"[lando] Running pre-merge checks...")

    if FAIL:
        print(f"[lando] ERROR: Target commit {commit} not found in source branch.", file=sys.stderr)
        sys.exit(1)

    step(f"[lando] Creating merge commit: \"{msg}\"")
    step(f"[lando] Pushing merge to {repo}...")
    print(f"[lando] ✓ Merge landed successfully on {repo}!")
    print(f"[lando]   Commit  : {commit}")
    print(f"[lando]   Message : {msg}")
    print(SEP + "\n")

# --- Dispatch ---

if len(sys.argv) < 2:
    err("Usage: lando <push-commits|push-merge> [options]")

subcmd = sys.argv[1]
args   = parse_args(sys.argv[2:])

if FAIL:
    print("[lando] ⚠  LANDO_MOCK_FAIL=1 — simulating failure mode", flush=True)
    time.sleep(0.5)

if subcmd == "push-commits":
    cmd_push_commits(args)
elif subcmd == "push-merge":
    cmd_push_merge(args)
else:
    err(f"Unknown subcommand: '{subcmd}'. Expected push-commits or push-merge.")
