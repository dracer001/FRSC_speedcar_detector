"""
roboflow.py
───────────
FRSC Speed Vigil — main Flask application.

Restructured for maintainability:
  • HTML moved out of Python strings into templates/ (Jinja, extends base.html)
  • Email sending moved into core/alerter.py — a stable, thread-safe,
    retrying SMTP sender on the dedicated "ids" mailbox (see core/alerter.py
    for why this fixes the old flaky Gmail-based sending).
  • New: /test_email route + a "Send Test Email" button on the dashboard.
  • New: /history/download_image and /history/download_zip so evidence
    images in the history view can be downloaded individually or in bulk.

Routes, behavior, and response shapes for the ESP32-facing endpoints
(/upload_and_infer, /health) are unchanged.
"""

from flask import (
    Flask, request, render_template, jsonify, Response, send_file
)
import requests
import os
import base64
import io
import json
import threading
import time
import zipfile
import cloudinary
import cloudinary.uploader
from datetime import datetime

from core.alerter import EmailAlerter

app = Flask(__name__)

# ─── SYSTEM CONFIGURATION ────────────────────────────────────
CONFIG = {
    "agency_name":        "Federal Road Safety Corps (FRSC)",
    "system_id":          "SPEED-VIGIL-001",
    "destination_email":  "jeremiah.m2200098@st.futminna.edu.ng",
    "model_id":           "toy-car-detection-uqfuq",
    "version":            "5",
    "api_key":            "HrN6gq24W5BypZTSwcgC",
    "threshold":          "2.25",
}

# ─── EMAIL (see core/alerter.py) ──────────────────────────────
# Priority: Laravel relay -> Brevo HTTP API -> raw SMTP, each used only
# if the ones before it aren't configured via env vars.
alerter = EmailAlerter(
    sender     = os.environ.get("SMTP_SENDER",   "ids@yunivolt.com"),
    password   = os.environ.get("SMTP_PASSWORD", "Intrusion123!"),
    smtp_host  = os.environ.get("SMTP_HOST",     "mail.yunivolt.com"),
    smtp_port  = int(os.environ.get("SMTP_PORT", 465)),
    api_key    = os.environ.get("BREVO_API_KEY"),           # set this on Render
    api_sender = os.environ.get("BREVO_SENDER"),            # optional override
    relay_url  = os.environ.get("LARAVEL_RELAY_URL", "https://yunivolt-official-site-main-x5ahdz.free.laravel.cloud/send-alert-email"),       # e.g. https://.../send-alert-email
    relay_key  = os.environ.get("LARAVEL_RELAY_KEY", "some-long-random-string-you-make-up"),       # must match ALERT_RELAY_KEY in Laravel's .env
)

# ─── CLOUDINARY CONFIG ───────────────────────────────────────
CLOUDINARY_CLOUD_NAME = "dc5hm0npx"
cloudinary.config(
    cloud_name = CLOUDINARY_CLOUD_NAME,
    api_key    = "532695523155545",
    api_secret = os.environ.get("CLOUDINARY_SECRET", "gjFx6nJ8BZmc-_azpwTnoJsgm4E"),
    secure     = True
)

# Only ever proxy-download images from Cloudinary — never an arbitrary
# user-supplied URL (avoids turning the download routes into an SSRF proxy).
ALLOWED_IMAGE_HOSTS = ("res.cloudinary.com",)

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
            public_id     = public_id,
            folder        = "frsc_speedvigil",
            resource_type = "image",
            overwrite     = True,
            format        = "jpg"
        )
        url = result.get("secure_url", "")
        print(f"[CLOUDINARY] Uploaded: {url}")
        return url
    except Exception as e:
        print(f"[CLOUDINARY] Upload failed: {e}")
        return None

def _is_allowed_image_url(url: str) -> bool:
    return bool(url) and any(f"://{host}" in url for host in ALLOWED_IMAGE_HOSTS)


# ════════════════════════════════════════════════════════════
#  ROUTES
# ════════════════════════════════════════════════════════════

# ─── HOME ────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template(
        "index.html",
        email=CONFIG["destination_email"],
        sys_id=CONFIG["system_id"],
    )


# ─── HISTORY PAGE ────────────────────────────────────────────
@app.route('/history')
def history_page():
    records = load_history()
    return render_template("history.html", records=records)


# ─── HISTORY API ─────────────────────────────────────────────
@app.route('/history/data')
def history_data():
    return jsonify(load_history())

@app.route('/history/clear', methods=['POST'])
def history_clear():
    save_history([])
    return jsonify({"status": "cleared"})


# ─── IMAGE DOWNLOAD (single) ─────────────────────────────────
@app.route('/history/download_image')
def download_image():
    url  = request.args.get('url', '')
    name = request.args.get('name') or 'evidence.jpg'
    if not _is_allowed_image_url(url):
        return jsonify({"error": "Invalid or disallowed image URL"}), 400
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Fetch failed: {e}"}), 502

    if not name.lower().endswith(('.jpg', '.jpeg', '.png')):
        name += '.jpg'

    return Response(
        resp.content,
        mimetype=resp.headers.get('Content-Type', 'image/jpeg'),
        headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


# ─── IMAGE DOWNLOAD (bulk zip) ────────────────────────────────
@app.route('/history/download_zip', methods=['POST'])
def download_zip():
    data  = request.get_json(silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({"error": "No items provided"}), 400
    if len(items) > 200:
        return jsonify({"error": "Too many items (max 200)"}), 400

    buf = io.BytesIO()
    added, skipped = 0, 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for item in items:
            url  = item.get('url', '')
            name = item.get('name') or 'evidence.jpg'
            if not _is_allowed_image_url(url):
                skipped += 1
                continue
            try:
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                print(f"[ZIP] Skipping {url}: {e}")
                skipped += 1
                continue

            if not name.lower().endswith(('.jpg', '.jpeg', '.png')):
                name += '.jpg'
            # avoid collisions inside the zip
            base_name, n = name, 1
            while name in used_names:
                stem, ext = os.path.splitext(base_name)
                name = f"{stem}_{n}{ext}"
                n += 1
            used_names.add(name)

            zf.writestr(name, resp.content)
            added += 1

    if added == 0:
        return jsonify({"error": "None of the requested images could be fetched"}), 502

    buf.seek(0)
    print(f"[ZIP] Built archive: {added} added, {skipped} skipped")
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="frsc_evidence_bulk.zip",
    )


# ─── TEST EMAIL ───────────────────────────────────────────────
@app.route('/test_email', methods=['POST'])
def test_email():
    recipient = CONFIG["destination_email"]
    ok, info = alerter.send_test(recipient)
    status_code = 200 if ok else 502
    return jsonify({
        "status": "sent" if ok else "failed",
        "recipient": recipient,
        "error": None if ok else info,
    }), status_code


# ─── CONFIG UPDATE ───────────────────────────────────────────
@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.json or {}
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
        ok, info = alerter.send_violation_report(
            recipient  = CONFIG["destination_email"],
            image_url  = image_url,
            label      = "toy_car",
            confidence = round(best_conf * 100, 2),
            location   = record["location"],
            speed      = record["speed"],
            threshold  = record["threshold"],
            system_id  = CONFIG["system_id"],
        )
        if not ok:
            print(f"[EMAIL] Violation report failed: {info}")


# ─── HEALTH CHECK ─────────────────────────────────────────────
# Lightweight liveness probe — no image processing, no DB, no
# external calls. The ESP32 (or any monitor) hits this to confirm
# the server process is up and responding, fast, every time.
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status":     "ok",
        "system_id":  CONFIG["system_id"],
        "agency":     CONFIG["agency_name"],
        "time":       datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }), 200


# ─── KEEP-ALIVE (anti cold-start) ────────────────────────────
# Render's free tier spins down web services after ~15 minutes of
# inactivity, and the next request then takes 30-60s to cold-start.
# This background thread pings our OWN /health endpoint every 10
# minutes so the service never goes idle long enough to sleep,
# which keeps ESP32 requests fast and predictable during testing
# and demos. Set SELF_URL to this service's own public Render URL.
SELF_URL = os.environ.get("SELF_URL", "https://frsc-speedcar-detector.onrender.com")
KEEPALIVE_INTERVAL_SEC = 600  # 10 minutes — safely under the 15-min sleep window

def keep_alive_loop():
    while True:
        time.sleep(KEEPALIVE_INTERVAL_SEC)
        try:
            r = requests.get(f"{SELF_URL}/health", timeout=10)
            print(f"[KEEPALIVE] Self-ping -> {r.status_code}")
        except Exception as e:
            print(f"[KEEPALIVE] Self-ping failed: {e}")

threading.Thread(target=keep_alive_loop, daemon=True).start()



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
#    6. Send email if car confirmed              — ~500-1500 ms (retried)
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
        "threshold":    CONFIG["threshold"],
        "travel_time":  travel_t,
        "frame_index":  frame_idx,
        "image_url":    "",          # patched by background thread
        "public_id":    public_id,
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
    # CHANGE THIS LINE to return the calculated flags to your ESP32-CAM
    return jsonify({
        "car_detected": car_detected,
        "is_violation": is_violation,
        "predictions": predictions,
        "roboflow_raw": rf_data
    })


# ─── RUN ─────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
