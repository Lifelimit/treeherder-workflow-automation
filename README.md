# Treeherder Workflow Automation Tool

A self-contained desktop GUI for Firefox Treeherder development workflows — reverting, cherry-picking, landing patches via Mozilla's Lando service, and managing WPT metadata.

## Core Features

- 🌓 **Automatic Light/Dark Theme** — Reads your OS system preference (macOS, Windows, Linux).
- 📺 **Streaming Terminal** — Real-time subprocess output with colored highlights, searchable logs, and link detection for Phabricator/Bugzilla.
- 📦 **Batch Accumulation Mode** — Keep multiple commits (reverts, cherry-picks, lint fixes) locally and push them all at once via the "Lando Push" button.
- 🛠️ **Environment Utilities** — One-click `pipx` installation and a system check tool to ensure all dependencies are ready.
- 🚀 **Lando Integration** — `push-commits`, `push-merge`, and `merge-back` workflows built-in.
- 🧹 **Linting Fixers** — Run `mach lint` (Prettier, Black, Whitespace) with automated `--fix` directly from the UI.
- 🍱 **WPT Metadata Editor** — Quickly update Web Platform Test metadata for single tests or batch-process a list from a file.

## Requirements

- **Python 3.10+** (included with macOS/Linux)
- **Git** (for repository operations)
- **Lando CLI** (can be installed via the "Utilities" tab)
- **Firefox Clone** (mozilla-central, autoland, etc.)

## Usage

```bash
python3 treeherder_app.py
```

1. Launch the app.
2. Click **"Browse..."** to select your local Firefox repository root.
3. Use the **Utilities > Check System** button to verify your environment.
4. Go! All actions are logged in the terminal with context-aware shortcuts.

## Workflows

| Category | Actions |
|---|---|
| **Git & Repo** | Fetch, Pull, Branch Switch, Sync Lando CLI |
| **Lando Flow** | Push all local commits at once, or merge changesets between Main and Autoland. |
| **Reverts** | Single Revert (with reason), Multiple Revert (interactive rebase) |
| **Linting** | Prettier --fix, Black --fix, Whitespace --fix |
| **WPT** | Update Metadata, Batch Process Test List |
| **Utilities** | System Check, Install Pipx, Lando Sync |
