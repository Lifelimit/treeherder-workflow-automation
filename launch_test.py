#!/usr/bin/env python3
"""
Launch treeherder_app.py pre-configured for local test mode:
  - Repo path set to the local firefox-test-repo
  - mock_lando.py injected onto PATH as 'lando'
  - Active branch pre-set to 'main'

Run: python3 launch_test.py
"""
import os
import sys
import subprocess
import pathlib

SCRIPT_DIR  = pathlib.Path(__file__).parent.resolve()
TEST_REPO   = SCRIPT_DIR.parent / "firefox-test-repo"
APP_SCRIPT  = SCRIPT_DIR / "treeherder_app.py"
MOCK_LANDO  = SCRIPT_DIR / "mock_lando.py"

if not TEST_REPO.exists():
    print(f"ERROR: test repo not found at {TEST_REPO}")
    sys.exit(1)

# Inject a 'lando' shim on PATH via a temp dir
import tempfile, stat

tmpbin = pathlib.Path(tempfile.mkdtemp())
shim   = tmpbin / "lando"
shim.write_text(
    f"#!/bin/sh\npython3 \"{MOCK_LANDO}\" \"$@\"\n"
)
shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

env = os.environ.copy()
env["PATH"] = str(tmpbin) + os.pathsep + env.get("PATH", "")

# Pass the test-repo path + branch via env vars the app will read
env["TREEHERDER_TEST_REPO"]   = str(TEST_REPO)
env["TREEHERDER_TEST_BRANCH"] = "main"

print(f"[TEST LAUNCHER] Repo  : {TEST_REPO}")
print(f"[TEST LAUNCHER] Branch: main")
print(f"[TEST LAUNCHER] lando : {shim}  →  mock_lando.py")
print()

subprocess.run([sys.executable, str(APP_SCRIPT)], env=env)
