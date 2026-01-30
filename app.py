# app.py
import os
import shutil
import sqlite3
import csv
import io
from datetime import datetime, date
from pathlib import Path
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, render_template_string, session,
    send_from_directory, abort, flash, Response
)
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash

# # ----------------- CONFIG -----------------
# DB = os.environ.get("DB_PATH", os.path.join("data", "database.db"))
# os.makedirs(os.path.dirname(DB), exist_ok=True)
DB = os.environ.get("DB_PATH",  "database.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_for_prod")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "10"))

INITIAL_USERS = [
    {"username": "9492126272", "password": "Madan@1440", "role": "admin", "name": "Admin One"},
    {"username": "9490479284", "password": "Laxmi@6799", "role": "admin", "name": "Admin Two"},
    {"username": "9492146644", "password": "Rupa@0642",  "role": "user",  "name": "User One"},
    {"username": "9492948661", "password": "Venky@8661",  "role": "user",  "name": "User Two"},
]

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ----------------- DB helpers & init -----------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_and_seed_users():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        name TEXT,
        brand TEXT,
        model TEXT,
        color TEXT,
        number TEXT UNIQUE,
        status TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sellers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        seller_name TEXT,
        seller_phone TEXT,
        seller_city TEXT,
        buy_value INTEGER,
        buy_date TEXT,
        comments TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        record_no TEXT,
        buyer_name TEXT,
        buyer_phone TEXT,
        buyer_address TEXT,
        sale_value INTEGER,
        finance_amount INTEGER,
        emi_amount INTEGER,
        tenure INTEGER,
        sale_date TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS emis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buyer_id INTEGER,
        emi_no INTEGER,
        due_date TEXT,
        amount INTEGER,
        status TEXT DEFAULT 'Unpaid',
        paid_date TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        name TEXT,
        password_hash TEXT,
        role TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        who TEXT,
        action TEXT,
        target TEXT,
        ts TEXT
    )""")
    conn.commit()

    # seed initial users only if table empty
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        for u in INITIAL_USERS:
            try:
                conn.execute("INSERT INTO users (username,name,password_hash,role) VALUES (?,?,?,?)",
                             (u["username"], u.get("name", u["username"]),
                              generate_password_hash(u["password"]), u.get("role", "user")))
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    conn.close()

Path(DB).parent.mkdir(parents=True, exist_ok=True) if Path(DB).parent != Path('.') else None
open(DB, "a").close()
init_db_and_seed_users()

# ----------------- utilities -----------------
def add_months(orig_date: date, months: int) -> date:
    return orig_date + relativedelta(months=months)

def log_action(who, action, target=""):
    try:
        conn = get_db()
        conn.execute("INSERT INTO audit_log (who, action, target, ts) VALUES (?, ?, ?, ?)",
                     (who or "", action, target, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ----------------- auth & decorators -----------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_user():
    return {
        "current_username": session.get("username"),
        "current_role": session.get("role")
    }

# ----------------- backups -----------------
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
def list_backups():
    files = sorted(BACKUP_DIR.glob("db_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files
def create_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"db_{ts}.db"
    dest = BACKUP_DIR / fname
    shutil.copy2(DB, dest)
    files = list_backups()
    if len(files) > BACKUP_KEEP:
        for p in files[BACKUP_KEEP:]:
            try:
                p.unlink()
            except Exception:
                pass
    log_action(session.get("username"), "create_backup", fname)
    return dest

# ----------------- auth routes -----------------
@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        u = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if not u or not check_password_hash(u["password_hash"], password):
            error = "Invalid username or password"
        else:
            session["user_id"] = u["id"]
            session["username"] = u["username"]
            session["name"] = u["name"]
            session["role"] = u["role"]
            log_action(u["username"], "login", "")
            return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    who = session.get("username")
    session.clear()
    log_action(who, "logout", "")
    return redirect(url_for("login"))

# ----------------- main app routes -----------------
@app.route("/")
@login_required
def dashboard():
    q = request.args.get("q", "").strip()
    vtype = request.args.get("type", "ALL")
    status = request.args.get("status", "ALL")

    sql = "SELECT * FROM vehicles WHERE 1=1"
    params = []
    if vtype and vtype != "ALL":
        sql += " AND type = ?"
        params.append(vtype)
    if status and status != "ALL":
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (name LIKE ? OR brand LIKE ? OR model LIKE ? OR number LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]

    conn = get_db()
    vehicles = conn.execute(sql, params).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    stock = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='Stock'").fetchone()[0]
    sold = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='Sold'").fetchone()[0]
    conn.close()
    return render_template_string(DASHBOARD_HTML, vehicles=vehicles, q=q, vtype=vtype, status=status, total=total, stock=stock, sold=sold)

# Add vehicle (admin only) — Bike default
@app.route("/add", methods=["GET","POST"])
@admin_required
def add_vehicle():
    if request.method == "POST":
        f = request.form
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vehicles (type, name, brand, model, color, number, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Stock')
        """, (f.get("type"), f.get("name"), f.get("brand"), f.get("model"), f.get("color"), f.get("number")))
        vid = cur.lastrowid
        try:
            buy_val = int(float(f.get("buy_value") or 0))
        except:
            buy_val = 0
        cur.execute("""
            INSERT INTO sellers (vehicle_id, seller_name, seller_phone, seller_city, buy_value, buy_date, comments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (vid, f.get("seller_name"), f.get("seller_phone"), f.get("seller_city"), buy_val, f.get("buy_date") or "", f.get("comments") or ""))
        conn.commit()
        conn.close()
        log_action(session.get("username"), "add_vehicle", f.get("number"))
        return redirect(url_for("dashboard"))
    return render_template_string(ADD_HTML)

# Edit vehicle (admin only)
@app.route("/edit/<int:vid>", methods=["GET","POST"])
@admin_required
def edit_vehicle(vid):
    conn = get_db()
    if request.method == "POST":
        f = request.form
        conn.execute("""
            UPDATE vehicles SET type=?, name=?, brand=?, model=?, color=?, number=?
            WHERE id=?
        """, (f.get("type"), f.get("name"), f.get("brand"), f.get("model"), f.get("color"), f.get("number"), vid))
        seller = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
        if seller:
            try:
                buy_val = int(float(f.get("buy_value") or 0))
            except:
                buy_val = 0
            conn.execute("""
                UPDATE sellers SET seller_name=?, seller_phone=?, seller_city=?, buy_value=?, buy_date=?, comments=?
                WHERE vehicle_id=?
            """, (f.get("seller_name"), f.get("seller_phone"), f.get("seller_city"), buy_val, f.get("buy_date") or "", f.get("comments") or "", vid))
        conn.commit()
        conn.close()
        log_action(session.get("username"), "edit_vehicle", str(vid))
        return redirect(url_for("dashboard"))
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    s = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
    conn.close()
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(EDIT_HTML, v=v, s=s)

# Delete (admin)
@app.route("/delete/<int:vid>", methods=["GET"])
@admin_required
def delete_vehicle(vid):
    conn = get_db()
    buyers = conn.execute("SELECT id FROM buyers WHERE vehicle_id=?", (vid,)).fetchall()
    for b in buyers:
        conn.execute("DELETE FROM emis WHERE buyer_id=?", (b["id"],))
    conn.execute("DELETE FROM buyers WHERE vehicle_id=?", (vid,))
    conn.execute("DELETE FROM sellers WHERE vehicle_id=?", (vid,))
    conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    log_action(session.get("username"), "delete_vehicle", str(vid))
    return redirect(url_for("dashboard"))

# Sell (admin) -> creates buyer + EMIs
@app.route("/sell/<int:vid>", methods=["GET","POST"])
@admin_required
def sell_vehicle(vid):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        conn.close()
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        f = request.form
        try:
            sale_value = int(float(f.get("sale_value") or 0))
        except:
            sale_value = 0
        try:
            finance_amount = int(float(f.get("finance_amount") or 0))
        except:
            finance_amount = 0
        try:
            emi_amount = int(float(f.get("emi_amount") or 0))
        except:
            emi_amount = 0
        try:
            tenure = int(float(f.get("tenure") or 0))
        except:
            tenure = 0

        sale_date = f.get("sale_date") or datetime.now().strftime("%Y-%m-%d")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO buyers (vehicle_id, record_no, buyer_name, buyer_phone, buyer_address,
            sale_value, finance_amount, emi_amount, tenure, sale_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (vid, f.get("record_no") or "", f.get("buyer_name"), f.get("buyer_phone"), f.get("buyer_address"),
              sale_value, finance_amount, emi_amount, tenure, sale_date))
        buyer_id = cur.lastrowid

        sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
        for i in range(1, tenure + 1):
            due = add_months(sd, i)
            cur.execute("INSERT INTO emis (buyer_id, emi_no, due_date, amount, status) VALUES (?, ?, ?, ?, 'Unpaid')",
                        (buyer_id, i, due.isoformat(), emi_amount))

        conn.execute("UPDATE vehicles SET status='Sold' WHERE id=?", (vid,))
        conn.commit()
        conn.close()
        log_action(session.get("username"), "sell_vehicle", f"vehicle:{vid} buyer:{buyer_id}")
        return redirect(url_for("view_vehicle", vid=vid))
    conn.close()
    return render_template_string(SELL_HTML, v=v, today=datetime.now().strftime("%Y-%m-%d"))

# View (both roles)
@app.route("/view/<int:vid>", methods=["GET"])
@login_required
def view_vehicle(vid):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    s = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
    b = conn.execute("SELECT * FROM buyers WHERE vehicle_id=?", (vid,)).fetchone()
    emis = []
    if b:
        emis = conn.execute("SELECT * FROM emis WHERE buyer_id=? ORDER BY emi_no", (b["id"],)).fetchall()
    conn.close()
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(VIEW_HTML, v=v, s=s, b=b, emis=emis)

# Edit buyer/finance (admin only) — safe EMI adjustments
@app.route("/buyer/<int:vid>", methods=["GET","POST"])
@admin_required
def edit_buyer(vid):
    conn = get_db()
    buyer = conn.execute("SELECT * FROM buyers WHERE vehicle_id=?", (vid,)).fetchone()

    if request.method == "POST":
        f = request.form
        try:
            new_sale_value = int(float(f.get("sale_value") or 0))
        except:
            new_sale_value = 0
        try:
            new_finance_amount = int(float(f.get("finance_amount") or 0))
        except:
            new_finance_amount = 0
        try:
            new_emi_amount = int(float(f.get("emi_amount") or 0))
        except:
            new_emi_amount = 0
        try:
            new_tenure = int(float(f.get("tenure") or 0))
        except:
            new_tenure = 0

        if not buyer:
            sale_date = datetime.now().strftime("%Y-%m-%d")
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO buyers (vehicle_id, buyer_name, buyer_phone, buyer_address, sale_value, finance_amount, tenure, emi_amount, sale_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (vid, f.get("buyer_name") or "", f.get("buyer_phone") or "", f.get("buyer_address") or "",
                  new_sale_value, new_finance_amount, new_tenure, new_emi_amount, sale_date))
            buyer_id = cur.lastrowid
            sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
            for i in range(1, new_tenure + 1):
                due = add_months(sd, i)
                cur.execute("INSERT INTO emis (buyer_id, emi_no, due_date, amount, status) VALUES (?, ?, ?, ?, 'Unpaid')",
                            (buyer_id, i, due.isoformat(), new_emi_amount))
            conn.commit()
            conn.close()
            log_action(session.get("username"), "create_buyer", f"vehicle:{vid} buyer:{buyer_id}")
            return redirect(url_for("view_vehicle", vid=vid))

        buyer_id = buyer["id"]
        old_tenure = int(buyer["tenure"] or 0)
        old_emi_amount = int(buyer["emi_amount"] or 0)
        sale_date_str = buyer["sale_date"] or datetime.now().strftime("%Y-%m-%d")
        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date()

        cur = conn.cursor()
        cur.execute("""
            UPDATE buyers SET buyer_name=?, buyer_phone=?, buyer_address=?,
                              sale_value=?, finance_amount=?, emi_amount=?, tenure=?
            WHERE vehicle_id=?
        """, (f.get("buyer_name") or "", f.get("buyer_phone") or "", f.get("buyer_address") or "",
              new_sale_value, new_finance_amount, new_emi_amount, new_tenure, vid))

        if new_emi_amount != old_emi_amount:
            cur.execute("UPDATE emis SET amount=? WHERE buyer_id=? AND status!='Paid'", (new_emi_amount, buyer_id))

        if new_tenure > old_tenure:
            for i in range(old_tenure + 1, new_tenure + 1):
                due = add_months(sale_date, i)
                cur.execute("INSERT INTO emis (buyer_id, emi_no, due_date, amount, status) VALUES (?, ?, ?, ?, 'Unpaid')",
                            (buyer_id, i, due.isoformat(), new_emi_amount))
        elif new_tenure < old_tenure:
            cur.execute("DELETE FROM emis WHERE buyer_id=? AND emi_no>? AND status!='Paid'", (buyer_id, new_tenure))

        conn.commit()
        conn.close()
        log_action(session.get("username"), "edit_buyer", f"vehicle:{vid} buyer:{buyer_id}")
        return redirect(url_for("view_vehicle", vid=vid))

    conn.close()
    return render_template_string(EDIT_BUYER_HTML, buyer=buyer, vid=vid)

# Toggle EMI (admin)
@app.route("/emi/toggle/<int:emi_id>", methods=["POST"])
@admin_required
def toggle_emi(emi_id):
    action = request.form.get("action")
    conn = get_db()
    if action == "mark_paid":
        conn.execute("UPDATE emis SET status='Paid', paid_date=? WHERE id=?", (date.today().isoformat(), emi_id))
        log_action(session.get("username"), "mark_emi_paid", str(emi_id))
    else:
        conn.execute("UPDATE emis SET status='Unpaid', paid_date=NULL WHERE id=?", (emi_id,))
        log_action(session.get("username"), "mark_emi_unpaid", str(emi_id))
    conn.commit()
    ref = request.form.get("ref") or url_for("dashboard")
    conn.close()
    return redirect(ref)

# ------------- Admin: Users management ----------------
@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute("SELECT id, username, name, role FROM users ORDER BY id").fetchall()
    conn.close()
    return render_template_string(ADMIN_USERS_HTML, users=users)

@app.route("/admin/users/create", methods=["GET","POST"])
@admin_required
def admin_users_create():
    if request.method == "POST":
        f = request.form
        username = f.get("username").strip()
        name = f.get("name").strip()
        role = f.get("role")
        pwd = f.get("password")
        if not username or not pwd:
            return "username & password required", 400
        pwhash = generate_password_hash(pwd)
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username,name,password_hash,role) VALUES (?,?,?,?)",
                         (username, name, pwhash, role))
            conn.commit()
            conn.close()
            log_action(session.get("username"), "create_user", username)
            return redirect(url_for("admin_users"))
        except sqlite3.IntegrityError:
            conn.close()
            return "username exists", 400
    return render_template_string(ADMIN_USERS_CREATE_HTML)

@app.route("/admin/users/edit/<int:uid>", methods=["GET","POST"])
@admin_required
def admin_users_edit(uid):
    conn = get_db()
    if request.method == "POST":
        f = request.form
        name = f.get("name").strip()
        role = f.get("role")
        pwd = f.get("password")
        if pwd:
            pwhash = generate_password_hash(pwd)
            conn.execute("UPDATE users SET name=?, role=?, password_hash=? WHERE id=?", (name, role, pwhash, uid))
        else:
            conn.execute("UPDATE users SET name=?, role=? WHERE id=?", (name, role, uid))
        conn.commit()
        conn.close()
        log_action(session.get("username"), "edit_user", str(uid))
        return redirect(url_for("admin_users"))
    user = conn.execute("SELECT id, username, name, role FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not user:
        return redirect(url_for("admin_users"))
    return render_template_string(ADMIN_USERS_EDIT_HTML, user=user)

@app.route("/admin/users/delete/<int:uid>", methods=["POST"])
@admin_required
def admin_users_delete(uid):
    # prevent deleting yourself
    if session.get("user_id") == uid:
        return "Cannot delete yourself", 400
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    log_action(session.get("username"), "delete_user", str(uid))
    return redirect(url_for("admin_users"))

# ------------- Admin: Backups UI ----------------
@app.route("/admin/backups")
@admin_required
def admin_backups():
    files = list_backups()
    files_info = [{"name": p.name, "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat()} for p in files]
    return render_template_string(ADMIN_BACKUPS_HTML, files=files_info)

@app.route("/admin/backups/create", methods=["POST"])
@admin_required
def admin_backup_create():
    dest = create_backup()
    return redirect(url_for("admin_backups"))

@app.route("/admin/backups/download/<path:filename>")
@admin_required
def admin_backup_download(filename):
    file_path = BACKUP_DIR / filename
    if not file_path.exists():
        abort(404)
    return send_from_directory(BACKUP_DIR.resolve(), filename, as_attachment=True)

@app.route("/admin/backups/delete/<path:filename>", methods=["POST"])
@admin_required
def admin_backup_delete(filename):
    file_path = BACKUP_DIR / filename
    if file_path.exists():
        file_path.unlink()
    return redirect(url_for("admin_backups"))

# ------------- Admin: CSV export ----------------
def rows_to_csv_response(filename, fieldnames, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    mem = output.getvalue()
    output.close()
    return Response(mem, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={filename}"})

@app.route("/admin/export")
@admin_required
def admin_export_ui():
    return render_template_string(ADMIN_EXPORT_HTML)

@app.route("/admin/export/csv")
@admin_required
def admin_export_csv():
    typ = request.args.get("type", "full")
    conn = get_db()

    if typ == "vehicles":
        rows = conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
        fieldnames = rows[0].keys() if rows else ["id","type","name","brand","model","color","number","status"]
        rows_dicts = [dict(r) for r in rows]
        conn.close()
        return rows_to_csv_response("vehicles.csv", fieldnames, rows_dicts)

    if typ == "sellers":
        rows = conn.execute("SELECT * FROM sellers ORDER BY id").fetchall()
        fieldnames = rows[0].keys() if rows else ["id","vehicle_id","seller_name","seller_phone","seller_city","buy_value","buy_date","comments"]
        rows_dicts = [dict(r) for r in rows]
        conn.close()
        return rows_to_csv_response("sellers.csv", fieldnames, rows_dicts)

    if typ == "buyers":
        rows = conn.execute("SELECT * FROM buyers ORDER BY id").fetchall()
        fieldnames = rows[0].keys() if rows else ["id","vehicle_id","record_no","buyer_name","buyer_phone","buyer_address","sale_value","finance_amount","emi_amount","tenure","sale_date"]
        rows_dicts = [dict(r) for r in rows]
        conn.close()
        return rows_to_csv_response("buyers.csv", fieldnames, rows_dicts)

    if typ == "emis":
        rows = conn.execute("SELECT * FROM emis ORDER BY id").fetchall()
        fieldnames = rows[0].keys() if rows else ["id","buyer_id","emi_no","due_date","amount","status","paid_date"]
        rows_dicts = [dict(r) for r in rows]
        conn.close()
        return rows_to_csv_response("emis.csv", fieldnames, rows_dicts)

    # "full" export: vehicles joined to seller and buyer (one row per vehicle)
    sql = """
    SELECT v.id as vehicle_id, v.type, v.name, v.brand, v.model, v.color, v.number, v.status,
           s.seller_name, s.seller_phone, s.seller_city, s.buy_value, s.buy_date, s.comments,
           b.id as buyer_id, b.record_no, b.buyer_name, b.buyer_phone, b.buyer_address, b.sale_value, b.finance_amount, b.emi_amount, b.tenure, b.sale_date
    FROM vehicles v
    LEFT JOIN sellers s ON s.vehicle_id = v.id
    LEFT JOIN buyers b ON b.vehicle_id = v.id
    ORDER BY v.id
    """
    rows = conn.execute(sql).fetchall()
    fieldnames = ["vehicle_id","type","name","brand","model","color","number","status",
                  "seller_name","seller_phone","seller_city","buy_value","buy_date","comments",
                  "buyer_id","record_no","buyer_name","buyer_phone","buyer_address","sale_value","finance_amount","emi_amount","tenure","sale_date"]
    rows_dicts = [dict(r) for r in rows]
    conn.close()
    return rows_to_csv_response("full_export.csv", fieldnames, rows_dicts)

# ----------------- Templates -----------------
# (kept concise and consistent: use 'e' as emi loop var)
LOGIN_HTML = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title><style>body{font-family:Inter;background:#f1f5f9;padding:20px}form{max-width:420px;margin:40px auto;background:white;padding:20px;border-radius:8px}label{display:block;margin-top:8px}</style></head><body>
<form method="post">
  <h2>Login</h2>
  {% if error %}<div style="color:red">{{ error }}</div>{% endif %}
  <label>Username (phone)</label><input name="username" required>
  <label>Password</label><input name="password" type="password" required>
  <div style="margin-top:12px"><button type="submit">Login</button></div>
</form></body></html>"""

BASE_CSS = """
<style>
:root{--bg:#f4f6fb;--card:#fff;--muted:#6b7280;--primary:#2563eb;--danger:#ef4444}
*{box-sizing:border-box;font-family:Inter,Arial,sans-serif}
body{margin:0;background:var(--bg);color:#0f172a}
header{background:linear-gradient(135deg,var(--primary),#1e40af);color:#fff;padding:12px 18px;position:relative}
.container{max-width:1100px;margin:18px auto;padding:0 18px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.controls .left{flex:1;display:flex;gap:8px;align-items:center}
input,select,textarea{padding:10px;border-radius:8px;border:1px solid #e6eefc;background:white}
.btn{background:var(--primary);color:white;padding:10px 12px;border-radius:8px;border:none;cursor:pointer;font-weight:600}
.card{background:var(--card);border-radius:12px;padding:12px;box-shadow:0 8px 30px rgba(2,6,23,0.06);margin-bottom:12px}
.table{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden}
th,td{padding:10px;border-bottom:1px solid #eef2ff;text-align:left}
.badge{padding:6px 10px;border-radius:8px}
.stock{background:#dcfce7;color:#166534}
.sold{background:#fee2e2;color:#991b1b}
.form-stack{display:flex;flex-direction:column;gap:10px}
.small-btn{padding:6px 8px;border-radius:6px}
.link{color:var(--primary);text-decoration:none}
.top-right{position:absolute;right:18px;top:12px;color:white}
@media(max-width:780px){ .controls{flex-direction:column} .controls .left{flex-direction:column;align-items:stretch} th,td{display:block} tr{margin-bottom:12px} }
</style>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sai Vijaya Laxmi Vehicle Finance</title>
""" + BASE_CSS + """</head><body>
<header>
  <div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong>
    <span class="top-right">{% if current_username %}{{ current_username }} ({{ current_role }}) • <a href="{{ url_for('logout') }}" style="color:white">Logout</a>{% endif %}</span>
  </div>
</header>
<div class="container">
  <div class="controls">
    <div class="left">
      <form id="searchForm" method="get" action="/" style="display:flex;gap:8px;align-items:center;width:100%">
        <input type="text" name="q" placeholder="Search name / brand / model / vehicle number" value="{{ q }}">
        <select name="type">
          <option value="ALL" {% if vtype=='ALL' %}selected{% endif %}>All Types</option>
          <option value="Car" {% if vtype=='Car' %}selected{% endif %}>Car</option>
          <option value="Bike" {% if vtype=='Bike' %}selected{% endif %}>Bike</option>
        </select>
        <select name="status">
          <option value="ALL" {% if status=='ALL' %}selected{% endif %}>All Status</option>
          <option value="Stock" {% if status=='Stock' %}selected{% endif %}>In Stock</option>
          <option value="Sold" {% if status=='Sold' %}selected{% endif %}>Sold</option>
        </select>
        <button class="btn" type="submit">Search</button>
      </form>
    </div>
    <div>{% if current_role == 'admin' %}<a class="btn" href="{{ url_for('add_vehicle') }}">+ Add Vehicle</a>{% endif %}</div>
  </div>

  <div class="card" style="display:flex;gap:12px;">
    <div style="flex:1"><div style="color:var(--muted)">Total</div><div style="font-weight:700">{{ total }}</div></div>
    <div style="flex:1"><div style="color:var(--muted)">In Stock</div><div style="font-weight:700">{{ stock }}</div></div>
    <div style="flex:1"><div style="color:var(--muted)">Sold</div><div style="font-weight:700">{{ sold }}</div></div>
  </div>

  <div class="card">
    <table class="table">
      <thead><tr><th>#</th><th>Type</th><th>Name</th><th>Brand</th><th>Model</th><th>Number</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>
      {% for v in vehicles %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ v.type }}</td>
          <td>{{ v.name }}</td>
          <td>{{ v.brand }}</td>
          <td>{{ v.model }}</td>
          <td><a href="{{ url_for('view_vehicle', vid=v.id) }}" class="link">{{ v.number }}</a></td>
          <td>{% if v.status=='Stock' %}<span class="badge stock">In Stock</span>{% else %}<span class="badge sold">Sold</span>{% endif %}</td>
          <td>
            <a href="{{ url_for('view_vehicle', vid=v.id) }}">View</a>
            {% if current_role == 'admin' %}
             | <a href="{{ url_for('edit_vehicle', vid=v.id) }}">Edit</a>
             {% if v.status=='Stock' %} | <a href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell</a>{% endif %}
             | <a href="#" onclick="if(confirm('Delete vehicle and all related data?')) location.href='{{ url_for('delete_vehicle', vid=v.id) }}'">Delete</a>
            {% endif %}
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  {% if current_role == 'admin' %}
  <div class="card">
    <h4>Admin Tools</h4>
    <a class="btn" href="{{ url_for('admin_backups') }}">Backups</a>
    <a class="btn" href="{{ url_for('admin_users') }}" style="margin-left:8px">Users</a>
    <a class="btn" href="{{ url_for('admin_export_ui') }}" style="margin-left:8px">Export CSV</a>
  </div>
  {% endif %}
</div></body></html>
"""

ADD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Add Vehicle</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong></div></header>
<div class="container"><div class="card"><a href="/">← Back to Dashboard</a>
<form method="post" class="form-stack" style="margin-top:12px">
  <label>Type</label>
  <select name="type" required>
    <option value="Bike" selected>Bike</option>
    <option value="Car">Car</option>
  </select>
  <label>Vehicle Name</label><input name="name" required>
  <label>Brand</label><input name="brand">
  <label>Model</label><input name="model">
  <label>Color</label><input name="color">
  <label>Vehicle Number</label><input name="number" required>
  <hr>
  <h4>Seller Information</h4>
  <label>Seller Name</label><input name="seller_name" required>
  <label>Seller Phone</label><input name="seller_phone">
  <label>Seller City</label><input name="seller_city">
  <label>Buy Value (integer)</label><input name="buy_value" type="number" step="1">
  <label>Buy Date</label><input name="buy_date" type="date">
  <label>Comments</label><textarea name="comments"></textarea>
  <div><button class="btn" type="submit">Save Vehicle</button></div>
</form></div></div></body></html>
"""

EDIT_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Vehicle</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong></div></header>
<div class="container"><div class="card"><a href="/">← Back to Dashboard</a>
<form method="post" class="form-stack" style="margin-top:12px">
  <label>Type</label>
  <select name="type" required>
    <option value="Car" {% if v.type=='Car' %}selected{% endif %}>Car</option>
    <option value="Bike" {% if v.type=='Bike' %}selected{% endif %}>Bike</option>
  </select>
  <label>Vehicle Name</label><input name="name" value="{{ v.name }}" required>
  <label>Brand</label><input name="brand" value="{{ v.brand }}">
  <label>Model</label><input name="model" value="{{ v.model }}">
  <label>Color</label><input name="color" value="{{ v.color }}">
  <label>Vehicle Number</label><input name="number" value="{{ v.number }}" required>
  <hr>
  <h4>Seller (update)</h4>
  <label>Seller Name</label><input name="seller_name" value="{{ s.seller_name if s else '' }}">
  <label>Seller Phone</label><input name="seller_phone" value="{{ s.seller_phone if s else '' }}">
  <label>Seller City</label><input name="seller_city" value="{{ s.seller_city if s else '' }}">
  <label>Buy Value (integer)</label><input name="buy_value" type="number" step="1" value="{{ s.buy_value if s else '' }}">
  <label>Buy Date</label><input name="buy_date" type="date" value="{{ s.buy_date if s else '' }}">
  <label>Comments</label><textarea name="comments">{{ s.comments if s else '' }}</textarea>
  <div><button class="btn" type="submit">Update (go to Dashboard)</button> <a href="/" style="margin-left:12px">Cancel</a></div>
</form></div></div></body></html>
"""

SELL_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sell Vehicle</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong></div></header>
<div class="container"><div class="card"><a href="/">← Back to Dashboard</a>
<h3>Sell: {{ v.name }} ({{ v.number }})</h3>
<form method="post" class="form-stack" style="margin-top:8px">
  <label>Record Number</label><input name="record_no">
  <label>Buyer Name</label><input name="buyer_name" required>
  <label>Buyer Phone</label><input name="buyer_phone">
  <label>Buyer Address</label><textarea name="buyer_address"></textarea>
  <label>Sale Value (integer)</label><input name="sale_value" type="number" step="1">
  <label>Finance Amount (integer)</label><input name="finance_amount" type="number" step="1">
  <label>EMI Amount (integer monthly)</label><input name="emi_amount" type="number" step="1" required>
  <label>Tenure (months)</label><input name="tenure" type="number" step="1" min="1" required>
  <label>Sale Date</label><input name="sale_date" type="date" value="{{ today }}">
  <div><button class="btn" type="submit">Confirm Sale & Generate EMIs</button></div>
</form></div></div></body></html>
"""

VIEW_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Details</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong></div></header>
<div class="container">
  <div class="card"><a href="/">← Back to Dashboard</a>
    <h2 style="margin-top:8px">{{ v.name }} <small style="color:var(--muted)">({{ v.type }})</small></h2>
    <p>{{ v.brand }} • {{ v.model }} • {{ v.color }}</p>
    <p><strong>Number:</strong> {{ v.number }}</p>
  </div>

  <div class="card"><h3>Seller Information</h3>
    {% if s %}
      <p><strong>Name:</strong> {{ s.seller_name }}</p>
      <p><strong>Phone:</strong> {{ s.seller_phone }}</p>
      <p><strong>City:</strong> {{ s.seller_city }}</p>
      <p><strong>Buy Value:</strong> ₹{{ s.buy_value }}</p>
      <p><strong>Buy Date:</strong> {{ s.buy_date }}</p>
      <p><strong>Comments:</strong> {{ s.comments }}</p>
    {% else %}
      <p>No seller info</p>
    {% endif %}
  </div>

  {% if b %}
  <div class="card">
    <h3>Buyer & Finance</h3>
    <p><strong>Buyer:</strong> {{ b.buyer_name }} • {{ b.buyer_phone }}</p>
    <p><strong>Sale Value:</strong> ₹{{ b.sale_value }} • <strong>Finance:</strong> ₹{{ b.finance_amount }}</p>
    <p><strong>EMI:</strong> ₹{{ b.emi_amount }} • <strong>Tenure:</strong> {{ b.tenure }} months • <strong>Sold on:</strong> {{ b.sale_date }}</p>

    <hr><h4>EMI Schedule</h4>
    <table class="table"><thead><tr><th>#</th><th>Due Date</th><th>Amount</th><th>Status</th><th>Action</th></tr></thead><tbody>
      {% for e in emis %}
      <tr>
        <td>{{ e.emi_no }}</td>
        <td>{{ e.due_date }}</td>
        <td>₹{{ e.amount }}</td>
        <td>{{ e.status }}</td>
        <td>
          {% if current_role == 'admin' %}
            <form method="post" action="{{ url_for('toggle_emi', emi_id=e.id) }}" style="display:inline">
              <input type="hidden" name="ref" value="{{ url_for('view_vehicle', vid=v.id) }}">
              {% if e.status != 'Paid' %}
                <button class="small-btn btn" name="action" value="mark_paid" onclick="return confirm('Mark EMI #{{ e.emi_no }} as PAID?')">Mark Paid</button>
              {% else %}
                <button class="small-btn" style="background:#ef4444;color:#fff;border:none;border-radius:6px;padding:8px" name="action" value="mark_unpaid" onclick="return confirm('Mark EMI #{{ e.emi_no }} as UNPAID?')">Mark Unpaid</button>
              {% endif %}
            </form>
          {% else %}
            -
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody></table>

    <div style="margin-top:10px">{% if current_role == 'admin' %}<a class="btn" href="{{ url_for('edit_buyer', vid=v.id) }}">Edit Buyer</a>{% endif %}</div>
  </div>
  {% else %}
  <div class="card"><h3>No buyer recorded</h3>{% if current_role == 'admin' %}<a class="btn" href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell this vehicle</a>{% endif %}</div>
  {% endif %}
</div></body></html>
"""

EDIT_BUYER_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Buyer</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong></div></header>
<div class="container"><div class="card"><a href="{{ url_for('view_vehicle', vid=vid) }}">← Back to Details</a>
<form method="post" class="form-stack" style="margin-top:12px">
  <label>Buyer Name</label><input name="buyer_name" value="{{ buyer.buyer_name if buyer else '' }}" required>
  <label>Buyer Phone</label><input name="buyer_phone" value="{{ buyer.buyer_phone if buyer else '' }}">
  <label>Buyer Address</label><textarea name="buyer_address">{{ buyer.buyer_address if buyer else '' }}</textarea>
  <label>Sale Value (integer)</label><input name="sale_value" type="number" step="1" value="{{ buyer.sale_value if buyer else '' }}">
  <label>Finance Amount (integer)</label><input name="finance_amount" type="number" step="1" value="{{ buyer.finance_amount if buyer else '' }}">
  <label>EMI Amount (integer)</label><input name="emi_amount" type="number" step="1" value="{{ buyer.emi_amount if buyer else '' }}">
  <label>Tenure (months)</label><input name="tenure" type="number" step="1" min="1" value="{{ buyer.tenure if buyer else '' }}">
  <div><button class="btn" type="submit">Save Buyer</button></div>
</form></div></div></body></html>
"""

# Admin users templates:
ADMIN_USERS_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Users</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Admin: Users</strong><span class="top-right"><a href="/">Back</a></span></div></header>
<div class="container">
  <div class="card">
    <a class="btn" href="{{ url_for('admin_users_create') }}">+ Create User</a>
    <table class="table"><thead><tr><th>#</th><th>Username</th><th>Name</th><th>Role</th><th>Actions</th></tr></thead><tbody>
    {% for u in users %}
      <tr><td>{{ loop.index }}</td><td>{{ u.username }}</td><td>{{ u.name }}</td><td>{{ u.role }}</td>
      <td><a href="{{ url_for('admin_users_edit', uid=u.id) }}">Edit</a> | 
          <form method="post" action="{{ url_for('admin_users_delete', uid=u.id) }}" style="display:inline" onsubmit="return confirm('Delete user?')">
            <button type="submit">Delete</button>
          </form>
      </td></tr>
    {% endfor %}
    </tbody></table>
  </div>
</div></body></html>
"""

ADMIN_USERS_CREATE_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Create User</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Create User</strong><span class="top-right"><a href="{{ url_for('admin_users') }}">Back</a></span></div></header>
<div class="container"><div class="card">
<form method="post" class="form-stack">
  <label>Username (phone)</label><input name="username" required>
  <label>Name</label><input name="name">
  <label>Role</label><select name="role"><option value="admin">admin</option><option value="user">user</option></select>
  <label>Password</label><input name="password" type="password" required>
  <div><button class="btn" type="submit">Create</button></div>
</form></div></div></body></html>
"""

ADMIN_USERS_EDIT_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit User</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Edit User</strong><span class="top-right"><a href="{{ url_for('admin_users') }}">Back</a></span></div></header>
<div class="container"><div class="card">
<form method="post" class="form-stack">
  <label>Username (readonly)</label><input value="{{ user.username }}" readonly>
  <label>Name</label><input name="name" value="{{ user.name }}">
  <label>Role</label><select name="role"><option value="admin" {% if user.role=='admin' %}selected{% endif %}>admin</option><option value="user" {% if user.role=='user' %}selected{% endif %}>user</option></select>
  <label>New Password (leave blank to keep)</label><input name="password" type="password">
  <div><button class="btn" type="submit">Save</button></div>
</form></div></div></body></html>
"""

# Admin backups template
ADMIN_BACKUPS_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Backups</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Backups</strong><span class="top-right"><a href="/">Back</a></span></div></header>
<div class="container"><div class="card">
  <form method="post" action="{{ url_for('admin_backup_create') }}"><button class="btn" type="submit">Create Backup Now</button></form>
  <hr><ul>
  {% for f in files %}
    <li>{{ f.name }} ({{ f.mtime }}) - <a href="{{ url_for('admin_backup_download', filename=f.name) }}">Download</a>
      <form method="post" action="{{ url_for('admin_backup_delete', filename=f.name) }}" style="display:inline"><button type="submit">Delete</button></form>
    </li>
  {% endfor %}
  </ul>
</div></div></body></html>
"""

# Admin export UI
ADMIN_EXPORT_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Export</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Export CSV</strong><span class="top-right"><a href="/">Back</a></span></div></header>
<div class="container"><div class="card">
  <h4>Choose export</h4>
  <a class="btn" href="{{ url_for('admin_export_csv', type='full') }}">Full export (vehicles+sellers+buyers)</a>
  <a class="btn" href="{{ url_for('admin_export_csv', type='vehicles') }}" style="margin-left:6px">Vehicles CSV</a>
  <a class="btn" href="{{ url_for('admin_export_csv', type='sellers') }}" style="margin-left:6px">Sellers CSV</a>
  <a class="btn" href="{{ url_for('admin_export_csv', type='buyers') }}" style="margin-left:6px">Buyers CSV</a>
  <a class="btn" href="{{ url_for('admin_export_csv', type='emis') }}" style="margin-left:6px">EMIs CSV</a>
</div></div></body></html>
"""

# ----------------- run -----------------
if __name__ == "__main__":
    #app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    app.run()
