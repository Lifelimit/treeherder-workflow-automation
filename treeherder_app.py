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
            bg="#1e1e1e",
            bg2="#2d2d2d",
            bg3="#3c3c3c",
            bg_active="#505050",
            fg="#d4d4d4",
            fg_btn="#ffffff",
            fg_disabled="#777777",
            term_bg="#000000",
            term_fg="#d4d4d4",
            err_fg="#ff5555",
            ok_fg="#55ff55",
            info_fg="#55ffff",
            dim_fg="#888888",
        )
    else:
        return dict(
            bg="#f0f0f0",
            bg2="#ffffff",
            bg3="#d0d0d0",
            bg_active="#b0b0b0",
            fg="#1a1a1a",
            fg_btn="#1a1a1a",
            fg_disabled="#999999",
            term_bg="#ffffff",
            term_fg="#1a1a1a",
            err_fg="#cc0000",
            ok_fg="#007700",
            info_fg="#0055cc",
            dim_fg="#555555",
        )


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
        self.after(500, lambda: self.attributes("-topmost", False))
        self.lift()
        self.focus_force()

        self._dark = is_dark_mode()
        self.T = build_theme(self._dark)

        self.configure(bg=self.T["bg"])
        self.process_queue = queue.Queue()
        self.is_running_command = False

        self.setup_ui()
        self.check_queue()
        # Check for stuck git state a moment after the window is ready
        self.after(500, self._startup_git_check)
        self.after(600, self._update_git_status)

    def setup_ui(self):
        T = self.T
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=T["bg"], foreground=T["fg"])
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

        default_repo = os.environ.get("TREEHERDER_TEST_REPO") or self._load_repo_path() or os.getcwd()
        self.repo_var = tk.StringVar(value=default_repo)
        self.repo_var.trace_add("write", lambda *args: self._save_repo_path(self.repo_var.get()))

        tk.Entry(top, textvariable=self.repo_var, bg=T["bg2"], fg=T["fg"],
                 insertbackground=T["fg"], font=("Helvetica", 11),
                 relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=4)

        def browse_repo():
            d = filedialog.askdirectory(initialdir=self.repo_var.get(),
                                        title="Select Firefox Repository")
            if d:
                self.repo_var.set(d)

        ttk.Button(top, text="Browse…", command=browse_repo).pack(side=tk.LEFT, padx=(0, 20))

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
        
        # Disable accidental mouse scroll
        def disable_scroll(event):
            return "break"
        self.branch_dropdown.bind("<MouseWheel>", disable_scroll)
        self.branch_dropdown.bind("<Button-4>", disable_scroll)
        self.branch_dropdown.bind("<Button-5>", disable_scroll)

        self.status_var = tk.StringVar(value="Status: ?")
        self.status_label = tk.Label(top, textvariable=self.status_var, bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 11, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=12)

        # ---- Action buttons (2 × 4) ----
        btn_frame = tk.Frame(main, bg=T["bg"])
        btn_frame.pack(fill=tk.X, pady=(0, 18))

        defs = [
            ("Git Fetch",        self.do_fetch),
            ("Git Pull",         self.do_pull),
            ("Git Hard Reset",   self.do_hard_reset),
            ("Single Revert",    self.do_single_revert),
            ("Multiple Revert",  self.do_multiple_reverts),
            ("Cherry-Pick",      self.do_cherry_pick),
            ("Lando Merge",      self.do_merge),
            ("Lando Merge Back", self.do_push_merge_back),
            ("Lando Push",       self.do_lando_push),
            ("View Git Log",     self.do_view_log),
        ]
        self.btn_widgets = []
        for text, cmd in defs:
            b = ttk.Button(btn_frame, text=text, command=cmd, width=15)
            self.btn_widgets.append(b)

        for idx, w in enumerate(self.btn_widgets):
            w.grid(row=idx // 3, column=idx % 3, padx=5, pady=5, sticky="ew")
        for i in range(3):
            btn_frame.columnconfigure(i, weight=1)

        # ---- Terminal ----
        lbl_frame = tk.Frame(main, bg=T["bg"])
        lbl_frame.pack(fill=tk.X, pady=(6, 4))
        tk.Label(lbl_frame, text="Terminal Output:", bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11, "bold")).pack(side=tk.LEFT)
                 
        def clear_terminal():
            self.terminal.config(state=tk.NORMAL)
            self.terminal.delete("1.0", tk.END)
            self.terminal.config(state=tk.DISABLED)

        ttk.Button(lbl_frame, text="Clear", command=clear_terminal).pack(side=tk.RIGHT, padx=(8, 0))

        self.progress = ttk.Progressbar(lbl_frame, mode="indeterminate", length=120)
        # We will pack it dynamically when running, or just leave it hidden
        self.progress.pack(side=tk.RIGHT, padx=10)
        self.progress.pack_forget()

        term_frame = tk.Frame(main, bg=T["bg"])
        term_frame.pack(fill=tk.BOTH, expand=True)

        self.terminal = tk.Text(
            term_frame, bg=T["term_bg"], fg=T["term_fg"],
            font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD,
            undo=True
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
        self.terminal.tag_bind("link", "<Enter>", lambda e: self.terminal.config(cursor="hand2"))
        self.terminal.tag_bind("link", "<Leave>", lambda e: self.terminal.config(cursor=""))

        # ---- Search bar below terminal ----
        search_f = tk.Frame(main, bg=T["bg"])
        search_f.pack(fill=tk.X, pady=(4, 0))
        
        tk.Label(search_f, text="Search Terminal:", bg=T["bg"], fg=T["dim_fg"], font=("Helvetica", 10)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_f, textvariable=self.search_var, bg=T["bg2"], fg=T["fg"], 
                                     insertbackground=T["fg"], font=("Helvetica", 10), relief=tk.FLAT, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=8, ipady=2)
        self.search_entry.bind("<Return>", lambda e: self._search_terminal())
        
        ttk.Button(search_f, text="Find", command=self._search_terminal, width=8).pack(side=tk.LEFT)
        ttk.Button(search_f, text="Next", command=lambda: self._search_terminal(forward=True), width=8).pack(side=tk.LEFT, padx=4)

    # -----------------------------------------------------------------------
    # Queue / UI helpers
    # -----------------------------------------------------------------------

    def _startup_git_check(self):
        """Run once at startup: warn user if repo has an in-progress git operation."""
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
        self.after(100, self.check_queue)

    def set_buttons_state(self, state):
        for b in self.btn_widgets:
            b.config(state=state)

    # -----------------------------------------------------------------------
    # Popup helpers  (main-thread blocking via wait_window)
    # -----------------------------------------------------------------------

    def _make_popup(self, title: str, h: int) -> tk.Toplevel:
        T = self.T
        top = tk.Toplevel(self)
        top.title(title)
        top.configure(bg=T["bg"])
        top.transient(self)
        top.grab_set()
        top.update_idletasks()
        w = 460
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
            v1, v2 = e1.get().strip(), e2.get().strip()
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

    # -----------------------------------------------------------------------
    # Subprocess/State helpers
    # -----------------------------------------------------------------------

    def _get_config_path(self) -> str:
        return os.path.expanduser("~/.treeherder_app.json")

    def _load_repo_path(self) -> str | None:
        conf = self._get_config_path()
        if os.path.exists(conf):
            try:
                with open(conf, "r") as f:
                    return json.load(f).get("repo_path")
            except Exception:
                pass
        return None

    def _save_repo_path(self, path: str):
        if not path: return
        try:
            with open(self._get_config_path(), "w") as f:
                json.dump({"repo_path": path}, f)
        except Exception:
            pass

    def _update_git_status(self):
        """Update the UI Status label to show ahead/behind/state."""
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
                elif ahead > 0:
                    self.status_var.set(f"Status: ↑ {ahead} unpushed")
                    self.status_label.config(fg=self.T["ok_fg"])
                elif behind > 0:
                    self.status_var.set(f"Status: ↓ {behind} behind")
                    self.status_label.config(fg=self.T["info_fg"])
                else:
                    self.status_var.set("Status: ✓ Clean")
                    self.status_label.config(fg=self.T["dim_fg"])
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
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                                text=True, env=env, cwd=cwd)
        is_interactive = cmd and cmd[0] == "lando"
        buf = ""
        while True:
            c = proc.stdout.read(1)
            if not c and proc.poll() is not None:
                if buf: self.process_queue.put(("log", buf))
                break
            if c:
                buf += c
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

    def execute_workflow(self, name: str, fn):
        if self.is_running_command:
            messagebox.showwarning("Busy", "A workflow is currently running.")
            return
        self.is_running_command = True
        self.set_buttons_state(tk.DISABLED)
        self.progress.pack(side=tk.RIGHT, padx=10)
        self.progress.start(15)

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
        return None

    def show_recovery_dialog(self, state: str, then_run):
        """Show a one-click recovery popup for an in-progress git state."""
        T = self.T
        abort_cmd  = {"revert": ["git", "revert", "--quit"],
                      "cherry-pick": ["git", "cherry-pick", "--abort"],
                      "merge": ["git", "merge", "--abort"]}.get(state, [])
        cont_cmd   = {"revert": ["git", "revert", "--continue"],
                      "cherry-pick": ["git", "cherry-pick", "--continue"],
                      "merge": ["git", "merge", "--continue"]}.get(state, [])

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
                self.process_queue.put(("dim", f"\n> Already on '{branch}'. Skipping switch.\n"))
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

        def logic():
            self.run_cmd(["git", "reset", "--hard", f"HEAD~{n}"])

        self.execute_workflow(f"Git Hard Reset (HEAD~{n})", logic)

    def do_single_revert(self):
        h = self.ask_input("Single Revert", "Changeset hash to revert:")
        if not h: return
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
            if not self.ask_yes_no_threadsafe("Verify Commit Message", f"Does this commit message look correct?\n\n{final_msg.strip()}\n\nClick Yes to push to Lando, or No to abort and keep it locally."):
                raise Exception("Push aborted by user. The revert commit is preserved locally for manual editing.")
            
            # Use lando to push, then drop the internal commit so we don't accidentally push it upstream later
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])
            self.run_cmd(["git", "reset", "--hard", "HEAD~1"])
            self.process_queue.put(("log", "\n> [Cleanup] Dropped local revert commit (HEAD~1) after successful lando push.\n"))

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
            if not self.ask_yes_no_threadsafe("Verify Commit Message", f"Does this squash commit message look correct?\n\n{final_msg.strip()}\n\nClick Yes to push to Lando, or No to abort and keep it locally."):
                raise Exception("Push aborted by user. The squashed commit is preserved locally for manual editing.")
                
            # Use lando to push, then drop the squash commit (rebase reduced it to 1 commit)
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])
            self.run_cmd(["git", "reset", "--hard", "HEAD~1"])
            self.process_queue.put(("log", "\n> [Cleanup] Dropped local squashed revert (HEAD~1) after successful lando push.\n"))

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
        h = self.ask_input("Cherry-Pick", "Changeset hash(es) to cherry-pick:")
        if not h: return

        def logic():
            self.run_cmd(["git", "pull"])
            hashes = h.replace(",", " ").split()
            self.run_cmd(["git", "cherry-pick"] + hashes)
            
            final_msg = self.get_output(["git", "log", "-1", "--pretty=%B"])
            if not self.ask_yes_no_threadsafe("Verify Cherry-Pick", f"Successfully cherry-picked {len(hashes)} commit(s).\n\nLatest commit message:\n{final_msg.strip()}\n\nClick Yes to push to Lando, or No to abort and keep them locally."):
                raise Exception("Push aborted by user. Cherry-picked commits preserved locally.")
            
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])
            self.run_cmd(["git", "reset", "--hard", f"HEAD~{len(hashes)}"])
            self.process_queue.put(("log", f"\n> [Cleanup] Dropped passed cherry-picks (HEAD~{len(hashes)}) after successful lando push.\n"))

        self.execute_workflow("Cherry-Pick", logic)

    def do_lando_push(self):
        branch = self.branch_var.get()
        def logic():
            self.run_cmd(["git", "pull"])
            
            count = "0"
            # Guard: check if we actually have any commits to push
            try:
                count = self.get_output(["git", "rev-list", "--count", f"origin/{branch}..HEAD"]).strip()
                if count == "0":
                    raise Exception(f"Guard failed: You have 0 local unpushed commits on '{branch}'. Aborting lando push.")
            except subprocess.CalledProcessError:
                # If origin doesn't exist or git command fails, just proceed and let lando try
                pass

            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{branch}"])
            if count != "0":
                self.run_cmd(["git", "reset", "--hard", f"HEAD~{count}"])
                self.process_queue.put(("log", f"\n> [Cleanup] Dropped {count} commits after successful standalone lando push.\n"))

        self.execute_workflow("Lando Push", logic)

    def do_view_log(self):
        try:
            author_email = subprocess.check_output(
                ["git", "config", "user.email"], cwd=self._cwd(), text=True
            ).strip()
        except Exception:
            author_email = ""

        top = self._make_popup("Recent Git Log", 450)
        # make it a bit wider
        top.geometry(f"700x450+{top.winfo_x()-100}+{top.winfo_y()}")

        T = self.T
        top.configure(bg=T["bg"])
        top.transient(self)

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

    def _linkify_terminal(self):
        """Scan the terminal for Phabricator Revisions (D123) and Bug IDs."""
        self.terminal.config(state=tk.NORMAL)
        # Search for patterns like D12345 or Bug 123456
        content = self.terminal.get("1.0", tk.END)
        
        # Clear existing link tags first
        self.terminal.tag_remove("link", "1.0", tk.END)

        patterns = [
            r"\bD\d{5,}\b",           # Phabricator Revision: D12345
            r"\bbug\s+\d{5,}\b",      # Bugzilla: bug 123456 (case insensitive usually)
            r"https?://\S+",          # Direct URLs
        ]

        for p in patterns:
            for m in re.finditer(p, content, re.IGNORECASE):
                start = f"1.0 + {m.start()} chars"
                end = f"1.0 + {m.end()} chars"
                self.terminal.tag_add("link", start, end)
        
        self.terminal.config(state=tk.DISABLED)

    def _on_link_click(self, event):
        """Handle clicking a link tag."""
        idx = self.terminal.index(f"@{event.x},{event.y}")
        # Get start and end of the tag
        range = self.terminal.tag_prevrange("link", idx + " + 1c")
        if not range: return
        text = self.terminal.get(*range).strip()
        
        url = ""
        if text.lower().startswith("http"):
            url = text
        elif text.lower().startswith("bug"):
            bug_id = re.search(r"\d+", text).group()
            url = f"https://bugzilla.mozilla.org/show_bug.cgi?id={bug_id}"
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

if __name__ == "__main__":
    app = TreeherderTool()
    app.mainloop()
