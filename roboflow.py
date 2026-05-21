from flask import Flask, request, render_template_string, jsonify
import requests
import os
import smtplib
import base64
import json
import threading
import cloudinary
import cloudinary.uploader
from datetime import datetime
from email.message import EmailMessage

app = Flask(__name__)

# ─── SYSTEM SETTINGS ────────────────────────────────────────
EMAIL_SENDER  = "daviddracer@gmail.com"
EMAIL_PASS    = "ebtjeycmvlscobwr"
SMTP_SERVER   = 'smtp.gmail.com'
SMTP_PORT     = 465

# ─── SYSTEM CONFIGURATION ────────────────────────────────────
CONFIG = {
    "agency_name":        "Federal Road Safety Corps (FRSC)",
    "system_id":          "SPEED-VIGIL-001",
    "destination_email":  "david.m1901456@st.futminna.edu.ng",
    "model_id":           "toy-car-detection-uqfuq",
    "version":            "5",
    "api_key":            "HrN6gq24W5BypZTSwcgC"
}

# ─── CLOUDINARY CONFIG ───────────────────────────────────────
cloudinary.config(
    cloud_name = "dc5hm0npx",
    api_key    = "532695523155545",
    api_secret = os.environ.get("CLOUDINARY_SECRET", "gjFx6nJ8BZmc-_azpwTnoJsgm4E"),   # set as env var on Render
    secure     = True
)

# ─── HISTORY FILE ────────────────────────────────────────────
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(records):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(records, f, indent=2)
    except Exception as e:
        print(f"[HISTORY] Save failed: {e}")

def append_history(record):
    records = load_history()
    records.insert(0, record)      # newest first
    records = records[:200]        # keep last 200 records
    save_history(records)

# ─── CLOUDINARY UPLOAD ───────────────────────────────────────
def upload_to_cloudinary(img_bytes, public_id):
    """Upload image bytes to Cloudinary, return secure URL or None."""
    try:
        result = cloudinary.uploader.upload(
            img_bytes,
            public_id   = public_id,
            folder      = "frsc_speedvigil",
            resource_type = "image",
            overwrite   = True,
            format      = "jpg"
        )
        url = result.get("secure_url", "")
        print(f"[CLOUDINARY] Uploaded: {url}")
        return url
    except Exception as e:
        print(f"[CLOUDINARY] Upload failed: {e}")
        return None

# ─── EMAIL ───────────────────────────────────────────────────
def send_violation_report(image_url, label, conf, loc, spd):
    msg = EmailMessage()
    report_id = datetime.now().strftime("%Y%m%d-%H%M")
    msg['Subject'] = f'Traffic Record Update: {report_id} - {loc}'
    msg['From']    = f"FRSC Automated System <{EMAIL_SENDER}>"
    msg['To']      = CONFIG["destination_email"]
    body = (
        f"OFFICIAL TRAFFIC RECORD - {CONFIG['system_id']}\n"
        f"-------------------------------------------\n"
        f"Event Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Location        : {loc}\n"
        f"Classification  : {label.upper()}\n"
        f"Confidence      : {conf}%\n"
        f"Recorded Speed  : {spd} km/h\n"
        f"-------------------------------------------\n"
        f"Evidence Image  : {image_url}\n"
    )
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASS)
            smtp.send_message(msg)
        print(f"[EMAIL] Report sent to {CONFIG['destination_email']}")
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")


# ════════════════════════════════════════════════════════════
#  ROUTES
# ════════════════════════════════════════════════════════════

# ─── HOME ────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>FRSC Speed Vigil Console</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:#0b0e14;color:#e0e0e0;font-family:'Segoe UI',Tahoma,sans-serif;
         display:flex;flex-direction:column;align-items:center;padding:40px 16px;min-height:100vh}
    h1{color:#f39c12;letter-spacing:2px;font-size:22px;margin-bottom:4px}
    .subtitle{color:#7f8c8d;font-size:13px;margin-bottom:28px;display:flex;align-items:center;gap:6px}
    .dot{width:9px;height:9px;background:#27ae60;border-radius:50%;display:inline-block}
    .card{background:#151921;padding:28px;border-radius:12px;border:1px solid #232a35;
          width:100%;max-width:460px;box-shadow:0 10px 30px rgba(0,0,0,.5);margin-bottom:16px}
    .config-box{background:#1c222d;padding:14px;border-radius:8px;margin-bottom:18px}
    label{font-size:11px;color:#f39c12;display:block;margin-bottom:4px}
    input[type=text],input[type=file]{width:100%;padding:9px 10px;margin:6px 0 10px;
      border-radius:5px;border:1px solid #34495e;background:#0b0e14;color:#ecf0f1;font-size:13px}
    .row{display:flex;gap:8px;align-items:flex-end}
    .row input{flex:1;margin-bottom:0}
    .btn{background:#f39c12;color:#000;border:none;padding:11px 18px;border-radius:5px;
         font-weight:700;cursor:pointer;transition:.2s;font-size:13px;width:100%;margin-top:10px}
    .btn:hover{background:#e67e22;transform:translateY(-1px)}
    .btn-sm{width:auto;padding:7px 14px;font-size:12px;margin-top:0}
    .btn-outline{background:transparent;border:1px solid #f39c12;color:#f39c12;margin-top:0}
    .btn-outline:hover{background:#f39c12;color:#000}
    .nav{display:flex;gap:10px;margin-bottom:24px}
    .result{background:#1c222d;border-radius:8px;padding:14px;margin-top:14px;
            font-size:12px;color:#7fb3d3;white-space:pre-wrap;word-break:break-all;display:none}
    .result.show{display:block}
  </style>
</head>
<body>
  <h1>⚡ FRSC SPEED VIGIL</h1>
  <p class="subtitle"><span class="dot"></span> System Operational &mdash; {{ sys_id }}</p>

  <div class="nav">
    <a href="/history"><button class="btn btn-outline" style="width:auto;padding:9px 20px">📋 View History</button></a>
  </div>

  <div class="card">
    <div class="config-box">
      <label>Recipient Officer Email</label>
      <div class="row">
        <input type="text" id="emailInput" value="{{ email }}">
        <button class="btn btn-sm" onclick="updateConfig()">Update</button>
      </div>
    </div>

    <label>Evidence Upload (Manual Test)</label>
    <input type="file" id="imgFile" accept="image/*">
    <input type="text" id="location" placeholder="Site Location (e.g., Minna Bypass)" value="FUT Minna">
    <input type="text" id="speed" placeholder="Measured Speed (km/h)">
    <button class="btn" onclick="submitForm()">⚡ EXECUTE INFERENCE</button>
    <div class="result" id="result"></div>
  </div>

  <script>
    function updateConfig(){
      fetch('/update_config',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({destination_email:document.getElementById('emailInput').value})
      }).then(()=>alert('Officer contact updated.'));
    }

    async function submitForm(){
      const file = document.getElementById('imgFile').files[0];
      if(!file){alert('Please select an image file first.');return;}
      const fd = new FormData();
      fd.append('imageFile', file);
      fd.append('location', document.getElementById('location').value);
      fd.append('speed',    document.getElementById('speed').value);
      const btn = document.querySelector('.btn[onclick="submitForm()"]');
      btn.textContent='Processing...'; btn.disabled=true;
      try{
        const r = await fetch('/upload_and_infer',{method:'POST',body:fd});
        const data = await r.json();
        const el = document.getElementById('result');
        el.textContent = JSON.stringify(data, null, 2);
        el.classList.add('show');
      }catch(e){alert('Error: '+e);}
      btn.textContent='⚡ EXECUTE INFERENCE'; btn.disabled=false;
    }
  </script>
</body>
</html>
""", email=CONFIG["destination_email"], sys_id=CONFIG["system_id"])


# ─── HISTORY PAGE ────────────────────────────────────────────
@app.route('/history')
def history_page():
    records = load_history()
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>FRSC — Detection History</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:#0b0e14;color:#e0e0e0;font-family:'Segoe UI',Tahoma,sans-serif;
         padding:32px 16px;min-height:100vh}
    h1{color:#f39c12;letter-spacing:2px;font-size:20px;margin-bottom:4px}
    .topbar{display:flex;justify-content:space-between;align-items:center;
            max-width:1100px;margin:0 auto 24px}
    .subtitle{color:#7f8c8d;font-size:12px}
    .btn-back{background:transparent;border:1px solid #f39c12;color:#f39c12;
              padding:8px 18px;border-radius:5px;font-weight:700;cursor:pointer;
              font-size:13px;text-decoration:none}
    .btn-back:hover{background:#f39c12;color:#000}
    .stats{display:flex;gap:12px;max-width:1100px;margin:0 auto 24px;flex-wrap:wrap}
    .stat{background:#151921;border:1px solid #232a35;border-radius:10px;
          padding:14px 20px;flex:1;min-width:140px}
    .stat-label{font-size:11px;color:#7f8c8d;margin-bottom:4px}
    .stat-value{font-size:22px;font-weight:700;color:#f39c12}
    .stat-value.green{color:#27ae60}
    .stat-value.red{color:#e74c3c}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
          gap:16px;max-width:1100px;margin:0 auto}
    .card{background:#151921;border:1px solid #232a35;border-radius:12px;overflow:hidden;
          box-shadow:0 4px 16px rgba(0,0,0,.4);transition:.2s}
    .card:hover{transform:translateY(-2px);border-color:#f39c12}
    .card-img{width:100%;height:180px;object-fit:cover;background:#0b0e14;display:block}
    .card-img-placeholder{width:100%;height:180px;background:#1c222d;
      display:flex;align-items:center;justify-content:center;color:#4a5568;font-size:13px}
    .card-body{padding:14px}
    .card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
    .badge{padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700}
    .badge-viol{background:#e74c3c22;color:#e74c3c;border:1px solid #e74c3c}
    .badge-ok{background:#27ae6022;color:#27ae60;border:1px solid #27ae60}
    .badge-none{background:#f39c1222;color:#f39c12;border:1px solid #f39c12}
    .ts{font-size:11px;color:#7f8c8d}
    .row{display:flex;justify-content:space-between;margin-bottom:6px}
    .row-label{font-size:11px;color:#7f8c8d}
    .row-val{font-size:12px;color:#e0e0e0;font-weight:600}
    .speed-big{font-size:26px;font-weight:700;color:#f39c12;line-height:1}
    .speed-unit{font-size:11px;color:#7f8c8d}
    .preds{margin-top:8px;padding-top:8px;border-top:1px solid #232a35}
    .pred-item{font-size:11px;color:#7fb3d3;margin-bottom:3px}
    .conf-bar{height:4px;background:#232a35;border-radius:2px;margin-top:3px}
    .conf-fill{height:4px;background:#f39c12;border-radius:2px}
    .empty{text-align:center;color:#4a5568;padding:60px 20px;max-width:1100px;margin:0 auto;font-size:15px}
    .clear-btn{background:#e74c3c22;border:1px solid #e74c3c;color:#e74c3c;
               padding:7px 16px;border-radius:5px;font-size:12px;cursor:pointer;font-weight:600}
    .clear-btn:hover{background:#e74c3c;color:#fff}
    .filter-row{display:flex;gap:10px;max-width:1100px;margin:0 auto 20px;flex-wrap:wrap;align-items:center}
    .filter-btn{background:#1c222d;border:1px solid #34495e;color:#e0e0e0;
                padding:6px 14px;border-radius:20px;font-size:12px;cursor:pointer}
    .filter-btn.active,.filter-btn:hover{background:#f39c12;color:#000;border-color:#f39c12}
  </style>
</head>
<body>
  <div class="topbar">
    <div>
      <h1>📋 Detection History</h1>
      <p class="subtitle">Last {{ records|length }} events — newest first</p>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <button class="clear-btn" onclick="clearHistory()">🗑 Clear All</button>
      <a href="/" class="btn-back">← Dashboard</a>
    </div>
  </div>

  <!-- Stats bar -->
  {% set total = records|length %}
  {% set violations = records|selectattr('is_violation','equalto',true)|list|length %}
  {% set confirmed  = records|selectattr('car_detected','equalto',true)|list|length %}
  <div class="stats">
    <div class="stat">
      <div class="stat-label">Total Events</div>
      <div class="stat-value">{{ total }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Speed Violations</div>
      <div class="stat-value red">{{ violations }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Cars Confirmed</div>
      <div class="stat-value red">{{ confirmed }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">False Positives</div>
      <div class="stat-value" style="color:#f39c12">{{ violations - confirmed }}</div>
    </div>
  </div>

  <!-- Filter buttons -->
  <div class="filter-row">
    <span style="font-size:12px;color:#7f8c8d">Filter:</span>
    <button class="filter-btn active" onclick="filter('all',this)">All</button>
    <button class="filter-btn" onclick="filter('violation',this)">Violations</button>
    <button class="filter-btn" onclick="filter('confirmed',this)">Confirmed Cars</button>
    <button class="filter-btn" onclick="filter('clear',this)">Speed OK</button>
  </div>

  {% if records %}
  <div class="grid" id="grid">
    {% for r in records %}
    <div class="card"
         data-viol="{{ 'true' if r.is_violation else 'false' }}"
         data-confirmed="{{ 'true' if r.car_detected else 'false' }}">

      {% if r.image_url %}
        <img class="card-img" src="{{ r.image_url }}" alt="Evidence" loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
        <div class="card-img-placeholder" style="display:none">📷 Image unavailable</div>
      {% else %}
        <div class="card-img-placeholder">📷 No image</div>
      {% endif %}

      <div class="card-body">
        <div class="card-header">
          {% if r.car_detected %}
            <span class="badge badge-viol">🚗 CAR CONFIRMED</span>
          {% elif r.is_violation %}
            <span class="badge badge-none">⚠ SPEED VIOLATION</span>
          {% else %}
            <span class="badge badge-ok">✓ Speed OK</span>
          {% endif %}
          <span class="ts">{{ r.timestamp }}</span>
        </div>

        <div style="margin-bottom:10px">
          <div class="speed-big">{{ "%.2f"|format(r.speed|float) }}</div>
          <div class="speed-unit">km/h &nbsp;·&nbsp; limit {{ r.threshold }} km/h</div>
        </div>

        <div class="row">
          <span class="row-label">📍 Location</span>
          <span class="row-val">{{ r.location }}</span>
        </div>
        <div class="row">
          <span class="row-label">⏱ Travel time</span>
          <span class="row-val">{{ r.travel_time or '—' }}</span>
        </div>
        <div class="row">
          <span class="row-label">🖼 Frames sent</span>
          <span class="row-val">{{ r.frame_index or '?' }}</span>
        </div>

        {% if r.predictions %}
        <div class="preds">
          {% for p in r.predictions %}
          <div class="pred-item">
            {{ p.class }} &mdash; {{ "%.1f"|format(p.confidence * 100) }}% confidence
            <div class="conf-bar"><div class="conf-fill" style="width:{{ (p.confidence*100)|int }}%"></div></div>
          </div>
          {% endfor %}
        </div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">No detection history yet.<br>Events will appear here once the ESP32 starts sending data.</div>
  {% endif %}

<script>
  function filter(type, btn) {
    document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.card').forEach(card => {
      const v = card.dataset.viol === 'true';
      const c = card.dataset.confirmed === 'true';
      let show = true;
      if(type==='violation') show = v;
      else if(type==='confirmed') show = c;
      else if(type==='clear') show = !v;
      card.style.display = show ? '' : 'none';
    });
  }
  function clearHistory() {
    if(!confirm('Clear all history records?')) return;
    fetch('/history/clear', {method:'POST'})
      .then(r=>r.json())
      .then(()=>location.reload());
  }
</script>
</body>
</html>
""", records=records)


# ─── HISTORY API ─────────────────────────────────────────────
@app.route('/history/data')
def history_data():
    return jsonify(load_history())

@app.route('/history/clear', methods=['POST'])
def history_clear():
    save_history([])
    return jsonify({"status": "cleared"})


# ─── CONFIG UPDATE ───────────────────────────────────────────
@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.json
    if "destination_email" in data:
        CONFIG["destination_email"] = data["destination_email"]
        print(f"[CONFIG] Email updated: {CONFIG['destination_email']}")
    return jsonify({"status": "success"})


# ─── BACKGROUND WORKER ───────────────────────────────────────
# Runs AFTER the ESP32 has already received its response.
# Handles Cloudinary upload, history save, and email — none of
# which the ESP32 needs to wait for.
def background_save(img_bytes, public_id, record, car_detected, predictions):
    """Upload image to Cloudinary, patch the history record, send email."""
    image_url = upload_to_cloudinary(img_bytes, public_id)

    record["image_url"] = image_url or ""
    append_history(record)
    print(f"[BG] History saved  image_url={'ok' if image_url else 'MISSING'}")

    if car_detected and image_url:
        best_conf = max((p['confidence'] for p in predictions), default=0)
        send_violation_report(
            image_url, "toy_car",
            round(best_conf * 100, 2),
            record["location"],
            record["speed"]
        )


# ─── MAIN INFERENCE ENDPOINT ─────────────────────────────────
#
#  SPEED STRATEGY
#  ──────────────
#  The ESP32 is waiting on this response to decide whether to
#  buzz 3 times. Every millisecond counts.
#
#  Fast path  (what the ESP32 waits for):
#    1. Read image bytes from request            — local, instant
#    2. Base64-encode + call Roboflow            — ~200-600 ms
#    3. Return jsonify(rf_data) to ESP32         — done, ESP32 happy
#
#  Slow path  (background thread, ESP32 already gone):
#    4. Upload image to Cloudinary               — ~800-2000 ms
#    5. Append history record to JSON file       — local, instant
#    6. Send email if car confirmed              — ~500-1500 ms
#
#  This keeps the round-trip to the ESP32 at ~300-700 ms instead
#  of 2-4 seconds.
#
@app.route('/upload_and_infer', methods=['POST'])
def upload_and_infer():
    file      = request.files.get('imageFile')
    loc       = request.form.get('location')    or 'Default Enforcement Site'
    spd       = request.form.get('speed')       or '0'
    travel_t  = request.form.get('travel_time') or None
    frame_idx = request.form.get('frame_index') or None

    if not file:
        return jsonify({"error": "No image file provided"}), 400

    img_bytes = file.read()
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    public_id = f"LOG_{ts}"

    t_start = datetime.now()
    print(f"\n{'='*60}")
    print(f"[REQUEST] {t_start.strftime('%H:%M:%S')}  loc={loc}  spd={spd} km/h  size={len(img_bytes)}B")

    # ── FAST: Roboflow inference ──────────────────────────────
    rf_url  = (f"https://serverless.roboflow.com/{CONFIG['model_id']}"
               f"/{CONFIG['version']}?api_key={CONFIG['api_key']}")
    b64_img = base64.b64encode(img_bytes).decode('utf-8')

    rf_data      = {}
    predictions  = []
    car_detected = False
    is_violation = False

    try:
        resp        = requests.post(
            rf_url, data=b64_img,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=12
        )
        rf_data     = resp.json()
        predictions = rf_data.get('predictions', [])

        print(f"[ROBOFLOW] {len(predictions)} prediction(s)  "
              f"took {(datetime.now()-t_start).total_seconds():.2f}s")

        for p in predictions:
            label = p['class']
            conf  = round(p['confidence'] * 100, 2)
            print(f"  → {label.upper()} @ {conf}%")
            if label == 'toy_car':
                car_detected = True
                is_violation = True

    except Exception as e:
        print(f"[ROBOFLOW] Error: {e}")
        rf_data = {"error": str(e), "predictions": []}

    # ── Build partial history record (image_url filled later) ─
    record = {
        "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "location":     loc,
        "speed":        spd,
        "threshold":    "2.25",
        "travel_time":  travel_t,
        "frame_index":  frame_idx,
        "image_url":    "",          # patched by background thread
        "is_violation": is_violation,
        "car_detected": car_detected,
        "predictions":  predictions,
        "roboflow_raw": rf_data
    }

    # ── SLOW: fire-and-forget background thread ───────────────
    t = threading.Thread(
        target=background_save,
        args=(img_bytes, public_id, record, car_detected, predictions),
        daemon=True
    )
    t.start()

    # ── Return to ESP32 immediately ───────────────────────────
    total_ms = (datetime.now() - t_start).total_seconds() * 1000
    print(f"[RESPONSE] Returning to ESP32  total={total_ms:.0f}ms")
    print(f"{'='*60}\n")
    return jsonify(rf_data)


# ─── RUN ─────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
