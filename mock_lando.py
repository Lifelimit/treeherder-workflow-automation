#!/usr/bin/env python3
import sys
import time

print(f">>> [Mock Lando] Received command: {' '.join(sys.argv)}")
print(">>> [Mock Lando] Simulating push to Lando integration branch...")
time.sleep(1)
print(">>> [Mock Lando] Success! Commits are now in the Lando queue.")
sys.exit(0)
