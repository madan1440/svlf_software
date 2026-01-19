from flask import Flask, request, redirect, url_for, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB = "vehicle_finance.db"

# -------------------------
# Database helpers
# -------------------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_type TEXT,
        name TEXT,
        brand TEXT,
        model TEXT,
        color TEXT,
        vehicle_number TEXT,
        status TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sellers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        seller_name TEXT,
        seller_phone TEXT,
        seller_city TEXT,
        buy_value REAL,
        buy_date TEXT,
        comments TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        record_no TEXT,
        buyer_name TEXT,
        buyer_phone TEXT,
        buyer_address TEXT,
        sale_value REAL,
        finance_amount REAL,
        emi REAL,
        sale_date TEXT
    )
    """)
    conn.commit()
    conn.close()

# initialize DB once on startup
init_db()

# -------------------------
# Routes
# -------------------------

@app.route("/", methods=["GET"])
def dashboard():
    q = request.args.get("q", "").strip()
    vfilter = request.args.get("type", "ALL")
    status = request.args.get("status", "ALL")   # new status filter
    conn = get_db()

    sql = "SELECT * FROM vehicles WHERE 1=1"
    params = []
    if vfilter and vfilter != "ALL":
        sql += " AND vehicle_type = ?"
        params.append(vfilter)
    if status and status != "ALL":
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (name LIKE ? OR brand LIKE ? OR model LIKE ? OR vehicle_number LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]

    vehicles = conn.execute(sql, params).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    stock = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='Stock'").fetchone()[0]
    sold = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='Sold'").fetchone()[0]
    conn.close()

    return render_template_string(DASHBOARD_HTML,
                                  vehicles=vehicles,
                                  total=total,
                                  stock=stock,
                                  sold=sold,
                                  q=q,
                                  vfilter=vfilter,
                                  status=status)

@app.route("/add", methods=["GET","POST"])
def add_vehicle():
    if request.method == "POST":
        f = request.form
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO vehicles (vehicle_type, name, brand, model, color, vehicle_number, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Stock')
        """, (f.get("vehicle_type"), f.get("name"), f.get("brand"), f.get("model"),
              f.get("color"), f.get("vehicle_number")))
        vid = cur.lastrowid
        cur.execute("""
            INSERT INTO sellers (vehicle_id, seller_name, seller_phone, seller_city, buy_value, buy_date, comments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (vid, f.get("seller_name"), f.get("seller_phone"), f.get("seller_city"),
              float(f.get("buy_value") or 0.0), f.get("buy_date") or "", f.get("comments") or ""))
        conn.commit()
        conn.close()
        return redirect(url_for("dashboard"))
    return render_template_string(ADD_HTML)

@app.route("/view/<int:vid>")
def view_vehicle(vid):
    conn = get_db()
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    s = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
    b = conn.execute("SELECT * FROM buyers WHERE vehicle_id=?", (vid,)).fetchone()
    conn.close()
    if not v:
        return redirect(url_for("dashboard"))
    return render_template_string(VIEW_HTML, v=v, s=s, b=b)

@app.route("/edit/<int:vid>", methods=["GET","POST"])
def edit_vehicle(vid):
    conn = get_db()
    if request.method == "POST":
        f = request.form
        conn.execute("""
            UPDATE vehicles SET vehicle_type=?, name=?, brand=?, model=?, color=?, vehicle_number=?
            WHERE id=?
        """, (f.get("vehicle_type"), f.get("name"), f.get("brand"), f.get("model"),
              f.get("color"), f.get("vehicle_number"), vid))

        seller = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
        if seller:
            conn.execute("""
                UPDATE sellers SET seller_name=?, seller_phone=?, seller_city=?, buy_value=?, buy_date=?, comments=?
                WHERE vehicle_id=?
            """, (f.get("seller_name"), f.get("seller_phone"), f.get("seller_city"),
                  float(f.get("buy_value") or 0.0), f.get("buy_date") or "", f.get("comments") or "", vid))
        conn.commit()
        conn.close()
        # Redirect directly to dashboard as requested
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
        conn.execute("""
            INSERT INTO buyers (vehicle_id, record_no, buyer_name, buyer_phone, buyer_address, sale_value, finance_amount, emi, sale_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (vid, f.get("record_no") or "", f.get("buyer_name") or "", f.get("buyer_phone") or "",
              f.get("buyer_address") or "", float(f.get("sale_value") or 0.0),
              float(f.get("finance_amount") or 0.0), float(f.get("emi") or 0.0),
              f.get("sale_date") or datetime.now().strftime("%Y-%m-%d")))
        conn.execute("UPDATE vehicles SET status='Sold' WHERE id=?", (vid,))
        conn.commit()
        conn.close()
        return redirect(url_for("view_vehicle", vid=vid))

    s = conn.execute("SELECT * FROM sellers WHERE vehicle_id=?", (vid,)).fetchone()
    conn.close()
    return render_template_string(SELL_HTML, v=v, s=s)

@app.route("/delete/<int:vid>")
def delete_vehicle(vid):
    conn = get_db()
    conn.execute("DELETE FROM buyers WHERE vehicle_id=?", (vid,))
    conn.execute("DELETE FROM sellers WHERE vehicle_id=?", (vid,))
    conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))

# -------------------------
# HTML Templates (render_template_string)
# -------------------------

BASE_CSS = """
<style>
:root{
  --bg:#f4f6fb; --card:#ffffff; --muted:#6b7280; --primary:#2563eb; --danger:#ef4444;
}
*{box-sizing:border-box;font-family:Inter, Arial, sans-serif}
body{margin:0;background:var(--bg);color:#0f172a}
header{background:linear-gradient(135deg,var(--primary),#1e40af);padding:14px 18px;color:white}
.container{max-width:1100px;margin:18px auto;padding:0 18px}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.control-left{flex:1;display:flex;gap:8px;align-items:center}
input[type="text"], select, input[type="date"], input[type="number"]{padding:10px 12px;border-radius:10px;border:1px solid #e6eefc;background:white}
.btn{background:var(--primary);color:white;padding:10px 12px;border-radius:10px;border:none;cursor:pointer;font-weight:600}
.btn:active{transform:translateY(1px)}
.card{background:var(--card);border-radius:12px;padding:12px;box-shadow:0 8px 30px rgba(2,6,23,0.06)}
.stats{display:flex;gap:10px;margin-bottom:12px}
.stat{flex:1;background:var(--card);padding:12px;border-radius:10px;text-align:center}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 8px 30px rgba(2,6,23,0.06)}
th,td{padding:12px;border-bottom:1px solid #eef2ff;text-align:left;font-size:14px}
th{background:#f8fafc;font-weight:700;color:var(--muted)}
tr:hover td{background:#fbfdff}
.tag-stock{color:#16a34a;font-weight:700}
.tag-sold{color:var(--danger);font-weight:700}
.actions a, .actions button{margin-right:8px;text-decoration:none;border:none;background:none;cursor:pointer;color:var(--primary)}
a.link{color:var(--primary);text-decoration:none}

/* Status buttons */
.status-buttons{display:flex;gap:8px;margin-left:8px}
.status-button{padding:8px 12px;border-radius:8px;border:1px solid #e6eefc;background:white;cursor:pointer}
.status-button.active{background:var(--primary);color:white;border-color:var(--primary)}

@media(max-width:780px){
  .controls{flex-direction:column;align-items:stretch}
  .control-left{flex-direction:column;align-items:stretch}
  th,td{display:block}
  tr{margin-bottom:12px;border-bottom:none}
  td{border:none;padding:8px 6px}
  td::after{content:"";display:block;height:1px;background:#f1f5f9;margin-top:8px}
  table{border-radius:8px}
}
</style>
"""

DASHBOARD_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Finance</title>
""" + BASE_CSS + """
</head>
<body>
<header>
  <div style="max-width:1100px;margin:0 auto;padding:0 18px;"><strong>Vehicle Finance Manager</strong></div>
</header>

<div class="container">
  <div class="controls">
    <div class="control-left">
      <form id="searchForm" method="get" action="/" style="display:flex;gap:8px;flex:1;align-items:center">
        <input type="text" name="q" id="search" placeholder="Search by name / brand / model / vehicle number" value="{{ q }}">
        <input type="hidden" name="type" id="typeInput" value="{{ vfilter }}">
        <input type="hidden" name="status" id="statusInput" value="{{ status }}">
        <button type="submit" class="btn" style="padding:10px 12px">Search</button>
      </form>

      <select id="typeSelect" onchange="onTypeChange()" style="margin-left:8px;padding:10px;border-radius:8px">
        <option value="ALL" {% if vfilter=='ALL' %}selected{% endif %}>All Types</option>
        <option value="Car" {% if vfilter=='Car' %}selected{% endif %}>Cars</option>
        <option value="Bike" {% if vfilter=='Bike' %}selected{% endif %}>Bikes</option>
      </select>

      <div class="status-buttons" style="margin-left:8px">
        <button class="status-button {% if status=='ALL' %}active{% endif %}" onclick="setStatus('ALL')">All</button>
        <button class="status-button {% if status=='Stock' %}active{% endif %}" onclick="setStatus('Stock')">In Stock</button>
        <button class="status-button {% if status=='Sold' %}active{% endif %}" onclick="setStatus('Sold')">Sold</button>
      </div>
    </div>

    <div style="display:flex;gap:8px">
      <a class="btn" href="/add">+ Add Vehicle</a>
    </div>
  </div>

  <div class="stats">
    <div class="stat card"><div style="font-size:13px;color:#6b7280">Total</div><div style="font-size:20px;font-weight:700">{{ total }}</div></div>
    <div class="stat card"><div style="font-size:13px;color:#6b7280">In Stock</div><div style="font-size:20px;font-weight:700">{{ stock }}</div></div>
    <div class="stat card"><div style="font-size:13px;color:#6b7280">Sold</div><div style="font-size:20px;font-weight:700">{{ sold }}</div></div>
  </div>

  <div class="card">
    <table>
      <thead>
        <tr><th>#</th><th>Type</th><th>Name</th><th>Brand</th><th>Model</th><th>Vehicle No</th><th>Status</th><th>Actions</th></tr>
      </thead>
      <tbody>
      {% for v in vehicles %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ v.vehicle_type }}</td>
          <td>{{ v.name }}</td>
          <td>{{ v.brand }}</td>
          <td>{{ v.model }}</td>
          <td><a class="link" href="{{ url_for('view_vehicle', vid=v.id) }}">{{ v.vehicle_number }}</a></td>
          <td>
            {% if v.status == 'Stock' %}
              <span class="tag-stock">In Stock</span>
            {% else %}
              <span class="tag-sold">Sold</span>
            {% endif %}
          </td>
          <td class="actions">
            <a href="{{ url_for('view_vehicle', vid=v.id) }}">View</a>
            <a href="{{ url_for('edit_vehicle', vid=v.id) }}">Edit</a>
            {% if v.status == 'Stock' %}
              <a href="{{ url_for('sell_vehicle', vid=v.id) }}">Sell</a>
            {% endif %}
            <a href="#" onclick="confirmDelete({{ v.id }});" style="color:var(--danger)">Delete</a>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

</div>

<script>
function onTypeChange(){
  const sel = document.getElementById('typeSelect').value;
  document.getElementById('typeInput').value = sel;
  document.getElementById('searchForm').submit();
}

function setStatus(value){
  document.getElementById('statusInput').value = value;
  document.getElementById('searchForm').submit();
}

function confirmDelete(id){
  if(confirm('Delete this vehicle and all related records? This cannot be undone.')){
    location.href = '/delete/' + id;
  }
}
</script>
</body>
</html>
"""

ADD_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Add Vehicle</title>""" + BASE_CSS + """</head>
<body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Add Vehicle</header>
<div class="container">
  <div class="card">
    <a href="/">← Back to Dashboard</a>
    <form method="post" style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
      <label>Type</label>
      <select name="vehicle_type" required>
        <option>Car</option>
        <option>Bike</option>
      </select>

      <label>Vehicle Name</label><input name="name" required>

      <label>Brand</label><input name="brand">
      <label>Model</label><input name="model">
      <label>Color</label><input name="color">
      <label>Vehicle Number</label><input name="vehicle_number" required>

      <hr style="margin:12px 0">

      <h4>Seller Information</h4>
      <label>Seller Name</label><input name="seller_name" required>
      <label>Seller Phone</label><input name="seller_phone">
      <label>Seller City</label><input name="seller_city">
      <label>Buy Value</label><input name="buy_value" type="number" step="0.01">
      <label>Buy Date</label><input name="buy_date" type="date">
      <label>Comments</label><input name="comments">

      <div style="margin-top:12px">
        <button class="btn" type="submit">Save Vehicle</button>
      </div>
    </form>
  </div>
</div>
</body>
</html>
"""

VIEW_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vehicle Details</title>""" + BASE_CSS + """</head>
<body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Vehicle Details</header>
<div class="container">
  <div class="card">
    <a href="/">← Back to Dashboard</a>
    <h2 style="margin-top:8px">{{ v.name }} <small style="color:var(--muted)">({{ v.vehicle_type }})</small></h2>
    <p style="margin:6px 0">{{ v.brand }} • {{ v.model }} • {{ v.color }}</p>
    <p style="margin:6px 0"><strong>Number:</strong> {{ v.vehicle_number }}</p>
  </div>

  <div class="card" style="margin-top:12px">
    <h3>Seller Information</h3>
    {% if s %}
      <p><strong>Name:</strong> {{ s.seller_name }}</p>
      <p><strong>Phone:</strong> {{ s.seller_phone }}</p>
      <p><strong>City:</strong> {{ s.seller_city }}</p>
      <p><strong>Buy Value:</strong> ₹{{ s.buy_value }}</p>
      <p><strong>Buy Date:</strong> {{ s.buy_date }}</p>
      <p><strong>Comments:</strong> {{ s.comments }}</p>
    {% else %}
      <p>No seller information available.</p>
    {% endif %}
  </div>

  {% if b %}
  <div class="card" style="margin-top:12px">
    <h3>Buyer & Finance Information</h3>
    <p><strong>Record No:</strong> {{ b.record_no }}</p>
    <p><strong>Buyer:</strong> {{ b.buyer_name }} • {{ b.buyer_phone }}</p>
    <p><strong>Address:</strong> {{ b.buyer_address }}</p>
    <p><strong>Sale Value:</strong> ₹{{ b.sale_value }}</p>
    <p><strong>Finance Amount:</strong> ₹{{ b.finance_amount }}</p>
    <p><strong>EMI:</strong> ₹{{ b.emi }}</p>
    <p><strong>Sale Date:</strong> {{ b.sale_date }}</p>
  </div>
  {% else %}
  <div class="card" style="margin-top:12px">
    <h3>Sell Vehicle</h3>
    <form method="post" action="{{ url_for('sell_vehicle', vid=v.id) }}" style="display:flex;flex-direction:column;gap:10px">
      <label>Record Number</label><input name="record_no">
      <label>Buyer Name</label><input name="buyer_name" required>
      <label>Buyer Phone</label><input name="buyer_phone">
      <label>Buyer Address</label><input name="buyer_address">
      <label>Sale Value</label><input name="sale_value" type="number" step="0.01">
      <label>Finance Amount</label><input name="finance_amount" type="number" step="0.01">
      <label>EMI (manual)</label><input name="emi" type="number" step="0.01">
      <label>Sale Date</label><input name="sale_date" type="date" value="{{ now }}">
      <div style="margin-top:12px">
        <button class="btn" type="submit">Confirm Sale</button>
        <a href="{{ url_for('edit_vehicle', vid=v.id) }}" style="margin-left:8px">Edit Vehicle</a>
      </div>
    </form>
  </div>
  {% endif %}

</div>
</body>
</html>
"""

SELL_HTML = VIEW_HTML  # selling handled via the view form

EDIT_HTML = """
<!doctype html>
<html>
<head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Edit Vehicle</title>""" + BASE_CSS + """</head>
<body>
<header style="background:linear-gradient(135deg,var(--primary),#1e40af);color:white;padding:12px 18px">Edit Vehicle</header>
<div class="container">
  <div class="card">
    <a href="{{ url_for('dashboard') }}">← Back to Dashboard</a>
    <form method="post" style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
      <label>Type</label>
      <select name="vehicle_type" required>
        <option {% if v.vehicle_type=='Car' %}selected{% endif %}>Car</option>
        <option {% if v.vehicle_type=='Bike' %}selected{% endif %}>Bike</option>
      </select>

      <label>Vehicle Name</label><input name="name" value="{{ v.name }}" required>

      <label>Brand</label><input name="brand" value="{{ v.brand }}">
      <label>Model</label><input name="model" value="{{ v.model }}">
      <label>Color</label><input name="color" value="{{ v.color }}">
      <label>Vehicle Number</label><input name="vehicle_number" value="{{ v.vehicle_number }}" required>

      <hr style="margin:12px 0">
      <h4>Seller (update)</h4>
      <label>Seller Name</label><input name="seller_name" value="{{ s.seller_name if s else '' }}">
      <label>Seller Phone</label><input name="seller_phone" value="{{ s.seller_phone if s else '' }}">
      <label>Seller City</label><input name="seller_city" value="{{ s.seller_city if s else '' }}">
      <label>Buy Value</label><input name="buy_value" type="number" step="0.01" value="{{ s.buy_value if s else '' }}">
      <label>Buy Date</label><input name="buy_date" type="date" value="{{ s.buy_date if s else '' }}">
      <label>Comments</label><input name="comments" value="{{ s.comments if s else '' }}">

      <div style="margin-top:12px">
        <button class="btn" type="submit">Update (go to Dashboard)</button>
        <a href="{{ url_for('dashboard') }}" style="margin-left:12px">Cancel</a>
      </div>
    </form>
  </div>
</div>
</body>
</html>
"""

# -------------------------
# Template context processors
# -------------------------
@app.context_processor
def inject_now():
    return {"now": datetime.now().strftime("%Y-%m-%d")}

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    #app.run(debug=True)
    app.run()
