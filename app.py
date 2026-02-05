# app.py
import os
import csv
import io
import zipfile
from datetime import datetime, date
from pathlib import Path
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, render_template_string, session,
    send_from_directory, abort, flash, Response
)
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import escape

# # ----------------- CONFIG -----------------
FULL_CSV = os.environ.get("FULL_CSV_PATH", "data/full.csv")
EMI_CSV = os.environ.get("EMI_CSV_PATH", "data/emi.csv")
USERS_CSV = os.environ.get("USERS_CSV_PATH", "data/users.csv")
AUDIT_CSV = os.environ.get("AUDIT_CSV_PATH", "data/audit_log.csv")
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_for_prod")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "10"))
VEHICLE_PAGE_SIZE = int(os.environ.get("VEHICLE_PAGE_SIZE", "15"))

INITIAL_USERS = [
    {"username": "9492126272", "password": "Madan@1440", "role": "admin", "name": "Admin One"},
    {"username": "9490479284", "password": "Laxmi@6799", "role": "admin", "name": "Admin Two"},
    {"username": "9492146644", "password": "Rupa@0642",  "role": "user",  "name": "User One"},
    {"username": "9492948661", "password": "Venky@8661",  "role": "user",  "name": "User Two"},
]

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ----------------- CSV helpers & init -----------------
FULL_FIELDS = [
    "vehicle_id", "type", "name", "brand", "model", "color", "number", "status",
    "seller_name", "seller_phone", "seller_city", "buy_value", "buy_date", "comments",
    "buyer_id", "record_no", "buyer_name", "buyer_phone", "buyer_address", "sale_value",
    "finance_amount", "emi_amount", "tenure", "sale_date",
]
EMI_FIELDS = ["id", "buyer_id", "emi_no", "due_date", "amount", "status", "paid_date"]
USER_FIELDS = ["id", "username", "name", "password_hash", "role"]
AUDIT_FIELDS = ["id", "who", "action", "target", "ts"]

def ensure_csv(path, fieldnames):
    path_obj = Path(path)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with path_obj.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

def read_csv_rows(path, fieldnames):
    ensure_csv(path, fieldnames)
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({key: row.get(key, "") for key in fieldnames})
    return rows

def write_csv_rows(path, fieldnames, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

def load_full_rows():
    return read_csv_rows(FULL_CSV, FULL_FIELDS)

def save_full_rows(rows):
    write_csv_rows(FULL_CSV, FULL_FIELDS, rows)

def load_emi_rows():
    return read_csv_rows(EMI_CSV, EMI_FIELDS)

def save_emi_rows(rows):
    write_csv_rows(EMI_CSV, EMI_FIELDS, rows)

def load_users():
    return read_csv_rows(USERS_CSV, USER_FIELDS)

def save_users(rows):
    write_csv_rows(USERS_CSV, USER_FIELDS, rows)

def load_audit_rows():
    return read_csv_rows(AUDIT_CSV, AUDIT_FIELDS)

def save_audit_rows(rows):
    write_csv_rows(AUDIT_CSV, AUDIT_FIELDS, rows)

def next_id(rows, key):
    max_id = 0
    for row in rows:
        try:
            max_id = max(max_id, int(row.get(key) or 0))
        except ValueError:
            continue
    return max_id + 1

def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def normalize_finance_terms(finance_amount, emi_amount, tenure):
    finance_amount = max(finance_amount, 0)
    emi_amount = max(emi_amount, 0)
    tenure = max(tenure, 0)

    # No-finance sale: store EMI details as zero and skip EMI generation.
    if finance_amount == 0:
        return 0, 0, 0

    return finance_amount, emi_amount, tenure

def parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def derive_emi_status(emi_row, today=None):
    today = today or date.today()
    if (emi_row.get("status") or "").strip().lower() == "paid":
        return "Paid"
    due_date = parse_iso_date(emi_row.get("due_date"))
    if not due_date:
        return "Unpaid"
    if due_date < today:
        return "Overdue"
    if due_date > today:
        return "Upcoming"
    return "Due Today"

def seed_initial_users():
    users = load_users()
    if users:
        return
    for u in INITIAL_USERS:
        users.append({
            "id": str(next_id(users, "id")),
            "username": u["username"],
            "name": u.get("name", u["username"]),
            "password_hash": generate_password_hash(u["password"]),
            "role": u.get("role", "user"),
        })
    save_users(users)

seed_initial_users()

# ----------------- utilities -----------------
def add_months(orig_date: date, months: int) -> date:
    return orig_date + relativedelta(months=months)

def vehicle_row_from_full(row):
    vehicle = dict(row)
    vehicle["id"] = to_int(row.get("vehicle_id") or 0)
    return vehicle

def seller_from_full(row):
    if not row:
        return None
    return {
        "id": to_int(row.get("vehicle_id") or 0),
        "vehicle_id": to_int(row.get("vehicle_id") or 0),
        "seller_name": row.get("seller_name", ""),
        "seller_phone": row.get("seller_phone", ""),
        "seller_city": row.get("seller_city", ""),
        "buy_value": row.get("buy_value", ""),
        "buy_date": row.get("buy_date", ""),
        "comments": row.get("comments", ""),
    }

def buyer_from_full(row):
    buyer_id = row.get("buyer_id") if row else ""
    if not buyer_id:
        return None
    return {
        "id": to_int(buyer_id),
        "vehicle_id": to_int(row.get("vehicle_id") or 0),
        "record_no": row.get("record_no", ""),
        "buyer_name": row.get("buyer_name", ""),
        "buyer_phone": row.get("buyer_phone", ""),
        "buyer_address": row.get("buyer_address", ""),
        "sale_value": row.get("sale_value", ""),
        "finance_amount": row.get("finance_amount", ""),
        "emi_amount": row.get("emi_amount", ""),
        "tenure": row.get("tenure", ""),
        "sale_date": row.get("sale_date", ""),
    }

def emis_for_buyer(buyer_id):
    rows = load_emi_rows()
    filtered = [row for row in rows if str(row.get("buyer_id")) == str(buyer_id)]
    for row in filtered:
        row["id"] = to_int(row.get("id") or 0)
        row["emi_no"] = to_int(row.get("emi_no") or 0)
    filtered.sort(key=lambda r: r.get("emi_no") or 0)
    return filtered

def log_action(who, action, target=""):
    try:
        rows = load_audit_rows()
        rows.append({
            "id": str(next_id(rows, "id")),
            "who": who or "",
            "action": action,
            "target": target,
            "ts": datetime.now().isoformat(),
        })
        save_audit_rows(rows)
    except Exception:
        pass


def filtered_vehicle_rows(rows, q, metric, overdue_buyer_ids):
    vehicles = []
    q_lower = q.lower()
    for row in rows:
        if metric == "Stock" and row.get("status") != "Stock":
            continue
        if metric == "Sold" and row.get("status") != "Sold":
            continue
        if metric == "EMI_PENDING":
            if row.get("status") != "Sold":
                continue
            if str(row.get("buyer_id")) not in overdue_buyer_ids:
                continue
        if metric == "ALL" and row.get("status") not in {"Stock", "Sold"}:
            continue
        if q:
            haystack = " ".join([
                row.get("name", ""),
                row.get("brand", ""),
                row.get("model", ""),
                row.get("number", ""),
                row.get("seller_name", ""),
                row.get("seller_phone", ""),
                row.get("seller_city", ""),
                row.get("buyer_name", ""),
                row.get("buyer_phone", ""),
            ]).lower()
            if q_lower not in haystack:
                continue
        vehicles.append(vehicle_row_from_full(row))
    return vehicles

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
    files = sorted(BACKUP_DIR.glob("data_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files
def create_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"data_{ts}.zip"
    dest = BACKUP_DIR / fname
    files_to_backup = [FULL_CSV, EMI_CSV, USERS_CSV, AUDIT_CSV]
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files_to_backup:
            if Path(path).exists():
                zf.write(path, arcname=Path(path).name)
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
        users = load_users()
        u = next((user for user in users if user.get("username") == username), None)
        if not u or not check_password_hash(u.get("password_hash", ""), password):
            error = "Invalid username or password"
        else:
            session["user_id"] = int(u.get("id") or 0)
            session["username"] = u.get("username")
            session["name"] = u.get("name")
            session["role"] = u.get("role")
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
    vtype = request.args.get("type", "Bike")
    metric = request.args.get("metric", "ALL")
    if vtype not in {"Car", "Bike"}:
        vtype = "Bike"
    if metric not in {"ALL", "Stock", "Sold", "EMI_PENDING"}:
        metric = "ALL"

    rows = load_full_rows()
    emi_rows = load_emi_rows()
    overdue_buyer_ids = {
        str(emi.get("buyer_id"))
        for emi in emi_rows
        if derive_emi_status(emi) == "Overdue"
    }
    type_rows = [row for row in rows if row.get("type") == vtype]

    total = len(type_rows)
    stock = sum(1 for row in type_rows if row.get("status") == "Stock")
    sold = sum(1 for row in type_rows if row.get("status") == "Sold")
    emi_pending = sum(
        1 for row in type_rows
        if row.get("status") == "Sold"
        and row.get("buyer_id")
        and str(row.get("buyer_id")) in overdue_buyer_ids
    )

    filtered_vehicles = filtered_vehicle_rows(type_rows, q, metric, overdue_buyer_ids)
    vehicles = filtered_vehicles[:VEHICLE_PAGE_SIZE]
    has_more = len(filtered_vehicles) > len(vehicles)
    return render_template_string(
        DASHBOARD_HTML,
        vehicles=vehicles,
        vehicle_page_size=VEHICLE_PAGE_SIZE,
        initial_count=len(vehicles),
        has_more=has_more,
        q=q,
        vtype=vtype,
        metric=metric,
        total=total,
        stock=stock,
        sold=sold,
        emi_pending=emi_pending,
    )


@app.route("/vehicles")
@login_required
def dashboard_vehicle_page():
    q = request.args.get("q", "").strip()
    vtype = request.args.get("type", "Bike")
    metric = request.args.get("metric", "ALL")
    offset = max(to_int(request.args.get("offset"), 0), 0)
    limit = max(to_int(request.args.get("limit"), VEHICLE_PAGE_SIZE), 1)

    if vtype not in {"Car", "Bike"}:
        vtype = "Bike"
    if metric not in {"ALL", "Stock", "Sold", "EMI_PENDING"}:
        metric = "ALL"

    rows = load_full_rows()
    emi_rows = load_emi_rows()
    overdue_buyer_ids = {
        str(emi.get("buyer_id"))
        for emi in emi_rows
        if derive_emi_status(emi) == "Overdue"
    }
    type_rows = [row for row in rows if row.get("type") == vtype]
    filtered_vehicles = filtered_vehicle_rows(type_rows, q, metric, overdue_buyer_ids)

    page_vehicles = filtered_vehicles[offset:offset + limit]
    html_rows = []
    for index, vehicle in enumerate(page_vehicles, start=offset + 1):
        number_url = url_for("view_vehicle", vid=vehicle["id"])
        if session.get("role") == "admin":
            edit_url = url_for("edit_vehicle", vid=vehicle["id"])
            sell_url = url_for("sell_vehicle", vid=vehicle["id"])
            delete_url = url_for("delete_vehicle", vid=vehicle["id"])
            actions = f'<a href="{edit_url}">Edit</a>'
            if vehicle.get("status") == "Stock":
                actions += f' | <a href="{sell_url}">Sell</a>'
            actions += f" | <a href=\"#\" onclick=\"if(confirm('Delete vehicle and all related data?')) location.href='{delete_url}'\">Delete</a>"
        else:
            actions = "-"

        status_badge = '<span class="badge stock">In Stock</span>' if vehicle.get("status") == "Stock" else '<span class="badge sold">Sold</span>'
        html_rows.append(
            """
            <tr>
              <td>{idx}</td>
              <td>{typ}</td>
              <td>{name}</td>
              <td>{brand}</td>
              <td>{model}</td>
              <td><a href="{number_url}" class="link">{number}</a></td>
              <td>{status_badge}</td>
              <td>{actions}</td>
            </tr>
            """.format(
                idx=index,
                typ=escape(vehicle.get("type", "")),
                name=escape(vehicle.get("name", "")),
                brand=escape(vehicle.get("brand", "")),
                model=escape(vehicle.get("model", "")),
                number_url=number_url,
                number=escape(vehicle.get("number", "")),
                status_badge=status_badge,
                actions=actions,
            )
        )

    return {
        "rows_html": "".join(html_rows),
        "next_offset": offset + len(page_vehicles),
        "has_more": offset + len(page_vehicles) < len(filtered_vehicles),
    }

# Add vehicle (admin only) — Bike default
@app.route("/add", methods=["GET","POST"])
@admin_required
def add_vehicle():
    if request.method == "POST":
        f = request.form
        try:
            buy_val = int(float(f.get("buy_value") or 0))
        except:
            buy_val = 0
        rows = load_full_rows()
        vid = next_id(rows, "vehicle_id")
        rows.append({
            "vehicle_id": str(vid),
            "type": f.get("type"),
            "name": f.get("name"),
            "brand": f.get("brand"),
            "model": f.get("model"),
            "color": f.get("color"),
            "number": f.get("number"),
            "status": "Stock",
            "seller_name": f.get("seller_name"),
            "seller_phone": f.get("seller_phone"),
            "seller_city": f.get("seller_city"),
            "buy_value": str(buy_val),
            "buy_date": f.get("buy_date") or "",
            "comments": f.get("comments") or "",
            "buyer_id": "",
            "record_no": "",
            "buyer_name": "",
            "buyer_phone": "",
            "buyer_address": "",
            "sale_value": "",
            "finance_amount": "",
            "emi_amount": "",
            "tenure": "",
            "sale_date": "",
        })
        save_full_rows(rows)
        log_action(session.get("username"), "add_vehicle", f.get("number"))
        return redirect(url_for("dashboard"))
    return render_template_string(ADD_HTML)

# Edit vehicle (admin only)
@app.route("/edit/<int:vid>", methods=["GET","POST"])
@admin_required
def edit_vehicle(vid):
    rows = load_full_rows()
    if request.method == "POST":
        f = request.form
        try:
            buy_val = int(float(f.get("buy_value") or 0))
        except:
            buy_val = 0
        for row in rows:
            if to_int(row.get("vehicle_id") or 0) == vid:
                row.update({
                    "type": f.get("type"),
                    "name": f.get("name"),
                    "brand": f.get("brand"),
                    "model": f.get("model"),
                    "color": f.get("color"),
                    "number": f.get("number"),
                    "seller_name": f.get("seller_name"),
                    "seller_phone": f.get("seller_phone"),
                    "seller_city": f.get("seller_city"),
                    "buy_value": str(buy_val),
                    "buy_date": f.get("buy_date") or "",
                    "comments": f.get("comments") or "",
                })
                break
        save_full_rows(rows)
        log_action(session.get("username"), "edit_vehicle", str(vid))
        return redirect(url_for("dashboard"))
    row = next((r for r in rows if to_int(r.get("vehicle_id") or 0) == vid), None)
    v = vehicle_row_from_full(row) if row else None
    s = seller_from_full(row) if row else None
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(EDIT_HTML, v=v, s=s)

# Delete (admin)
@app.route("/delete/<int:vid>", methods=["GET"])
@admin_required
def delete_vehicle(vid):
    rows = load_full_rows()
    buyer_ids = [row.get("buyer_id") for row in rows if to_int(row.get("vehicle_id") or 0) == vid and row.get("buyer_id")]
    rows = [row for row in rows if to_int(row.get("vehicle_id") or 0) != vid]
    save_full_rows(rows)
    if buyer_ids:
        emis = load_emi_rows()
        emis = [row for row in emis if str(row.get("buyer_id")) not in {str(bid) for bid in buyer_ids}]
        save_emi_rows(emis)
    log_action(session.get("username"), "delete_vehicle", str(vid))
    return redirect(url_for("dashboard"))

# Sell (admin) -> creates buyer + EMIs
@app.route("/sell/<int:vid>", methods=["GET","POST"])
@admin_required
def sell_vehicle(vid):
    rows = load_full_rows()
    row = next((r for r in rows if to_int(r.get("vehicle_id") or 0) == vid), None)
    v = vehicle_row_from_full(row) if row else None
    if not v:
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

        finance_amount, emi_amount, tenure = normalize_finance_terms(finance_amount, emi_amount, tenure)

        sale_date = f.get("sale_date") or datetime.now().strftime("%Y-%m-%d")
        buyer_id = next_id(rows, "buyer_id")
        for current in rows:
            if to_int(current.get("vehicle_id") or 0) == vid:
                current.update({
                    "record_no": f.get("record_no") or "",
                    "buyer_name": f.get("buyer_name"),
                    "buyer_phone": f.get("buyer_phone"),
                    "buyer_address": f.get("buyer_address"),
                    "sale_value": str(sale_value),
                    "finance_amount": str(finance_amount),
                    "emi_amount": str(emi_amount),
                    "tenure": str(tenure),
                    "sale_date": sale_date,
                    "buyer_id": str(buyer_id),
                    "status": "Sold",
                })
                break

        sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
        emis_rows = load_emi_rows()
        for i in range(1, tenure + 1):
            due = add_months(sd, i)
            emis_rows.append({
                "id": str(next_id(emis_rows, "id")),
                "buyer_id": str(buyer_id),
                "emi_no": str(i),
                "due_date": due.isoformat(),
                "amount": str(emi_amount),
                "status": "Unpaid",
                "paid_date": "",
            })

        save_full_rows(rows)
        save_emi_rows(emis_rows)
        log_action(session.get("username"), "sell_vehicle", f"vehicle:{vid} buyer:{buyer_id}")
        return redirect(url_for("view_vehicle", vid=vid))
    return render_template_string(SELL_HTML, v=v, today=datetime.now().strftime("%Y-%m-%d"))

# View (both roles)
@app.route("/view/<int:vid>", methods=["GET"])
@login_required
def view_vehicle(vid):
    rows = load_full_rows()
    row = next((r for r in rows if to_int(r.get("vehicle_id") or 0) == vid), None)
    v = vehicle_row_from_full(row) if row else None
    s = seller_from_full(row) if row else None
    b = buyer_from_full(row) if row else None
    emis = emis_for_buyer(b["id"]) if b else []
    for emi in emis:
        emi["derived_status"] = derive_emi_status(emi)
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(VIEW_HTML, v=v, s=s, b=b, emis=emis)

# Edit buyer/finance (admin only) — safe EMI adjustments
@app.route("/buyer/<int:vid>", methods=["GET","POST"])
@admin_required
def edit_buyer(vid):
    rows = load_full_rows()
    row = next((r for r in rows if to_int(r.get("vehicle_id") or 0) == vid), None)
    buyer = buyer_from_full(row) if row else None

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

        new_finance_amount, new_emi_amount, new_tenure = normalize_finance_terms(
            new_finance_amount, new_emi_amount, new_tenure
        )

        if not buyer:
            sale_date = datetime.now().strftime("%Y-%m-%d")
            buyer_id = next_id(rows, "buyer_id")
            if row:
                row.update({
                    "buyer_id": str(buyer_id),
                    "buyer_name": f.get("buyer_name") or "",
                    "buyer_phone": f.get("buyer_phone") or "",
                    "buyer_address": f.get("buyer_address") or "",
                    "sale_value": str(new_sale_value),
                    "finance_amount": str(new_finance_amount),
                    "tenure": str(new_tenure),
                    "emi_amount": str(new_emi_amount),
                    "sale_date": sale_date,
                })
            sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
            emis_rows = load_emi_rows()
            for i in range(1, new_tenure + 1):
                due = add_months(sd, i)
                emis_rows.append({
                    "id": str(next_id(emis_rows, "id")),
                    "buyer_id": str(buyer_id),
                    "emi_no": str(i),
                    "due_date": due.isoformat(),
                    "amount": str(new_emi_amount),
                    "status": "Unpaid",
                    "paid_date": "",
                })
            save_full_rows(rows)
            save_emi_rows(emis_rows)
            log_action(session.get("username"), "create_buyer", f"vehicle:{vid} buyer:{buyer_id}")
            return redirect(url_for("view_vehicle", vid=vid))

        buyer_id = buyer["id"]
        old_tenure = int(buyer["tenure"] or 0)
        old_emi_amount = int(buyer["emi_amount"] or 0)
        sale_date_str = buyer["sale_date"] or datetime.now().strftime("%Y-%m-%d")
        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date()

        if row:
            row.update({
                "buyer_name": f.get("buyer_name") or "",
                "buyer_phone": f.get("buyer_phone") or "",
                "buyer_address": f.get("buyer_address") or "",
                "sale_value": str(new_sale_value),
                "finance_amount": str(new_finance_amount),
                "emi_amount": str(new_emi_amount),
                "tenure": str(new_tenure),
            })

        emis_rows = load_emi_rows()
        if new_emi_amount != old_emi_amount:
            for emi in emis_rows:
                if str(emi.get("buyer_id")) == str(buyer_id) and emi.get("status") != "Paid":
                    emi["amount"] = str(new_emi_amount)

        if new_tenure > old_tenure:
            for i in range(old_tenure + 1, new_tenure + 1):
                due = add_months(sale_date, i)
                emis_rows.append({
                    "id": str(next_id(emis_rows, "id")),
                    "buyer_id": str(buyer_id),
                    "emi_no": str(i),
                    "due_date": due.isoformat(),
                    "amount": str(new_emi_amount),
                    "status": "Unpaid",
                    "paid_date": "",
                })
        elif new_tenure < old_tenure:
            emis_rows = [
                emi for emi in emis_rows
                if not (str(emi.get("buyer_id")) == str(buyer_id)
                        and to_int(emi.get("emi_no") or 0) > new_tenure
                        and emi.get("status") != "Paid")
            ]

        save_full_rows(rows)
        save_emi_rows(emis_rows)
        log_action(session.get("username"), "edit_buyer", f"vehicle:{vid} buyer:{buyer_id}")
        return redirect(url_for("view_vehicle", vid=vid))

    return render_template_string(EDIT_BUYER_HTML, buyer=buyer, vid=vid)

# Toggle EMI (admin)
@app.route("/emi/toggle/<int:emi_id>", methods=["POST"])
@admin_required
def toggle_emi(emi_id):
    action = request.form.get("action")
    emis_rows = load_emi_rows()
    for row in emis_rows:
        if to_int(row.get("id") or 0) == emi_id:
            if action == "mark_paid":
                row["status"] = "Paid"
                row["paid_date"] = date.today().isoformat()
                log_action(session.get("username"), "mark_emi_paid", str(emi_id))
            else:
                row["status"] = "Unpaid"
                row["paid_date"] = ""
                log_action(session.get("username"), "mark_emi_unpaid", str(emi_id))
            break
    save_emi_rows(emis_rows)
    ref = request.form.get("ref") or url_for("dashboard")
    return redirect(ref)

# ------------- Admin: Users management ----------------
@app.route("/admin/users")
@admin_required
def admin_users():
    users = load_users()
    users = [{**u, "id": to_int(u.get("id") or 0)} for u in users]
    users.sort(key=lambda u: u.get("id") or 0)
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
        users = load_users()
        if any(u.get("username") == username for u in users):
            return "username exists", 400
        users.append({
            "id": str(next_id(users, "id")),
            "username": username,
            "name": name,
            "password_hash": pwhash,
            "role": role,
        })
        save_users(users)
        log_action(session.get("username"), "create_user", username)
        return redirect(url_for("admin_users"))
    return render_template_string(ADMIN_USERS_CREATE_HTML)

@app.route("/admin/users/edit/<int:uid>", methods=["GET","POST"])
@admin_required
def admin_users_edit(uid):
    if request.method == "POST":
        f = request.form
        name = f.get("name").strip()
        role = f.get("role")
        pwd = f.get("password")
        users = load_users()
        for user in users:
            if to_int(user.get("id") or 0) == uid:
                user["name"] = name
                user["role"] = role
                if pwd:
                    user["password_hash"] = generate_password_hash(pwd)
                break
        save_users(users)
        log_action(session.get("username"), "edit_user", str(uid))
        return redirect(url_for("admin_users"))
    users = load_users()
    user = next((u for u in users if to_int(u.get("id") or 0) == uid), None)
    if not user:
        return redirect(url_for("admin_users"))
    return render_template_string(ADMIN_USERS_EDIT_HTML, user=user)

@app.route("/admin/users/delete/<int:uid>", methods=["POST"])
@admin_required
def admin_users_delete(uid):
    # prevent deleting yourself
    if session.get("user_id") == uid:
        return "Cannot delete yourself", 400
    users = load_users()
    users = [u for u in users if to_int(u.get("id") or 0) != uid]
    save_users(users)
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
    rows = load_full_rows()

    if typ == "vehicles":
        fieldnames = ["id","type","name","brand","model","color","number","status"]
        rows_dicts = [{
            "id": row.get("vehicle_id", ""),
            "type": row.get("type", ""),
            "name": row.get("name", ""),
            "brand": row.get("brand", ""),
            "model": row.get("model", ""),
            "color": row.get("color", ""),
            "number": row.get("number", ""),
            "status": row.get("status", ""),
        } for row in rows]
        return rows_to_csv_response("vehicles.csv", fieldnames, rows_dicts)

    if typ == "sellers":
        fieldnames = ["id","vehicle_id","seller_name","seller_phone","seller_city","buy_value","buy_date","comments"]
        rows_dicts = [{
            "id": row.get("vehicle_id", ""),
            "vehicle_id": row.get("vehicle_id", ""),
            "seller_name": row.get("seller_name", ""),
            "seller_phone": row.get("seller_phone", ""),
            "seller_city": row.get("seller_city", ""),
            "buy_value": row.get("buy_value", ""),
            "buy_date": row.get("buy_date", ""),
            "comments": row.get("comments", ""),
        } for row in rows]
        return rows_to_csv_response("sellers.csv", fieldnames, rows_dicts)

    if typ == "buyers":
        fieldnames = ["id","vehicle_id","record_no","buyer_name","buyer_phone","buyer_address","sale_value","finance_amount","emi_amount","tenure","sale_date"]
        rows_dicts = [{
            "id": row.get("buyer_id", ""),
            "vehicle_id": row.get("vehicle_id", ""),
            "record_no": row.get("record_no", ""),
            "buyer_name": row.get("buyer_name", ""),
            "buyer_phone": row.get("buyer_phone", ""),
            "buyer_address": row.get("buyer_address", ""),
            "sale_value": row.get("sale_value", ""),
            "finance_amount": row.get("finance_amount", ""),
            "emi_amount": row.get("emi_amount", ""),
            "tenure": row.get("tenure", ""),
            "sale_date": row.get("sale_date", ""),
        } for row in rows if row.get("buyer_id")]
        return rows_to_csv_response("buyers.csv", fieldnames, rows_dicts)

    if typ == "emis":
        rows = load_emi_rows()
        fieldnames = EMI_FIELDS
        return rows_to_csv_response("emis.csv", fieldnames, rows)

    fieldnames = FULL_FIELDS
    return rows_to_csv_response("full_export.csv", fieldnames, rows)

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
.top-right{position:absolute;right:120px;top:12px;color:white}
.search-input{width:100%;min-width:520px;max-width:760px;padding:12px 14px;border:1px solid #dbe5f4;border-radius:10px}
.metric-total{background:#eef2ff;border-color:#c7d2fe}
.metric-stock{background:#ecfdf5;border-color:#86efac}
.metric-sold{background:#fef2f2;border-color:#fca5a5}
.metric-emi{background:#fffbeb;border-color:#fcd34d}
.pill{padding:8px 12px;border-radius:999px;border:1px solid #cbd5e1;text-decoration:none;color:#0f172a;background:#fff;font-weight:600}
.pill.active{background:#2563eb;color:#fff;border-color:#2563eb}
.metric-card{flex:1;text-decoration:none;color:inherit;border:1px solid #e2e8f0;border-radius:10px;padding:10px;display:block}
.metric-card.active{border-color:#2563eb;background:#eff6ff}
.emi-overdue{background:#fef3c7;color:#92400e}
.emi-upcoming{background:#dbeafe;color:#1e3a8a}
.vehicle-table-scroll{max-height:460px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:10px}
.vehicle-table-scroll table{margin:0}
.vehicle-table-scroll thead th{position:sticky;top:0;background:#f8fafc;z-index:1}
@media(max-width:780px){ .controls{flex-direction:column} .controls .left{flex-direction:column;align-items:stretch} th,td{display:block} tr{margin-bottom:12px} }
</style>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sai Vijaya Laxmi Vehicle Finance</title>
""" + BASE_CSS + """</head><body>
<header>
  <div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Sai Vijaya Laxmi Vehicle Finance</strong>
    <span class="top-right">{% if current_username %}<a href="{{ url_for('logout') }}" style="color:white">Logout</a>{% endif %}</span>
  </div>
</header>
<div class="container">
  <div class="controls">
    <div class="left">
      <form id="searchForm" method="get" action="/" style="display:flex;gap:8px;align-items:center;width:100%">
        <input type="hidden" name="type" value="{{ vtype }}">
        <input type="hidden" name="metric" value="{{ metric }}">
        <input id="searchInput" class="search-input" type="text" name="q" placeholder="Search by vehicle, seller/buyer name, phone, city (press Enter)" value="{{ q }}" autocomplete="off">
      </form>
    </div>
    <div style="display:flex;gap:8px">
      <a class="pill {% if vtype=='Car' %}active{% endif %}" href="{{ url_for('dashboard', type='Car', metric=metric, q=q) }}">Cars</a>
      <a class="pill {% if vtype=='Bike' %}active{% endif %}" href="{{ url_for('dashboard', type='Bike', metric=metric, q=q) }}">Bikes</a>
    </div>
    <div>{% if current_role == 'admin' %}<a class="btn" href="{{ url_for('add_vehicle') }}">+ Add Vehicle</a>{% endif %}</div>
  </div>

  <div class="card" style="display:flex;gap:12px;">
    <a class="metric-card metric-total {% if metric=='ALL' %}active{% endif %}" href="{{ url_for('dashboard', type=vtype, metric='ALL', q=q) }}"><div style="color:var(--muted)">Total</div><div style="font-weight:700">{{ total }}</div></a>
    <a class="metric-card metric-stock {% if metric=='Stock' %}active{% endif %}" href="{{ url_for('dashboard', type=vtype, metric='Stock', q=q) }}"><div style="color:var(--muted)">In Stock</div><div style="font-weight:700">{{ stock }}</div></a>
    <a class="metric-card metric-sold {% if metric=='Sold' %}active{% endif %}" href="{{ url_for('dashboard', type=vtype, metric='Sold', q=q) }}"><div style="color:var(--muted)">Sold</div><div style="font-weight:700">{{ sold }}</div></a>
    <a class="metric-card metric-emi {% if metric=='EMI_PENDING' %}active{% endif %}" href="{{ url_for('dashboard', type=vtype, metric='EMI_PENDING', q=q) }}"><div style="color:var(--muted)">EMI Pending</div><div style="font-weight:700">{{ emi_pending }}</div></a>
  </div>

  <div class="card">
    <div id="vehiclesScroll" class="vehicle-table-scroll">
      <table class="table">
        <thead><tr><th>#</th><th>Type</th><th>Name</th><th>Brand</th><th>Model</th><th>Number</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody id="vehiclesBody">
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
              {% if current_role == 'admin' %}
               <a href="{{ url_for('edit_vehicle', vid=v.id) }}">Edit</a>
               {% if v.status=='Stock' %} | <a href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell</a>{% endif %}
               | <a href="#" onclick="if(confirm('Delete vehicle and all related data?')) location.href='{{ url_for('delete_vehicle', vid=v.id) }}'">Delete</a>
              {% else %}
               -
              {% endif %}
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      <div id="vehiclesLoader" style="padding:12px;text-align:center;color:var(--muted);{% if not has_more %}display:none;{% endif %}">Loading more vehicles...</div>
      <div id="vehiclesEnd" style="padding:12px;text-align:center;color:var(--muted);{% if has_more %}display:none;{% endif %}">All vehicles loaded.</div>
      <div id="vehiclesSentinel" style="height:1px"></div>
    </div>
  </div>


<script>
(function () {
  const body = document.getElementById('vehiclesBody');
  const sentinel = document.getElementById('vehiclesSentinel');
  const loader = document.getElementById('vehiclesLoader');
  const end = document.getElementById('vehiclesEnd');
  const scrollRoot = document.getElementById('vehiclesScroll');
  if (!body || !sentinel || !scrollRoot) return;

  let offset = {{ initial_count }};
  const limit = {{ vehicle_page_size }};
  let hasMore = {{ 'true' if has_more else 'false' }};
  let loading = false;

  function syncState() {
    loader.style.display = hasMore ? 'block' : 'none';
    end.style.display = hasMore ? 'none' : 'block';
  }

  async function loadMore() {
    if (loading || !hasMore) return;
    loading = true;
    try {
      const params = new URLSearchParams({
        q: '{{ q|e }}',
        type: '{{ vtype|e }}',
        metric: '{{ metric|e }}',
        offset: String(offset),
        limit: String(limit)
      });
      const response = await fetch(`/vehicles?${params.toString()}`);
      if (!response.ok) return;
      const data = await response.json();
      if (data.rows_html) {
        body.insertAdjacentHTML('beforeend', data.rows_html);
      }
      offset = data.next_offset;
      hasMore = data.has_more;
      syncState();
    } finally {
      loading = false;
    }
  }

  syncState();
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        loadMore();
      }
    });
  }, { root: scrollRoot, rootMargin: '150px' });
  observer.observe(sentinel);
})();
</script>

  {% if current_role == 'admin' %}
  <div class="card">
    <h4>Admin Tools</h4>
    <a class="btn" href="{{ url_for('admin_backups') }}">Backups</a>
    <a class="btn" href="{{ url_for('admin_users') }}" style="margin-left:8px">Users</a>
    <a class="btn" href="{{ url_for('admin_export_ui') }}" style="margin-left:8px">Export CSV</a>
  </div>
  {% endif %}
</div>
</body></html>
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
  <label>EMI Amount (integer monthly)</label><input name="emi_amount" type="number" step="1" min="0">
  <label>Tenure (months)</label><input name="tenure" type="number" step="1" min="0">
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
    <p><strong>Record #:</strong> {{ b.record_no or '-' }}</p>
    <p><strong>Buyer:</strong> {{ b.buyer_name }} • {{ b.buyer_phone }}</p>
    <p><strong>Address:</strong> {{ b.buyer_address or '-' }}</p>
    <p><strong>Sale Value:</strong> ₹{{ b.sale_value }} • <strong>Finance:</strong> ₹{{ b.finance_amount }}</p>
    <p><strong>EMI:</strong> ₹{{ b.emi_amount }} • <strong>Tenure:</strong> {{ b.tenure }} months • <strong>Sold on:</strong> {{ b.sale_date }}</p>

    <hr><h4>EMI Schedule</h4>
    <table class="table"><thead><tr><th>#</th><th>Due Date</th><th>Amount</th><th>Status</th><th>Action</th></tr></thead><tbody>
      {% for e in emis %}
      <tr>
        <td>{{ e.emi_no }}</td>
        <td>{{ e.due_date }}</td>
        <td>₹{{ e.amount }}</td>
        <td>
          {% if e.derived_status == 'Paid' %}
            <span class="badge stock">Paid</span>
          {% elif e.derived_status == 'Overdue' %}
            <span class="badge emi-overdue">Overdue</span>
          {% elif e.derived_status == 'Upcoming' %}
            <span class="badge emi-upcoming">Upcoming</span>
          {% else %}
            <span class="badge sold">{{ e.derived_status }}</span>
          {% endif %}
        </td>
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
  <label>Tenure (months)</label><input name="tenure" type="number" step="1" min="0" value="{{ buyer.tenure if buyer else '' }}">
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
