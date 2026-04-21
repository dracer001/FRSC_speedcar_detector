from flask import Flask, request, render_template_string, jsonify
import requests
import os
import smtplib
import base64
from datetime import datetime
from email.message import EmailMessage

app = Flask(__name__)

# --- SYSTEM SETTINGS ---
EMAIL_SENDER = "daviddracer@gmail.com" 
EMAIL_PASS = "ebtjeycmvlscobwr" 
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465

# --- SYSTEM CONFIGURATION ---
CONFIG = {
    "agency_name": "Federal Road Safety Corps (FRSC)",
    "system_id": "SPEED-VIGIL-001",
    "destination_email": "david.m1901456@st.futminna.edu.ng",
    "model_id": "toy-car-detection-uqfuq",
    "version": "1",
    "api_key": "HrN6gq24W5BypZTSwcgC"
}

UPLOAD_FOLDER = 'violation_records'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def send_violation_report(image_path, label, conf, loc, spd):
    """Sends a formal traffic violation report via secure SMTP."""
    msg = EmailMessage()
    
    # Professional Subject Line to avoid spam filters
    report_id = datetime.now().strftime("%Y%m%d-%H%M")
    msg['Subject'] = f'Traffic Record Update: {report_id} - {loc}'
    msg['From'] = f"FRSC Automated System <{EMAIL_SENDER}>"
    msg['To'] = CONFIG["destination_email"]
    
    # Formal Body Text
    body = (
        f"OFFICIAL TRAFFIC RECORD - {CONFIG['system_id']}\n"
        f"-------------------------------------------\n"
        f"Event Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Location: {loc}\n"
        f"Classification: {label.upper()}\n"
        f"Detection Confidence: {conf}%\n"
        f"Recorded Speed: {spd} km/h\n"
        f"-------------------------------------------\n"
        f"Evidence file attached to this automated log."
    )
    msg.set_content(body)

    try:
        with open(image_path, 'rb') as f:
            msg.add_attachment(
                f.read(), 
                maintype='image', 
                subtype='jpeg', 
                filename=f"VIOLATION_{report_id}.jpg"
            )
        
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASS)
            smtp.send_message(msg)
        print(f"📧 [SYSTEM] Formal report dispatched to: {CONFIG['destination_email']}")
    except Exception as e:
        print(f"❌ [SYSTEM ERROR] Dispatch failed: {e}")

@app.route('/')
def index():
    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>FRSC Speed Vigil Console</title>
            <style>
                body { background: #0b0e14; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, sans-serif; text-align: center; padding: 40px; }
                .container { background: #151921; padding: 30px; border-radius: 12px; border: 1px solid #232a35; display: inline-block; box-shadow: 0 10px 30px rgba(0,0,0,0.5); width: 450px; }
                h1 { color: #f39c12; letter-spacing: 2px; font-size: 24px; margin-bottom: 5px; }
                p.subtitle { color: #7f8c8d; margin-bottom: 25px; font-size: 14px; }
                .config-box { background: #1c222d; padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: left; }
                input[type="text"], input[type="file"] { width: 90%; padding: 10px; margin: 10px 0; border-radius: 5px; border: 1px solid #34495e; background: #0b0e14; color: #ecf0f1; }
                button { background: #f39c12; color: #000; border: none; padding: 12px 25px; border-radius: 5px; font-weight: bold; cursor: pointer; transition: 0.3s; width: 100%; margin-top: 10px; }
                button:hover { background: #e67e22; transform: translateY(-2px); }
                .status-dot { height: 10px; width: 10px; background-color: #27ae60; border-radius: 50%; display: inline-block; margin-right: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>FRSC SPEED VIGIL</h1>
                <p class="subtitle"><span class="status-dot"></span> System Operational: {{sys_id}}</p>
                
                <div class="config-box">
                    <label style="font-size: 12px; color: #f39c12;">Recipient Officer Email:</label>
                    <input type="text" id="emailInput" value="{{email}}">
                    <button onclick="updateConfig()" style="padding: 5px 10px; font-size: 12px; width: auto; float: right;">Update</button>
                    <div style="clear:both;"></div>
                </div>

                <form action="/upload_and_infer" method="post" enctype="multipart/form-data">
                    <div style="text-align: left;">
                        <label style="font-size: 12px;">Evidence Upload:</label>
                        <input type="file" name="imageFile" required>
                        <input type="text" name="location" placeholder="Site Location (e.g., Minna Bypass)">
                        <input type="text" name="speed" placeholder="Measured Speed (km/h)">
                    </div>
                    <button type="submit">EXECUTE INFERENCE</button>
                </form>
            </div>

            <script>
                function updateConfig() {
                    const newEmail = document.getElementById('emailInput').value;
                    fetch('/update_config', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({destination_email: newEmail})
                    }).then(r => alert('Officer Contact Updated Successfully.'));
                }
            </script>
        </body>
        </html>
    """, email=CONFIG["destination_email"], sys_id=CONFIG["system_id"])

@app.route('/update_config', methods=['POST'])
def update_config():
    data = request.json
    if "destination_email" in data:
        CONFIG["destination_email"] = data["destination_email"]
        print(f"🔧 [CONFIG] Destination email updated to: {CONFIG['destination_email']}")
    return jsonify({"status": "success"})

@app.route('/upload_and_infer', methods=['POST'])
def upload_and_infer():
    file = request.files.get('imageFile')
    loc = request.form.get('location') or 'Default Enforcement Site'
    spd = request.form.get('speed') or '0'
    
    if not file: return "No source file provided", 400

    img_bytes = file.read()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(UPLOAD_FOLDER, f"LOG_{ts}.jpg")
    
    with open(img_path, 'wb') as f:
        f.write(img_bytes)

    # Roboflow Serverless Call
    url = f"https://serverless.roboflow.com/{CONFIG['model_id']}/{CONFIG['version']}?api_key={CONFIG['api_key']}"
    b64_img = base64.b64encode(img_bytes).decode('utf-8')
    
    try:
        resp = requests.post(url, data=b64_img, headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = resp.json()
        
        print("\n" + "="*60)
        print(f"📡 FRSC DETECTION LOG | {datetime.now().strftime('%H:%M:%S')}")
        print(f"📍 Location: {loc} | 💨 Speed: {spd} km/h")
        print("-" * 60)
        
        predictions = data.get('predictions', [])
        if not predictions:
            print("STATUS: Frame clear. No targets identified.")
        
        for p in predictions:
            label = p['class']
            conf = round(p['confidence'] * 100, 2)
            print(f"DETECTED: [{label.upper()}] - Confidence: {conf}%")
            
            # Logic: If car is detected, trigger the enforcement report
            if label == 'toy_car':
                send_violation_report(img_path, label, conf, loc, spd)
        
        print("="*60 + "\n")
        return jsonify(data)
        
    except Exception as e:
        print(f"❌ [SYSTEM CRASH] API Connection Failure: {e}")
        return str(e), 500

if __name__ == '__main__':
    # Running with debug=False to keep terminal logs clean and single-threaded
    app.run(host='0.0.0.0', port=5000, debug=True)