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
        self.geometry("900x720")
        self.minsize(800, 600)

        self._dark = is_dark_mode()
        self.T = build_theme(self._dark)

        self.configure(bg=self.T["bg"])
        self.process_queue = queue.Queue()
        self.is_running_command = False

        self.setup_ui()
        self.check_queue()

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

        self.repo_var = tk.StringVar(value=os.getcwd())
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
        self.branch_var = tk.StringVar(value="autoland")
        self.branch_dropdown = ttk.Combobox(
            top, textvariable=self.branch_var,
            values=["autoland", "main", "beta", "release", "esr140", "esr115"],
            state="readonly", width=12, font=("Helvetica", 11)
        )
        self.branch_dropdown.pack(side=tk.LEFT, padx=8)
        self.branch_dropdown.bind("<<ComboboxSelected>>", self.on_branch_change)

        # ---- Action buttons (2 × 4) ----
        btn_frame = tk.Frame(main, bg=T["bg"])
        btn_frame.pack(fill=tk.X, pady=(0, 18))

        defs = [
            ("Git Fetch",        self.do_fetch),
            ("Git Pull",         self.do_pull),
            ("Single Revert",    self.do_single_revert),
            ("Multiple Revert",  self.do_multiple_reverts),
            ("Cherry-Pick",      self.do_cherry_pick),
            ("Lando Merge",      self.do_merge),
            ("Lando Merge Back", self.do_push_merge_back),
            ("Lando Push",       self.do_lando_push),
        ]
        self.btn_widgets = []
        for text, cmd in defs:
            b = ttk.Button(btn_frame, text=text, command=cmd, width=15)
            self.btn_widgets.append(b)

        for idx, w in enumerate(self.btn_widgets):
            w.grid(row=idx // 4, column=idx % 4, padx=5, pady=5, sticky="ew")
        for i in range(4):
            btn_frame.columnconfigure(i, weight=1)

        # ---- Terminal ----
        tk.Label(main, text="Terminal Output:", bg=T["bg"], fg=T["fg"],
                 font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(6, 4))

        term_frame = tk.Frame(main, bg=T["bg"])
        term_frame.pack(fill=tk.BOTH, expand=True)

        self.terminal = tk.Text(
            term_frame, bg=T["term_bg"], fg=T["term_fg"],
            font=("Consolas", 10), state=tk.DISABLED, wrap=tk.WORD
        )
        self.terminal.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(term_frame, command=self.terminal.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.terminal.config(yscrollcommand=sb.set)

        self.terminal.tag_config("error",   foreground=T["err_fg"])
        self.terminal.tag_config("success", foreground=T["ok_fg"])
        self.terminal.tag_config("info",    foreground=T["info_fg"])
        self.terminal.tag_config("dim",     foreground=T["dim_fg"])

    # -----------------------------------------------------------------------
    # Queue / UI helpers
    # -----------------------------------------------------------------------

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
                    self.terminal.see(tk.END)
                    self.terminal.config(state=tk.DISABLED)
                elif msg_type == "alert":
                    messagebox.showerror("Execution Error", data)
                elif msg_type == "done":
                    self.is_running_command = False
                    self.set_buttons_state(tk.NORMAL)
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
    # Subprocess helpers
    # -----------------------------------------------------------------------

    def _cwd(self):
        return self.repo_var.get()

    def run_cmd(self, cmd, env=None, cwd=None):
        cwd = cwd or self._cwd()
        self.process_queue.put(("log", f"\n> {' '.join(cmd)}\n"))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=env, cwd=cwd)
        for line in proc.stdout:
            self.process_queue.put(("log", line))
        rc = proc.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)

    def get_output(self, cmd, env=None, cwd=None) -> str:
        cwd = cwd or self._cwd()
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

    def on_branch_change(self, _event):
        branch = self.branch_var.get()
        self.execute_workflow(f"Switch Branch → {branch}",
                              lambda: self.run_cmd(["git", "switch", branch]))

    def do_fetch(self):
        self.execute_workflow("Git Fetch", lambda: self.run_cmd(["git", "fetch"]))

    def do_pull(self):
        self.execute_workflow("Git Pull", lambda: self.run_cmd(["git", "pull"]))

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
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])

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
                lines = open(path, encoding='utf-8').readlines()
                if lines:
                    lines[0] = lines[0].rstrip('\\n') + ' ' + {reason_r} + '\\n'
                open(path, 'w', encoding='utf-8').writelines(lines)
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
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])

        self.execute_workflow("Multiple Reverts (Rebase & Squash)", logic)

    def do_merge(self):
        branch = self.branch_var.get()
        if branch == "main":
            src, tgt = "main", "autoland"
        elif branch == "autoland":
            src, tgt = "autoland", "main"
        else:
            messagebox.showwarning("Not Supported", "Merge is only between 'main' and 'autoland'.")
            return
        h = self.ask_input("Lando Merge", f"Target commit ({src} → {tgt}):")
        if not h: return
        self.execute_workflow("Lando Merge", lambda: self.run_cmd([
            "lando", "push-merge",
            "--lando-repo", f"firefox-{tgt}",
            "--target-commit", h,
            "--commit-message", f"Merge firefox-{src} to firefox-{tgt}",
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
            self.run_cmd(["git", "cherry-pick"] + h.replace(",", " ").split())
            self.run_cmd(["lando", "push-commits", "--lando-repo", f"firefox-{self.branch_var.get()}"])

        self.execute_workflow("Cherry-Pick", logic)

    def do_lando_push(self):
        branch = self.branch_var.get()
        self.execute_workflow("Lando Push", lambda: self.run_cmd([
            "lando", "push-commits", "--lando-repo", f"firefox-{branch}"
        ]))


if __name__ == "__main__":
    app = TreeherderTool()
    app.mainloop()
