# app.py  -- Read-only CSV backed viewer with login (static users in code)
import os
import csv
from pathlib import Path
from datetime import datetime, date
from flask import Flask, request, render_template_string, send_from_directory, abort, url_for, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash

# -------- CONFIG --------
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
FULL_CSV = DATA_DIR / "full.csv"
EMI_CSV = DATA_DIR / "emi.csv"
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_secret_for_prod")
DEBUG = True

app = Flask(__name__)
app.config['DEBUG'] = DEBUG
app.secret_key = SECRET_KEY

# -------- Static users (phone -> password) --------
# Using the exact accounts you provided. Passwords will be hashed at startup.
INITIAL_USERS = [
    {"username": "9492126272", "password": "Madan@1440", "role": "admin", "name": "Admin One"},
    {"username": "9490479284", "password": "Laxmi@6799", "role": "admin", "name": "Admin Two"},
    {"username": "9492146644", "password": "Rupa@0642",  "role": "user",  "name": "User One"},
    {"username": "9492948661", "password": "Venky@8661",  "role": "user",  "name": "User Two"},
]
USERS = {}
for u in INITIAL_USERS:
    USERS[u["username"]] = {
        "name": u.get("name", u["username"]),
        "role": u.get("role", "user"),
        "password_hash": generate_password_hash(u["password"])
    }

# -------- Helpers to read CSVs --------
def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        return rows

def write_csv_rows(path: Path, rows, fieldnames):
    ensure_data_dir()
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

# If files are missing, create dummy sample data (10 entries)
def create_dummy_data():
    ensure_data_dir()
    if not FULL_CSV.exists() or not EMI_CSV.exists():
        full_rows = []
        emi_rows = []
        for i in range(1, 11):
            vehicle_id = i
            vtype = "Bike" if i % 2 else "Car"
            number = f"AP{40 + i}XY{1000 + i}"
            buyer_id = i if i % 3 == 0 else ""  # some vehicles unsold
            status = "Sold" if buyer_id else "Stock"

            full_rows.append({
                "vehicle_id": str(vehicle_id),
                "type": vtype,
                "name": f"Model-{i}",
                "brand": "BrandA" if i % 2 else "BrandB",
                "model": f"{2020+i%5}",
                "color": "Black" if i%2 else "White",
                "number": number,
                "status": status,
                "seller_name": f"Seller {i}",
                "seller_phone": f"9000000{i:03d}",
                "seller_city": "CityX",
                "buy_value": str(50000 + i*1000),
                "buy_date": (datetime.now().date()).isoformat(),
                "comments": ""
            })

            if status == "Sold":
                full_rows[-1].update({
                    "buyer_id": str(buyer_id),
                    "record_no": f"REC{i:04d}",
                    "buyer_name": f"Buyer {i}",
                    "buyer_phone": f"9900000{i:03d}",
                    "buyer_address": "Address, City",
                    "sale_value": str(60000 + i*1200),
                    "finance_amount": str(30000 + i*200),
                    "emi_amount": str(3000 + i*10),
                    "tenure": str(6 if i%2 else 12),
                    "sale_date": (datetime.now().date()).isoformat()
                })
                tenure = int(full_rows[-1]["tenure"])
                sale_date = datetime.now().date()
                from dateutil.relativedelta import relativedelta
                for j in range(1, tenure+1):
                    due_dt = sale_date + relativedelta(months=j)
                    emi_rows.append({
                        "buyer_id": str(buyer_id),
                        "emi_no": str(j),
                        "due_date": due_dt.isoformat(),
                        "amount": full_rows[-1]["emi_amount"],
                        "status": "Unpaid",
                        "paid_date": ""
                    })
            else:
                full_rows[-1].update({
                    "buyer_id": "",
                    "record_no": "",
                    "buyer_name": "",
                    "buyer_phone": "",
                    "buyer_address": "",
                    "sale_value": "",
                    "finance_amount": "",
                    "emi_amount": "",
                    "tenure": "",
                    "sale_date": ""
                })

        full_fieldnames = ["vehicle_id","type","name","brand","model","color","number","status",
                           "seller_name","seller_phone","seller_city","buy_value","buy_date","comments",
                           "buyer_id","record_no","buyer_name","buyer_phone","buyer_address","sale_value","finance_amount","emi_amount","tenure","sale_date"]
        emi_fieldnames = ["buyer_id","emi_no","due_date","amount","status","paid_date"]
        write_csv_rows(FULL_CSV, full_rows, full_fieldnames)
        write_csv_rows(EMI_CSV, emi_rows, emi_fieldnames)

# Load CSVs into memory (read every request for fresh data)
def load_data():
    full = read_csv_rows(FULL_CSV)
    emis = read_csv_rows(EMI_CSV)
    # normalize: ensure keys exist in full rows
    for r in full:
        for k in ["vehicle_id","type","name","brand","model","color","number","status",
                  "seller_name","seller_phone","seller_city","buy_value","buy_date","comments",
                  "buyer_id","record_no","buyer_name","buyer_phone","buyer_address","sale_value","finance_amount","emi_amount","tenure","sale_date"]:
            r.setdefault(k, "")
    return full, emis

# Create dummy data if missing so you can test immediately
create_dummy_data()

# -------- LOGIN / AUTH HELPERS --------
def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.context_processor
def inject_user():
    return {
        "current_username": session.get("username"),
        "current_name": (USERS.get(session.get("username")) or {}).get("name")
    }

# --------- TEMPLATES (LOGIN + UI) ---------
LOGIN_HTML = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title><style>body{font-family:Inter;background:#f1f5f9;padding:20px}form{max-width:420px;margin:40px auto;background:white;padding:20px;border-radius:8px}label{display:block;margin-top:8px}.err{color:red;margin-bottom:8px}</style></head><body>
<form method="post">
  <h2>Login</h2>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <label>Username (phone)</label><input name="username" required>
  <label>Password</label><input name="password" type="password" required>
  <div style="margin-top:12px"><button type="submit">Login</button> <a href="/" style="margin-left:12px">Back (will require login)</a></div>
  <p style="font-size:12px;color:#444;margin-top:12px">Use one of seeded users (phone numbers). Your account passwords were provided earlier.</p>
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

/* Responsive table -> mobile card conversion */
@media (max-width: 780px) {
  table thead { display: none; }
  table, tbody, tr, td, th { display: block; width: 100%; }
  tr { background: #fff; margin-bottom: 14px; border-radius: 12px; padding: 10px; box-shadow: 0 4px 14px rgba(0,0,0,0.08); }
  td { display: flex; justify-content: space-between; padding: 8px 6px; font-size: 14px; border: none; border-bottom: 1px solid #f1f5f9; }
  td::before { content: attr(data-label); font-weight: 600; color: #4b5563; margin-right: 8px; }
  td[data-label="Actions"] { padding-top: 10px; }
  .badge { font-size: 12px; padding: 4px 10px; border-radius: 20px; }
  a, button { white-space: normal; }
}
</style>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Finance - Readonly Viewer</title>
""" + BASE_CSS + """</head><body>
<header>
  <div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Vehicle Finance (Read-only)</strong>
    <span class="top-right">{% if current_username %}{{ current_username }} • <a href="{{ url_for('logout') }}" style="color:white">Logout</a>{% endif %}</span>
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
    <div><a class="btn" href="{{ url_for('download_full') }}">Download full.csv</a> <a class="btn" href="{{ url_for('download_emi') }}" style="margin-left:8px">Download emi.csv</a></div>
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
          <td data-label="#">{{ loop.index }}</td>
          <td data-label="Type">{{ v.type }}</td>
          <td data-label="Name">{{ v.name }}</td>
          <td data-label="Brand">{{ v.brand }}</td>
          <td data-label="Model">{{ v.model }}</td>
          <td data-label="Number"><a href="{{ url_for('view_vehicle', vid=v.vehicle_id) }}" class="link">{{ v.number }}</a></td>
          <td data-label="Status">{% if v.status=='Stock' %}<span class="badge stock">In Stock</span>{% else %}<span class="badge sold">Sold</span>{% endif %}</td>
          <td data-label="Actions">
            <a href="{{ url_for('view_vehicle', vid=v.vehicle_id) }}">View</a>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div></body></html>
"""

VIEW_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Details</title>""" + BASE_CSS + """</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Vehicle Finance (Read-only)</strong> <span class="top-right"><a href="/">Back</a></span></div></header>
<div class="container">
  <div class="card">
    <h2 style="margin-top:8px">{{ v.name }} <small style="color:var(--muted)">({{ v.type }})</small></h2>
    <p>{{ v.brand }} • {{ v.model }} • {{ v.color }}</p>
    <p><strong>Number:</strong> {{ v.number }}</p>
  </div>

  <div class="card"><h3>Seller Information</h3>
    {% if v.seller_name %}
      <p><strong>Name:</strong> {{ v.seller_name }}</p>
      <p><strong>Phone:</strong> {{ v.seller_phone }}</p>
      <p><strong>City:</strong> {{ v.seller_city }}</p>
      <p><strong>Buy Value:</strong> ₹{{ v.buy_value }}</p>
      <p><strong>Buy Date:</strong> {{ v.buy_date }}</p>
      <p><strong>Comments:</strong> {{ v.comments }}</p>
    {% else %}
      <p>No seller info</p>
    {% endif %}
  </div>

  {% if v.buyer_id %}
  <div class="card">
    <h3>Buyer & Finance</h3>
    <p><strong>Buyer:</strong> {{ v.buyer_name }} • {{ v.buyer_phone }}</p>
    <p><strong>Sale Value:</strong> ₹{{ v.sale_value }} • <strong>Finance:</strong> ₹{{ v.finance_amount }}</p>
    <p><strong>EMI:</strong> ₹{{ v.emi_amount }} • <strong>Tenure:</strong> {{ v.tenure }} months • <strong>Sold on:</strong> {{ v.sale_date }}</p>

    <hr><h4>EMI Schedule</h4>
    <table class="table"><thead><tr><th>#</th><th>Due Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>
      {% for e in emis %}
      <tr>
        <td data-label="#">{{ e.emi_no }}</td>
        <td data-label="Due Date">{{ e.due_date }}</td>
        <td data-label="Amount">₹{{ e.amount }}</td>
        <td data-label="Status">{{ e.status }}</td>
      </tr>
      {% endfor %}
    </tbody></table>
  </div>
  {% else %}
  <div class="card"><h3>No buyer recorded</h3></div>
  {% endif %}
</div></body></html>
"""

# -------- Routes (protected) --------
@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        u = USERS.get(username)
        if not u or not check_password_hash(u["password_hash"], password):
            error = "Invalid username or password"
        else:
            session["username"] = username
            return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    q = request.args.get("q", "").strip()
    vtype = request.args.get("type", "ALL")
    status = request.args.get("status", "ALL")

    full, emis = load_data()

    # convert vehicle_id to int for sorting/consistency
    for r in full:
        r["vehicle_id"] = int(r.get("vehicle_id") or 0)

    # filtering
    rows = full
    if vtype and vtype != "ALL":
        rows = [r for r in rows if (r.get("type") or "").lower() == vtype.lower()]
    if status and status != "ALL":
        rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join([str(r.get(c,"")) for c in ("name","brand","model","number")]).lower()]

    rows_sorted = sorted(rows, key=lambda x: x.get("vehicle_id", 0))
    total = len(full)
    stock = len([r for r in full if (r.get("status") or "").lower() == "stock"])
    sold = len([r for r in full if (r.get("status") or "").lower() == "sold"])
    return render_template_string(DASHBOARD_HTML, vehicles=rows_sorted, q=q, vtype=vtype, status=status, total=total, stock=stock, sold=sold)

@app.route("/view/<int:vid>")
@login_required
def view_vehicle(vid):
    full, emis = load_data()
    v = next((r for r in full if int(r.get("vehicle_id") or 0) == int(vid)), None)
    if not v:
        return redirect(url_for("dashboard"))
    buyer_id = v.get("buyer_id") or ""
    emis_list = [e for e in emis if e.get("buyer_id") == buyer_id] if buyer_id else []
    emis_sorted = sorted(emis_list, key=lambda x: int(x.get("emi_no") or 0))
    return render_template_string(VIEW_HTML, v=v, emis=emis_sorted)

# endpoints to download the CSVs (protected)
@app.route("/download/full.csv")
@login_required
def download_full():
    if not FULL_CSV.exists():
        abort(404)
    return send_from_directory(FULL_CSV.parent.resolve(), FULL_CSV.name, as_attachment=True)

@app.route("/download/emi.csv")
@login_required
def download_emi():
    if not EMI_CSV.exists():
        abort(404)
    return send_from_directory(EMI_CSV.parent.resolve(), EMI_CSV.name, as_attachment=True)

# -------- run --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

