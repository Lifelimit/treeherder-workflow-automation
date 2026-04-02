#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import queue
import os
import sys
import tempfile
import textwrap
import platform
import json
import webbrowser
import re
import time
import datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# System theme detection
# ---------------------------------------------------------------------------

def is_dark_mode() -> bool:
    """Return True if the OS is currently using a dark appearance."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True
            )
            return result.stdout.strip().lower() == "dark"
        elif system == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return val == 0
        else:  # Linux / fallback
            # Try gsettings (GNOME)
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            return "dark" in result.stdout.lower()
    except Exception:
        return True   # default to dark if detection fails


# ---------------------------------------------------------------------------
# Theme palettes
# ---------------------------------------------------------------------------

def build_theme(dark: bool) -> dict:
    if dark:
        return dict(
            bg="#121212",           # Deeper/Muted background
            bg2="#1e1e1e",          # Surface color
            bg3="#333333",
            bg_active="#3d3d3d",
            fg="#e0e0e0",           # Off-white for less eye-strain
            fg_btn="#ffffff",
            fg_disabled="#555555",
            term_bg="#000000",
            term_fg="#d4d4d4",
            err_fg="#f38ba8",       # Softer red
            ok_fg="#a6e3a1",        # Softer green
            info_fg="#89b4fa",       # Softer blue
            dim_fg="#7f849c",
            # Professional muted buttons
            git_btn="#1c5d99",      # Deeper Business Blue
            git_hover="#2b7fd1",    # Lighter for highlight
            lando_btn="#1a5d1a",    # Deeper Forest Green
            lando_hover="#288d28",   # Lighter for highlight
            revert_btn="#a42e01",   # Burnt Orange/Red
            revert_hover="#cd3a01",  # Lighter for highlight
            wpt_btn="#452c63",      # Deep Purple
            wpt_hover="#64408f",     # Lighter for highlight
            lint_btn="#008b8b",     # Teal
            lint_hover="#00b3b3",    # Lighter for highlight
            btn_fg="#ffffff",
        )
    else:
        return dict(
            bg="#f8f9fa",           # Clean Google-style light bg
            bg2="#ffffff",
            bg3="#e9ecef",
            bg_active="#dee2e6",
            fg="#212529",
            fg_btn="#212529",
            fg_disabled="#adb5bd",
            term_bg="#ffffff",
            term_fg="#212529",
            err_fg="#dc3545",
            ok_fg="#28a745",
            info_fg="#007bff",
            dim_fg="#6c757d",
            git_btn="#1976D2",      # Softer Material Blue
            git_hover="#42a5f5",    # Lighter highlight
            lando_btn="#2E7D32",    # Softer Material Green
            lando_hover="#66bb6a",   # Lighter highlight
            revert_btn="#D84315",   # Deeper burnt orange
            revert_hover="#ff7043",  # Lighter highlight
            wpt_btn="#6A1B9A",      # Softer Muted Purple
            wpt_hover="#ab47bc",     # Lighter highlight
            lint_btn="#00838F",     # Professional Dark Teal
            lint_hover="#26c6da",    # Lighter highlight
            btn_fg="#ffffff",
        )


# ---------------------------------------------------------------------------
# Tooltip Helper
# ---------------------------------------------------------------------------

class Tooltip:
    """Helper to show hover tooltips for any widget."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window: Optional[tk.Toplevel] = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hide_tip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.show_tip)

    def unschedule(self):
        id_val = self.id
        self.id = None
        if id_val:
            self.widget.after_cancel(id_val)

    def show_tip(self):
        if not self.widget.winfo_exists(): return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        # Determine tooltip theme based on app's current theme (via widget Master)
        bg = "#333333" if getattr(self.widget.master, "_dark", True) else "#ffffff"
        fg = "#ffffff" if getattr(self.widget.master, "_dark", True) else "#333333"

        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background=bg, foreground=fg, relief=tk.SOLID, borderwidth=1,
                         font=("Helvetica", 10, "normal"), padx=6, pady=4)
        label.pack(ipadx=1)

    def hide_tip(self):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class TreeherderTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Treeherder Workflow Automation Tool")
        
        # Center window on screen
        w, h = 900, 720
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int((sw - w) / 2)
        y = int((sh - h) / 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(800, 600)

        # Pop to front on startup
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False) if self.winfo_exists() else None)
        self.lift()
        self.focus_force()

        self._dark = is_dark_mode()
        self.T = build_theme(self._dark)

        self.configure(bg=self.T["bg"])
        self.process_queue: queue.Queue[Any] = queue.Queue()
        self.is_running_command = False
        self.btn_widgets = []
        
        # Initialize UI variables and widgets to avoid AttributeError/Lints
        self.repo_var: tk.StringVar = tk.StringVar()
        self.branch_var: tk.StringVar = tk.StringVar()
        self.branch_dropdown: ttk.Combobox = None # type: ignore
        self.status_var: tk.StringVar = tk.StringVar()
        self.status_label: tk.Label = None # type: ignore
        self.terminal: tk.Text = None # type: ignore
        self.search_var: tk.StringVar = tk.StringVar()
        self.search_entry: tk.Entry = None # type: ignore
        self.progress: ttk.Progressbar = None # type: ignore
        self._popup_result: Any = None
        self._search_current_idx: str = "1.0"
        self._wpt_text: tk.Text = None # type: ignore
        
        # Feature: Undo Last Workflow
        self._last_workflow_head: str | None = None
        
        # Feature: Status Bar Timer
        self._workflow_start_time: float | None = None
        self._timer_label: tk.Label = None # type: ignore
        self._timer_after_id: str | None = None
        
        # Feature: Recent Hashes
        self._recent_hashes: list[str] = []
        
        # Feature: Theme toggle
        self._theme_toggle_label: tk.Label = None # type: ignore
        self._lando_push_btn: tk.Label = None # type: ignore

        # Load persistent config
        self._load_config()

        self.setup_ui()
        self.check_queue()
        # Check for stuck git state a moment after the window is ready
        self.after(500, self._startup_git_check) # type: ignore
        self.after(600, self._update_git_status) # type: ignore
        # Feature: Auto-fetch on startup
        self.after(700, self._auto_fetch) # type: ignore

    def setup_ui(self):
        T = self.T
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=T["bg"], foreground=T["fg"])
        
        # --- FIX: Explicitly flatten LabelFrame borders on startup ---
        style.configure("TLabelframe", background=T["bg"], bordercolor=T["bg3"], 
                        lightcolor=T["bg3"], darkcolor=T["bg3"], relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=T["bg"], foreground=T["dim_fg"], font=("Helvetica", 10, "bold"))
        # -------------------------------------------------------------

        style.configure(
            "TButton",
            background=T["bg3"], foreground=T["fg_btn"],
            font=("Helvetica", 10, "bold"), borderwidth=1, focuscolor="none"
        )
        style.map(
            "TButton",
            background=[("active", T["bg_active"]), ("disabled", T["bg2"])],
            foreground=[("disabled", T["fg_disabled"])]
        )
        self.bind_class("TButton", "<Enter>", lambda e: e.widget.config(cursor="hand2")) # type: ignore
        style.configure(
            "TCombobox",
            fieldbackground=T["bg2"], background=T["bg3"],
            foreground=T["fg"], arrowcolor=T["fg"]
        )
        style.map("TCombobox", fieldbackground=[("readonly", T["bg2"])])

        main = tk.Frame(self, bg=T["bg"])
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ---- Repo + Branch row ----
        top = tk.Frame(main, bg=T["bg"])
        top.pack(fill=tk.X, pady=(0, 14))

        tk.Label(top, text="Firefox Repo Path:", bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11)).pack(side=tk.LEFT, padx=(0, 8))

        default_repo = os.getcwd()
        self.repo_var = tk.StringVar(value=default_repo)
        self.repo_var.trace_add("write", lambda n, i, m: self._save_repo_path(self.repo_var.get()))

        tk.Entry(top, textvariable=self.repo_var, bg=T["bg2"], fg=T["fg"],
                 insertbackground=T["fg"], font=("Helvetica", 11),
                 relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=4)

        def browse_repo():
            d = filedialog.askdirectory(initialdir=self.repo_var.get(),
                                        title="Select Firefox Repository")
            if d:
                self.repo_var.set(d)

        browse_btn = ttk.Button(top, text="Browse…", command=browse_repo)
        browse_btn.pack(side=tk.LEFT, padx=(0, 20))
        Tooltip(browse_btn, "Select the Firefox repository root directory.")

        tk.Label(top, text="Active Branch:", bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11)).pack(side=tk.LEFT, padx=(0, 8))
                 
        # Auto-detect real local branch to perfectly sync with filesystem
        try:
            curr = subprocess.check_output(
                ["git", "branch", "--show-current"], 
                cwd=self.repo_var.get(), text=True, stderr=subprocess.DEVNULL
            ).strip()
            initial_branch = curr if curr else "autoland"
        except Exception:
            initial_branch = "autoland"
            
        self.branch_var = tk.StringVar(value=initial_branch)
        self.branch_dropdown = ttk.Combobox(
            top, textvariable=self.branch_var,
            values=["autoland", "main", "beta", "release", "esr140", "esr115"],
            state="readonly", width=12, font=("Helvetica", 11)
        )
        self.branch_dropdown.pack(side=tk.LEFT, padx=8)
        self.branch_dropdown.bind("<<ComboboxSelected>>", self.on_branch_change)
        Tooltip(self.branch_dropdown, "Select the active local branch to target.")
        
        # Disable accidental mouse scroll
        def disable_scroll(event):
            return "break"
        self.branch_dropdown.bind("<MouseWheel>", disable_scroll)
        self.branch_dropdown.bind("<Button-4>", disable_scroll)
        self.branch_dropdown.bind("<Button-5>", disable_scroll)

        self.status_var = tk.StringVar(value="Status: ?")
        self.status_label = tk.Label(top, textvariable=self.status_var, bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 11, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=12)

        # Feature: Dark/Light mode toggle
        toggle_text = "☀️ Light" if self._dark else "🌙 Dark"
        self._theme_toggle_label = tk.Label(top, text=toggle_text, bg=T["bg3"], fg=T["fg"],
                                            font=("Helvetica", 10, "bold"), padx=8, pady=2, relief=tk.FLAT, cursor="hand2")
        self._theme_toggle_label.pack(side=tk.RIGHT, padx=4)
        self._theme_toggle_label.bind("<Button-1>", lambda e: self._toggle_theme())
        self._theme_toggle_label.bind("<Enter>", lambda e: self._theme_toggle_label.config(bg=self.T["bg_active"]))
        self._theme_toggle_label.bind("<Leave>", lambda e: self._theme_toggle_label.config(bg=self.T["bg3"]))
        Tooltip(self._theme_toggle_label, "Switch between Dark and Light mode (CMD+D).")

        # Define categorized button groups
        groups = [
            ("Git & Repo", [
                ("Git Fetch",      self.do_fetch, "Download objects and refs from another repository."),
                ("Git Pull",       self.do_pull, "Fetch from and integrate with another repository or local branch."),
                ("Git Hard Reset", self.do_hard_reset, "Reset current HEAD (WARNING: discards local changes)."),
                ("Revert Last Action", self.do_undo_last, "Revert the most recent repository change using git reflog."),
                ("View Git Log",   self.do_view_log, "Show commit logs for the current branch."),
            ]),
            ("Lando Flow", [
                ("Cherry-Pick",      self.do_cherry_pick, "Apply changes introduced by some existing commits."),
                ("Lando Merge",      self.do_merge, "Merge specific changesets from the source repository into the target destination."),
                ("Lando Merge Back", self.do_push_merge_back, "Push a merge back to the integration branch."),
                ("Lando Push",       self.do_lando_push, "Directly push to the current active branch."),
            ]),
            ("Reverts", [
                ("Single Revert",    self.do_single_revert, "Create a revert commit for a single revision."),
                ("Multiple Revert",  self.do_multiple_reverts, "Create revert commits for a range of revisions."),
            ]),
            ("Linting", [
                ("Prettier Fix",     self.do_lint_prettier, "Run Prettier linter with --fix on specified paths."),
                ("Whitespace Fix",   self.do_lint_whitespace, "Run Whitespace linter with --fix on specified paths."),
                ("Black Fix",        self.do_lint_black, "Run Black linter with --fix on specified paths."),
            ]),
            ("WPT Metadata", [
                ("Update WPT",       self.do_update_wpt, "Update WPT metadata for a single test."),
                ("Batch WPT",        self.do_batch_wpt, "Update WPT metadata for multiple tests from a list."),
            ]),
            ("Utilities", [
                ("Check System",    self.do_check_system, "Scan system for git, lando, pipx, and mach presence."),
                ("Install pipx",     self.do_install_pipx, "Install pipx via python3 -m pip (for fresh environments)."),
                ("Lando Sync",       self.do_upgrade_lando, "Install or update the Mozilla Lando CLI via pipx."),
            ])
        ]

        self.btn_widgets = []
        # ---- Action Category Frames ----
        categories_frame = tk.Frame(main, bg=T["bg"])
        categories_frame.pack(fill=tk.X, pady=(0, 15))

        # Configure 3 equal-width columns
        for i in range(3):
            categories_frame.columnconfigure(i, weight=1, uniform="group1")

        # 1. Git & Repo (Left Column, Top)
        lf_git = tk.LabelFrame(categories_frame, text=" Git & Repo ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_git.grid(row=0, column=0, padx=(0, 5), pady=(0, 10), sticky="new") # Removed rowspan
        for text, cmd, tip in groups[0][1]:
            self._add_colored_btn(lf_git, text, cmd, "git", tip)

        # 2. Lando Flow (Middle Column, Top)
        lf_lando = tk.LabelFrame(categories_frame, text=" Lando Flow ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_lando.grid(row=0, column=1, padx=5, pady=(0, 10), sticky="new")
        for text, cmd, tip in groups[1][1]:
            self._add_colored_btn(lf_lando, text, cmd, "lando", tip)

        # 3. Linting (Right Column, Top)
        lf_lint = tk.LabelFrame(categories_frame, text=" Linting ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_lint.grid(row=0, column=2, padx=(5, 0), pady=(0, 10), sticky="new")
        for text, cmd, tip in groups[3][1]:
            self._add_colored_btn(lf_lint, text, cmd, "lint", tip)

        # 4. Reverts (Left Column, Bottom) - Shifted to column 0
        lf_revert = tk.LabelFrame(categories_frame, text=" Reverts ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_revert.grid(row=1, column=0, padx=(0, 5), pady=(0, 10), sticky="new")
        for text, cmd, tip in groups[2][1]:
            self._add_colored_btn(lf_revert, text, cmd, "revert", tip)

        # 5. WPT Metadata (Middle Column, Bottom) - Shifted to column 1
        lf_wpt = tk.LabelFrame(categories_frame, text=" WPT Metadata ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_wpt.grid(row=1, column=1, padx=5, pady=(0, 10), sticky="new")
        for text, cmd, tip in groups[4][1]:
            self._add_colored_btn(lf_wpt, text, cmd, "wpt", tip)

        # 6. Utilities (Right Column, Bottom)
        lf_util = tk.LabelFrame(categories_frame, text=" Utilities ", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10, "bold"), bd=1, relief="solid", padx=10, pady=8)
        lf_util.grid(row=1, column=2, padx=(5, 0), pady=(0, 10), sticky="new")
        for text, cmd, tip in groups[5][1]:
            self._add_colored_btn(lf_util, text, cmd, "git", tip)

        # ---- Terminal ----
        lbl_frame = tk.Frame(main, bg=T["bg"])
        lbl_frame.pack(fill=tk.X, pady=(6, 4))
        tk.Label(lbl_frame, text="Terminal Output:", bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)

        # Feature: Timer label (hidden by default)
        self._timer_label = tk.Label(lbl_frame, text="", bg=T["bg"], fg=T["info_fg"],
                                      font=("Helvetica", 10, "bold"))
        self._timer_label.pack(side=tk.LEFT, padx=12)
                 
        def clear_terminal():
            self.terminal.config(state=tk.NORMAL)
            self.terminal.delete("1.0", tk.END)
            self.terminal.config(state=tk.DISABLED)

        clear_btn = ttk.Button(lbl_frame, text="Clear", command=clear_terminal)
        clear_btn.pack(side=tk.RIGHT, padx=(8, 0))
        Tooltip(clear_btn, "Clear the terminal output.")

        # Feature: Save Log button
        export_btn = ttk.Button(lbl_frame, text="Save Log", command=self.do_export_terminal)
        export_btn.pack(side=tk.RIGHT, padx=(4, 0))
        Tooltip(export_btn, "Export the current terminal output to a .log file.")

        self.progress = ttk.Progressbar(lbl_frame, mode="indeterminate", length=120)
        # We will pack it dynamically when running, or just leave it hidden
        self.progress.pack(side=tk.RIGHT, padx=10)
        self.progress.pack_forget()

        # ---- Search bar below terminal (Pack first to ensure space) ----
        search_f = tk.Frame(main, bg=T["bg"])
        search_f.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        
        tk.Label(search_f, text="Search Terminal:", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_f, textvariable=self.search_var, bg=T["bg2"], fg=T["fg"], 
                                     insertbackground=T["fg"], font=("Helvetica", 10), relief=tk.FLAT, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=8, ipady=2)
        self.search_entry.bind("<Return>", lambda e: self._search_terminal())

        term_frame = tk.Frame(main, bg=T["bg"])
        term_frame.pack(fill=tk.BOTH, expand=True)

        self.terminal = tk.Text(
            term_frame, bg=T["term_bg"], fg=T["term_fg"],
            font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD,
            height=15
        )
        self.terminal.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(term_frame, command=self.terminal.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.terminal.config(yscrollcommand=sb.set)

        self.terminal.tag_config("error",   foreground=T["err_fg"])
        self.terminal.tag_config("success", foreground=T["ok_fg"])
        self.terminal.tag_config("info",    foreground=T["info_fg"])
        self.terminal.tag_config("dim",     foreground=T["dim_fg"])
        self.terminal.tag_config("warn",    foreground="#ffaa00")
        self.terminal.tag_config("link",    foreground="#55aaff", underline=True)
        self.terminal.tag_config("search",  background="#ffff00", foreground="#000000")

        self.terminal.tag_bind("link", "<Button-1>", self._on_link_click)
        Tooltip(self.search_entry, "Enter text to search in terminal and press Enter.")
        
        find_btn = ttk.Button(search_f, text="Find", command=self._search_terminal, width=8)
        find_btn.pack(side=tk.LEFT)
        Tooltip(find_btn, "Search for text in the terminal output (CMD+F).")

        next_btn = ttk.Button(search_f, text="Next", command=lambda: self._search_terminal(forward=True), width=8)
        next_btn.pack(side=tk.LEFT, padx=4)
        Tooltip(next_btn, "Find the next occurrence of the search term.")

        # Feature: Cross-platform keyboard shortcuts
        mod = "Command" if platform.system() == "Darwin" else "Control"
        self.bind(f"<{mod}-f>", lambda e: (self.search_entry.focus_set(), self.search_entry.select_range(0, tk.END)))
        self.bind(f"<{mod}-l>", lambda e: self.do_view_log())
        self.bind(f"<{mod}-u>", lambda e: self.do_undo_last())
        self.bind(f"<{mod}-e>", lambda e: self.do_export_terminal())
        self.bind(f"<{mod}-d>", lambda e: self._toggle_theme())

    # -----------------------------------------------------------------------
    # Queue / UI helpers
    # -----------------------------------------------------------------------

    def _add_colored_btn(self, parent, text, cmd, key_prefix, tooltip_text=None):
        T = self.T
        # Using a Label provides 100% control over color on macOS.
        b = tk.Label(parent, text=text, bg=T[f"{key_prefix}_btn"], fg=T["btn_fg"],
                     font=("Helvetica", 11, "bold"),
                     padx=10, pady=5, relief=tk.FLAT)
        b.pack(fill=tk.X, pady=4)
        
        # Click effect
        def on_click(e):
            if self.is_running_command: return
            cmd()

        b.bind("<Button-1>", on_click)
        
        # Highlight on hover
        def on_enter(e):
            b.config(background=self.T[f"{key_prefix}_hover"])
        def on_leave(e):
            b.config(background=self.T[f"{key_prefix}_btn"])
        
        b.bind("<Enter>", on_enter)
        b.bind("<Leave>", on_leave)
        b.config(cursor="hand2")
        
        if text == "Lando Push":
            self._lando_push_btn = b

        b.key_prefix = key_prefix # type: ignore
        self.btn_widgets.append(b)
        
        if tooltip_text:
            Tooltip(b, tooltip_text)

    def _startup_git_check(self):
        """Run once at startup: warn user if repo has an in-progress git operation."""
        if not self.winfo_exists(): return
        state = self.detect_git_state()
        if state:
            banner = (
                f"\n{'⚠'*30}\n"
                f"  WARNING: Repo has an IN-PROGRESS {state.upper()} operation!\n"
                f"  Branch switching and most workflows will fail until resolved.\n"
                f"  To ABORT:    git {state} --quit   (or --abort for cherry-pick/merge)\n"
                f"  To CONTINUE: git {state} --continue\n"
                f"{'⚠'*30}\n"
            )
            self.terminal.config(state=tk.NORMAL)
            self.terminal.insert(tk.END, banner, ("warn",))
            self.terminal.config(state=tk.DISABLED)

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.process_queue.get_nowait()
                if msg_type == "log":
                    self.terminal.config(state=tk.NORMAL)
                    s = str(data) if data is not None else ""
                    if "ERROR" in s or "failed with exit code" in s or "!!!" in s:
                        tag = ("error",)
                    elif "SUCCESSFULLY" in s:
                        tag = ("success",)
                    elif "Starting Workflow" in s or "Workflow Completed" in s:
                        tag = ("info",)
                    elif s.startswith(">"):
                        tag = ("dim",)
                    else:
                        tag = ()
                    self.terminal.insert(tk.END, s, tag)
                    self._linkify_terminal()
                    self._trim_terminal()
                    self.terminal.see(tk.END)
                    self.terminal.config(state=tk.DISABLED)
                elif msg_type == "alert":
                    messagebox.showerror("Execution Error", data)
                elif msg_type == "done":
                    self.is_running_command = False
                    self.set_buttons_state(tk.NORMAL)
                    self.progress.stop()
                    self.progress.pack_forget()
                    self._update_git_status()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self.check_queue)

    _TERMINAL_MAX_LINES = 5000

    def _trim_terminal(self):
        """Keep the terminal buffer capped at _TERMINAL_MAX_LINES to prevent memory bloat."""
        line_count = int(self.terminal.index("end-1c").split(".")[0])
        if line_count > self._TERMINAL_MAX_LINES:
            overshoot = line_count - self._TERMINAL_MAX_LINES
            self.terminal.delete("1.0", f"{overshoot}.0")

    def set_buttons_state(self, state):
        if not self.winfo_exists(): return
        cursor = "watch" if state == tk.DISABLED else "hand2"
        for b in self.btn_widgets:
            b.config(cursor=cursor)

    # -----------------------------------------------------------------------
    # Popup helpers  (main-thread blocking via wait_window)
    # -----------------------------------------------------------------------

    def _make_popup(self, title: str, h: int, w: int = 460) -> tk.Toplevel:
        T = self.T
        top = tk.Toplevel(self)
        top.title(title)
        top.configure(bg=T["bg"])
        top.transient(self)
        top.grab_set()
        top.update_idletasks()
        
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        top.geometry(f"{w}x{h}+{x}+{y}")
        return top

    def _entry(self, parent, label_text: str) -> tk.Entry:
        T = self.T
        tk.Label(parent, text=label_text, bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11)).pack(pady=(14, 4))
        e = tk.Entry(parent, bg=T["bg2"], fg=T["fg"], insertbackground=T["fg"],
                     font=("Helvetica", 11), relief=tk.FLAT)
        e.pack(fill=tk.X, padx=20, ipady=4)
        return e

    def _ok_cancel(self, parent, on_ok, on_cancel):
        T = self.T
        f = tk.Frame(parent, bg=T["bg"])
        f.pack(pady=16)
        ttk.Button(f, text="OK",     command=on_ok,     width=10).pack(side=tk.LEFT, padx=8)
        ttk.Button(f, text="Cancel", command=on_cancel, width=10).pack(side=tk.LEFT, padx=8)

    def ask_input(self, title: str, prompt: str) -> str | None:
        """Original ask_input (without history dropdown)."""
        top = self._make_popup(title, 180)
        e = self._entry(top, prompt)
        e.focus_set()
        self._popup_result = None

        def ok(ev=None):
            v = e.get().strip()
            self._popup_result = v if v else None
            top.destroy()

        def cancel(ev=None):
            top.destroy()

        self._ok_cancel(top, ok, cancel)
        top.bind("<Return>", ok)
        top.bind("<Escape>", cancel)
        top.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(top)
        return self._popup_result

    def ask_yes_no_threadsafe(self, title: str, message: str) -> bool:
        """Safely show a Yes/No dialog from a background worker thread."""
        result = [False]
        event = threading.Event()
        def show():
            result[0] = messagebox.askyesno(title, message, parent=self)
            event.set()
        self.after(0, show)
        event.wait()
        return result[0]

    def ask_two_inputs(self, title: str, p1: str, p2: str) -> tuple | None:
        top = self._make_popup(title, 270)
        e1 = self._entry(top, p1)
        e1.focus_set()
        e2 = self._entry(top, p2)
        self._popup_result = None

        def ok(ev=None):
            v1 = e1.get().strip()
            v2 = e2.get().strip()
            self._popup_result = (v1, v2) if (v1 and v2) else None
            top.destroy()

        def cancel(ev=None):
            top.destroy()

        self._ok_cancel(top, ok, cancel)
        top.bind("<Return>", ok)
        top.bind("<Escape>", cancel)
        top.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(top)
        return self._popup_result

    def ask_input_with_history(self, title: str, prompt: str) -> str | None:
        """ask_input but displaying deduplicated _recent_hashes as clickable buttons below."""
        # Taller if we have history
        h_height = min(180 + (min(len(self._recent_hashes), 5) * 35), 380)
        top = self._make_popup(title, h_height, 460)
        e = self._entry(top, prompt)
        e.focus_set()
        
        self._popup_result = None

        def ok(ev=None):
            v = e.get().strip()
            self._popup_result = v if v else None
            top.destroy()

        def cancel(ev=None):
            top.destroy()

        self._ok_cancel(top, ok, cancel)
        
        # Inject History Panel
        if self._recent_hashes:
            hist_frame = tk.Frame(top, bg=self.T["bg"])
            hist_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
            tk.Label(hist_frame, text="Recent Hashes:", bg=self.T["bg"], fg=self.T["dim_fg"], font=("Helvetica", 10)).pack(anchor=tk.W)
            
            # Show up to 5 recently used
            recent_display = list(self._recent_hashes)[:5] # type: ignore
            for h in recent_display:
                def set_val(val=h):
                    e.delete(0, tk.END)
                    e.insert(0, val)
                    ok()
                # A flatter button style for history items
                btn = tk.Label(hist_frame, text=h, bg=self.T["bg2"], fg=self.T["fg"], 
                               font=("Consolas", 10), padx=6, pady=4, relief=tk.FLAT, cursor="hand2")
                btn.pack(fill=tk.X, pady=2)
                btn.bind("<Button-1>", lambda e, v=h: set_val(v))
                btn.bind("<Enter>", lambda ev, b=btn: b.config(bg=self.T["bg3"]))
                btn.bind("<Leave>", lambda ev, b=btn: b.config(bg=self.T["bg2"]))

        top.bind("<Return>", ok)
        top.bind("<Escape>", cancel)
        top.protocol("WM_DELETE_WINDOW", cancel)
        self.wait_window(top)
        return self._popup_result

    # -----------------------------------------------------------------------
    # Subprocess/State helpers
    # -----------------------------------------------------------------------

    def _get_config_path(self) -> str:
        return os.path.expanduser("~/.treeherder_app.json")

    def _load_config(self):
        """Load persistent config: repo_path, recent_hashes, dark_mode."""
        conf = self._get_config_path()
        if os.path.exists(conf):
            try:
                with open(conf, "r") as f:
                    data = json.load(f)
                    saved_repo = data.get("repo_path")
                    if saved_repo:
                        self.repo_var.set(saved_repo)
                    saved_hashes = data.get("recent_hashes", [])
                    self._recent_hashes = list(saved_hashes)[:10] # type: ignore
                    saved_dark = data.get("dark_mode")
                    if saved_dark is not None:
                        self._dark = saved_dark
                        self.T = build_theme(self._dark)
            except Exception:
                pass

    def _save_config(self):
        """Persist config to disk."""
        try:
            data = {
                "repo_path": self.repo_var.get(),
                "recent_hashes": list(self._recent_hashes)[:10], # type: ignore
                "dark_mode": self._dark,
            }
            with open(self._get_config_path(), "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _save_repo_path(self, path: str):
        if not path: return
        self._save_config()

    def _remember_hash(self, h: str):
        """Add a hash to the recent hashes list (deduplicated, max 10)."""
        for part in h.replace(",", " ").split():
            part = part.strip()
            if part and len(part) >= 6:
                if part in self._recent_hashes:
                    self._recent_hashes.remove(part)
                self._recent_hashes.insert(0, part)
        self._recent_hashes = list(self._recent_hashes)[:10] # type: ignore
        self._save_config()

    def _auto_fetch(self):
        """Feature: Background auto-fetch on app startup."""
        if not self.winfo_exists(): return
        if not self._cwd() or not os.path.exists(os.path.join(self._cwd(), ".git")):
            return
        
        def worker():
            try:
                subprocess.run(["git", "fetch", "--quiet"], cwd=self._cwd(), check=True, env=self._build_env())
                # Once fetch finishes in background, refresh status gently
                self.after(0, self._update_git_status)
            except Exception:
                pass
        
        threading.Thread(target=worker, daemon=True).start()

    def _soft_toggle_theme(self):
        """Feature: Soft theme switch without full app restart."""
        self._dark = not self._dark
        self._save_config()
        self.T = build_theme(self._dark)
        T = self.T

        # 1. Update ttk Styles
        style = ttk.Style(self)
        style.configure(".", background=T["bg"], foreground=T["fg"])
        style.configure("TLabelframe", background=T["bg"], bordercolor=T["bg3"], 
                        lightcolor=T["bg3"], darkcolor=T["bg3"], relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=T["bg"], foreground=T["dim_fg"], font=("Helvetica", 10, "bold"))
        style.configure("TButton", background=T["bg3"], foreground=T["fg_btn"])
        style.configure("TCombobox", fieldbackground=T["bg2"], background=T["bg3"], foreground=T["fg"], arrowcolor=T["fg"])
        style.map("TCombobox", 
                  fieldbackground=[("readonly", T["bg2"]), ("disabled", T["bg"])],
                  foreground=[("readonly", T["fg"]), ("disabled", T["fg_disabled"])])
        style.map("TButton", background=[("active", T["bg_active"]), ("disabled", T["bg2"])], foreground=[("disabled", T["fg_disabled"])])
        
        # 2. Apply theme to self
        self.configure(bg=T["bg"])
        
        # 3. Apply theme to custom action buttons
        for b in self.btn_widgets:
            prefix = getattr(b, "key_prefix", "git")
            b.config(bg=T[f"{prefix}_btn"], fg=T["btn_fg"])

        # 4. Apply theme to all widgets recursively
        self._apply_theme_to_widgets(self)
        
        # 5. Manually update the toggle label
        toggle_text = "☀️ Light" if self._dark else "🌙 Dark"
        self._theme_toggle_label.config(text=toggle_text, bg=T["bg3"], fg=T["fg"])
        
        # 6. Re-apply status colors
        self._update_git_status()

    def _apply_theme_to_widgets(self, root):
        T = self.T
        for child in root.winfo_children():
            try:
                # 1. Update colors
                if isinstance(child, (tk.Frame, tk.LabelFrame)):
                    child.configure(bg=T["bg"])
                    if isinstance(child, tk.LabelFrame):
                        child.configure(fg=T["dim_fg"], highlightbackground=T["bg3"], highlightcolor=T["bg3"])
                elif isinstance(child, tk.Label):
                    if child in self.btn_widgets:
                        pass
                    elif child == getattr(self, "status_label", None):
                         child.configure(bg=T["bg"], fg=T["fg"])
                    else:
                        child.configure(bg=T["bg"], fg=T["fg"])
                elif isinstance(child, (tk.Entry, tk.Text, tk.Listbox)):
                    if isinstance(child, tk.Listbox):
                         child.configure(bg=T["bg2"], fg=T["fg"])
                    elif child == getattr(self, "terminal", None):
                        child.configure(bg=T["term_bg"], fg=T["term_fg"], 
                                        insertbackground=T["fg"], highlightcolor=T["git_btn"])
                    else:
                        child.configure(bg=T["bg2"], fg=T["fg"], insertbackground=T["fg"])
                elif isinstance(child, tk.Canvas):
                    child.configure(bg=T["bg"], highlightthickness=0)
                elif isinstance(child, ttk.Combobox):
                    child.configure(style="TCombobox")
                
                # 2. ALWAYS recurse into children if they exist
                if child.winfo_children(): # type: ignore
                    self._apply_theme_to_widgets(child)
            except Exception:
                pass

    def _toggle_theme(self):
        """Feature: One-click Dark/Light Theme Switcher."""
        # Use soft reload to avoid background crashes
        self._soft_toggle_theme()

    def _start_timer(self):
        if not self.winfo_exists(): return
        self._workflow_start_time = time.time()
        self._timer_label.config(text="⏱ 00:00")
        self._update_timer()

    def _update_timer(self):
        if not self.winfo_exists():
            return
        start = self._workflow_start_time
        if start is None:
            return
        elapsed = int(time.time() - float(start))
        mins, secs = divmod(elapsed, 60)
        self._timer_label.config(text=f"⏱ {mins:02d}:{secs:02d}")
        if self.is_running_command:
            self._timer_after_id = self.after(1000, self._update_timer) # type: ignore

    def _stop_timer(self):
        tid = self._timer_after_id
        if tid:
            self.after_cancel(tid)
            self._timer_after_id = None
        
        start = self._workflow_start_time
        if start:
            # Leave the final time string visible for a few seconds as feedback
            elapsed = int(time.time() - float(start))
            mins, secs = divmod(elapsed, 60)
            self._timer_label.config(text=f"⏱ {mins:02d}:{secs:02d} (Done!)")
            self._workflow_start_time = None
            self.after(4000, lambda: self._timer_label.config(text="") if not self.is_running_command else None) # type: ignore

    def _update_git_status(self):
        """Update the UI Status label to show ahead/behind/state."""
        if not self.winfo_exists(): return
        branch = self.branch_var.get()
        cwd = self._cwd()
        if not os.path.exists(os.path.join(cwd, ".git")):
            self.status_var.set("Status: Not a repo")
            self.status_label.config(fg=self.T["err_fg"])
            return

        state = self.detect_git_state()
        if state:
            self.status_var.set(f"Status: ⚠ {state.upper()} in progress")
            self.status_label.config(fg="#ffaa00")
            return

        try:
            # First check if the tracking branch exists
            try:
                subprocess.check_call(["git", "rev-parse", "--verify", f"origin/{branch}"], 
                                      cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                has_upstream = True
            except subprocess.CalledProcessError:
                has_upstream = False

            if not has_upstream:
                self.status_var.set(f"Status: ✓ Local only")
                self.status_label.config(fg=self.T["dim_fg"])
                return

            out = subprocess.check_output(
                ["git", "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"],
                cwd=cwd, text=True, stderr=subprocess.DEVNULL
            ).strip()
            # output format: "behind  ahead" e.g., "0\t1"
            parts = out.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])
                if ahead > 0 and behind > 0:
                    self.status_var.set(f"Status: ↓ {behind} ↑ {ahead}")
                    self.status_label.config(fg="#ffaa00")
                    if self._lando_push_btn:
                        self._lando_push_btn.config(text=f"Lando Push ({ahead} pending)")
                elif ahead > 0:
                    self.status_var.set(f"Status: ↑ {ahead} unpushed")
                    self.status_label.config(fg=self.T["ok_fg"])
                    if self._lando_push_btn:
                        self._lando_push_btn.config(text=f"Lando Push ({ahead} pending)")
                elif behind > 0:
                    self.status_var.set(f"Status: ↓ {behind} behind")
                    self.status_label.config(fg=self.T["info_fg"])
                    if self._lando_push_btn:
                        self._lando_push_btn.config(text="Lando Push")
                else:
                    self.status_var.set("Status: ✓ Clean")
                    self.status_label.config(fg=self.T["dim_fg"])
                    if self._lando_push_btn:
                        self._lando_push_btn.config(text="Lando Push")
        except Exception:
            self.status_var.set("Status: ?")
            self.status_label.config(fg=self.T["dim_fg"])

    def _cwd(self):
        return self.repo_var.get()

    def _build_env(self, env=None):
        """Return an env dict with an enriched PATH that includes ~/bin and common tool dirs."""
        if env is not None:
            return env   # caller already provided a custom env, don't touch it
        e = os.environ.copy()
        extra = [
            os.path.expanduser("~/bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
            "/opt/pkg/env/active/bin",
        ]
        current_path = e.get("PATH", "")
        additions = os.pathsep.join(p for p in extra if p not in current_path)
        e["PATH"] = additions + os.pathsep + current_path if additions else current_path
        return e

    def run_cmd(self, cmd, env=None, cwd=None):
        cwd = cwd or self._cwd()
        env = self._build_env(env)
        self.process_queue.put(("log", f"\n> {' '.join(cmd)}\n"))
        is_interactive = cmd and cmd[0] == "lando"
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE if is_interactive else subprocess.DEVNULL,
                                text=True, env=env, cwd=cwd)
        buf: str = ""
        while True:
            if not proc.stdout: break
            c: str = proc.stdout.read(1) # type: ignore
            if not c and proc.poll() is not None:
                if buf: self.process_queue.put(("log", buf))
                break
            if c:
                buf += c # type: ignore
                if c == '\n':
                    self.process_queue.put(("log", buf))
                    buf = ""
                elif is_interactive:
                    lbuf = buf.lower()
                    if ("y/n" in lbuf) and lbuf.endswith((' ', ':', '?', '>')):
                        self.process_queue.put(("log", buf))
                        ans = self.ask_yes_no_threadsafe(
                            "Lando Confirmation Required", 
                            f"Lando is actively asking for Confirmation:\n\n{buf.strip()}\n\nClick Yes to proceed (sends 'y'), or No to abort (sends 'n')."
                        )
                        reply = "y\n" if ans else "n\n"
                        self.process_queue.put(("log", reply))
                        proc.stdin.write(reply)
                        proc.stdin.flush()
                        buf = ""

        rc = proc.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)

    def get_output(self, cmd, env=None, cwd=None) -> str:
        cwd = cwd or self._cwd()
        env = self._build_env(env)
        self.process_queue.put(("log", f"\n> [output] {' '.join(cmd)}\n"))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, cwd=cwd)
        out, err = proc.communicate()
        if proc.returncode != 0:
            self.process_queue.put(("log", err + "\n"))
            raise subprocess.CalledProcessError(proc.returncode, cmd, out, err)
        return out

    def _push_and_cleanup(self, branch: str, fallback_count: str = "1"):
        """Push local commits to Lando and reset the local branch afterward."""
        try:
            count = self.get_output(["git", "rev-list", "--count", f"origin/{branch}..HEAD"]).strip()
        except Exception:
            count = fallback_count
        self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{branch}"])
        if count != "0":
            self.run_cmd(["git", "reset", "--hard", f"HEAD~{count}"])
            self.process_queue.put(("log", f"\n> [Cleanup] Dropped {count} local commit(s) after successful lando push.\n"))

    def execute_workflow(self, name: str, fn):
        if self.is_running_command:
            messagebox.showwarning("Busy", "A workflow is currently running.")
            return
        self.is_running_command = True
        self.set_buttons_state(tk.DISABLED)
        self.progress.pack(side=tk.RIGHT, padx=10)
        self.progress.start(15)
        self._start_timer()
        
        # Feature: Save HEAD before workflow for undo
        try:
            self._last_workflow_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self._cwd(), text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            self._last_workflow_head = None

        def worker():
            try:
                self.process_queue.put(("log", f"\n{'='*60}\nStarting Workflow: {name}\n{'='*60}\n"))
                fn()
                self.process_queue.put(("log", f"\n{'='*60}\nWorkflow Completed SUCCESSFULLY: {name}\n{'='*60}\n"))
            except subprocess.CalledProcessError as e:
                msg = f"Command failed (exit {e.returncode}): {' '.join(e.cmd)}"
                self.process_queue.put(("log", f"\n!!! ERROR !!! {msg}\n"))
                self.process_queue.put(("alert", f"{msg}\n\nResolve manually and retry."))
            except Exception as e:
                self.process_queue.put(("log", f"\n!!! ERROR !!! {e}\n"))
                self.process_queue.put(("alert", str(e)))
            finally:
                self.process_queue.put(("done", None))
                self.after(0, self._stop_timer)

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Workflows
    # -----------------------------------------------------------------------

    def detect_git_state(self) -> str | None:
        """Return the name of any in-progress git operation, or None if clean."""
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=self._cwd()
        )
        if git_dir_result.returncode != 0:
            return None
        git_dir = os.path.join(self._cwd(), git_dir_result.stdout.strip())
        if os.path.exists(os.path.join(git_dir, "REVERT_HEAD")):
            return "revert"
        if os.path.exists(os.path.join(git_dir, "CHERRY_PICK_HEAD")):
            return "cherry-pick"
        if os.path.exists(os.path.join(git_dir, "MERGE_HEAD")):
            return "merge"
        if os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(os.path.join(git_dir, "rebase-apply")):
            return "rebase"
        return None

    def show_recovery_dialog(self, state: str, then_run):
        """Show a one-click recovery popup for an in-progress git state."""
        T = self.T
        abort_cmd  = {"revert": ["git", "revert", "--quit"],
                      "cherry-pick": ["git", "cherry-pick", "--abort"],
                      "merge": ["git", "merge", "--abort"],
                      "rebase": ["git", "rebase", "--abort"]}.get(state, [])
        cont_cmd   = {"revert": ["git", "revert", "--continue"],
                      "cherry-pick": ["git", "cherry-pick", "--continue"],
                      "merge": ["git", "merge", "--continue"],
                      "rebase": ["git", "rebase", "--continue"]}.get(state, [])

        top = self._make_popup(f"⚠ In-Progress {state.title()} Detected", 210)
        tk.Label(top,
                 text=f"Git is mid-{state}. What do you want to do?",
                 bg=T["bg"], fg=T["fg"], font=("Helvetica", 11)
                ).pack(pady=(20, 6))
        tk.Label(top,
                 text="Abort — discard and switch branch\nContinue — finish the operation first",
                 bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10), justify=tk.CENTER
                ).pack(pady=(0, 12))

        choice = [None]

        def pick(c):
            choice[0] = c
            top.destroy()

        row = tk.Frame(top, bg=T["bg"])
        row.pack()
        ttk.Button(row, text="Abort & Switch",  command=lambda: pick("abort"),    width=14).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Continue",         command=lambda: pick("continue"), width=14).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Cancel",           command=lambda: pick(None),       width=10).pack(side=tk.LEFT, padx=8)
        top.protocol("WM_DELETE_WINDOW", lambda: pick(None))
        self.wait_window(top)

        if choice[0] == "abort":
            def do_abort():
                if abort_cmd:
                    self.run_cmd(abort_cmd)
                then_run()
            return do_abort
        elif choice[0] == "continue":
            def do_continue():
                if cont_cmd:
                    self.run_cmd(cont_cmd)
                then_run()
            return do_continue
        return None

    def on_branch_change(self, _event):
        branch = self.branch_var.get()

        try:
            current = subprocess.check_output(
                ["git", "branch", "--show-current"], 
                cwd=self._cwd(), text=True, stderr=subprocess.DEVNULL
            ).strip()
            if branch == current:
                self.process_queue.put(("log", f"\n> Already on '{branch}'. Skipping switch.\n"))
                return
        except Exception:
            pass

        def switch():
            self.run_cmd(["git", "switch", branch])

        # Check for in-progress git state before switching
        state = self.detect_git_state()
        if state:
            recovery_fn = self.show_recovery_dialog(state, switch)
            if recovery_fn:
                self.execute_workflow(f"Recover & Switch → {branch}", recovery_fn)
            else:
                # User cancelled — revert dropdown to previous branch
                try:
                    current = subprocess.check_output(
                        ["git", "branch", "--show-current"], 
                        cwd=self._cwd(), text=True, stderr=subprocess.DEVNULL
                    ).strip()
                except Exception:
                    current = ""
                self.branch_var.set(current or branch)
        else:
            self.execute_workflow(f"Switch Branch → {branch}", switch)

    def do_fetch(self):
        self.execute_workflow("Git Fetch", lambda: self.run_cmd(["git", "fetch"]))

    def do_pull(self):
        self.execute_workflow("Git Pull", lambda: self.run_cmd(["git", "pull"]))

    def do_hard_reset(self):
        n = self.ask_input("Hard Reset", "Reset current branch back by how many commits? (e.g. 1):")
        if not n: return
        if not n.isdigit():
            messagebox.showerror("Error", "Please enter a valid number.")
            return
        if not messagebox.askyesno("⚠ Confirm Hard Reset",
                f"This will PERMANENTLY discard the last {n} commit(s).\n\n"
                f"Are you sure you want to run:\n  git reset --hard HEAD~{n}"):
            return

        def logic():
            self.run_cmd(["git", "reset", "--hard", f"HEAD~{n}"])

        self.execute_workflow(f"Git Hard Reset (HEAD~{n})", logic)

    def do_undo_last(self):
        """Feature: Recover from an accidental workflow step via reflog tracking."""
        if not self._last_workflow_head:
            messagebox.showinfo("Undo", "No previous workflow HEAD tracked in this session.")
            return
            
        def logic():
            self.run_cmd(["git", "reset", "--hard", self._last_workflow_head])
            
        self.execute_workflow("Undo Last Workflow", logic)


    def do_single_revert(self):
        _h = self.ask_input_with_history("Single Revert", "Changeset hash to revert:")
        if not _h: return
        h: str = _h
        self._remember_hash(h)
        reason = self.ask_input("Revert Reason", "Revert reason (e.g. 'for causing bustages'):")
        if not reason: return

        def logic():
            self.run_cmd(["git", "pull"])
            self.run_cmd(["git", "revert"] + h.replace(",", " ").split() + ["--no-edit"])
            msg = self.get_output(["git", "log", "-1", "--pretty=%B"])
            lines = msg.split("\n")
            if lines:
                lines[0] = f"{lines[0]} {reason}"
            new_msg = "\n".join(lines)
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as f:
                f.write(new_msg)
                tmp = f.name
            try:
                self.run_cmd(["git", "commit", "--amend", "-F", tmp])
            finally:
                os.unlink(tmp)
            
            final_msg = self.get_output(["git", "log", "-1", "--pretty=%B"])
            if not self.ask_yes_no_threadsafe("Verify Commit Message", f"Does this commit message look correct?\n\n{final_msg.strip()}\n\nClick YES to push to Lando now.\nClick NO to keep locally and batch with other commits."):
                self.process_queue.put(("log", "\n> [Batch Mode] Commit kept locally. Run more workflows, or use 'Lando Push' when ready.\n"))
                return
            
            self._push_and_cleanup(self.branch_var.get())

        self.execute_workflow("Single Revert", logic)

    def do_multiple_reverts(self):
        res = self.ask_two_inputs(
            "Multiple Reverts",
            "First (oldest) changeset hash:",
            "Second (newest) changeset hash:",
        )
        if not res: return
        hash1, hash2 = res
        reason = self.ask_input("Revert Reason", "Revert reason:")
        if not reason: return

        def logic():
            self.run_cmd(["git", "pull"])
            old_head = self.get_output(["git", "rev-parse", "HEAD"]).strip()
            self.run_cmd(["git", "revert", f"{hash1}~1..{hash2}", "--no-edit"])
            count = int(self.get_output(["git", "rev-list", "--count", f"{old_head}..HEAD"]).strip())
            if count <= 1:
                raise Exception(f"Expected >1 revert commit, got {count}.")

            reason_r = repr(reason)
            seq_code = textwrap.dedent(f"""\
                import sys
                path = sys.argv[1]
                lines = open(path, encoding='utf-8').readlines()
                first = True
                for i, l in enumerate(lines):
                    if l.startswith('pick ') or l.startswith('p '):
                        if first:
                            first = False
                        else:
                            lines[i] = 'squash ' + l.split(' ', 1)[1]
                open(path, 'w', encoding='utf-8').writelines(lines)
            """)
            msg_code = textwrap.dedent(f"""\
                import sys
                path = sys.argv[1]
                with open(path, encoding='utf-8') as f:
                    lines = f.readlines()
                    
                for i, line in enumerate(lines):
                    if not line.startswith('#') and line.strip():
                        # First real commit subject line
                        lines[i] = line.rstrip('\\n') + ' ' + {reason_r} + '\\n'
                        break
                        
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
            """)

            def tmp_script(code):
                f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
                f.write(code); f.close()
                return f.name

            seq_f, msg_f = tmp_script(seq_code), tmp_script(msg_code)
            py = sys.executable
            env = os.environ.copy()
            env["GIT_SEQUENCE_EDITOR"] = f'"{py}" "{seq_f}"'
            env["GIT_EDITOR"]          = f'"{py}" "{msg_f}"'
            try:
                self.run_cmd(["git", "rebase", "-i", f"HEAD~{count}"], env=env)
            finally:
                os.unlink(seq_f); os.unlink(msg_f)
                
            final_msg = self.get_output(["git", "log", "-1", "--pretty=%B"])
            if not self.ask_yes_no_threadsafe("Verify Commit Message", f"Does this squash commit message look correct?\n\n{final_msg.strip()}\n\nClick YES to push to Lando now.\nClick NO to keep locally and batch with other commits."):
                self.process_queue.put(("log", "\n> [Batch Mode] Squashed commit kept locally. Run more workflows, or use 'Lando Push' when ready.\n"))
                return
                
            self._push_and_cleanup(self.branch_var.get())

        self.execute_workflow("Multiple Reverts (Rebase & Squash)", logic)

    def do_merge(self):
        h = self.ask_input("Lando Merge", "Target commit (autoland → main):")
        if not h: return
        self.execute_workflow("Lando Merge", lambda: self.run_cmd([
            "lando", "push-merge",
            "--lando-repo", "firefox-main",
            "--target-commit", h,
            "--commit-message", "Merge firefox-autoland to firefox-main",
        ]))

    def do_push_merge_back(self):
        h = self.ask_input("Lando Merge Back", "Target commit (main → autoland):")
        if not h: return
        self.execute_workflow("Lando Merge Back", lambda: self.run_cmd([
            "lando", "push-merge",
            "--lando-repo", "firefox-autoland",
            "--target-commit", h,
            "--commit-message", "Merge firefox-main to firefox-autoland",
        ]))

    def do_cherry_pick(self):
        h = self.ask_input_with_history("Cherry-Pick", "Changeset hash(es) to cherry-pick:")
        if not h: return
        self._remember_hash(h)

        def logic():
            self.run_cmd(["git", "pull"])
            _h: str = h # type: ignore
            hashes = _h.replace(",", " ").split()
            self.run_cmd(["git", "cherry-pick"] + hashes)
            
            final_msg = self.get_output(["git", "log", "-1", "--pretty=%B"])
            if not self.ask_yes_no_threadsafe("Verify Cherry-Pick", f"Successfully cherry-picked {len(hashes)} commit(s).\n\nLatest commit message:\n{final_msg.strip()}\n\nClick YES to push to Lando now.\nClick NO to keep locally and batch with other commits."):
                self.process_queue.put(("log", "\n> [Batch Mode] Cherry-picks kept locally. Run more workflows, or use 'Lando Push' when ready.\n"))
                return
            
            self._push_and_cleanup(self.branch_var.get(), fallback_count=str(len(hashes)))

        self.execute_workflow("Cherry-Pick", logic)

    def do_lando_push(self):
        branch = self.branch_var.get()
        def logic():
            self.run_cmd(["git", "pull"])
            
            # Guard: abort early if there are no local commits to push
            try:
                count = self.get_output(["git", "rev-list", "--count", f"origin/{branch}..HEAD"]).strip()
                if count == "0":
                    raise Exception(f"You have 0 local unpushed commits on '{branch}'. Nothing to push.")
            except subprocess.CalledProcessError:
                pass  # If origin tracking doesn't exist, let lando try anyway

            self._push_and_cleanup(branch)

        self.execute_workflow("Lando Push", logic)

    def do_upgrade_lando(self):
        def logic():
            self.process_queue.put(("log", "\n> Checking Lando CLI status via pipx...\n"))
            try:
                # Check if lando_cli is already managed by pipx
                out = subprocess.check_output(["pipx", "list"], text=True, stderr=subprocess.DEVNULL)
                is_installed = "lando_cli" in out or "lando-cli" in out
            except Exception:
                is_installed = False

            if is_installed:
                self.process_queue.put(("log", "> Lando CLI is installed. Upgrading...\n"))
                self.run_cmd(["pipx", "upgrade", "lando_cli"])
            else:
                self.process_queue.put(("log", "> Lando CLI not found. Installing...\n"))
                self.run_cmd(["pipx", "install", "lando_cli"])
        
        self.execute_workflow("Install/Upgrade Lando CLI", logic)

    def do_install_pipx(self):
        def logic():
            self.process_queue.put(("log", "\n> Attempting to install pipx via python3 -m pip...\n"))
            # Standard Mozilla installation path for pipx
            self.run_cmd([sys.executable, "-m", "pip", "install", "--user", "pipx"])
            self.run_cmd([sys.executable, "-m", "pipx", "ensurepath"])
            self.process_queue.put(("log", "\n> pipx installation attempt finished. Please restart the app if commands still fail.\n"))
        self.execute_workflow("Install pipx", logic)

    def do_check_system(self):
        def logic():
            self.process_queue.put(("log", "\n>>> SYSTEM STATUS CHECK <<<\n"))
            
            checks = [
                ("Python3", [sys.executable, "--version"]),
                ("Git",     ["git", "--version"]),
                ("pipx",    ["pipx", "--version"]),
                ("Lando",   ["lando", "--version"]),
            ]
            
            cwd = self._cwd()
            mach = os.path.join(cwd, "mach")
            if os.path.exists(mach):
                checks.append(("Mach (Repo)", [mach, "--version"]))
            else:
                self.process_queue.put(("log", "! Mach: NOT FOUND in current repository path.\n"))

            for name, cmd in checks:
                try:
                    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, env=self._build_env()).strip()
                    self.process_queue.put(("log", f"✓ {name}: {out}\n"))
                except Exception:
                    self.process_queue.put(("log", f"✗ {name}: NOT FOUND or failed to run.\n"))
            
            self.process_queue.put(("log", "\n>>> Check Complete.\n"))

        self.execute_workflow("System Check", logic)

    def do_view_log(self):
        try:
            author_email = subprocess.check_output(
                ["git", "config", "user.email"], cwd=self._cwd(), text=True
            ).strip()
        except Exception:
            author_email = ""

        top = self._make_popup("Recent Git Log", 450, 700)

        T = self.T
        top.configure(bg=T["bg"])

        top_frame = tk.Frame(top, bg=T["bg"])
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(top_frame, text="Double-click a line to copy its hash:", 
                 bg=T["bg"], fg=T["fg"], font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)

        only_me_var = tk.BooleanVar(value=True if author_email else False)

        listbox = tk.Listbox(top, bg=T["term_bg"], fg=T["term_fg"], font=("Consolas", 10), selectbackground=T["bg_active"])
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        def refresh_log():
            listbox.delete(0, tk.END)
            cmd = ["git", "log", "-n", "50", "--oneline", "--decorate"]
            if only_me_var.get() and author_email:
                cmd.append(f"--author={author_email}")
            
            try:
                out = subprocess.check_output(cmd, cwd=self._cwd(), text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if line.strip():
                        listbox.insert(tk.END, f" {line.strip()}")
            except subprocess.CalledProcessError:
                listbox.insert(tk.END, " Failed to fetch git log.")

        if author_email:
            chk = tk.Checkbutton(top_frame, text="Show only my commits", variable=only_me_var, 
                                 command=refresh_log, bg=T["bg"], fg=T["fg"], selectcolor=T["bg2"], activebackground=T["bg"])
            chk.pack(side=tk.RIGHT)

        def on_double_click(event):
            sel = listbox.curselection()
            if not sel: return
            line = listbox.get(sel[0]).strip()
            if not line: return
            hash_val = line.split(" ", 1)[0]
            # Strip decorator brackets if they accidentally click a ref
            hash_val = hash_val.replace("(", "").replace(")", "")
            self.clipboard_clear()
            self.clipboard_append(hash_val)
            messagebox.showinfo("Copied!", f"Hash '{hash_val}' copied to clipboard!", parent=top)

        listbox.bind("<Double-1>", on_double_click)
        refresh_log()

    def do_export_terminal(self):
        """Feature: Terminal log export with file dialog."""
        text = self.terminal.get("1.0", tk.END)
        default_name = f"treeherder_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = filedialog.asksaveasfilename(
            initialdir=os.path.expanduser("~/Desktop"),
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("Log Files", "*.log"), ("All Files", "*.*")],
            title="Save Terminal Log"
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Export Successful", f"Log saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save log:\n{e}")

    def _linkify_terminal(self):
        """Scan only the last inserted line for Phabricator Revisions (D123), Bug IDs, and URLs."""
        self.terminal.config(state=tk.NORMAL)
        # Only scan the last line to avoid O(n²) re-scanning of the full buffer
        last_line_idx = self.terminal.index("end-2l linestart")
        last_line_end = self.terminal.index("end-1c")
        content = self.terminal.get(last_line_idx, last_line_end)

        patterns = [
            r"\bD\d{5,}\b",           # Phabricator Revision: D12345
            r"\bbug\s+\d{5,}\b",      # Bugzilla: bug 123456 (case insensitive usually)
            r"https?://\S+",          # Direct URLs
        ]

        for p in patterns:
            for m in re.finditer(p, content, re.IGNORECASE):
                start = f"{last_line_idx} + {m.start()} chars"
                end = f"{last_line_idx} + {m.end()} chars"
                self.terminal.tag_add("link", start, end)
        
        self.terminal.config(state=tk.DISABLED)

    def _on_link_click(self, event):
        """Handle clicking a link tag."""
        idx = self.terminal.index(f"@{event.x},{event.y}")
        # Get start and end of the tag
        tag_range = self.terminal.tag_prevrange("link", idx + " + 1c")
        if not tag_range: return
        text = self.terminal.get(*tag_range).strip()
        
        url = ""
        if text.lower().startswith("http"):
            url = text
        elif text.lower().startswith("bug"):
            m = re.search(r"\d+", text)
            if m:
                url = f"https://bugzilla.mozilla.org/show_bug.cgi?id={m.group()}"
        elif text.startswith("D") or text.startswith("d"):
            url = f"https://phabricator.services.mozilla.com/{text.upper()}"
        
        if url:
            webbrowser.open(url)

    def _search_terminal(self, forward=False):
        """Highlight search terms in the terminal and scroll to the next one."""
        query = self.search_var.get()
        if not query:
            self.terminal.tag_remove("search", "1.0", tk.END)
            return

        # Always re-highlight everything whenever search is triggered
        self.terminal.tag_remove("search", "1.0", tk.END)
        start = "1.0"
        while True:
            pos = self.terminal.search(query, start, stopindex=tk.END, nocase=True)
            if not pos: break
            end = f"{pos} + {len(query)}c"
            self.terminal.tag_add("search", pos, end)
            start = end

        # Now handle the "Next" navigation
        if not hasattr(self, "_search_current_idx") or not forward:
            self._search_current_idx = "1.0"

        # Search from current position
        pos = self.terminal.search(query, self._search_current_idx, stopindex=tk.END, nocase=True)
        if not pos:
            # Wrap around to the start
            pos = self.terminal.search(query, "1.0", stopindex=tk.END, nocase=True)
        
        if pos:
            self.terminal.see(pos)
            self._search_current_idx = f"{pos} + 1c"
            # Briefly darken the current match for better visibility
            tmp_tag = "search_current"
            self.terminal.tag_config(tmp_tag, background="#ffaa00", foreground="#000000")
            self.terminal.tag_remove(tmp_tag, "1.0", tk.END)
            self.terminal.tag_add(tmp_tag, pos, f"{pos} + {len(query)}c")
            # Clear it after a moment
            self.after(800, lambda: self.terminal.tag_remove(tmp_tag, "1.0", tk.END))

    def do_update_wpt(self):
        log_line = self.ask_input("Update WPT", "Paste Treeherder TEST-UNEXPECTED log line:")
        if not log_line: return

        m = re.search(r"TEST-UNEXPECTED\s*\|\s*([^|]+)\s*\|\s*([^|]+)", log_line)
        if not m:
            messagebox.showerror("Error", "Could not parse log line. Expected format:\nTEST-UNEXPECTED | /path/to/test.html | subtest - expected FAIL")
            return
        
        test_path = m.group(1).strip()
        subtest_raw = m.group(2).strip()
        subtest_name = re.split(r"\s+-\s+expected\s+", subtest_raw, flags=re.IGNORECASE)[0]

        cwd = self._cwd()
        meta_root = os.path.join(cwd, "testing", "web-platform", "meta")
        relative_meta = test_path.lstrip("/") + ".ini"
        meta_path = os.path.join(meta_root, relative_meta)

        if not os.path.exists(meta_path):
            if messagebox.askyesno("Create File?", f"Meta file does not exist:\n{relative_meta}\n\nDo you want to create it?"):
                os.makedirs(os.path.dirname(meta_path), exist_ok=True)
                with open(meta_path, "w", encoding="utf-8") as f:
                    filename = os.path.basename(test_path)
                    # Precision WPT Indentation (2rd space increment)
                    f.write(f"[{filename}]\n")
                    if subtest_name and subtest_name != filename:
                        # Root(0) -> Subtest(2) -> Expected(4) -> Conditional(6)
                        f.write(f"  [{subtest_name}]\n    expected:\n      ")
                    else:
                        # Root(0) -> Expected(2) -> Conditional(4)
                        f.write(f"  expected:\n    ")
            else:
                return

        self.open_wpt_editor(meta_path, subtest_name)
        
    def do_batch_wpt(self):
        """Feature: Parse a multiline paste of many FAIL/TIMEOUT logs and extract the paths."""
        top = self._make_popup("Batch Update WPT", 300, 600)
        
        tk.Label(top, text="Paste multiple lines containing TEST-UNEXPECTED:", 
                 bg=self.T["bg"], fg=self.T["dim_fg"], font=("Helvetica", 11)).pack(pady=(12, 4))
                 
        text_area = tk.Text(top, bg=self.T["bg2"], fg=self.T["fg"], font=("Consolas", 10), height=8)
        text_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        
        def process(ev=None):
            content = text_area.get("1.0", tk.END)
            top.destroy()
            
            # Simple unique file extraction
            files_to_open = set()
            for line in content.splitlines():
                if "TEST-UNEXPECTED" in line:
                    m = re.search(r"TEST-UNEXPECTED\s*\|\s*([^|]+)\s*\|", line)
                    if m:
                        test_path = m.group(1).strip()
                        files_to_open.add(test_path)
            
            if not files_to_open:
                messagebox.showerror("Error", "No valid paths found in the pasted data.")
                return
                
            cwd = self._cwd()
            meta_root = os.path.join(cwd, "testing", "web-platform", "meta")
            
            for test_path in sorted(list(files_to_open)):
                relative_meta = test_path.lstrip("/") + ".ini" # type: ignore
                meta_path = os.path.join(meta_root, relative_meta)
                if os.path.exists(meta_path):
                    self.open_wpt_editor(meta_path, os.path.basename(test_path))
                else:
                    self.process_queue.put(("log", f"\n> Skipping new file creation in Batch Mode: {relative_meta}\n"))
                    
        self._ok_cancel(top, process, lambda ev=None: top.destroy())

    def open_wpt_editor(self, meta_path, subtest_name):
        top = self._make_popup(f"WPT Editor: {os.path.basename(meta_path)}", 600)
        top.geometry("800x650")
        T = self.T

        toolbar = tk.Frame(top, bg=T["bg2"])
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        def insert_text(txt):
            # Dynamic Relative Indentation
            line_str = self._wpt_text.get("insert linestart", "insert")
            if not line_str.strip():
                # On a fresh line, look back for context
                prev_text = self._wpt_text.get("1.0", "insert")
                lines = [l for l in prev_text.split("\n") if l.strip()]
                if lines:
                    last_l = lines[-1]
                    # Calculate parent indentation
                    p_indent_len = len(last_l) - len(last_l.lstrip())
                    new_indent_len = p_indent_len
                    
                    # If parent was a header, go deeper
                    if last_l.strip().endswith("expected:") or (last_l.strip().startswith("[") and last_l.strip().endswith("]")):
                        new_indent_len += 2
                    
                    indent_str = " " * new_indent_len
                    if not line_str.startswith(indent_str):
                        self._wpt_text.insert("insert linestart", indent_str)
            
            self._wpt_text.insert(tk.INSERT, txt)

        def delete_line():
            self._wpt_text.delete("insert linestart", "insert lineend + 1c")

        btns = [
            ("win", 'if os == "win": '), ("mac", 'if os == "mac": '), ("linux", 'if os == "linux": '),
            ("android", 'if os == "android": '), ("debug", 'if debug: '), ("asan", 'if asan: '),
            ("FAIL", "FAIL"), ("PASS", "PASS"),
        ]
        for lbl, val in btns:
            ttk.Button(toolbar, text=lbl, width=8, command=lambda v=val: insert_text(v)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete Line", width=12, command=delete_line).pack(side=tk.RIGHT, padx=5)

        txt_frame = tk.Frame(top, bg=T["bg"])
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self._wpt_text = tk.Text(txt_frame, bg=T["term_bg"], fg=T["term_fg"], font=("Consolas", 10), undo=True)
        self._wpt_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(txt_frame, command=self._wpt_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._wpt_text.config(yscrollcommand=sb.set)

        with open(meta_path, "r", encoding="utf-8") as f:
            self._wpt_text.insert("1.0", f.read())

        query = f"[{subtest_name}]"
        pos = self._wpt_text.search(query, "1.0", tk.END, exact=True)
        if pos:
            exp_pos = self._wpt_text.search("expected:", pos, stopindex=f"{pos} + 5 lines")
            target = exp_pos if exp_pos else pos
            self._wpt_text.mark_set(tk.INSERT, target)
            self._wpt_text.see(target)
            self._wpt_text.tag_add("search", target + " linestart", target + " lineend")
            self._wpt_text.tag_config("search", background="#ffff00", foreground="#000000")
            self._wpt_text.focus_set()

        def save():
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(self._wpt_text.get("1.0", tk.END).strip() + "\n")
            top.destroy()
            self.execute_workflow("Save WPT & Diff", lambda: self.run_cmd(["git", "diff", meta_path]))

        ttk.Button(top, text="Save to File", command=save, width=20).pack(pady=(0, 15))

    # -----------------------------------------------------------------------
    # Automated Linting Fixes
    # -----------------------------------------------------------------------
    
    def do_lint_prettier(self):   self._run_lint("prettier")
    def do_lint_whitespace(self): self._run_lint("whitespace")
    def do_lint_black(self):      self._run_lint("black")

    def _run_lint(self, linter_type):
        top = self._make_popup(f"Mach Lint Fix: {linter_type.title()}", 320)
        
        # Bug Number
        tk.Label(top, text="Bug Number (e.g. 1234567):", bg=self.T["bg"], fg=self.T["fg"], font=("Helvetica", 11)).pack(pady=(15, 4))
        bug_entry = tk.Entry(top, bg=self.T["bg2"], fg=self.T["fg"], insertbackground=self.T["fg"], font=("Helvetica", 11), relief=tk.FLAT)
        bug_entry.pack(fill=tk.X, padx=20, ipady=4)
        
        path_lbl = tk.Label(top, text="Test Path(s) (space separated):", bg=self.T["bg"], fg=self.T["fg"], font=("Helvetica", 11))
        path_lbl.pack(pady=(14, 4))
        path_entry = tk.Entry(top, bg=self.T["bg2"], fg=self.T["fg"], insertbackground=self.T["fg"], font=("Helvetica", 11), relief=tk.FLAT)
        path_entry.pack(fill=tk.X, padx=20, ipady=4)
        
        def start_workflow():
            bug_no = bug_entry.get().strip()
            paths_str = path_entry.get().strip()
            top.destroy()
            
            if not bug_no or not paths_str:
                messagebox.showerror("Error", "Both Bug Number and Paths are required.")
                return

            paths = paths_str.split()
            cwd = self._cwd()
            mach = os.path.join(cwd, "mach")
            if not os.path.exists(mach):
                self.process_queue.put(("log", f"! Error: 'mach' executable not found in {cwd}. Automated linting requires a Firefox source tree.\n"))
                messagebox.showerror("Error", f"'mach' was not found in {cwd}.\n\nPlease ensure you are running this in a Firefox source repository.")
                return

            if platform.system() == "Windows":
                mach_cmd = ["python", mach]
            else:
                mach_cmd = [mach]

            def work():
                self.process_queue.put(("log", f"\n>>> Starting Automated {linter_type.upper()} Fix Workflow...\n"))
                
                # 1. git pull
                self.run_cmd(["git", "pull"])
                
                # 2. Run linter
                if linter_type == "prettier":
                    cmd = mach_cmd + ["lint", "--fix"] + paths
                elif linter_type == "whitespace":
                    cmd = mach_cmd + ["lint", "--linter", "file-whitespace", "--fix"] + paths
                else: # black
                    cmd = mach_cmd + ["lint", "-l", "black", "--fix"] + paths
                
                self.process_queue.put(("log", f"> Running: {' '.join(cmd)}\n"))
                # Linters often exit >0 if they fix things but leave warnings. We ignore exit code.
                subprocess.run(cmd, cwd=cwd, capture_output=True, env=self._build_env())
                
                # 3. Check for modifications
                status = subprocess.check_output(
                    ["git", "status", "--porcelain"] + paths,
                    cwd=cwd, text=True, env=self._build_env()
                ).strip()
                if not status:
                    self.process_queue.put(("log", "> No changes detected after linting. Nothing to commit.\n"))
                    return

                # 4. git add
                self.run_cmd(["git", "add"] + paths)
                
                # 5. Commit formatting
                suffix = "a=lint-fix"
                if len(paths) == 1:
                    basename = os.path.basename(paths[0])
                    msg = f"Bug {bug_no} - Fix lint failure in {basename} {suffix}"
                else:
                    msg = f"Bug {bug_no} - Fix lint failure {suffix}"
                
                self.run_cmd(["git", "commit", "-m", msg])
                self.process_queue.put(("log", f"> Committed: {msg}\n"))
                
                # 6. Push confirmation
                if self.ask_yes_no_threadsafe("Push to Lando?", f"Commit created:\n\n{msg}\n\nClick YES to push to Lando now.\nClick NO to keep locally and batch with other commits."):
                    branch = self.branch_var.get()
                    self.process_queue.put(("log", f"> Pushing to Lando (firefox-{branch})...\n"))
                    self._push_and_cleanup(branch)
                    self.process_queue.put(("log", ">>> Lint Fix Workflow Complete.\n"))
                else:
                    self.process_queue.put(("log", "> [Batch Mode] Push aborted. Commit kept locally.\n"))

            self.execute_workflow(f"Lint Fix ({linter_type.title()})", work)

        self._ok_cancel(top, start_workflow, lambda ev=None: top.destroy())

if __name__ == "__main__":
    app = TreeherderTool()
    app.mainloop()
