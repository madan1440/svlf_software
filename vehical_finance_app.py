# app.py
import os
import sqlite3
from datetime import datetime, date
from flask import Flask, request, redirect, url_for, render_template_string
from dateutil.relativedelta import relativedelta

app = Flask(__name__)
DB = os.environ.get("DB_PATH", "database.db")

# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.before_first_request
def init_db():
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

    conn.commit()
    conn.close()

# ---------------- utilities ----------------
def add_months(orig_date: date, months: int) -> date:
    return orig_date + relativedelta(months=months)

# ---------------- Routes ----------------
@app.route("/", methods=["GET"])
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

@app.route("/add", methods=["GET","POST"])
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
        return redirect(url_for("dashboard"))
    return render_template_string(ADD_HTML)

@app.route("/edit/<int:vid>", methods=["GET","POST"])
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
        return redirect(url_for("dashboard"))
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    s = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
    conn.close()
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(EDIT_HTML, v=v, s=s)

@app.route("/sell/<int:vid>", methods=["GET","POST"])
def sell_vehicle(vid):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        conn.close()
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        f = request.form
        buyer_name = f.get("buyer_name")
        buyer_phone = f.get("buyer_phone")
        buyer_address = f.get("buyer_address")
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
        """, (vid, f.get("record_no") or "", buyer_name, buyer_phone, buyer_address, sale_value, finance_amount, emi_amount, tenure, sale_date))
        buyer_id = cur.lastrowid

        sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
        # generate exactly 'tenure' EMIs, first due one month after sale_date
        for i in range(1, tenure + 1):
            due = add_months(sd, i)  # i months after sale_date
            cur.execute("""
                INSERT INTO emis (buyer_id, emi_no, due_date, amount, status)
                VALUES (?, ?, ?, ?, 'Unpaid')
            """, (buyer_id, i, due.isoformat(), emi_amount))

        conn.execute("UPDATE vehicles SET status='Sold' WHERE id=?", (vid,))
        conn.commit()
        conn.close()
        return redirect(url_for("view_vehicle", vid=vid))
    conn.close()
    return render_template_string(SELL_HTML, v=v, today=datetime.now().strftime("%Y-%m-%d"))

@app.route("/view/<int:vid>", methods=["GET"])
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

@app.route("/buyer/<int:vid>", methods=["GET","POST"])
def edit_buyer(vid):
    conn = get_db()
    buyer = conn.execute("SELECT * FROM buyers WHERE vehicle_id=?", (vid,)).fetchone()

    if request.method == "POST":
        f = request.form

        # parse and sanitize numeric inputs (integers)
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

        # If there's no existing buyer row (unexpected), create one
        if not buyer:
            # create buyer (use sale_date = today)
            sale_date = datetime.now().strftime("%Y-%m-%d")
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO buyers (vehicle_id, buyer_name, buyer_phone, buyer_address, sale_value, finance_amount, tenure, emi_amount, sale_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (vid, f.get("buyer_name") or "", f.get("buyer_phone") or "", f.get("buyer_address") or "",
                  new_sale_value, new_finance_amount, new_tenure, new_emi_amount, sale_date))
            buyer_id = cur.lastrowid

            # generate EMIs for tenure
            sd = datetime.strptime(sale_date, "%Y-%m-%d").date()
            for i in range(1, new_tenure + 1):
                due = add_months(sd, i)
                cur.execute("""
                    INSERT INTO emis (buyer_id, emi_no, due_date, amount, status)
                    VALUES (?, ?, ?, ?, 'Unpaid')
                """, (buyer_id, i, due.isoformat(), new_emi_amount))

            conn.commit()
            conn.close()
            return redirect(url_for("view_vehicle", vid=vid))

        # If buyer exists: perform safe update + EMI adjustments
        buyer_id = buyer["id"]
        old_tenure = int(buyer["tenure"] or 0)
        old_emi_amount = int(buyer["emi_amount"] or 0)
        sale_date_str = buyer["sale_date"] or datetime.now().strftime("%Y-%m-%d")
        sale_date = datetime.strptime(sale_date_str, "%Y-%m-%d").date()

        cur = conn.cursor()
        # update buyer main fields
        cur.execute("""
            UPDATE buyers SET buyer_name=?, buyer_phone=?, buyer_address=?,
                              sale_value=?, finance_amount=?, emi_amount=?, tenure=?
            WHERE vehicle_id=?
        """, (f.get("buyer_name") or "", f.get("buyer_phone") or "", f.get("buyer_address") or "",
              new_sale_value, new_finance_amount, new_emi_amount, new_tenure, vid))

        # 1) If EMI amount changed: update unpaid EMIs to new amount
        if new_emi_amount != old_emi_amount:
            cur.execute("""
                UPDATE emis SET amount=? WHERE buyer_id=? AND status!='Paid'
            """, (new_emi_amount, buyer_id))

        # 2) If tenure increased -> add EMIs (emi_no from old_tenure+1 .. new_tenure)
        if new_tenure > old_tenure:
            for i in range(old_tenure + 1, new_tenure + 1):
                due = add_months(sale_date, i)
                cur.execute("""
                    INSERT INTO emis (buyer_id, emi_no, due_date, amount, status)
                    VALUES (?, ?, ?, ?, 'Unpaid')
                """, (buyer_id, i, due.isoformat(), new_emi_amount))

        # 3) If tenure decreased -> remove unpaid EMIs with emi_no > new_tenure
        elif new_tenure < old_tenure:
            cur.execute("""
                DELETE FROM emis WHERE buyer_id=? AND emi_no>? AND status!='Paid'
            """, (buyer_id, new_tenure))

        conn.commit()
        conn.close()
        return redirect(url_for("view_vehicle", vid=vid))

    conn.close()
    return render_template_string(EDIT_BUYER_HTML, buyer=buyer, vid=vid)

@app.route("/emi/toggle/<int:emi_id>", methods=["POST"])
def toggle_emi(emi_id):
    action = request.form.get("action")
    conn = get_db()
    if action == "mark_paid":
        conn.execute("UPDATE emis SET status='Paid', paid_date=? WHERE id=?", (date.today().isoformat(), emi_id))
    else:
        conn.execute("UPDATE emis SET status='Unpaid', paid_date=NULL WHERE id=?", (emi_id,))
    conn.commit()
    ref = request.form.get("ref") or url_for("dashboard")
    conn.close()
    return redirect(ref)

@app.route("/delete/<int:vid>", methods=["GET"])
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
    return redirect(url_for("dashboard"))

# ---------------- Templates (plain strings) ----------------
BASE_CSS = """
<style>
:root{--bg:#f4f6fb;--card:#fff;--muted:#6b7280;--primary:#2563eb;--danger:#ef4444}
*{box-sizing:border-box;font-family:Inter,Arial,sans-serif}
body{margin:0;background:var(--bg);color:#0f172a}
header{background:linear-gradient(135deg,var(--primary),#1e40af);color:#fff;padding:14px 18px}
.container{max-width:1100px;margin:18px auto;padding:0 18px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.controls .left{flex:1;display:flex;gap:8px;align-items:center}
input,select,textarea{padding:10px;border-radius:8px;border:1px solid #e6eefc;background:white}
.btn{background:var(--primary);color:white;padding:10px 12px;border-radius:8px;border:none;cursor:pointer;font-weight:600}
.card{background:var(--card);border-radius:12px;padding:12px;box-shadow:0 8px 30px rgba(2,6,23,0.06);margin-bottom:12px}
.table{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden}
th,td{padding:10px;border-bottom:1px solid #eef2ff;text-align:left}
th{background:#f8fafc;color:var(--muted)}
.badge{padding:6px 10px;border-radius:8px}
.stock{background:#dcfce7;color:#166534}
.sold{background:#fee2e2;color:#991b1b}
.form-stack{display:flex;flex-direction:column;gap:10px}
.small-btn{padding:6px 8px;border-radius:6px}
.link{color:var(--primary);text-decoration:none}
@media(max-width:780px){
  .controls{flex-direction:column}
  .controls .left{flex-direction:column;align-items:stretch}
  th,td{display:block}
  tr{margin-bottom:12px}
}
</style>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Finance</title>
""" + BASE_CSS + """
</head><body>
<header><div style="max-width:1100px;margin:0 auto;padding:0 18px"><strong>Vehicle Finance Manager</strong></div></header>
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
    <div>
      <a class="btn" href="/add">+ Add Vehicle</a>
    </div>
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
            <a href="{{ url_for('view_vehicle', vid=v.id) }}">View</a> |
            <a href="{{ url_for('edit_vehicle', vid=v.id) }}">Edit</a>
            {% if v.status=='Stock' %}| <a href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell</a>{% endif %}
            | <a href="#" onclick="if(confirm('Delete vehicle and all related data?')) location.href='{{ url_for('delete_vehicle', vid=v.id) }}'">Delete</a>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

</div></body></html>
"""

ADD_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Add Vehicle</title>
""" + BASE_CSS + """
</head><body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Add Vehicle</header>
<div class="container">
  <div class="card">
    <a href="/">← Back to Dashboard</a>
    <form method="post" class="form-stack" style="margin-top:12px">
      <label>Type</label><select name="type" required><option>Car</option><option>Bike</option></select>
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
    </form>
  </div>
</div>
</body></html>
"""

EDIT_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Vehicle</title>
""" + BASE_CSS + """
</head><body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Edit Vehicle</header>
<div class="container">
  <div class="card">
    <a href="{{ url_for('dashboard') }}">← Back to Dashboard</a>
    <form method="post" class="form-stack" style="margin-top:12px">
      <label>Type</label>
      <select name="type" required>
        <option {% if v.type=='Car' %}selected{% endif %}>Car</option>
        <option {% if v.type=='Bike' %}selected{% endif %}>Bike</option>
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

      <div><button class="btn" type="submit">Update (go to Dashboard)</button>
      <a href="{{ url_for('dashboard') }}" style="margin-left:12px">Cancel</a></div>
    </form>
  </div>
</div>
</body></html>
"""

SELL_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sell Vehicle</title>
""" + BASE_CSS + """
</head><body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Sell Vehicle</header>
<div class="container">
  <div class="card">
    <a href="/">← Back to Dashboard</a>
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
    </form>
  </div>
</div>
</body></html>
"""

VIEW_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Details</title>
""" + BASE_CSS + """
</head><body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Vehicle Details</header>
<div class="container">
  <div class="card">
    <a href="/">← Back to Dashboard</a>
    <h2 style="margin-top:8px">{{ v.name }} <small style="color:var(--muted)">({{ v.type }})</small></h2>
    <p>{{ v.brand }} • {{ v.model }} • {{ v.color }}</p>
    <p><strong>Number:</strong> {{ v.number }}</p>
  </div>

  <div class="card">
    <h3>Seller Information</h3>
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

    <hr>
    <h4>EMI Schedule</h4>
      <table class="table">
        <thead><tr><th>#</th><th>Due Date</th><th>Amount</th><th>Status</th><th>Action</th></tr></thead>
        <tbody>
        {% for e in emis %}
          <tr>
            <td>{{ e.emi_no }}</td>
            <td>{{ e.due_date }}</td>
            <td>₹{{ e.amount }}</td>
            <td>{{ e.status }}</td>
            <td>
              <form method="post" action="{{ url_for('toggle_emi', emi_id=e.id) }}" style="display:inline">
                <input type="hidden" name="ref" value="{{ url_for('view_vehicle', vid=v.id) }}">
                {% if e.status != 'Paid' %}
                  <button class="small-btn btn" name="action" value="mark_paid" onclick="return confirm('Mark EMI #{{ e.emi_no }} as PAID?')">Mark Paid</button>
                {% else %}
                  <button class="small-btn" style="background:#ef4444;color:#fff;border:none;border-radius:6px;padding:8px" name="action" value="mark_unpaid" onclick="return confirm('Mark EMI #{{ e.emi_no }} as UNPAID?')">Mark Unpaid</button>
                {% endif %}
              </form>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>

    <div style="margin-top:10px"><a class="btn" href="{{ url_for('edit_buyer', vid=v.id) }}">Edit Buyer</a></div>
  </div>
  {% else %}
  <div class="card">
    <h3>No buyer recorded</h3>
    <a class="btn" href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell this vehicle</a>
  </div>
  {% endif %}

</div>
</body></html>
"""

EDIT_BUYER_HTML = """
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Buyer</title>
""" + BASE_CSS + """
</head><body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Edit Buyer</header>
<div class="container">
  <div class="card">
    <a href="{{ url_for('view_vehicle', vid=vid) }}">← Back to Details</a>
    <form method="post" class="form-stack" style="margin-top:12px">
      <label>Buyer Name</label><input name="buyer_name" value="{{ buyer.buyer_name if buyer else '' }}" required>
      <label>Buyer Phone</label><input name="buyer_phone" value="{{ buyer.buyer_phone if buyer else '' }}">
      <label>Buyer Address</label><textarea name="buyer_address">{{ buyer.buyer_address if buyer else '' }}</textarea>
      <label>Sale Value (integer)</label><input name="sale_value" type="number" step="1" value="{{ buyer.sale_value if buyer else '' }}">
      <label>Finance Amount (integer)</label><input name="finance_amount" type="number" step="1" value="{{ buyer.finance_amount if buyer else '' }}">
      <label>EMI Amount (integer)</label><input name="emi_amount" type="number" step="1" value="{{ buyer.emi_amount if buyer else '' }}">
      <label>Tenure (months)</label><input name="tenure" type="number" step="1" min="1" value="{{ buyer.tenure if buyer else '' }}">
      <div><button class="btn" type="submit">Save Buyer</button></div>
    </form>
  </div>
</div>
</body></html>
"""

# ---------------- Run ----------------
if __name__ == "__main__":
    open(DB, "a").close()
    print("Starting app with DB:", DB)
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
