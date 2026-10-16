#!/usr/bin/env python3
"""
MySQL IDLE - an IDLE-style desktop shell for MySQL / MariaDB.

Looks and behaves like Python's IDLE: one white window, a menu bar on top,
and a live `mysql>` prompt where you type SQL. Results are printed as
mysql-style ASCII tables, and can also be opened in a sortable grid window.

Setup
-----
    pip install pymysql
    python mysql_idle.py          (do NOT name the file mysql.py or pymysql.py)

Build a desktop executable (no console window)
-----------------------------------------------
    pip install pyinstaller
    pyinstaller --clean mysql_idle.spec
    -> dist/mysql_idle/mysql_idle.exe

For a single-file executable instead, use:
    pyinstaller --noconsole --onefile mysql_idle.py

Notes
-----
* No password is stored in this file. You type it in the Connect dialog.
* Host / port / user / database are remembered in the per-user settings file.
  SQL command history remains in memory by default and is not persisted. Set
  MYSQLIDLE_SAVE_HISTORY=1 before launch to opt into SQL history persistence.
  Passwords are never saved.
* SQL runs on a dedicated worker thread so the window remains responsive.
* Query results are streamed in batches to a temporary CSV file; only a small
  preview is retained in RAM. Temporary result files are removed on normal exit.
* The shell keeps a bounded number of lines to prevent unbounded UI memory use.
* The `DELIMITER` command (stored-procedure scripts) is not supported.
* Tools > Android / Mobile Companion starts a temporary, paired web UI for Android.
"""

import csv
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from feature_governor import APPROVAL_TTL_SECONDS, FeatureGovernor
from sql_toolbox import explain_sql, format_sql, load_snippets, save_snippets
from password_auth import (
    MIN_PASSWORD_LENGTH as MIN_MASTER_PASSWORD_LENGTH,
    load_password_record,
    save_password_record,
    verify_password,
)

try:
    import pymysql
    PYMYSQL_IMPORT_ERROR = None
except Exception as _pymysql_exc:  # Show a friendly first-run error for source installs.
    pymysql = None
    PYMYSQL_IMPORT_ERROR = _pymysql_exc

APP_NAME = "MySQL IDLE"
APP_VERSION = "3.0"


def _resource_path(relative_path):
    """Resolve assets from source or the bundled PyInstaller application."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def _apply_window_icon(window):
    """Use the generated multi-size ICO where supported, avoiding DPI-induced blur."""
    icon_path = _resource_path(Path("assets") / "mysqlidle.ico")
    logo_path = _resource_path(Path("assets") / "mysqlidle-logo.png")
    icon_set = False
    if icon_path.is_file():
        try:
            window.iconbitmap(default=str(icon_path))
            icon_set = True
        except (tk.TclError, OSError):
            # Some Tk builds do not support ICO title-bar images.
            pass
    if not icon_set and logo_path.is_file():
        try:
            # PNG is a fallback for platforms that cannot use the Windows ICO.
            # Keep a strong reference so Tk does not garbage-collect the icon.
            window._mysqlidle_icon_photo = tk.PhotoImage(file=str(logo_path))
            window.iconphoto(True, window._mysqlidle_icon_photo)
        except (tk.TclError, OSError):
            # Title-bar icon is optional when assets are missing from a source install.
            pass


def _configure_ttk_style(root):
    """Prefer crisp native controls and consistent typography on each platform."""
    try:
        style = ttk.Style(root)
        available = set(style.theme_names())
        if os.name == "nt":
            preferred = ("vista", "xpnative", "clam")
        elif sys.platform == "darwin":
            preferred = ("aqua", "clam")
        else:
            preferred = ("clam", "alt", "default")
        theme = next((candidate for candidate in preferred if candidate in available), None)
        if theme and style.theme_use() != theme:
            style.theme_use(theme)

        families = set(tkfont.families(root))
        ui_family = "Segoe UI" if "Segoe UI" in families else "TkDefaultFont"
        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(font_name, root=root).configure(family=ui_family, size=10)
            except (tk.TclError, TypeError):
                pass

        style.configure("TButton", padding=(12, 7), font=(ui_family, 10))
        style.configure("TEntry", padding=(7, 5), font=(ui_family, 10))
        style.configure("TCheckbutton", padding=(3, 4), font=(ui_family, 10))
        style.configure("TCombobox", padding=(7, 5), font=(ui_family, 10))
        style.configure("Treeview", rowheight=27, font=(ui_family, 10))
        style.configure("Treeview.Heading", font=(ui_family, 10, "bold"))
        return style
    except (tk.TclError, OSError):
        return None


def get_app_data_dir():
    """Return a per-user writable config/data directory without admin rights."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "MySQL IDLE"
        return Path.home() / "AppData" / "Local" / "MySQL IDLE"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "mysql-idle"


APP_DATA_DIR = get_app_data_dir()
LOG_DIR = APP_DATA_DIR / "logs"
CONFIG_PATH = APP_DATA_DIR / "settings.json"
MASTER_PASSWORD_PATH = APP_DATA_DIR / "master_password.json"
SQL_SNIPPETS_PATH = APP_DATA_DIR / "sql_snippets.json"
LEGACY_CONFIG_PATH = Path.home() / ".mysql_idle.json"
# SQL text can contain literals or tokens. Disk persistence is opt-in.
SAVE_HISTORY = os.environ.get("MYSQLIDLE_SAVE_HISTORY", "").strip().lower() in {"1", "true", "yes"}
MAX_HISTORY = 200
TLS_PREFERENCE_SCHEMA_VERSION = 3
DEFAULT_MYSQL_TLS_VERIFY = False
MAX_SHELL_LINES = 20000
FETCH_BATCH_SIZE = 512
MAX_COMPLETION_IDENTIFIERS = 20000

PS1 = "mysql> "          # main prompt
PS2 = "    -> "          # continuation prompt
MAX_DISPLAY_ROWS = 1000  # rows retained for shell preview; full results are spooled to disk
MAX_GRID_ROWS = 5000     # rows loaded into the grid window
MAX_CELL_WIDTH = 80      # longer cell text is cut with "..." in the shell

KEYWORDS = """
ADD ALL ALTER AND AS ASC AUTO_INCREMENT AVG BEGIN BETWEEN BIGINT BOOLEAN BY CALL CASE CHARSET
COLUMN COLUMNS COMMIT CONSTRAINT COUNT CREATE CROSS DATABASE DATABASES DATE DATETIME DECIMAL
DEFAULT DELETE DESC DESCRIBE DISTINCT DOUBLE DROP ELSE END ENGINE EXISTS EXPLAIN FLOAT FOREIGN
FROM FULL FUNCTION GRANT GRANTS GROUP HAVING IDENTIFIED IF IN INDEX INNER INSERT INT INTO IS
JOIN KEY LEFT LIKE LIMIT MAX MIN NOT NOW NULL OFFSET ON OR ORDER OUTER PRIMARY PROCEDURE
PROCESSLIST REFERENCES RENAME REPLACE REVOKE RIGHT ROLLBACK SELECT SET SHOW STATUS SUM TABLE
TABLES TEXT THEN TIMESTAMP TRIGGER TRUNCATE UNION UNIQUE UPDATE USE USER USING VALUES VARCHAR
VARIABLES VIEW WHEN WHERE WITH
""".split()
KEYWORD_SET = set(KEYWORDS)

KW_RE = re.compile(
    r"\b(?:" + "|".join(sorted(KEYWORDS, key=len, reverse=True)) + r")\b", re.IGNORECASE
)
STR_RE = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"")
COMMENT_RE = re.compile(r"--[ \t].*|#.*")

_NAV_KEYS = {
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock",
    "Num_Lock", "Scroll_Lock", "Right", "End", "Prior", "Next", "Win_L", "Win_R",
    "Meta_L", "Meta_R", "Menu", "Insert", "Pause", "Print", "ISO_Level3_Shift",
}

HELP_TEXT = """\
Shell commands (no ';' needed):
  help            show this text
  clear / cls     clear the shell
  exit / quit     close the program
  \\c              cancel the statement you are typing

SQL statements end with ';' and may span several lines (the prompt changes
to '    ->' until the statement is finished).

Keys:
  Enter           run the statement      Shift+Enter  new line inside a statement
  Up / Down       command history        Alt+P / Alt+N  (same)
  Tab             autocomplete keywords, databases, tables and columns
  Esc             clear the current line
  Ctrl+N          connect                Ctrl+S  save shell log
  F5              run a .sql script      F6      show last result in a grid
  Ctrl+L          clear shell            Ctrl +/-  zoom text
  Ctrl+Shift+F    format current SQL      Ctrl+Shift+E  prepare EXPLAIN SELECT
  Ctrl+Shift+C    copy current SQL
  Ctrl+Break      cancel the active MySQL query (server permissions apply)

Tools:
  Android / Mobile Companion  use a phone browser on the same trusted private Wi-Fi
  Help > Check Environment    show runtime and diagnostic paths

Performance:
  Results stream in batches; only the first 1000 rows are shown in the shell.
  Full results are spooled to a temporary CSV for export; the grid loads at
  most 5000 rows. Old shell lines and command history are bounded in memory.
"""


# --------------------------------------------------------------------------
# Pure helper functions
# --------------------------------------------------------------------------

def split_sql(text):
    """Split text into complete ';'-terminated statements.

    Returns (statements, remainder). Quotes, backticks and comments are
    respected, so a ';' inside a string or comment does not end a statement.
    """
    statements, cur = [], []
    quote = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote:
            cur.append(c)
            if c == "\\" and quote != "`" and i + 1 < n:
                cur.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                # SQL also escapes quotes by doubling them: 'it''s; fine'.
                if i + 1 < n and text[i + 1] == quote:
                    cur.append(text[i + 1])
                    i += 2
                    continue
                quote = None
        elif c in "'\"`":
            quote = c
            cur.append(c)
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            cur.append(text[i:j])
            i = j
            continue
        elif c == "#" or (text.startswith("--", i) and (i + 2 >= n or text[i + 2] in " \t\r\n")):
            j = text.find("\n", i)
            j = n if j == -1 else j
            cur.append(text[i:j])
            i = j
            continue
        elif c == ";":
            statements.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    return [s for s in statements if s], "".join(cur)


def is_blank_sql(stmt):
    """True if the statement contains nothing but whitespace / line comments."""
    for line in stmt.splitlines():
        s = line.strip()
        if s and not s.startswith(("--", "#")):
            return False
    return True


def cell_to_str(value, limit=MAX_CELL_WIDTH):
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        try:
            s = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            s = "0x" + bytes(value).hex()
    else:
        s = str(value)
    s = s.replace("\r", "").replace("\n", "\\n").replace("\t", "\\t")
    if limit and len(s) > limit:
        s = s[: limit - 3] + "..."
    return s


def format_table(columns, rows):
    """Render rows like the classic mysql command-line client."""
    columns = [str(c) for c in columns]
    body = [[cell_to_str(v) for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep, "| " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)) + " |", sep]
    for raw, row in zip(rows, body):
        cells = []
        for i, text in enumerate(row):
            numeric = isinstance(raw[i], (int, float, Decimal))
            cells.append(text.rjust(widths[i]) if numeric else text.ljust(widths[i]))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


def quote_ident(name):
    """`db`.`table` style quoting; accepts 'table' or 'db.table'."""
    parts = [p.strip().strip("`") for p in name.split(".")]
    return ".".join("`" + p.replace("`", "``") + "`" for p in parts if p)


def fmt_error(exc):
    if len(exc.args) >= 2 and isinstance(exc.args[0], int):
        return f"ERROR {exc.args[0]}: {exc.args[1]}"
    return f"ERROR: {exc}"


def load_config():
    """Read current settings and migrate the older home-directory file once."""
    for candidate in (CONFIG_PATH, LEGACY_CONFIG_PATH):
        try:
            if not candidate.is_file():
                continue
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            # Defensive migration: connection passwords must never be persisted.
            last = data.get("last_connection")
            tls_preference_migrated = False
            if isinstance(last, dict):
                last.pop("password", None)
                # Normalize saved connection profiles when the TLS preference
                # contract changes. Version 3 makes certificate verification opt-in
                # again so upgrades do not retain a stale "verify" choice that blocks
                # local servers using a self-signed certificate. Users can still opt
                # into verification from Connect to MySQL and supply a trusted CA.
                if last.get("tls_verify_setting_version") != TLS_PREFERENCE_SCHEMA_VERSION:
                    last["tls_verify"] = DEFAULT_MYSQL_TLS_VERIFY
                    last["tls_verify_setting_version"] = TLS_PREFERENCE_SCHEMA_VERSION
                    tls_preference_migrated = True
            else:
                data.pop("last_connection", None)
            had_persisted_history = "history" in data
            if not SAVE_HISTORY:
                data.pop("history", None)
            elif not isinstance(data.get("history"), list):
                data["history"] = []
            else:
                data["history"] = [item for item in data["history"] if isinstance(item, str)][-MAX_HISTORY:]
            if candidate != CONFIG_PATH:
                save_config(data)
                if CONFIG_PATH.is_file():
                    try:
                        candidate.unlink()
                    except OSError:
                        logging.warning("Migrated settings, but could not remove legacy settings file %s", candidate)
            elif (had_persisted_history and not SAVE_HISTORY) or tls_preference_migrated:
                # Scrub old SQL history and migrate pre-versioned TLS preferences.
                save_config(data)
            return data
        except (OSError, ValueError, TypeError):
            logging.exception("Could not read settings from %s", candidate)
    return {}


def save_config(cfg):
    """Write preferences atomically; defensively strip credentials before disk I/O."""
    safe_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    last = safe_cfg.get("last_connection")
    if isinstance(last, dict):
        last = dict(last)
        last.pop("password", None)
        safe_cfg["last_connection"] = last
    history = safe_cfg.get("history")
    if not SAVE_HISTORY:
        safe_cfg.pop("history", None)
    elif history is None:
        safe_cfg.pop("history", None)
    elif isinstance(history, list):
        safe_cfg["history"] = [item for item in history if isinstance(item, str)][-MAX_HISTORY:]
    else:
        safe_cfg["history"] = []
    tmp_path = None
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=CONFIG_PATH.name + ".", suffix=".tmp", dir=str(CONFIG_PATH.parent))
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(safe_cfg, fh, indent=2)
            fh.write("\n")
        if os.name != "nt":
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
        os.replace(tmp_path, CONFIG_PATH)
    except OSError:
        logging.exception("Could not save MySQL IDLE settings")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _process_is_running(pid):
    """Return whether a process is live without using POSIX signal-0 semantics on Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows os.kill(pid, 0) is not a reliable POSIX-style liveness probe.
        # Query the process handle instead, conservatively treating unknown access
        # errors as "possibly running" so cleanup never deletes an active spool.
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            ERROR_INVALID_PARAMETER = 87
            ERROR_NOT_FOUND = 1168

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            open_process.restype = wintypes.HANDLE
            handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                error = ctypes.get_last_error()
                if error in (ERROR_INVALID_PARAMETER, ERROR_NOT_FOUND):
                    return False
                return True
            try:
                exit_code = wintypes.DWORD()
                get_exit_code = kernel32.GetExitCodeProcess
                get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
                get_exit_code.restype = wintypes.BOOL
                if not get_exit_code(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # Cleanup is destructive: preserve the directory if liveness is unknown.
            return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def _mark_temp_directory(path):
    try:
        (Path(path) / ".owner_pid").write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        logging.exception("Could not mark temporary directory ownership for %s", path)


def setup_runtime_environment():
    """Prepare per-user paths, rotating logs and writable temporary storage."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = (LOG_DIR / "application.log").resolve()
    if not any(isinstance(h, RotatingFileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == log_path
               for h in logging.getLogger().handlers):
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    # Verify temp storage now, so users get a friendly message instead of a late query failure.
    with tempfile.NamedTemporaryFile(prefix="mysql_idle_preflight_", dir=tempfile.gettempdir(), delete=True):
        pass
    # Remove only stale app-owned temp directories left after a crash, never recent results.
    cutoff = time.time() - 7 * 24 * 60 * 60
    for pattern in ("mysql_idle_mobile_*", "mysql_idle_results_*"):
        for stale in Path(tempfile.gettempdir()).glob(pattern):
            try:
                if not stale.is_dir() or stale.stat().st_mtime >= cutoff:
                    continue
                marker = stale / ".owner_pid"
                try:
                    owner_pid = int(marker.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    owner_pid = 0
                if owner_pid and _process_is_running(owner_pid):
                    continue
                shutil.rmtree(stale, ignore_errors=True)
            except OSError:
                logging.exception("Could not clean stale temporary result folder %s", stale)


def runtime_diagnostics():
    checks = [
        ("Application version", APP_VERSION),
        ("Python runtime", os.sys.version.split()[0]),
        ("Packaged executable", "yes" if getattr(os.sys, "frozen", False) else "running from source"),
        ("PyMySQL driver", getattr(pymysql, "__version__", "missing") if pymysql else "missing"),
        ("Settings directory", str(APP_DATA_DIR)),
        ("Diagnostic log", str(LOG_DIR / "application.log")),
        ("Temporary storage", tempfile.gettempdir()),
    ]
    return "\n".join(f"{label}: {value}" for label, value in checks)


# --------------------------------------------------------------------------
# Connect dialog
# --------------------------------------------------------------------------

class ConnectDialog(tk.Toplevel):
    # Keep the everyday connection form compact. Optional certificate controls live
    # under the collapsed "Advanced connection security" section.
    FIELDS = [
        ("Host", "host", False),
        ("Port", "port", False),
        ("User", "user", False),
        ("MySQL account password", "password", True),
        ("Database (optional)", "database", False),
    ]

    def __init__(self, parent, defaults, require_master_password=False):
        super().__init__(parent, bg="white", padx=12, pady=10)
        self.title("Connect to MySQL")
        _apply_window_icon(self)
        self.resizable(False, False)
        self.result = None
        self.require_master_password = bool(require_master_password)
        self.master_authenticated = not self.require_master_password
        self.master_auth_unavailable = False
        self.password_record = None
        self.master_attempts = 0
        self.master_password_var = None
        self.master_password_confirm_var = None
        self.vars = {}
        entries = {}

        if self.require_master_password:
            try:
                self.password_record = load_password_record(MASTER_PASSWORD_PATH)
            except (OSError, ValueError) as exc:
                logging.exception("Could not load the MySQL IDLE master-password verifier")
                self.master_auth_unavailable = True
                messagebox.showerror(
                    "Master password unavailable",
                    "The master-password record could not be read. Startup is blocked; "
                    "the password will not be reset automatically.\n\n" + str(exc),
                    parent=parent,
                )
                self.destroy()
                return

        # Use the original logo at native 96x96 size in a clean branded header.
        header = tk.Frame(self, bg="#0B182A", padx=12, pady=10)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        logo_path = _resource_path(Path("assets") / "mysqlidle-logo.png")
        self.logo_source_image = None
        self.logo_image = None
        if logo_path.is_file():
            try:
                self.logo_source_image = tk.PhotoImage(file=str(logo_path))
                self.logo_image = self.logo_source_image
                tk.Label(
                    header, image=self.logo_image, bg="#0B182A", bd=0,
                    highlightthickness=0,
                ).pack(side=tk.LEFT, padx=(0, 14))
            except (tk.TclError, OSError):
                self.logo_image = None
                self.logo_source_image = None

        header_copy = tk.Frame(header, bg="#0B182A", bd=0, highlightthickness=0)
        header_copy.pack(side=tk.LEFT, fill=tk.Y, expand=True, pady=(12, 0))
        tk.Label(
            header_copy, text="Connect to MySQL", bg="#0B182A", fg="#FFFFFF",
            font=("Segoe UI", 16, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header_copy, text="MySQL IDLE desktop workspace", bg="#0B182A",
            fg="#B9C8DD", font=("Segoe UI", 10), anchor="w",
        ).pack(anchor="w", pady=(5, 0))
        tk.Frame(self, bg="#DCE5F1", height=1, bd=0).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12)
        )

        row = 2
        self.master_password_entry = None
        self.master_password_confirm_entry = None
        self.first_master_setup = self.require_master_password and self.password_record is None
        if self.require_master_password:
            access = tk.LabelFrame(
                self, text="MySQL IDLE access", bg="white", padx=10, pady=8
            )
            access.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 10))
            row += 1

            master_label = (
                "Create master password" if self.first_master_setup else "Master password"
            )
            tk.Label(access, text=master_label, bg="white", anchor="e").grid(
                row=0, column=0, sticky="e", padx=(0, 10), pady=4
            )
            self.master_password_var = tk.StringVar()
            self.master_password_entry = ttk.Entry(
                access, textvariable=self.master_password_var, width=30, show="*"
            )
            self.master_password_entry.grid(row=0, column=1, sticky="ew", pady=4)

            visible = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                access, text="Show", variable=visible,
                command=lambda e=self.master_password_entry, v=visible: e.configure(
                    show="" if v.get() else "*"
                ),
            ).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=4)

            if self.first_master_setup:
                # Place confirmation immediately below the first entry so the
                # two-password setup reads as one clear, sequential step.
                tk.Label(access, text="Confirm master password", bg="white", anchor="e").grid(
                    row=1, column=0, sticky="e", padx=(0, 10), pady=4
                )
                self.master_password_confirm_var = tk.StringVar()
                self.master_password_confirm_entry = ttk.Entry(
                    access, textvariable=self.master_password_confirm_var, width=26, show="*"
                )
                self.master_password_confirm_entry.grid(row=1, column=1, sticky="ew", pady=4)
                confirm_visible = tk.BooleanVar(value=False)
                ttk.Checkbutton(
                    access, text="Show", variable=confirm_visible,
                    command=lambda e=self.master_password_confirm_entry, v=confirm_visible:
                        e.configure(show="" if v.get() else "*"),
                ).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)
                tk.Label(
                    access,
                    text=f"Use at least {MIN_MASTER_PASSWORD_LENGTH} characters. Type it again in the confirmation field. This is not your MySQL account password.",
                    bg="white", fg="#475569", wraplength=390, justify=tk.LEFT,
                ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 2))
            else:
                tk.Label(
                    access,
                    text="Enter the master password to unlock this app. It is verified locally and is not sent to MySQL.",
                    bg="white", fg="#475569", wraplength=390, justify=tk.LEFT,
                ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))
            access.columnconfigure(1, weight=1)

        tk.Label(
            self, text="MySQL connection", bg="white", fg="#0b182a",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1

        for offset, (label, key, secret) in enumerate(self.FIELDS):
            grid_row = row + offset
            tk.Label(self, text=label, bg="white", anchor="e").grid(
                row=grid_row, column=0, sticky="e", padx=(0, 10), pady=4
            )
            var = tk.StringVar(value=str(defaults.get(key, "")))
            entry = ttk.Entry(self, textvariable=var, width=30, show="*" if secret else "")
            entry.grid(row=grid_row, column=1, pady=4)
            self.vars[key] = var
            entries[key] = entry
            if secret:
                visible = tk.BooleanVar(value=False)
                ttk.Checkbutton(
                    self,
                    text="Show",
                    variable=visible,
                    command=lambda e=entry, v=visible: e.configure(
                        show="" if v.get() else "*"
                    ),
                ).grid(row=grid_row, column=2, sticky="w", padx=(8, 0), pady=4)
            elif key == "ssl_ca":
                ttk.Button(
                    self,
                    text="Browse…",
                    command=lambda v=var: self._browse_ca(v),
                ).grid(row=grid_row, column=2, sticky="w", padx=(8, 0), pady=4)

        # Optional CA/TLS controls are folded away for a smaller startup dialog.
        self.vars["ssl_ca"] = tk.StringVar(value=str(defaults.get("ssl_ca", "")))
        self.tls_verify = tk.BooleanVar(
            value=bool(defaults.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY))
        )
        self.advanced_open = bool(self.tls_verify.get() or self.vars["ssl_ca"].get().strip())
        self.advanced_caption = tk.StringVar()
        self.advanced_toggle = ttk.Button(
            self, textvariable=self.advanced_caption, command=self._toggle_advanced_tls
        )
        self.advanced_toggle_row = row + len(self.FIELDS)
        self.advanced_toggle.grid(
            row=self.advanced_toggle_row, column=0, columnspan=3,
            sticky="w", pady=(4, 0),
        )

        self.advanced_row = self.advanced_toggle_row + 1
        self.advanced_tls_frame = tk.Frame(self, bg="white", padx=2, pady=4)
        tk.Label(
            self.advanced_tls_frame, text="MySQL CA certificate (optional)",
            bg="white", fg="#334155", anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ca_entry = ttk.Entry(self.advanced_tls_frame, textvariable=self.vars["ssl_ca"], width=24)
        ca_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(
            self.advanced_tls_frame, text="Browse…",
            command=lambda v=self.vars["ssl_ca"]: self._browse_ca(v),
        ).grid(row=0, column=2, sticky="w", padx=(6, 0), pady=3)
        ttk.Checkbutton(
            self.advanced_tls_frame, text="Verify MySQL server certificate",
            variable=self.tls_verify,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 2))
        tk.Label(
            self.advanced_tls_frame,
            text="Certificate verification is optional and off by default for compatibility with local/self-signed servers.",
            bg="white", fg="#64748B", anchor="w", justify=tk.LEFT, wraplength=390,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 2))
        self.advanced_tls_frame.columnconfigure(1, weight=1)

        buttons = tk.Frame(self, bg="white")
        self.connect_buttons = buttons
        ttk.Button(buttons, text="Connect", command=self.on_ok).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=8)
        self.connect_button_row = self.advanced_row + (1 if self.advanced_open else 0)
        if self.advanced_open:
            self.advanced_tls_frame.grid(
                row=self.advanced_row, column=0, columnspan=3, sticky="ew", pady=(2, 2)
            )
        self.connect_buttons.grid(
            row=self.connect_button_row, column=0, columnspan=3, sticky="e", pady=(8, 0)
        )
        self._update_advanced_caption()

        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.destroy())
        if self.require_master_password and self.master_password_entry is not None:
            self.master_password_entry.focus_set()
        else:
            entries["password" if defaults.get("user") else "user"].focus_set()

        self.columnconfigure(1, weight=1)
        self.update_idletasks()
        self._center_on_screen()
        if parent.winfo_viewable():
            self.transient(parent)
        self.wait_visibility()
        self.grab_set()
        parent.wait_window(self)

    def _update_advanced_caption(self):
        marker = "▾" if self.advanced_open else "▸"
        self.advanced_caption.set(f"{marker} Advanced connection security")

    def _toggle_advanced_tls(self):
        self.advanced_open = not self.advanced_open
        self._update_advanced_caption()
        if self.advanced_open:
            self.advanced_tls_frame.grid(
                row=self.advanced_row, column=0, columnspan=3, sticky="ew", pady=(2, 2)
            )
            self.connect_buttons.grid_configure(row=self.advanced_row + 1)
        else:
            self.advanced_tls_frame.grid_remove()
            self.connect_buttons.grid_configure(row=self.advanced_row)
        self.update_idletasks()
        self._center_on_screen()

    def _center_on_screen(self):
        self.update_idletasks()
        if self.master.winfo_viewable():
            x = self.master.winfo_rootx() + (self.master.winfo_width() - self.winfo_width()) // 2
            y = self.master.winfo_rooty() + (self.master.winfo_height() - self.winfo_height()) // 3
        else:
            x = (self.winfo_screenwidth() - self.winfo_width()) // 2
            y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _browse_ca(self, variable):
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select MySQL CA certificate",
            filetypes=[("PEM certificates", "*.pem *.crt *.cer"), ("All files", "*.*")],
        )
        if selected:
            variable.set(selected)

    def on_ok(self):
        # Validate the non-secret connection fields before creating a master-password
        # record, so a simple port typo cannot leave the first-run form half-configured.
        values = {k: (v.get() if k == "password" else v.get().strip()) for k, v in self.vars.items()}
        values["tls_verify"] = bool(self.tls_verify.get())
        values["host"] = values["host"] or "localhost"
        try:
            values["port"] = int(values["port"] or 3306)
            if not 1 <= values["port"] <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid port", "Port must be an integer from 1 to 65535.", parent=self
            )
            return

        if self.require_master_password:
            master_password = self.master_password_var.get()
            if self.password_record is None:
                if not MIN_MASTER_PASSWORD_LENGTH <= len(master_password) <= 1024:
                    messagebox.showerror(
                        "Invalid master password",
                        f"Use between {MIN_MASTER_PASSWORD_LENGTH} and 1024 characters.",
                        parent=self,
                    )
                    self.master_password_entry.focus_set()
                    return
                confirmation = self.master_password_confirm_var.get()
                if master_password != confirmation:
                    messagebox.showerror(
                        "Passwords do not match",
                        "Enter the same master password in both master-password fields.",
                        parent=self,
                    )
                    self.master_password_confirm_entry.focus_set()
                    return
                try:
                    self.password_record = save_password_record(
                        MASTER_PASSWORD_PATH, master_password
                    )
                except (OSError, ValueError) as exc:
                    logging.exception("Could not save the MySQL IDLE master-password verifier")
                    messagebox.showerror(
                        "Could not save master password",
                        "MySQL IDLE cannot connect without saving the master-password verifier.\n\n"
                        + str(exc),
                        parent=self,
                    )
                    return
            elif not verify_password(master_password, self.password_record):
                self.master_attempts += 1
                remaining = 5 - self.master_attempts
                if remaining > 0:
                    messagebox.showerror(
                        "Incorrect master password",
                        f"The password did not match. {remaining} attempt(s) remain for this launch.",
                        parent=self,
                    )
                    self.master_password_entry.focus_set()
                else:
                    messagebox.showerror(
                        "Access denied",
                        "MySQL IDLE will close after five incorrect master-password attempts.",
                        parent=self,
                    )
                    self.destroy()
                return
            self.master_authenticated = True

        self.result = values
        self.destroy()


# --------------------------------------------------------------------------
# Serialized database worker
# --------------------------------------------------------------------------

class DatabaseWorker(threading.Thread):
    """Own the MySQL connection off the UI thread and stream result sets to disk."""

    def __init__(self, events, governor=None):
        super().__init__(name="mysql-idle-db", daemon=True)
        self.events = events
        self.governor = governor or FeatureGovernor()
        self.jobs = queue.Queue()
        self.conn = None
        self.conn_info = {}
        self.current_db = None
        self.identifiers = set()
        self._credentials = None  # In-memory only; never written to the config file.
        self._active_lock = threading.Lock()
        self._active_thread_id = None
        self._temp_dir = tempfile.TemporaryDirectory(prefix="mysql_idle_results_")
        _mark_temp_directory(self._temp_dir.name)
        self.start()

    def submit(self, kind, payload=None):
        self.jobs.put((kind, payload))

    def emit(self, kind, *payload):
        self.events.put((kind, *payload))

    def output(self, message, tag=None):
        self.emit("output", str(message), tag)

    def run(self):
        while True:
            kind, payload = self.jobs.get()
            try:
                if kind == "shutdown":
                    break
                if kind == "connect":
                    self._connect(payload)
                elif kind == "disconnect":
                    self._disconnect()
                elif kind == "query":
                    self._run_query_batch(**payload)
                elif kind == "script":
                    self._run_script(**payload)
                elif kind == "autocommit":
                    self._set_autocommit(payload)
                elif kind == "transaction":
                    self._transaction(payload)
                elif kind == "refresh":
                    self._refresh_state()
            except Exception as exc:
                logging.exception("Database worker operation %s failed", kind)
                self.output(fmt_error(exc) + "\n", "error")
            finally:
                self.jobs.task_done()
                if kind != "shutdown":
                    self.emit("task_done")
            if kind == "shutdown":
                break
        self._close_connection(emit_state=False)
        try:
            self._temp_dir.cleanup()
        except OSError:
            pass

    def _emit_connection_state(self):
        self.emit(
            "connection_state", self.conn is not None, dict(self.conn_info),
            self.current_db, set(self.identifiers),
        )

    def _connect(self, params):
        host = params.get("host") or "localhost"
        port = int(params.get("port") or 3306)
        user = params.get("user") or ""
        password = params.get("password") or ""
        database = params.get("database") or None
        autocommit = bool(params.get("autocommit", True))
        ssl_ca = str(params.get("ssl_ca") or "").strip()
        tls_verify = bool(params.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY))
        # A CA file is relevant only when certificate verification is explicitly
        # enabled. Ignore stale/optional CA paths in the default compatibility mode.
        if tls_verify and ssl_ca and not os.path.isfile(ssl_ca):
            self.output("MySQL CA certificate file was not found.\n", "error")
            return
        connection_options = {
            "host": host, "port": port, "user": user, "password": password,
            "database": database, "charset": "utf8mb4", "autocommit": autocommit,
            "connect_timeout": 10, "read_timeout": 60, "write_timeout": 10,
        }
        if tls_verify:
            connection_options.update(ssl_verify_cert=True, ssl_verify_identity=True)
            if ssl_ca:
                connection_options["ssl_ca"] = ssl_ca
        self.output(f"Connecting to {user}@{host}:{port} ...\n", "info")
        try:
            new_conn = pymysql.connect(**connection_options)
        except Exception as exc:
            self.output(fmt_error(exc) + "\n", "error")
            return

        old_conn = self.conn
        self.conn = new_conn
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
        self._credentials = {
            "host": host, "port": port, "user": user, "password": password,
            "ssl_ca": ssl_ca, "tls_verify": tls_verify,
        }
        self.conn_info = {
            "host": host, "port": port, "user": user, "database": database or "",
            "ssl_ca": ssl_ca, "tls_verify": tls_verify,
        }
        self.current_db = database
        self.identifiers = set()
        self._emit_connection_state()
        self.output(f"Connected. Server version: {new_conn.get_server_info()}\n", "ok")
        self._refresh_state()

    def _close_connection(self, emit_state=True):
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        self.conn_info = {}
        self.current_db = None
        self.identifiers = set()
        self._credentials = None
        with self._active_lock:
            self._active_thread_id = None
        if emit_state:
            self._emit_connection_state()

    def _disconnect(self):
        if self.conn is None:
            self.output("Not connected.\n", "info")
            return
        self._close_connection()
        self.output("Disconnected.\n", "info")

    @staticmethod
    def _csv_value(value):
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).decode("utf-8", "replace")
        return value

    @staticmethod
    def _preview_value(value):
        """Keep only bounded text in the in-memory preview, even for large BLOBs."""
        if value is None or isinstance(value, (int, float, Decimal)):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            length = len(value)
            prefix = bytes(value[:MAX_CELL_WIDTH]).decode("utf-8", "replace")
            return prefix[:MAX_CELL_WIDTH - 3] + "..." if length > MAX_CELL_WIDTH else prefix
        text = str(value)
        return text[:MAX_CELL_WIDTH - 3] + "..." if len(text) > MAX_CELL_WIDTH else text

    def _refresh_state(self):
        if self.conn is None:
            self._emit_connection_state()
            return
        try:
            names = set()
            with self.conn.cursor(pymysql.cursors.SSCursor) as cur:
                cur.execute("SELECT DATABASE()")
                row = cur.fetchone()
                self.current_db = row[0] if row else None

                cur.execute("SHOW DATABASES")
                while True:
                    batch = cur.fetchmany(FETCH_BATCH_SIZE)
                    if not batch:
                        break
                    for item in batch:
                        if len(names) < MAX_COMPLETION_IDENTIFIERS:
                            names.add(item[0])

                if self.current_db:
                    cur.execute(
                        "SELECT TABLE_NAME FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = DATABASE()"
                    )
                    while True:
                        batch = cur.fetchmany(FETCH_BATCH_SIZE)
                        if not batch:
                            break
                        for item in batch:
                            if len(names) < MAX_COMPLETION_IDENTIFIERS:
                                names.add(item[0])

                    cur.execute(
                        "SELECT DISTINCT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE()"
                    )
                    while True:
                        batch = cur.fetchmany(FETCH_BATCH_SIZE)
                        if not batch:
                            break
                        for item in batch:
                            if len(names) < MAX_COMPLETION_IDENTIFIERS:
                                names.add(item[0])
            self.identifiers = {name for name in names if isinstance(name, str)}
        except Exception as exc:
            self.output(f"Could not refresh autocomplete metadata: {fmt_error(exc)}\n", "info")
        self._emit_connection_state()

    def _run_query_batch(self, statements, stop_on_error=False, echo=False, script_name=None,
                         approved_statements=None):
        if script_name:
            self.output(f"-- running {script_name}: {len(statements)} statement(s)\n", "info")
        if self.conn is None:
            self.output("Not connected. Use File > Connect... (Ctrl+N).\n", "error")
            return

        # Bind approvals to this queued job (not shared global state), including
        # duplicate identical statements which each require their own confirmation.
        approved_expiries = {}
        for grant in approved_statements or ():
            try:
                approved_stmt, expires_at = grant
                expiry = float(expires_at)
            except (TypeError, ValueError):
                continue
            digest = self.governor._digest(approved_stmt)
            approved_expiries.setdefault(digest, []).append(expiry)

        completed = 0
        for index, stmt in enumerate(statements, start=1):
            digest = self.governor._digest(stmt)
            grants = approved_expiries.get(digest, [])
            expires_at = grants.pop(0) if grants else 0.0
            if not grants:
                approved_expiries.pop(digest, None)
            externally_approved = expires_at > time.monotonic()
            policy = self.governor.check_sql(stmt, externally_approved=externally_approved)
            if policy["decision"] != "allow":
                self.output(
                    f"Feature Governance stopped statement {index}: {policy['reason']} "
                    f"(risk: {policy['risk']}; fingerprint: {self.governor.fingerprint(stmt)}).\n",
                    "error",
                )
                # Fail closed: a batch never continues after a policy stop.
                return
            if echo:
                self.output(PS1 + stmt.rstrip().rstrip(";") + ";\n")
            ok = self._execute_statement(stmt)
            if not ok:
                if script_name:
                    self.output(
                        f"-- stopped at statement {index} of {len(statements)}\n", "error"
                    )
                if stop_on_error:
                    return
            else:
                completed += 1
        if script_name:
            self.output(f"-- finished: {completed} statement(s) executed\n", "ok")

    def _execute_statement(self, stmt):
        if self.conn is None:
            self.output("Not connected. Use File > Connect... (Ctrl+N).\n", "error")
            return False
        try:
            self.conn.ping(reconnect=False)
        except Exception as exc:
            self.output(f"Connection lost: {fmt_error(exc)}\n", "error")
            self._close_connection()
            return False

        started = time.perf_counter()
        spool_path = None
        try:
            with self.conn.cursor(pymysql.cursors.SSCursor) as cur:
                with self._active_lock:
                    self._active_thread_id = int(self.conn.thread_id())
                try:
                    cur.execute(stmt)
                    if cur.description:
                        columns = [str(item[0]) for item in cur.description]
                        preview = []
                        row_count = 0
                        handle = tempfile.NamedTemporaryFile(
                            mode="w", newline="", encoding="utf-8-sig",
                            prefix="result_", suffix=".csv", dir=self._temp_dir.name,
                            delete=False,
                        )
                        spool_path = handle.name
                        try:
                            with handle:
                                writer = csv.writer(handle)
                                writer.writerow(columns)
                                while True:
                                    batch = cur.fetchmany(FETCH_BATCH_SIZE)
                                    if not batch:
                                        break
                                    for row in batch:
                                        row_count += 1
                                        if len(preview) < MAX_DISPLAY_ROWS:
                                            preview.append(tuple(self._preview_value(value) for value in row))
                                        writer.writerow([self._csv_value(value) for value in row])
                        except Exception:
                            try:
                                os.unlink(spool_path)
                            except OSError:
                                pass
                            spool_path = None
                            raise
                        elapsed = time.perf_counter() - started
                        self.emit("result", columns, preview, row_count, elapsed, spool_path)
                    elif re.match(r"\s*use\b", stmt, re.IGNORECASE):
                        self.output("Database changed\n", "ok")
                    else:
                        affected = cur.rowcount
                        elapsed = time.perf_counter() - started
                        self.output(
                            f"Query OK, {affected} row{'s' if affected != 1 else ''} "
                            f"affected ({elapsed:.2f} sec)\n", "ok"
                        )
                finally:
                    with self._active_lock:
                        self._active_thread_id = None
        except Exception as exc:
            if spool_path:
                try:
                    os.unlink(spool_path)
                except OSError:
                    pass
            self.output(fmt_error(exc) + "\n", "error")
            return False

        if re.match(r"\s*(use|create|drop|alter|rename)\b", stmt, re.IGNORECASE):
            self._refresh_state()
        return True

    def _run_script(self, statements, name, approved_statements=None):
        self._run_query_batch(
            statements, stop_on_error=True, echo=True, script_name=name,
            approved_statements=approved_statements,
        )

    def _set_autocommit(self, enabled):
        if enabled and self.governor.read_only:
            message = (
                "Feature Governance blocked enabling auto-commit in read-only mode because it can "
                "commit pending changes. Roll back the transaction or disable read-only mode first.\n"
            )
            self.governor.record_decision(
                "SET autocommit=1", "block", message.strip(), "transaction", "high"
            )
            self.output(message, "error")
            return
        if self.conn is not None:
            try:
                self.conn.autocommit(bool(enabled))
            except Exception as exc:
                self.output(fmt_error(exc) + "\n", "error")
                return
        self.output(f"Auto-commit is {'ON' if enabled else 'OFF'}.\n", "info")

    def _transaction(self, action):
        if action == "commit" and self.governor.read_only:
            message = "Feature Governance blocked COMMIT in read-only mode; use Rollback if changes should be discarded."
            self.governor.record_decision("COMMIT", "block", message, "transaction", "high")
            self.output(message + "\n", "error")
            return
        if self.conn is None:
            self.output("Not connected.\n", "error")
            return
        try:
            getattr(self.conn, action)()
            self.output(f"{action.capitalize()} OK.\n", "ok")
        except Exception as exc:
            self.output(fmt_error(exc) + "\n", "error")

    def request_cancel(self, silent=False):
        """Cancel the active server query using a separate control connection."""
        threading.Thread(
            target=self._cancel_active_query, args=(silent,),
            name="mysql-idle-cancel", daemon=True,
        ).start()

    def _cancel_active_query(self, silent):
        # Hold the lock until KILL QUERY completes, preventing a race where the
        # worker advances to the next statement on the same MySQL connection.
        with self._active_lock:
            thread_id = self._active_thread_id
            credentials = dict(self._credentials or {})
            if not thread_id or not credentials:
                if not silent:
                    self.output("No running query to cancel.\n", "info")
                return
            control = None
            try:
                control_options = {
                    "host": credentials["host"], "port": credentials["port"],
                    "user": credentials["user"], "password": credentials["password"],
                    "charset": "utf8mb4", "autocommit": True,
                    "connect_timeout": 5, "read_timeout": 5, "write_timeout": 5,
                }
                if credentials.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY):
                    control_options.update(ssl_verify_cert=True, ssl_verify_identity=True)
                    if credentials.get("ssl_ca"):
                        control_options["ssl_ca"] = credentials["ssl_ca"]
                control = pymysql.connect(**control_options)
                with control.cursor() as cur:
                    cur.execute(f"KILL QUERY {int(thread_id)}")
                if not silent:
                    self.output("Cancellation request sent to MySQL.\n", "info")
            except Exception as exc:
                if not silent:
                    self.output(f"Could not cancel query: {fmt_error(exc)}\n", "error")
            finally:
                if control is not None:
                    try:
                        control.close()
                    except Exception:
                        pass

    def shutdown(self):
        # Drop queued work so closing the app will not execute commands later.
        while True:
            try:
                self.jobs.get_nowait()
                self.jobs.task_done()
            except queue.Empty:
                break
        self.submit("shutdown")


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class MySQLIDLE:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        if not SAVE_HISTORY:
            self.cfg.pop("history", None)

        self.governor = FeatureGovernor(self.cfg.get("feature_policy", {}))
        self.events = queue.Queue()
        self.worker = DatabaseWorker(self.events, self.governor)
        self.connected = False
        self.master_authenticated = False
        self.startup_connect_pending = True
        self._startup_reveal_pending = False
        self._startup_retry_defaults = None
        self._pending_startup_connect_error = None
        self.conn_info = {}
        self.current_db = None
        self.identifiers = set()      # database / table / column names for Tab completion
        self.pending = ""             # unfinished multi-line statement
        self.last_result = None       # {columns, row_count, path}; result rows are spooled to disk
        self.busy_count = 0
        self._closing = False
        self._persisted_connection = None
        self.mobile_server = None
        self._mobile_stopping = False

        # Previous sessions load history only when the explicit disk-persistence opt-in was enabled.
        self.history = list(self.cfg.get("history", []))[-MAX_HISTORY:]
        self.hist_idx = len(self.history)
        self.draft = ""

        root.title(APP_NAME)
        _apply_window_icon(root)
        _configure_ttk_style(root)
        root.geometry("1080x720")
        root.minsize(760, 500)
        root.configure(bg="#F5F8FC")

        families = set(tkfont.families())
        family = next((f for f in ("Consolas", "Menlo", "DejaVu Sans Mono") if f in families), "Courier New")
        self.font = tkfont.Font(family=family, size=11)
        self.autocommit = tk.BooleanVar(value=True)

        self.build_menu()
        self.build_ui()
        self.bind_keys()
        self.show_banner()
        self.new_prompt()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self.report_callback_exception
        root.after(50, self._poll_worker_events)

    # ----------------------------------------------------------------- UI --

    def build_menu(self):
        bar = tk.Menu(self.root)

        file_m = tk.Menu(bar, tearoff=0)
        file_m.add_command(label="Connect...", accelerator="Ctrl+N", command=self.connect_dialog)
        file_m.add_command(label="Disconnect", command=self.disconnect)
        file_m.add_separator()
        file_m.add_command(label="Run SQL Script...", accelerator="F5", command=self.run_script)
        file_m.add_command(label="Cancel Running Query", accelerator="Ctrl+Break", command=self.cancel_query)
        file_m.add_command(label="Save Shell Log...", accelerator="Ctrl+S", command=self.save_log)
        file_m.add_command(label="Save Last Result as CSV...", command=self.save_csv)
        file_m.add_separator()
        file_m.add_command(label="Exit", accelerator="Ctrl+Q", command=self.on_close)
        bar.add_cascade(label="File", menu=file_m)

        edit_m = tk.Menu(bar, tearoff=0)
        edit_m.add_command(label="Cut", accelerator="Ctrl+X", command=self.do_cut)
        edit_m.add_command(label="Copy", accelerator="Ctrl+C", command=self.do_copy)
        edit_m.add_command(label="Paste", accelerator="Ctrl+V", command=self.do_paste)
        edit_m.add_command(label="Select All", accelerator="Ctrl+A", command=self.do_select_all)
        edit_m.add_separator()
        edit_m.add_command(label="Format Current SQL", accelerator="Ctrl+Shift+F", command=self.format_current_sql)
        edit_m.add_command(label="Explain Current SELECT", accelerator="Ctrl+Shift+E", command=self.explain_current_sql)
        edit_m.add_command(label="Copy Current SQL", accelerator="Ctrl+Shift+C", command=self.copy_current_sql)
        edit_m.add_separator()
        edit_m.add_command(label="Save SQL Snippet...", command=self.save_sql_snippet)
        edit_m.add_command(label="Insert Saved SQL Snippet...", command=self.insert_sql_snippet)
        edit_m.add_separator()
        edit_m.add_command(label="Clear Shell", accelerator="Ctrl+L", command=self.clear_shell)
        bar.add_cascade(label="Edit", menu=edit_m)

        db_m = tk.Menu(bar, tearoff=0)
        db_m.add_command(label="Show Databases", command=lambda: self.inject("SHOW DATABASES;"))
        db_m.add_command(label="Use Database...", command=self.menu_use_database)
        db_m.add_command(label="Show Tables", command=lambda: self.inject("SHOW TABLES;"))
        db_m.add_command(label="Describe Table...", command=self.menu_describe_table)
        db_m.add_command(label="Show Processlist", command=lambda: self.inject("SHOW FULL PROCESSLIST;"))
        db_m.add_command(label="Server Info", command=lambda: self.inject(
            "SELECT VERSION() AS version, DATABASE() AS `database`, USER() AS user, "
            "@@hostname AS host, @@port AS port, @@character_set_server AS charset, "
            "@@autocommit AS autocommit;"))
        db_m.add_separator()
        db_m.add_command(label="Commit", command=self.do_commit)
        db_m.add_command(label="Rollback", command=self.do_rollback)
        bar.add_cascade(label="Database", menu=db_m)

        view_m = tk.Menu(bar, tearoff=0)
        view_m.add_command(label="Last Result in Grid Window", accelerator="F6", command=self.show_grid)
        view_m.add_separator()
        view_m.add_command(label="Zoom In", accelerator="Ctrl++", command=lambda: self.zoom(1))
        view_m.add_command(label="Zoom Out", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        view_m.add_command(label="Reset Zoom", accelerator="Ctrl+0", command=self.reset_zoom)
        bar.add_cascade(label="View", menu=view_m)

        opt_m = tk.Menu(bar, tearoff=0)
        opt_m.add_checkbutton(label="Auto-commit", variable=self.autocommit, command=self.toggle_autocommit)
        bar.add_cascade(label="Options", menu=opt_m)

        tools_m = tk.Menu(bar, tearoff=0)
        tools_m.add_command(label="Android / Mobile Companion...", command=self.show_mobile_companion)
        tools_m.add_command(label="Stop Mobile Companion", command=self.stop_mobile_companion, state=tk.DISABLED)
        tools_m.add_separator()
        tools_m.add_command(label="Feature Governance...", command=self.show_feature_governance)
        self.tools_menu = tools_m
        bar.add_cascade(label="Tools", menu=tools_m)

        help_m = tk.Menu(bar, tearoff=0)
        help_m.add_command(label="Commands and Keys", command=self.menu_help)
        help_m.add_command(label="Check Environment", command=self.show_diagnostics)
        help_m.add_command(label="About", command=self.menu_about)
        bar.add_cascade(label="Help", menu=help_m)

        self.root.config(menu=bar)

    def build_ui(self):
        # Application chrome: show the same untouched logo that appears in the README
        # and connection page. Display it at its original 96x96 pixels; do not scale it.
        header = tk.Frame(self.root, bg="#0B182A", padx=18, pady=10)
        header.pack(side=tk.TOP, fill=tk.X)
        self.brand_header = header
        logo_path = _resource_path(Path("assets") / "mysqlidle-logo.png")
        self.brand_logo_source = None
        self.brand_logo_image = None
        if logo_path.is_file():
            try:
                self.brand_logo_source = tk.PhotoImage(file=str(logo_path))
                self.brand_logo_image = self.brand_logo_source
                self.brand_logo_label = tk.Label(
                    header, image=self.brand_logo_image, bg="#0B182A", bd=0,
                    highlightthickness=0,
                )
                self.brand_logo_label.pack(side=tk.LEFT, padx=(0, 16))
            except (tk.TclError, OSError):
                self.brand_logo_source = None
                self.brand_logo_image = None
                self.brand_logo_label = None

        brand_copy = tk.Frame(header, bg="#0B182A", bd=0, highlightthickness=0)
        brand_copy.pack(side=tk.LEFT, fill=tk.Y, expand=False, pady=(12, 0))
        tk.Label(
            brand_copy, text="MySQL IDLE", bg="#0B182A", fg="#FFFFFF",
            font=("Segoe UI", 18, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand_copy, text="MySQL / MariaDB SQL workspace", bg="#0B182A",
            fg="#B9C8DD", font=("Segoe UI", 10), anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        brand_note = tk.Label(
            header, text="DESKTOP SQL WORKSPACE", bg="#0B182A", fg="#8FA8C8",
            font=("Segoe UI", 9, "bold"), padx=12, pady=7,
            bd=0, highlightthickness=0,
        )
        brand_note.pack(side=tk.RIGHT, anchor="center", padx=(8, 4))

        tk.Frame(self.root, bg="#263852", height=1, bd=0).pack(side=tk.TOP, fill=tk.X)

        status = tk.Frame(self.root, bg="#EAF0F7", padx=10, pady=5)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Not connected")
        self.hint_var = tk.StringVar()
        tk.Label(
            status, textvariable=self.status_var, bg="#EAF0F7", fg="#334155",
            anchor="w", padx=4, font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)
        tk.Label(
            status, textvariable=self.hint_var, bg="#EAF0F7", fg="#64748B",
            anchor="e", padx=4, font=("Segoe UI", 9),
        ).pack(side=tk.RIGHT)

        frame = tk.Frame(self.root, bg="#F5F8FC", padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(
            frame, wrap=tk.NONE, font=self.font, bg="#FFFFFF", fg="#172033",
            insertbackground="#2563EB", relief=tk.FLAT, undo=False, padx=14, pady=12,
            selectbackground="#C9DDFB", selectforeground="#14213A",
            highlightthickness=1, highlightbackground="#E2E8F0", highlightcolor="#93B4E8",
        )
        ys = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.text.yview)
        xs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        xs.pack(side=tk.BOTTOM, fill=tk.X)
        ys.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(fill=tk.BOTH, expand=True)

        t = self.text
        # Later tags have higher priority, like IDLE's colours.
        t.tag_configure("kw", foreground="#C45B0A")
        t.tag_configure("str", foreground="#16803C")
        t.tag_configure("comment", foreground="#B42318")
        t.tag_configure("prompt", foreground="#2457C5")
        t.tag_configure("error", foreground="#B42318")
        t.tag_configure("ok", foreground="#18794E")
        t.tag_configure("info", foreground="#64748B")
        t.tag_raise("sel")

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Cut", command=self.do_cut)
        self.context_menu.add_command(label="Copy", command=self.do_copy)
        self.context_menu.add_command(label="Paste", command=self.do_paste)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Clear Shell", command=self.clear_shell)

    def bind_keys(self):
        t = self.text
        t.bind("<Return>", self.on_return)
        t.bind("<KP_Enter>", self.on_return)
        t.bind("<BackSpace>", self.on_backspace)
        t.bind("<Left>", self.on_left)
        t.bind("<Home>", self.on_home)
        t.bind("<Up>", self.on_up)
        t.bind("<Down>", self.on_down)
        t.bind("<Alt-p>", self.on_up)
        t.bind("<Alt-n>", self.on_down)
        t.bind("<Tab>", self.on_tab)
        t.bind("<Escape>", self.on_escape)
        t.bind("<KeyPress>", self.on_keypress)
        t.bind("<KeyRelease>", self.on_keyrelease)
        t.bind("<<Paste>>", self.on_paste)
        t.bind("<Button-3>", self.on_context_menu)

        shortcuts = {
            "<Control-n>": self.connect_dialog,
            "<Control-s>": self.save_log,
            "<Control-q>": self.on_close,
            "<Control-l>": self.clear_shell,
            "<Control-Break>": self.cancel_query,
            "<Control-Shift-f>": self.format_current_sql,
            "<Control-Shift-e>": self.explain_current_sql,
            "<Control-Shift-c>": self.copy_current_sql,
            "<F5>": self.run_script,
            "<F6>": self.show_grid,
            "<Control-equal>": lambda: self.zoom(1),
            "<Control-plus>": lambda: self.zoom(1),
            "<Control-minus>": lambda: self.zoom(-1),
            "<Control-0>": self.reset_zoom,
        }
        for seq, fn in shortcuts.items():
            t.bind(seq, lambda e, fn=fn: (fn(), "break")[1])
        t.focus_set()

    # ------------------------------------------------------- text plumbing --

    def write(self, text, tag=None):
        self.text.insert("end-1c", text, (tag,) if tag else ())
        # Keep the widget bounded; long sessions must not grow the Text buffer forever.
        try:
            line_count = int(self.text.index("end-1c").split(".", 1)[0])
            if line_count > MAX_SHELL_LINES:
                self.text.delete("1.0", f"{line_count - MAX_SHELL_LINES + 1}.0")
        except (tk.TclError, ValueError):
            pass
        self.text.see("end")

    def new_prompt(self, continuation=False):
        self.write(PS2 if continuation else PS1, "prompt")
        t = self.text
        t.mark_set("input_start", "end-1c")
        t.mark_gravity("input_start", tk.LEFT)
        t.mark_set("insert", "end-1c")
        t.see("end")

    def set_input(self, text):
        t = self.text
        t.delete("input_start", "end-1c")
        t.insert("end-1c", text)
        t.mark_set("insert", "end-1c")
        t.see("end")
        self.highlight_input()

    def with_output(self, func):
        """Write asynchronous output without losing the editable input or caret."""
        t = self.text
        typed = t.get("input_start", "end-1c")
        cursor_offset = None
        selection_offsets = None
        try:
            if t.compare("insert", ">=", "input_start"):
                counted = t.count("input_start", "insert", "chars")
                cursor_offset = counted[0] if counted else len(typed)
            ranges = t.tag_ranges("sel")
            if len(ranges) >= 2 and t.compare(ranges[0], ">=", "input_start"):
                if t.compare(ranges[1], "<=", "end-1c"):
                    first = t.count("input_start", ranges[0], "chars")
                    last = t.count("input_start", ranges[1], "chars")
                    if first and last:
                        selection_offsets = (first[0], last[0])
        except tk.TclError:
            pass
        continuation = bool(self.pending)
        t.delete("input_start linestart", "end-1c")
        try:
            func()
        finally:
            self.new_prompt(continuation)
            if typed:
                self.set_input(typed)
                if cursor_offset is not None:
                    offset = max(0, min(cursor_offset, len(typed)))
                    t.mark_set("insert", f"input_start+{offset}c")
                if selection_offsets:
                    first, last = selection_offsets
                    t.tag_add(
                        "sel", f"input_start+{first}c",
                        f"input_start+{min(last, len(typed))}c",
                    )

    def fix_selection(self):
        """Keep edits inside the editable input area."""
        t = self.text
        if t.tag_ranges("sel") and t.compare("sel.first", "<", "input_start"):
            t.tag_remove("sel", "1.0", "end")
        if t.compare("insert", "<", "input_start"):
            t.mark_set("insert", "end-1c")

    def highlight_input(self):
        t = self.text
        for tag in ("kw", "str", "comment"):
            t.tag_remove(tag, "input_start", "end")
        s = t.get("input_start", "end-1c")
        if not s:
            return
        for tag, regex in (("kw", KW_RE), ("str", STR_RE), ("comment", COMMENT_RE)):
            for m in regex.finditer(s):
                t.tag_add(tag, f"input_start+{m.start()}c", f"input_start+{m.end()}c")

    def show_banner(self):
        version = getattr(pymysql, "__version__", "?")
        self.write(f"{APP_NAME} {APP_VERSION}  (PyMySQL {version})\n", "info")
        self.write("Type 'help' for commands. End SQL statements with ';'.  "
                   "Tab = autocomplete, Up/Down = history.\n\n", "info")

    def show_help(self):
        self.write(HELP_TEXT + "\n", "info")

    def clear_shell(self):
        self.text.delete("1.0", "end")
        self.pending = ""
        self.show_banner()
        self.new_prompt()

    # ------------------------------------------------------------ key events --

    def on_keypress(self, event):
        ks = event.keysym
        if ks in _NAV_KEYS or (ks.startswith("F") and ks[1:].isdigit()):
            return None
        printable = bool(event.char) and event.char >= " " and event.char != "\x7f"
        if (event.state & 0x4) and not printable:       # Ctrl+<key>
            if ks.lower() in ("c", "a"):
                return None
            if ks.lower() in ("x", "v"):
                self.fix_selection()
                return None
            return "break"                              # block emacs-style Ctrl keys
        self.fix_selection()
        return None

    def on_keyrelease(self, event):
        self.highlight_input()

    def on_return(self, event):
        self.fix_selection()
        if event.state & 0x1:                           # Shift+Enter: new line in statement
            self.text.insert("insert", "\n")
            return "break"
        self.submit()
        return "break"

    def on_backspace(self, event):
        t = self.text
        if t.tag_ranges("sel"):
            if t.compare("sel.first", "<", "input_start"):
                t.tag_remove("sel", "1.0", "end")
                return "break"
            return None
        if t.compare("insert", "<=", "input_start"):
            return "break"
        return None

    def on_left(self, event):
        if self.text.compare("insert", "<=", "input_start"):
            return "break"
        return None

    def on_home(self, event):
        self.text.mark_set("insert", "input_start")
        return "break"

    def on_escape(self, event):
        self.set_input("")
        return "break"

    def on_paste(self, event):
        self.fix_selection()
        return None

    def on_up(self, event):
        if not self.history:
            return "break"
        if self.hist_idx == len(self.history):
            self.draft = self.text.get("input_start", "end-1c")
        if self.hist_idx > 0:
            self.hist_idx -= 1
            self.set_input(self.history[self.hist_idx])
        return "break"

    def on_down(self, event):
        if self.hist_idx < len(self.history) - 1:
            self.hist_idx += 1
            self.set_input(self.history[self.hist_idx])
        elif self.hist_idx == len(self.history) - 1:
            self.hist_idx = len(self.history)
            self.set_input(self.draft)
        return "break"

    def on_tab(self, event):
        t = self.text
        self.fix_selection()
        before = t.get("input_start", "insert")
        m = re.search(r"[\w$]*$", before)
        prefix = m.group(0) if m else ""
        if not prefix:
            t.insert("insert", "    ")
            return "break"

        low = prefix.lower()
        pool = KEYWORD_SET | self.identifiers
        matches = sorted((w for w in pool if w.lower().startswith(low)), key=lambda w: (w.lower(), w))
        if not matches:
            self.hint_var.set("no completions")
            return "break"

        def styled(word):
            if word in KEYWORD_SET:
                return word if prefix.isupper() else word.lower()
            return word

        if len(matches) == 1:
            replacement = styled(matches[0])
            self.hint_var.set("")
        else:
            common = os.path.commonprefix([w.lower() for w in matches])
            replacement = styled(matches[0])[: len(common)]
            shown = "  ".join(matches[:12]) + ("  ..." if len(matches) > 12 else "")
            self.hint_var.set(shown)
        t.delete(f"insert-{len(prefix)}c", "insert")
        t.insert("insert", replacement)
        self.highlight_input()
        return "break"

    def on_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    # ------------------------------------------------------- edit actions --

    def do_cut(self):
        self.fix_selection()
        self.text.event_generate("<<Cut>>")

    def do_copy(self):
        self.text.event_generate("<<Copy>>")

    def do_paste(self):
        self.fix_selection()
        self.text.event_generate("<<Paste>>")

    def do_select_all(self):
        self.text.tag_add("sel", "1.0", "end-1c")

    def _current_sql(self):
        """Return only the editable statement, not the terminal transcript."""
        return self.text.get("input_start", "end-1c").strip()

    def format_current_sql(self):
        sql = self._current_sql()
        if not sql:
            self.status_var.set("Enter SQL before formatting.")
            return
        self.set_input(format_sql(sql))
        self.status_var.set("SQL formatted locally. Review it before execution.")

    def explain_current_sql(self):
        sql = self._current_sql()
        try:
            explained = explain_sql(sql)
        except ValueError as exc:
            messagebox.showwarning("Explain SELECT", str(exc), parent=self.root)
            return
        self.set_input(explained)
        self.status_var.set("EXPLAIN inserted. Review the statement, then press Enter to run it.")

    def copy_current_sql(self):
        sql = self._current_sql()
        if not sql:
            self.status_var.set("There is no current SQL statement to copy.")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(sql)
            self.root.update_idletasks()
            self.status_var.set("Current SQL copied to the clipboard.")
        except tk.TclError as exc:
            messagebox.showerror("Copy SQL", f"Could not access the clipboard.\n\n{exc}", parent=self.root)

    def save_sql_snippet(self):
        sql = self._current_sql()
        if not sql:
            messagebox.showinfo("Save SQL Snippet", "Enter a SQL statement first.", parent=self.root)
            return
        name = simpledialog.askstring(
            "Save SQL Snippet",
            "Name this snippet. Its SQL text will be stored locally on this computer; avoid saving secrets in SQL literals.",
            parent=self.root,
        )
        if name is None:
            return
        name = name.strip()
        if not name or len(name) > 80:
            messagebox.showerror("Save SQL Snippet", "Choose a name from 1 to 80 characters.", parent=self.root)
            return
        snippets = load_snippets(SQL_SNIPPETS_PATH)
        if name in snippets and not messagebox.askyesno(
            "Replace SQL Snippet", f"Replace the existing snippet \"{name}\"?", parent=self.root
        ):
            return
        snippets[name] = sql
        try:
            save_snippets(SQL_SNIPPETS_PATH, snippets)
        except (OSError, ValueError) as exc:
            logging.exception("Could not save SQL snippet")
            messagebox.showerror("Save SQL Snippet", str(exc), parent=self.root)
            return
        self.status_var.set(f"Saved SQL snippet: {name}")

    def insert_sql_snippet(self):
        snippets = load_snippets(SQL_SNIPPETS_PATH)
        if not snippets:
            messagebox.showinfo("Insert SQL Snippet", "No saved snippets were found on this computer.", parent=self.root)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Insert Saved SQL Snippet")
        _apply_window_icon(dialog)
        dialog.transient(self.root)
        dialog.configure(bg="#F5F8FC")
        outer = ttk.Frame(dialog, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="Saved SQL snippets", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        names = sorted(snippets, key=str.casefold)
        selected = tk.StringVar(value=names[0])
        selector = ttk.Combobox(outer, textvariable=selected, values=names, state="readonly")
        selector.pack(fill=tk.X, pady=(10, 10))
        preview = tk.Text(outer, height=8, width=62, wrap=tk.WORD, relief=tk.FLAT, padx=10, pady=8)
        preview.pack(fill=tk.BOTH, expand=True)

        def refresh_preview(_event=None):
            preview.configure(state=tk.NORMAL)
            preview.delete("1.0", tk.END)
            preview.insert("1.0", snippets.get(selected.get(), ""))
            preview.configure(state=tk.DISABLED)

        def insert_selected():
            sql = snippets.get(selected.get())
            if sql:
                self.set_input(sql)
                self.status_var.set(f"Inserted SQL snippet: {selected.get()}")
            dialog.destroy()

        selector.bind("<<ComboboxSelected>>", refresh_preview)
        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Insert into editor", command=insert_selected).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        refresh_preview()
        dialog.geometry("560x360")
        dialog.minsize(480, 300)
        dialog.grab_set()
        dialog.focus_set()

    def zoom(self, delta):
        self.font.configure(size=max(6, min(40, int(self.font.cget("size")) + delta)))

    def reset_zoom(self):
        self.font.configure(size=11)

    # ------------------------------------------------------ run statements --

    def submit(self):
        t = self.text
        line = t.get("input_start", "end-1c")
        t.mark_set("insert", "end-1c")
        t.insert("end-1c", "\n")
        t.see("end")
        self.hint_var.set("")
        self.process(line)

    def process(self, line):
        stripped = line.strip()
        if stripped and (not self.history or self.history[-1] != stripped):
            self.history.append(stripped)
            if len(self.history) > MAX_HISTORY:
                del self.history[:len(self.history) - MAX_HISTORY]
        self.hist_idx = len(self.history)
        self.draft = ""

        if stripped == "\\c":
            self.pending = ""
            self.write("Statement cancelled.\n", "info")
            self.new_prompt()
            return

        word = stripped.lower().rstrip(";").strip()
        if not self.pending.strip():
            if word in ("exit", "quit", "\\q"):
                self.on_close()
                return
            if word in ("clear", "cls"):
                self.clear_shell()
                return
            if word in ("help", "\\h", "?"):
                self.show_help()
                self.new_prompt()
                return

        self.pending += line + "\n"
        statements, rest = split_sql(self.pending)
        self.pending = rest if rest.strip() else ""
        complete = [stmt for stmt in statements if not is_blank_sql(stmt)]
        if complete:
            approved_statements = self._preflight_statements(complete, source="interactive query")
            if approved_statements is not None:
                self._queue_job("query", {
                    "statements": complete, "stop_on_error": False,
                    "echo": False, "script_name": None,
                    "approved_statements": approved_statements,
                })
        self.new_prompt(continuation=bool(self.pending))

    def _preflight_statements(self, statements, source="query"):
        """Return approvals scoped to one queued job, or None if it should not run."""
        approvals = []
        for stmt in statements:
            policy = self.governor.inspect_sql(stmt)
            digest = self.governor.fingerprint(stmt)
            if policy["decision"] == "block":
                self.governor.record_decision(stmt, "block", str(policy["reason"]),
                                              str(policy["category"]), str(policy["risk"]))
                messagebox.showwarning(
                    "Feature Governance",
                    f"Blocked by current policy.\n\n{policy['reason']}\n\n"
                    f"Risk: {policy['risk']} | Statement fingerprint: {digest}",
                    parent=self.root,
                )
                self.write(f"Feature Governance blocked a statement ({digest}).\n", "error")
                return None
            if policy["decision"] == "confirm":
                approved = messagebox.askyesno(
                    "Confirm high-impact SQL",
                    f"MySQL IDLE detected a high-impact statement in {source}.\n\n"
                    f"Risk category: {policy['category']}\nRisk level: {policy['risk']}\n"
                    f"Reason: {policy['reason']}\n\n"
                    f"Statement fingerprint: {digest}\n\n"
                    "Approve this exact statement once?",
                    icon="warning",
                    parent=self.root,
                )
                if not approved:
                    self.governor.record_decision(stmt, "cancelled", "User declined high-impact SQL.",
                                                  str(policy["category"]), str(policy["risk"]))
                    self.write("High-impact SQL cancelled by Feature Governance.\n", "info")
                    return None
                approvals.append((stmt, time.monotonic() + APPROVAL_TTL_SECONDS))
        return approvals

    def show_result(self, columns, rows, row_count, elapsed):
        if row_count == 0:
            self.write(f"Empty set ({elapsed:.2f} sec)\n", "info")
            return
        self.write(format_table(columns, rows[:MAX_DISPLAY_ROWS]) + "\n")
        self.write(f"{row_count} row{'s' if row_count != 1 else ''} in set ({elapsed:.2f} sec)\n", "ok")
        if row_count > MAX_DISPLAY_ROWS:
            self.write(
                f"(showing the first {MAX_DISPLAY_ROWS} rows; full result streamed to a temporary file "
                "for CSV export)\n", "info"
            )

    def _queue_job(self, kind, payload=None):
        if self._closing:
            return
        self.busy_count += 1
        self.hint_var.set("Working in background..." if self.busy_count == 1 else f"{self.busy_count} tasks queued")
        self.worker.submit(kind, payload)

    def _poll_worker_events(self):
        if self._closing:
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "output":
                    message, tag = event[1], event[2]
                    if self._startup_reveal_pending and tag == "error":
                        self._pending_startup_connect_error = message
                    else:
                        self.with_output(lambda message=message, tag=tag: self.write(message, tag))
                elif kind == "result":
                    columns, preview, row_count, elapsed, path = event[1:]
                    previous = self.last_result
                    self.last_result = {"columns": columns, "row_count": row_count, "path": path}
                    if previous and previous.get("path") and previous["path"] != path:
                        try:
                            os.unlink(previous["path"])
                        except OSError:
                            pass
                    self.with_output(
                        lambda: self.show_result(columns, preview, row_count, elapsed)
                    )
                elif kind == "connection_state":
                    connected, info, current_db, identifiers = event[1:]
                    self.connected = connected
                    self.conn_info = info
                    self.current_db = current_db
                    self.identifiers = identifiers
                    if connected and self._startup_reveal_pending:
                        self._startup_reveal_pending = False
                        self._pending_startup_connect_error = None
                        self._startup_retry_defaults = None
                        self.root.deiconify()
                        self.root.lift()
                        self.text.focus_set()
                    if connected:
                        saved = {
                            "host": info.get("host", "localhost"),
                            "port": info.get("port", 3306),
                            "user": info.get("user", ""),
                            "database": info.get("database", "") or "",
                            "ssl_ca": info.get("ssl_ca", "") or "",
                            "tls_verify": bool(info.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY)),
                            "tls_verify_setting_version": TLS_PREFERENCE_SCHEMA_VERSION,
                        }
                        signature = tuple(saved.items())
                        if signature != self._persisted_connection:
                            self.cfg["last_connection"] = saved
                            save_config(self.cfg)
                            self._persisted_connection = signature
                    self.update_status()
                elif kind == "task_done":
                    self.busy_count = max(0, self.busy_count - 1)
                    if self.busy_count == 0:
                        self.hint_var.set("")
                    else:
                        self.hint_var.set(f"{self.busy_count} tasks queued")
                    if (
                        self.busy_count == 0
                        and self._startup_reveal_pending
                        and self._pending_startup_connect_error
                    ):
                        self.root.after_idle(self._handle_startup_connection_failure)
        except queue.Empty:
            pass
        finally:
            if not self._closing:
                self.root.after(40, self._poll_worker_events)

    # ------------------------------------------------------------ connection --

    def _handle_startup_connection_failure(self):
        """Keep startup on the compact connect dialog when a database connection fails."""
        if (
            self._closing
            or not self._startup_reveal_pending
            or self.connected
            or not self._pending_startup_connect_error
        ):
            return
        error_message = self._pending_startup_connect_error.strip()
        retry_defaults = dict(self._startup_retry_defaults or {})
        self._pending_startup_connect_error = None
        self._startup_reveal_pending = False
        messagebox.showerror(
            "Could not connect to MySQL",
            error_message or "The connection failed. Check the server details and try again.",
            parent=self.root,
        )
        if not self._closing:
            self.root.after_idle(
                lambda defaults=retry_defaults: self.connect_dialog(defaults_override=defaults)
            )

    def connect_dialog(self, defaults_override=None):
        defaults = {
            "host": "localhost", "port": "3306", "user": "root", "password": "",
            "database": "", "ssl_ca": "", "tls_verify": DEFAULT_MYSQL_TLS_VERIFY,
        }
        defaults.update(self.cfg.get("last_connection", {}))
        if defaults_override:
            defaults.update(defaults_override)

        initial_page = self.startup_connect_pending
        shell_was_hidden = not self.root.winfo_viewable()
        dialog = ConnectDialog(
            self.root, defaults, require_master_password=initial_page
        )
        if dialog.master_authenticated:
            self.master_authenticated = True
        if dialog.result:
            # Master-password setup/verification occurs on this compact page. The
            # large SQL workspace stays withdrawn until the database server accepts
            # the connection, not merely until the form is submitted.
            if initial_page and dialog.master_authenticated:
                self.startup_connect_pending = False
            self._pending_startup_connect_error = None
            if shell_was_hidden:
                self._startup_retry_defaults = dict(dialog.result)
                self._startup_reveal_pending = True
            else:
                self._startup_retry_defaults = None
                self._startup_reveal_pending = False
            self.connect(**dialog.result)
            if not shell_was_hidden:
                self.text.focus_set()
        elif initial_page or shell_was_hidden:
            # Canceling startup must not leave a hidden, still-running app process.
            self.on_close()
        else:
            self.text.focus_set()

    def connect(self, host, port, user, password, database, ssl_ca="", tls_verify=DEFAULT_MYSQL_TLS_VERIFY):
        self._queue_job("connect", {
            "host": host, "port": port, "user": user, "password": password,
            "database": database, "ssl_ca": ssl_ca, "tls_verify": bool(tls_verify),
            "autocommit": self.autocommit.get(),
        })

    def disconnect(self):
        self._queue_job("disconnect")

    def update_status(self):
        if not self.connected:
            self.status_var.set("Not connected")
            self.root.title(APP_NAME)
            return
        info = self.conn_info
        db = self.current_db or "(none)"
        self.status_var.set(f"{info.get('user', '')}@{info.get('host', '')}:{info.get('port', '')}    |    database: {db}")
        self.root.title(f"{APP_NAME} - {info.get('user', '')}@{info.get('host', '')}/{self.current_db or ''}")

    def toggle_autocommit(self):
        enabled = bool(self.autocommit.get())
        if enabled and self.governor.read_only:
            self.autocommit.set(False)
            message = (
                "Read-only mode prevents enabling auto-commit because MySQL may commit pending "
                "changes. Roll back the current transaction or disable read-only mode first."
            )
            self.governor.record_decision("SET autocommit=1", "block", message, "transaction", "high")
            messagebox.showwarning("Feature Governance", message, parent=self.root)
            return
        self._queue_job("autocommit", enabled)

    def do_commit(self):
        self._txn("commit")

    def do_rollback(self):
        self._txn("rollback")

    def _txn(self, action):
        self._queue_job("transaction", action)

    def cancel_query(self):
        self.worker.request_cancel()

    # --------------------------------------------------------- menu actions --

    def inject(self, sql):
        """Type a statement into the prompt and run it, as if the user had typed it."""
        self.pending = ""
        self.with_output(lambda: None)      # fresh 'mysql> ' prompt
        self.set_input(sql)
        self.submit()
        self.text.focus_set()

    def menu_use_database(self):
        name = simpledialog.askstring("Use Database", "Database name:", parent=self.root)
        if name and name.strip():
            self.inject(f"USE {quote_ident(name)};")

    def menu_describe_table(self):
        name = simpledialog.askstring("Describe Table", "Table name:", parent=self.root)
        if name and name.strip():
            self.inject(f"DESCRIBE {quote_ident(name)};")

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        logging.error("Unhandled user-interface callback exception", exc_info=(exc_type, exc_value, exc_traceback))
        try:
            messagebox.showerror(
                f"{APP_NAME} encountered an error",
                f"{exc_value}\n\nDetails were saved to the application log in:\n{LOG_DIR}",
                parent=self.root,
            )
        except tk.TclError:
            pass

    def show_diagnostics(self):
        messagebox.showinfo(f"{APP_NAME} Environment Check", runtime_diagnostics(), parent=self.root)

    def show_feature_governance(self):
        """Expose runtime policy controls and a redacted, bounded audit view."""
        win = tk.Toplevel(self.root, bg="white", padx=16, pady=14)
        win.title("MySQL IDLE Feature Governance")
        win.geometry("720x560")
        win.minsize(580, 420)
        win.transient(self.root)

        tk.Label(win, text="Runtime policy controls", bg="white",
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            win,
            text="Policies apply to Windows SQL execution and the paired Android companion. "
                 "High-impact statements require one-time approval. The audit trail stores only a "
                 "statement fingerprint and decision, never SQL text or credentials.",
            bg="white", fg="#555555", justify=tk.LEFT, wraplength=680, anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        read_only_var = tk.BooleanVar(value=self.governor.read_only)
        mobile_var = tk.BooleanVar(value=self.governor.mobile_companion_enabled)
        ttk.Checkbutton(
            win, text="Read-only mode — block writes, schema changes and administrative SQL",
            variable=read_only_var,
        ).pack(anchor="w", pady=3)
        ttk.Checkbutton(
            win, text="Allow Android / Mobile Companion",
            variable=mobile_var,
        ).pack(anchor="w", pady=3)

        notes = self.governor.forced_policy_notes
        notes_text = "Environment overrides: " + (" ".join(notes) if notes else "none")
        tk.Label(win, text=notes_text, bg="white", fg="#7c2d12",
                 wraplength=680, justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=(4, 10))

        tk.Label(win, text="Recent policy decisions (newest at bottom)", bg="white",
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill=tk.X)
        audit = tk.Text(win, height=14, wrap=tk.WORD, state=tk.DISABLED,
                        font=("Consolas", 9), bg="#f7f9fc", relief=tk.SOLID, borderwidth=1)
        audit.pack(fill=tk.BOTH, expand=True, pady=(5, 10))

        def refresh_audit():
            events = self.governor.audit_events(60)
            audit.configure(state=tk.NORMAL)
            audit.delete("1.0", tk.END)
            for item in events:
                audit.insert(
                    tk.END,
                    f"{item['time']} | {item['decision'].upper()} | "
                    f"{item['category']}/{item['risk']} | {item['reason']} "
                    f"[{item['statement_digest']}]\n",
                )
            if not events:
                audit.insert(tk.END, "No policy events in this session yet.\n")
            audit.configure(state=tk.DISABLED)

        def apply_policy():
            self.governor.set_policy(
                read_only=read_only_var.get(),
                mobile_companion_enabled=mobile_var.get(),
            )
            self.cfg["feature_policy"] = self.governor.snapshot()
            save_config(self.cfg)
            read_only_var.set(self.governor.read_only)
            mobile_var.set(self.governor.mobile_companion_enabled)
            if not self.governor.mobile_companion_enabled and self.mobile_server is not None:
                self.stop_mobile_companion()
            self.with_output(lambda: self.write(
                "Feature Governance policy updated: "
                f"{'READ-ONLY' if self.governor.read_only else 'GUARDED'} mode; "
                f"mobile companion {'enabled' if self.governor.mobile_companion_enabled else 'disabled'}.\n",
                "info",
            ))
            refresh_audit()

        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Refresh audit", command=refresh_audit).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Apply policy", command=apply_policy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side=tk.RIGHT, padx=8)
        refresh_audit()
        win.grab_set()

    def show_mobile_companion(self):
        if self._mobile_stopping:
            messagebox.showinfo("Mobile Companion", "The previous mobile session is still shutting down. Try again in a moment.", parent=self.root)
            return
        if not self.governor.feature_enabled("mobile_companion"):
            messagebox.showwarning(
                "Feature Governance",
                "The Android / Mobile Companion is disabled by the current feature policy.",
                parent=self.root,
            )
            return
        if self.mobile_server and self.mobile_server.running:
            self._show_mobile_companion_dialog()
            return
        consent = messagebox.askyesno(
            "Enable Android / Mobile Companion",
            "This starts a temporary web interface on your local network so an Android phone can run SQL through this computer.\n\n"
            "Security note: the phone must enter the same MySQL IDLE master password you set on this Windows computer, as well as the temporary pairing code. HTTPS uses certificate fingerprint verification. Enable it only on a trusted private Wi-Fi/LAN, never on public Wi-Fi, and never forward its port to the internet.\n\n"
            "Start it now?",
            icon="warning", parent=self.root,
        )
        if not consent:
            return
        try:
            from mobile_companion import MobileCompanionServer
            password_record = load_password_record(MASTER_PASSWORD_PATH)
            if password_record is None:
                raise RuntimeError("Set a MySQL IDLE master password before enabling the Android / Mobile Companion.")
            self.mobile_server = MobileCompanionServer(
                governor=self.governor, password_record=password_record
            )
            self.mobile_server.start()
            self.tools_menu.entryconfig(1, state=tk.NORMAL)
            self.with_output(lambda: self.write("Android / Mobile Companion enabled on the local network.\n", "info"))
            self._show_mobile_companion_dialog()
        except Exception as exc:
            logging.exception("Could not start mobile companion")
            if self.mobile_server is not None:
                try:
                    self.mobile_server.stop()
                except Exception:
                    logging.exception("Could not clean up a partially started mobile companion")
            self.mobile_server = None
            messagebox.showerror("Could not start mobile companion", f"{exc}\n\nCheck that the selected port is available and review the app log.", parent=self.root)

    def _show_mobile_companion_dialog(self):
        server = self.mobile_server
        if not server or not server.running:
            return
        win = tk.Toplevel(self.root, bg="white", padx=16, pady=14)
        win.title("Android / Mobile Companion")
        win.geometry("680x510")
        win.minsize(560, 450)
        win.transient(self.root)
        tk.Label(win, text="Verify this desktop in the MySQL IDLE Android app", bg="white", anchor="w", font=("Segoe UI", 10, "bold")).pack(fill=tk.X, pady=(0, 5))
        tk.Label(win, text="Keep both devices on the same trusted private Wi-Fi network. Do not port-forward this service.", bg="white", fg="#555555", anchor="w", wraplength=640, justify=tk.LEFT).pack(fill=tk.X, pady=(0, 6))
        url_var = tk.StringVar(value=server.url)
        url_entry = ttk.Entry(win, textvariable=url_var, state="readonly")
        url_entry.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(win, text="Copy HTTPS address", command=lambda: self._copy_text(server.url, win)).pack(anchor="e")
        tk.Label(win, text="TLS certificate SHA-256 fingerprint (compare every pair)", bg="white", anchor="w", font=("Segoe UI", 10, "bold")).pack(fill=tk.X, pady=(8, 5))
        fingerprint_entry = ttk.Entry(win, font=("Consolas", 9))
        fingerprint_entry.insert(0, server.certificate_fingerprint)
        fingerprint_entry.configure(state="readonly")
        fingerprint_entry.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(win, text="Copy certificate fingerprint", command=lambda: self._copy_text(server.certificate_fingerprint, win)).pack(anchor="e")
        tk.Label(win, text="Temporary pairing code (keep private)", bg="white", anchor="w", font=("Segoe UI", 10, "bold")).pack(fill=tk.X, pady=(8, 5))
        code_var = tk.StringVar(value=server.pairing_code)
        code_entry = ttk.Entry(win, textvariable=code_var, state="readonly", font=("Consolas", 11))
        code_entry.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(win, text="Copy pairing code", command=lambda: self._copy_text(server.pairing_code, win)).pack(anchor="e")
        tk.Label(win, text="On Android: enter this HTTPS address, compare the certificate fingerprint, then enter the same MySQL IDLE master password set on this Windows computer plus the temporary pairing code. A mismatch is rejected. Verified TLS protects traffic to the companion. For MySQL connections, leave verified TLS enabled and supply your server CA certificate if needed. Allow Windows Firewall access on private networks only. Stop the companion when finished.", bg="white", fg="#8a3636", wraplength=640, justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=(12, 8))
        buttons = tk.Frame(win, bg="white")
        buttons.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(buttons, text="Stop Companion", command=lambda: (self.stop_mobile_companion(), win.destroy())).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Close Window", command=win.destroy).pack(side=tk.RIGHT, padx=8)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.grab_set()

    @staticmethod
    def _copy_text(value, owner):
        owner.clipboard_clear()
        owner.clipboard_append(value)
        owner.update_idletasks()

    def stop_mobile_companion(self):
        if self._mobile_stopping:
            return
        server, self.mobile_server = self.mobile_server, None
        try:
            self.tools_menu.entryconfig(1, state=tk.DISABLED)
        except tk.TclError:
            pass
        if server is None:
            return
        self._mobile_stopping = True
        try:
            self.tools_menu.entryconfig(0, state=tk.DISABLED)
        except tk.TclError:
            pass

        def stop_in_background():
            try:
                server.stop()
            except Exception:
                logging.exception("Error while stopping mobile companion")
            if self._closing:
                return
            try:
                self.root.after(0, self._mobile_companion_stopped)
            except tk.TclError:
                pass

        # A running mobile SQL request can hold its session lock until a server timeout;
        # never make the desktop UI wait for that cleanup.
        threading.Thread(target=stop_in_background, name="mysql-idle-mobile-stop", daemon=True).start()
        if not self._closing:
            self.with_output(lambda: self.write("Stopping Android / Mobile Companion; active mobile requests are being closed.\n", "info"))

    def _mobile_companion_stopped(self):
        self._mobile_stopping = False
        try:
            self.tools_menu.entryconfig(0, state=tk.NORMAL)
            self.tools_menu.entryconfig(1, state=tk.DISABLED)
        except tk.TclError:
            pass
        if not self._closing:
            self.with_output(lambda: self.write("Android / Mobile Companion stopped; paired sessions were closed.\n", "info"))

    def menu_help(self):
        self.with_output(self.show_help)

    def menu_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\nAn IDLE-style shell for MySQL / MariaDB.\n\n"
            f"Python {os.sys.version.split()[0]}  |  PyMySQL {getattr(pymysql, '__version__', '?')}",
            parent=self.root,
        )

    def run_script(self):
        path = filedialog.askopenfilename(
            title="Run SQL Script", parent=self.root,
            filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            sql = Path(path).read_text(encoding="utf-8-sig")
        except Exception as exc:
            messagebox.showerror("Cannot read file", str(exc), parent=self.root)
            return

        statements, rest = split_sql(sql)
        if rest.strip():
            statements.append(rest.strip())
        statements = [stmt for stmt in statements if not is_blank_sql(stmt)]
        self.pending = ""
        approved_statements = self._preflight_statements(statements, source=os.path.basename(path))
        if approved_statements is None:
            return
        self._queue_job("script", {
            "statements": statements, "name": os.path.basename(path),
            "approved_statements": approved_statements,
        })

    def save_log(self):
        path = filedialog.asksaveasfilename(
            title="Save Shell Log", parent=self.root, defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            try:
                Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Cannot save", str(exc), parent=self.root)

    def save_csv(self):
        if not self.last_result:
            self.with_output(lambda: self.write("No result to save yet - run a SELECT first.\n", "info"))
            return
        path = filedialog.asksaveasfilename(
            title="Save Last Result as CSV", parent=self.root, defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        result = dict(self.last_result)
        try:
            shutil.copyfile(result["path"], path)
        except Exception as exc:
            messagebox.showerror("Cannot save", str(exc), parent=self.root)
            return
        self.with_output(lambda: self.write(
            f"Saved {result['row_count']} row(s) to {path}\n", "ok"
        ))

    # ------------------------------------------------------------ grid window --

    def show_grid(self):
        if not self.last_result:
            self.with_output(lambda: self.write("No result to show yet - run a SELECT first.\n", "info"))
            return
        result = dict(self.last_result)
        columns = result["columns"]
        try:
            # Large BLOB/text columns can exceed csv's conservative default.
            try:
                csv.field_size_limit(2**31 - 1)
            except OverflowError:
                csv.field_size_limit(2**30)
            with open(result["path"], "r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                next(reader, None)  # header row
                shown = []
                for row in reader:
                    shown.append([
                        value if len(value) <= MAX_CELL_WIDTH else value[:MAX_CELL_WIDTH - 3] + "..."
                        for value in row
                    ])
                    if len(shown) >= MAX_GRID_ROWS:
                        break
        except (OSError, csv.Error) as exc:
            messagebox.showerror("Cannot open result", str(exc), parent=self.root)
            return

        win = tk.Toplevel(self.root, bg="white")
        suffix = f" (first {MAX_GRID_ROWS} of {result['row_count']})" if result["row_count"] > MAX_GRID_ROWS else ""
        win.title(f"Result grid - {result['row_count']} row(s){suffix}")
        win.geometry("940x520")

        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True)
        ids = [f"c{i}" for i in range(len(columns))]
        tree = ttk.Treeview(frame, columns=ids, show="headings")
        ys = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        xs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        xs.pack(side=tk.BOTTOM, fill=tk.X)
        ys.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        state = {"col": None, "reverse": False, "loaded": False}

        def sort_by(cid):
            if not state["loaded"]:
                win.after(40, lambda: sort_by(cid))
                return
            reverse = state["col"] == cid and not state["reverse"]

            def key(item):
                value = tree.set(item, cid)
                try:
                    return (0, float(value), "")
                except ValueError:
                    return (1, 0.0, value.lower())

            for pos, item in enumerate(sorted(tree.get_children(""), key=key, reverse=reverse)):
                tree.move(item, "", pos)
            state.update(col=cid, reverse=reverse)

        for cid, name in zip(ids, columns):
            tree.heading(cid, text=str(name), command=lambda c=cid: sort_by(c))
            tree.column(cid, width=max(90, min(320, 10 * len(str(name)) + 40)), anchor="w", stretch=False)

        def insert_batch(start=0):
            stop = min(start + 200, len(shown))
            for row in shown[start:stop]:
                tree.insert("", tk.END, values=row)
            if stop < len(shown):
                win.after(1, lambda: insert_batch(stop))
            else:
                state["loaded"] = True

        insert_batch()

    # ------------------------------------------------------------------ exit --

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        if SAVE_HISTORY:
            self.cfg["history"] = self.history[-MAX_HISTORY:]
        save_config(self.cfg)
        self.stop_mobile_companion()
        # Best-effort cancellation keeps shutdown responsive for long-running SQL.
        self.worker.request_cancel(silent=True)
        self.worker.shutdown()
        self.root.destroy()


def _show_startup_error(title, message):
    try:
        import tkinter.messagebox as tk_messagebox
        temp_root = tk.Tk()
        temp_root.withdraw()
        tk_messagebox.showerror(title, message, parent=temp_root)
        temp_root.destroy()
    except Exception:
        print(f"{title}: {message}", file=os.sys.stderr)


def main():
    try:  # Crisp text on high-DPI Windows screens.
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        setup_runtime_environment()
    except Exception as exc:
        _show_startup_error(
            f"{APP_NAME} startup problem",
            f"The application could not prepare its per-user settings/log directory or temporary storage.\n\n{exc}\n\nTry running from a Windows account with a writable AppData folder.",
        )
        return
    if pymysql is None:
        if PYMYSQL_IMPORT_ERROR is not None:
            logging.error("PyMySQL could not be imported: %s", PYMYSQL_IMPORT_ERROR,
                          exc_info=(type(PYMYSQL_IMPORT_ERROR), PYMYSQL_IMPORT_ERROR, PYMYSQL_IMPORT_ERROR.__traceback__))
        _show_startup_error(
            f"{APP_NAME} dependency missing",
            "The MySQL driver could not be loaded. If you are running from source, open a terminal in the app folder and run:\n\npython -m pip install -r requirements.txt\n\nIf you are using the packaged EXE, reinstall the complete application folder from the official build package.",
        )
        return
    logging.info("Starting %s %s", APP_NAME, APP_VERSION)
    try:
        root = tk.Tk()
        root.withdraw()
        _apply_window_icon(root)
        app = MySQLIDLE(root)
        # Keep the shell hidden until the single Connect to MySQL page completes
        # its local master-password check and database connection form.
        root.after_idle(app.connect_dialog)
        root.mainloop()
    except Exception as exc:
        logging.exception("Fatal application startup/runtime error")
        _show_startup_error(
            f"{APP_NAME} could not start",
            f"{exc}\n\nA diagnostic log was written to:\n{LOG_DIR / 'application.log'}",
        )


if __name__ == "__main__":
    main()
