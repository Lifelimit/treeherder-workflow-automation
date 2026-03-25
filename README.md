# Treeherder Workflow Automation Tool

A self-contained desktop GUI for Firefox Treeherder development workflows — reverting, cherry-picking, and landing patches via Mozilla's Lando service.

## Features

- 🌗 **Automatic Light/Dark theme** — reads your OS system preference (macOS, Windows, Linux)
- 🔀 **Branch switching** — dropdown auto-runs `git switch <branch>`
- 📋 **Context-aware popups** — every action prompts only for what it needs
- 📺 **Streaming terminal** — real-time subprocess output with coloured highlights
- 🚀 **Lando integration** — push-commits and push-merge workflows built-in

## Requirements

- Python 3.10+
- `git` available on `PATH`
- `lando` CLI available on `PATH`
- No external Python packages needed (stdlib only)

## Usage

```bash
python3 treeherder_app.py
```

Set the **Firefox Repo Path** browser to your local Firefox clone. All `git` and `lando` commands will run inside that directory.

## Workflows

| Button | Action |
|---|---|
| Git Fetch | `git fetch` |
| Git Pull | `git pull` |
| Single Revert | Pull → revert hash → amend message with reason → lando push-commits |
| Multiple Revert | Pull → revert range → interactive rebase squash → lando push-commits |
| Cherry-Pick | Pull → cherry-pick → lando push-commits |
| Lando Merge | `lando push-merge` between main ↔ autoland |
| Lando Merge Back | `lando push-merge` main → autoland |
| Lando Push | `lando push-commits` on the active branch |
