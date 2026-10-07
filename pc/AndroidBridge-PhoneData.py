import os
import sys
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

MODE = (sys.argv[1] if len(sys.argv) > 1 else "calls").lower()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

SEARCH_DIRS = [
    SCRIPT_DIR,
    REPO_ROOT,
    r"C:\AndroidBridge-Lite",
    r"C:\AndroidBridge-Lite-backup",
]


def existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def find_file(name):
    candidates = [os.path.join(d, name) for d in SEARCH_DIRS]
    return existing(candidates)


def choose_table(conn, keywords):
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()

    tables = [r[0] for r in rows]

    for kw in keywords:
        for name in tables:
            if kw in name.lower():
                return name

    return tables[0] if tables else None


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def read_db(path, keywords):
    conn = sqlite3.connect(path)

    try:
        table = choose_table(conn, keywords)

        if not table:
            return [], [], "No data tables found."

        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(" + quote_ident(table) + ")"
            ).fetchall()
        ]

        if not cols:
            return [], [], "No columns found."

        order_col = None

        preferred = [
            "timestamp", "time", "date", "created_at",
            "updated_at", "id"
        ]

        lower_map = {c.lower(): c for c in cols}

        for p in preferred:
            if p in lower_map:
                order_col = lower_map[p]
                break

        sql = "SELECT * FROM " + quote_ident(table)

        if order_col:
            sql += " ORDER BY " + quote_ident(order_col) + " DESC"

        sql += " LIMIT 500"

        rows = conn.execute(sql).fetchall()

        return cols, rows, "Table: " + table

    finally:
        conn.close()


def find_location_json():
    names = [
        "location.json",
        "latest_location.json",
        "last_location.json",
    ]

    for d in SEARCH_DIRS:
        for name in names:
            p = os.path.join(d, name)

            if os.path.exists(p):
                return p

    return None


def find_location_in_db():
    dbs = [
        find_file("androidbridge_calls.db"),
        find_file("phone_activity.db"),
    ]

    for db in [p for p in dbs if p]:
        try:
            conn = sqlite3.connect(db)

            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]

            for table in tables:
                cols = [
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(" + quote_ident(table) + ")"
                    ).fetchall()
                ]

                low = [c.lower() for c in cols]

                has_lat = any(x in low for x in ["lat", "latitude"])
                has_lon = any(
                    x in low for x in ["lon", "lng", "longitude"]
                )

                if not (has_lat and has_lon):
                    continue

                sql = (
                    "SELECT * FROM " + quote_ident(table) +
                    " ORDER BY rowid DESC LIMIT 1"
                )

                row = conn.execute(sql).fetchone()

                if row:
                    return db, table, cols, row

        except Exception:
            pass

        finally:
            try:
                conn.close()
            except Exception:
                pass

    return None


def build_table(title, db_path, keywords):
    root = tk.Tk()
    root.title(title)
    root.geometry("1000x600")

    top = tk.Frame(root)
    top.pack(fill="x", padx=10, pady=10)

    tk.Label(
        top,
        text=title,
        font=("Microsoft YaHei UI", 16, "bold")
    ).pack(anchor="w")

    tk.Label(
        top,
        text=db_path,
        font=("Microsoft YaHei UI", 9)
    ).pack(anchor="w", pady=(2, 0))

    try:
        cols, rows, meta = read_db(db_path, keywords)
    except Exception as e:
        messagebox.showerror(title, str(e))
        root.destroy()
        return

    tk.Label(
        top,
        text=meta,
        font=("Microsoft YaHei UI", 9)
    ).pack(anchor="w", pady=(2, 0))

    if not cols:
        tk.Label(root, text="暂无数据。").pack(pady=30)
        root.mainloop()
        return

    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    tree = ttk.Treeview(
        frame,
        columns=cols,
        show="headings"
    )

    y = ttk.Scrollbar(
        frame,
        orient="vertical",
        command=tree.yview
    )

    x = ttk.Scrollbar(
        frame,
        orient="horizontal",
        command=tree.xview
    )

    tree.configure(
        yscrollcommand=y.set,
        xscrollcommand=x.set
    )

    tree.grid(row=0, column=0, sticky="nsew")
    y.grid(row=0, column=1, sticky="ns")
    x.grid(row=1, column=0, sticky="ew")

    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    for col in cols:
        tree.heading(col, text=col)
        tree.column(col, width=140, minwidth=80)

    for row in rows:
        tree.insert(
            "",
            "end",
            values=[
                "" if v is None else str(v)
                for v in row
            ]
        )

    root.mainloop()


def show_location():
    path = find_location_json()

    root = tk.Tk()
    root.title("Samsung Secure - 最新位置")
    root.geometry("620x420")

    tk.Label(
        root,
        text="最新位置",
        font=("Microsoft YaHei UI", 16, "bold")
    ).pack(anchor="w", padx=16, pady=(16, 8))

    box = tk.Text(
        root,
        wrap="word",
        font=("Consolas", 10)
    )

    box.pack(
        fill="both",
        expand=True,
        padx=16,
        pady=(0, 16)
    )

    if path:
        try:
            with open(
                path,
                "r",
                encoding="utf-8",
                errors="replace"
            ) as f:
                data = json.load(f)

            box.insert(
                "1.0",
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False
                )
            )

            root.title(
                "Samsung Secure - 最新位置 - " +
                os.path.basename(path)
            )

        except Exception as e:
            box.insert(
                "1.0",
                "无法读取位置文件：\n\n" + str(e)
            )

    else:
        found = find_location_in_db()

        if found:
            db, table, cols, row = found

            text = {
                "source_db": db,
                "table": table,
                "record": dict(zip(cols, row))
            }

            box.insert(
                "1.0",
                json.dumps(
                    text,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                )
            )

        else:
            box.insert(
                "1.0",
                "未找到已保存的位置数据。\n\n"
                "Samsung Secure 已检查当前项目和之前的 "
                "C:\\AndroidBridge-Lite-backup folder."
            )

    box.config(state="disabled")
    root.mainloop()


if MODE == "calls":
    db = find_file("androidbridge_calls.db")

    if not db:
        messagebox.showerror(
            "Samsung Secure 通话记录",
            "androidbridge_calls.db was not found.\n\n"
            "Checked the current AndroidBridge folder and "
            "C:\\AndroidBridge-Lite-backup."
        )
    else:
        build_table(
            "Samsung Secure - 通话记录",
            db,
            ["call", "calls"]
        )

elif MODE == "activity":
    db = find_file("phone_activity.db")

    if not db:
        messagebox.showerror(
            "Samsung Secure 手机活动",
            "phone_activity.db was not found.\n\n"
            "Checked the current AndroidBridge folder and "
            "C:\\AndroidBridge-Lite-backup."
        )
    else:
        build_table(
            "Samsung Secure - 手机活动",
            db,
            ["activity", "event", "usage"]
        )

elif MODE == "location":
    show_location()

else:
    messagebox.showerror(
        "Samsung Secure",
        "未知模式：" + MODE
    )
