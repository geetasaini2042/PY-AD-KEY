from flask import Flask, request, jsonify, Response, redirect, make_response, render_template_string
from flask_cors import CORS
import requests
import secrets
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from urllib.parse import quote, urlparse
import os, json
import random
import logging
from bson import ObjectId


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


APP_DB_KEY = "app1_tokens_data"
APP_UNLIMITED_DB_KEY = "app_unlimited_tokens_data" 
# --- 1. कॉन्फ़िगरेशन (Configuration) ---
app = Flask(__name__)
import threading

# आपके पहले (Proxy) बैकएंड का वेबहुक URL
SERVER1_WEBHOOK_URL = "http://study-api.lnkz.tech/api/webhook/token"
def send_webhook_to_server1(payload):
    """यह फंक्शन बैकग्राउंड में पहले सर्वर को नया टोकन भेजेगा ताकि यह धीमा न हो"""
    logger.info("Preparing to send webhook in background thread...")
    
    def send():
        logger.debug(f"Webhook thread started. Payload to send: {payload}")
        try:
            logger.info(f"Sending POST request to {SERVER1_WEBHOOK_URL}...")
            response = requests.post(SERVER1_WEBHOOK_URL, json=payload, timeout=5)
            
            # रिस्पॉन्स का स्टेटस कोड चेक करना और लॉग करना
            if response.status_code in [200, 201]:
                logger.info(f"Webhook sent successfully! Status Code: {response.status_code}")
            else:
                logger.warning(f"Webhook sent but received unexpected status: {response.status_code}. Response: {response.text}")
                
        except Exception as e:
            # print की जगह logger.error का इस्तेमाल
            logger.error(f"Webhook Failed: {str(e)}")
    
    # थ्रेड को स्टार्ट करना
    threading.Thread(target=send).start()


# CORS हैंडलिंग
CORS(app, resources={r"/*": {"origins": "*"}})

# मोंगोडीबी यूआरआई (आप इसे एनवायरनमेंट वेरिएबल के रूप में सेट कर सकते हैं)
DT_MON = os.getenv("DT_MON", "mongodb://localhost:27017/") 
API_KEY = os.getenv("API_KEY", "") 
FA_KEY = os.getenv("FA_KEY", "") 
client = MongoClient(DT_MON)
db = client['tokens_database']
collection = db['kv_store']
DB_KEY = "tokens_data"
DT_MON = os.getenv("DT_MON", "mongodb://localhost:27017/") 
API_KEY = os.getenv("API_KEY", "") 
FA_KEY = os.getenv("FA_KEY", "") 
client = MongoClient(DT_MON)
db = client['tokens_database']
collection = db['kv_store']
DB_KEY = "tokens_data"
premium_collection = db['premium_tokens']


# JSON डेटा लोड करने के लिए फंक्शन
def load_apps_data():
    try:
        with open('apps_data.json', 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []

# कस्टम हेडर चेक करने का अलग फंक्शन
def should_block_request(app_signature, auth_token):
    # यहाँ अपना लॉजिक लिखें
    # उदाहरण के लिए: अगर हेडर मौजूद नहीं हैं, तो ब्लॉक करें
    if not app_signature or not auth_token:
        return False # True आने पर रिक्वेस्ट ब्लॉक हो जाएगी
        
    # अगर सब सही है तो False रिटर्न करें
    return False
@app.route('/api/v2/active_tokens', methods=['GET'])
def get_all_active_tokens():
    active_tokens = {}
    tz_kolkata = pytz.timezone('Asia/Kolkata')
    current_time_ts = datetime.now(tz_kolkata).timestamp()

    # 1. Standard 24h Tokens
    doc = collection.find_one({"_id": APP_DB_KEY})
    if doc and "data" in doc:
        for tracking_key, entry in doc["data"].items():
            created_dt = datetime.fromisoformat(entry["created_at"])
            created_time = created_dt.timestamp()
            
            if (current_time_ts - created_time) / 3600 < 24:
                final_token = entry.get("final_token")
                active_tokens[final_token] = {
                    "auth_token": final_token,
                    "app_signature": entry.get("app_signature"),
                    "start_time": created_dt.strftime('%Y-%m-%d %H:%M:%S'),
                    "expire_time": (created_dt + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "active"
                }

    # 2. Premium Tokens
    premium_docs = premium_collection.find({"status": "active"})
    for p in premium_docs:
        final_token = p.get("final_token")
        activated_dt = datetime.fromisoformat(p["activated_at"])
        validity_days = p.get("validity_days", 30)
        
        expire_dt = activated_dt + timedelta(days=validity_days)
        
        if datetime.now(tz_kolkata) <= expire_dt:
            active_tokens[final_token] = {
                "auth_token": final_token,
                "app_signature": p.get("app_device_id"),
                "start_time": activated_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "expire_time": expire_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active"
            }

    return jsonify(active_tokens), 200

@app.route('/PW/schedule-details', methods=['GET'])
def proxy_schedule_details():
    # आने वाले URL से सभी पैरामीटर्स (query string) प्राप्त करें
    query_string = request.query_string.decode('utf-8')
    
    # टारगेट URL जहाँ रिक्वेस्ट भेजनी है
    target_url = f"https://rarestudy.in/schedule-details?{query_string}"

    # ब्राउज़र वाले सभी हेडर्स (cURL से लिए गए)
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
       # 'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Encoding': 'gzip, deflate',
        'sec-ch-ua': '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'upgrade-insecure-requests': '1',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-user': '?1',
        'sec-fetch-dest': 'document',
        'referer': 'https://rarestudy.in/stream?batchId=691c37bcc8cc0783a9d602ee&subjectId=691e10b04a7ca45ed2d1dd13&chapterId=693822cf6de71259320d3374&batchName=Saakaar%202027%20Physics&subjectName=Physics&chapterName=EMT&section=videos',
        'accept-language': 'en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7,hi;q=0.6',
    }

    # शुरुआती कुकीज़
    cookies = {
        'session_expiry': '1780282006682',
        'favourite_batches': '%5B%226a0810667a12c6e8464434dd%22%2C%22691c37bcc8cc0783a9d602ee%22%5D',
        'session': '.eJyt1Meuq2gCBOB3OVt6ZHK4Ui8wYHLmN2FjkcHkHFr97nPmHWZfq1J99c_PZ8znLu7zfv35s85b_tdPnKb5snzWocn7nz8_q_rmTZPj8px-xuNzyTw0gi72jhYzdM3LhmSWZCUvfyFRpQP5DfVxZKXPoLrW0FdNrfcoB-NmxCWPCS_nHdhC3AZ1sktWZ7uRfwjtCg3-6xrlfjDFcJdviQ7KlwjQ4Tkbhv1qeRxSzvZSFOUs5EAjOnQRKyHlAg2CHjjo5AnlnfC1ZovZIANBQCWTpIWrnZ2vFLkHo3xErEpdLaW0F0hGD9sb-N9wo3g7UMEmKBp-s9W9DLJFkf5cquo8p99r81bGfaYR4WOzCquXG8mzh9lbsIeb_iYTPUBTLi4IVrc77itz4fQ4qrs14zgJosrIcKFNS4FzM0Gp_bkzAuMbtoy8oDjd2A0gMTjyLUK6Zwp5DF1ZH7JcAF3wO2_EdVhllz2nYCVgNlyoYcZ8IvBgk4VXbeWkgO_QzGQd3LrEnSJSB-PU_1aVvGDJaHt4P17sXQiaj5n4KPNzZpHF-GVQprob0D-IZyfzS-IqCx3t_t50eqO0iXJzmsk2VDWlboNK4U3A1psaAje38ZOr58Qr7_1hM7tbPZ12KDi15_byPQ495WaTxcSXihSowDht7KvxCua1ZVq7UAlwhXYPSmsWbU0L2Ncu4p3uuonTZ6vnCyid44dqOZ7ftraZBCxX4mGhID6CVNv0BMvB-6F8KMAyEslnA82YGXYrr0DvgdFgkuK-p-DZ5eNebyyzinLmthGbMW0YJTrJKWisJiasUs1Nylu-Ju9jrDR-5R_usFB1sybRtdN9JbF___z1Mx6f_zMAjSLY5jB-Q2ijF3e35WLXv9MtBEJkKpyol6v0zOnelLb2YZQ1RSt0RH5DWEv13cagc4lbS53xpGZjv2oHYUVnokrAKjyaNQ1PNAuUt2sfUzGPZW3Iepjc1ozu1GUWtcS24kC-RloHtrlXJl1LcJRABZePq5VvWhzI5W0niG7ADjyu-Dmrqq5rwSKMc3-pI8zommL6-RvNPBUVzhDPxOXEeEHyWHOK3HioDgRLWXHSeP2MqjYGMi1Rh4qN2DoblQ2wp9l9R4UcNs3NSytR9Id2vb6dC3wQRO7tlOW5QxKFKZyhENIszgXSl6VbMRVmlTbKapXJvXN458zcpGXIaBk-eN6DxhVCb7lsBclQHetK-Dg0hQvsXbZxJpwKo1lt33P5QW00z1RXI1W05e6deUgvEkmoKZlfjFyecfts1pvOQ0Gfj4EFK7DxY7sjLSTWC_vivURpPiUIN5CmA35G9XaKvwd1mgH98G1YUk-Q66-ax3Ib88XTOCQQPrJXfZMZs2-QHl387vpOU1dRWzpxj5oOK50FLOPvntKI1MNqhC8hPzvHnGFVG9pJn7BIbK_TN05u1ZypV4RsMFanBrpJ1pJsS18rJ02zqKjfdplFLSKgFkGv9XfvqJPyOSG_eEVpQbl7vn2C6QSmHBp7DptiYbmy4EjiiRTkd2lEahJKikkTh2kUnUwNwdnc6H21p3A5oUGuov6LYl4-yy-Jevifh13fPcEScPGeXi6eDu42DCGAlZ14lwhWYJJ0-Sy5hNXwFF1tajuNZ4o6JcZRifzQLaoO_p3hJ8eseFpVbZxIzkCO9FKDbxT_x28KMAgTC9d58-HXl5jjpRXCa046gOJgh8_iLgIBT54IrfYBh8Lk9-Ox7vANbb3WaG3GEhUm68gHNIZWLBF-KLm7io_3UZfdObj159__AoKzV0c.ahuxUg.3yzDCVMd2G_RMG0etYeZt-MZZoo'
    }

    # Session ऑब्जेक्ट बनाएँ ताकि कुकीज़ और 302 रीडायरेक्ट ब्राउज़र की तरह हैंडल हो सकें
    session = requests.Session()
    session.cookies.update(cookies)

    try:
        # allow_redirects=True से यह 302 लोकेशन को फॉलो करेगा और नया HTML लाए
        response = session.get(
            target_url, 
            headers=headers,
        )
        print(response.text)
        response = session.get(
            target_url, 
            headers=headers, 
            allow_redirects=True, 
            timeout=15
        )

        # अंतिम रिस्पॉन्स क्लाइंट को वापस भेजें
        return Response(
            response.content, 
            status=response.status_code, 
            content_type=response.headers.get('content-type', 'text/html')
        )

    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 500
@app.route('/get-time', methods=['GET', 'OPTIONS'])
def get_custom_time():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        # हमेशा एशिया/कोलकाता (IST) का एकदम सही समय लेगा
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        current_time_kolkata = datetime.now(tz_kolkata)
        
        # ISO 8601 फॉर्मेट में समय भेजना ताकि जावास्क्रिप्ट इसे आसानी से समझ सके
        # उदाहरण: 2026-05-10T10:22:00.123456+05:30
        formatted_time = current_time_kolkata.isoformat()
        
        return jsonify({
            "status": "success",
            "datetime": formatted_time
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/check-key-type', methods=['GET', 'OPTIONS'])
def check_key_type():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        # फ्रंटएंड से टोकन प्राप्त करना (?token=xyz)
        token = request.args.get('token')

        if token:
            # चेक करें कि क्या यह टोकन प्रीमियम डेटाबेस में मौजूद है
            premium_doc = premium_collection.find_one({"final_token": token})
            
            if premium_doc:
                # अगर टोकन प्रीमियम डेटाबेस में मिल गया
                return jsonify({
                    "status": "success",
                    "type": "premium"
                }), 200

        # अगर टोकन नहीं मिला या कुछ और भेजा गया है, तो डिफ़ॉल्ट URL Shortener मान लें
        return jsonify({
            "status": "success",
            "type": "url_shortner"
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/tokens/edit-premium', methods=['GET', 'POST'])
def premium_tokens_editor_ui():
    if request.method == 'GET':
        try:
            prem_cursor = premium_collection.find({})
            prem_data = []
            for p in prem_cursor:
                p['_id'] = str(p['_id']) 
                prem_data.append(p)
                
            tokens_json = json.dumps(prem_data, indent=4)

            html_template = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Premium Token Editor</title>
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e1e; color: #d4d4d4; margin: 0; padding: 20px; }
                    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
                    h2 { margin: 0; color: #c678dd; } 
                    textarea { width: 100%; height: 75vh; background-color: #252526; color: #9cdcfe; font-family: 'Courier New', Courier, monospace; font-size: 14px; padding: 15px; border: 1px solid #333; border-radius: 8px; box-sizing: border-box; outline: none; resize: vertical; }
                    textarea:focus { border-color: #c678dd; }
                    .btn-save { background-color: #c678dd; color: white; border: none; padding: 10px 24px; font-size: 16px; font-weight: bold; border-radius: 5px; cursor: pointer; transition: 0.2s; }
                    .btn-save:hover { background-color: #a05eb5; }
                    #status-msg { font-weight: bold; margin-top: 10px; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>Premium Token Editor (JSON)</h2>
                    <button class="btn-save" onclick="saveTokens()">💾 Save Premium Changes</button>
                </div>
                <div id="status-msg"></div>
                <textarea id="json-editor">{{ tokens_json }}</textarea>

                <script>
                    function showMessage(msg, isError) {
                        const statusEl = document.getElementById('status-msg');
                        statusEl.innerText = msg;
                        statusEl.style.color = isError ? '#f44336' : '#4caf50';
                        setTimeout(() => statusEl.innerText = '', 5000);
                    }

                    function saveTokens() {
                        const jsonText = document.getElementById('json-editor').value;
                        let parsedData;
                        
                        try {
                            parsedData = JSON.parse(jsonText);
                        } catch (e) {
                            alert("❌ Invalid JSON Format!\\n\\nDetails: " + e.message);
                            showMessage("Syntax Error in JSON!", true);
                            return;
                        }

                        showMessage("Saving...", false);
                        document.querySelector('.btn-save').disabled = true;

                        fetch('/tokens/edit-premium', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(parsedData)
                        })
                        .then(response => response.json())
                        .then(data => {
                            document.querySelector('.btn-save').disabled = false;
                            if(data.status === 'success') {
                                alert("✅ Premium Tokens successfully updated!");
                                showMessage("Saved Successfully!", false);
                            } else {
                                alert("❌ Error: " + data.message);
                                showMessage("Error saving data.", true);
                            }
                        })
                        .catch(err => {
                            document.querySelector('.btn-save').disabled = false;
                            alert("❌ Network Error!");
                            showMessage("Network Error.", true);
                        });
                    }
                </script>
            </body>
            </html>
            """
            # कैशिंग रोकने के लिए Response ऑब्जेक्ट
            response = make_response(render_template_string(html_template, tokens_json=tokens_json))
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
            
        except Exception as e:
            return f"Error loading premium data: {str(e)}", 500

    elif request.method == 'POST':
        try:
            updated_data = request.get_json()
            if not isinstance(updated_data, list):
                return jsonify({"status": "error", "message": "Data format should be a JSON array (list)"}), 400

            # 1. डेटाबेस से पुराने सभी टोकन्स डिलीट करें ताकि कचरा न बचे
            premium_collection.delete_many({})

            # 2. अगर नया डेटा खाली नहीं है, तो उसे इन्सर्ट करें
            if len(updated_data) > 0:
                for p_token in updated_data:
                    p_token.pop('_id', None) # MongoDB अपनी नई _id खुद बना लेगा
                
                premium_collection.insert_many(updated_data)

            return jsonify({"status": "success", "message": "Premium tokens updated completely!"})

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/generate-premium-link/', methods=['POST'])
def generate_premium_link():
    try:
        data = request.get_json() if request.is_json else {}
        validity_days = int(data.get('validity_days', 30))
        
        execute_token = secrets.token_urlsafe(16)
        
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        created_at = datetime.now(tz_kolkata).isoformat()
        
        premium_data = {
            "execute_token": execute_token,
            "status": "pending", 
            "validity_days": validity_days,
            "created_at": created_at,
            "browser_fingerprint": None,
            "final_token": None,
            "is_saved": "no",          
            "app_device_id": None      
        } 
        premium_collection.insert_one(premium_data)
        protocol = request.headers.get('X-Forwarded-Proto', 'http')
        auth_link = f"{protocol}://{request.host}/premium-auth?token={execute_token}"
        
        return jsonify({
            "status": "success",
            "execute_token": execute_token,
            "auth_link": auth_link,
            "validity_days": validity_days,
            "message": "Premium link generated successfully."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =====================================================================
# 2. यूज़र इंटरफ़ेस (Frontend): ब्राउज़र में फिंगरप्रिंट बनाने वाला पेज
# =====================================================================
@app.route('/premium-auth', methods=['GET'])
def premium_auth_page():
    execute_token = request.args.get('token')
    if not execute_token:
        return "Invalid or Missing Token", 400

    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Premium Access</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f4f7f6; }
            .box { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); display: inline-block; }
            #final-token { font-weight: bold; color: #2c3e50; font-size: 20px; margin: 20px 0; padding: 10px; background: #ecf0f1; border: 1px dashed #bdc3c7; word-break: break-all;}
            button { padding: 10px 20px; font-size: 16px; cursor: pointer; background: #27ae60; color: white; border: none; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>Verifying Your Device...</h2>
            <p id="status-text">Please wait while we generate your secure premium key.</p>
            <div id="token-container" style="display:none;">
                <p>Your Premium Token:</p>
                <div id="final-token"></div>
                <button onclick="copyToken()">Copy Token</button>
            </div>
        </div>

        <script>
            async function generateFingerprint() {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                ctx.textBaseline = "top";
                ctx.font = "14px 'Arial'";
                ctx.textBaseline = "alphabetic";
                ctx.fillStyle = "#f60";
                ctx.fillRect(125,1,62,20);
                ctx.fillStyle = "#069";
                ctx.fillText("Premium Fingerprint", 2, 15);
                ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
                ctx.fillText("Premium Fingerprint", 4, 17);
                
                const canvasData = canvas.toDataURL();
                const screenData = window.screen.width + "x" + window.screen.height + "-" + window.screen.colorDepth;
                const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                
                const rawFingerprint = navigator.userAgent + screenData + timezone + canvasData;
                
                const msgBuffer = new TextEncoder().encode(rawFingerprint);
                const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                const fingerprintHash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
                
                return fingerprintHash;
            }

            async function submitFingerprint() {
                const fp = await generateFingerprint();
                const execute_token = "{{ token }}";

                fetch('/api/premium/verify-fingerprint/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ execute_token: execute_token, fingerprint: fp })
                })
                .then(response => response.json())
                .then(data => {
                    if(data.status === 'success') {
                        document.getElementById('status-text').style.display = 'none';
                        document.getElementById('token-container').style.display = 'block';
                        document.getElementById('final-token').innerText = data.final_token;
                    } else {
                        document.getElementById('status-text').innerText = "Error: " + data.message;
                        document.getElementById('status-text').style.color = "red";
                    }
                })
                .catch(err => {
                    document.getElementById('status-text').innerText = "Network Error!";
                });
            }

            function copyToken() {
                const token = document.getElementById('final-token').innerText;
                navigator.clipboard.writeText(token);
                alert("Token Copied!");
            }

            window.onload = submitFingerprint;
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, token=execute_token)


# =====================================================================
# 3. बैकएंड (Backend): फिंगरप्रिंट सेव करना और फाइनल टोकन देना
# =====================================================================
@app.route('/api/premium/verify-fingerprint/', methods=['POST', 'OPTIONS'])
def verify_premium_fingerprint():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json()
        execute_token = data.get('execute_token')
        fingerprint = data.get('fingerprint')

        if not execute_token or not fingerprint:
            return jsonify({"status": "error", "message": "Missing required data"}), 400

        token_doc = premium_collection.find_one({"execute_token": execute_token})

        if not token_doc:
            return jsonify({"status": "error", "message": "Invalid link"}), 404

        if token_doc.get("status") != "pending":
            return jsonify({"status": "error", "message": "This link has already been used and is expired."}), 403

        final_token = secrets.token_hex(20)
        
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        activated_at = datetime.now(tz_kolkata).isoformat()

        premium_collection.update_one(
            {"_id": token_doc["_id"]},
            {"$set": {
                "status": "active",
                "browser_fingerprint": fingerprint,
                "final_token": final_token,
                "activated_at": activated_at
            }}
        )

        return jsonify({
            "status": "success",
            "final_token": final_token,
            "message": "Device registered and token generated successfully."
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/premium/check-key/', methods=['POST', 'OPTIONS'])
def check_premium_key():
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.get_json()
        final_token = data.get('final_token')
        
        app_device_id = data.get('app_device_id') or request.headers.get('X-SN-Signature')
        
        if not final_token:
            return jsonify({"status": "error", "message": "Final token is missing."}), 400
            
        if not app_device_id:
            return jsonify({"status": "error", "message": "Device ID (app_device_id) is missing."}), 400

        token_doc = premium_collection.find_one({"final_token": final_token})

        if not token_doc:
            return jsonify({"status": "error", "message": "Invalid token."}), 404

        if token_doc.get("status") == "expired":
            return jsonify({"status": "error", "message": "This premium token has expired."}), 403

        # 🌟 समाधान: समय की गणना (Time logic) को वेबहुक से पहले (ऊपर) लाया गया है 🌟
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        current_time_kolkata = datetime.now(tz_kolkata)
        
        activated_time = datetime.fromisoformat(token_doc["activated_at"])
        validity_days = token_doc.get("validity_days", 30) 
        expiration_time = activated_time + timedelta(days=validity_days)

        # --- मल्टी-डिवाइस सुरक्षा लॉजिक (is_saved) ---
        is_saved = token_doc.get("is_saved", "no")
        saved_device_id = token_doc.get("app_device_id")

        if is_saved == "no":
            premium_collection.update_one(
                {"_id": token_doc["_id"]},
                {"$set": {
                    "is_saved": "yes",
                    "app_device_id": app_device_id
                }}
            )
            
            # अब यह एरर नहीं देगा क्योंकि activated_time और expiration_time ऊपर बन चुके हैं
            webhook_payload = {
                "auth_token": final_token,
                "app_signature": app_device_id,
                "start_time": activated_time.strftime('%Y-%m-%d %H:%M:%S'),
                "expire_time": expiration_time.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active"
            }
            send_webhook_to_server1(webhook_payload)

        else:
            if saved_device_id != app_device_id:
                return jsonify({
                    "status": "error", 
                    "message": "This token is already in use on another device."
                }), 403

        # --- एक्सपायरी (Validity) चेक करना ---
        if current_time_kolkata <= expiration_time:
            days_left = (expiration_time - current_time_kolkata).days
            return jsonify({
                "status": "success", 
                "message": "Premium access granted.",
                "days_left": days_left
            }), 200
        else:
            premium_collection.update_one({"_id": token_doc["_id"]}, {"$set": {"status": "expired"}})
            return jsonify({"status": "error", "message": "Premium token has expired."}), 403
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@app.route('/auth-Key/generate-token/', methods=['GET', 'POST', 'OPTIONS'])
def handler():
    # OPTIONS रिक्वेस्ट के लिए 200 स्टेटस लौटाएं
    if request.method == 'OPTIONS':
        return '', 200

    try:
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
            
        current_time = datetime.now().timestamp()

        # मोंगोडीबी से डेटा पढ़ना
        doc = collection.find_one({"_id": DB_KEY})
        current_data = doc.get("data", {}) if doc else {}

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        
        # 1. चेक करें कि क्या यूज़र की कोई एक्टिव की (Key) है (24 घंटे से कम पुरानी)
        for token, entry in current_data.items():
            if entry.get("ip") == user_ip:
                created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                hours_diff = (current_time - created_time) / 3600

                if hours_diff < 24:
                    return jsonify({
                        "status": "success",
                        "url": entry["short_url"],
                        "message": "Active session found"
                    }), 200

        # 2. एक्सपायर हो चुकी की (Key) को रीयूज़ (Reuse) करना
        reused_token = None
        date_time_now = datetime.now(tz_kolkata).isoformat()

        for token, entry in current_data.items():
            created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
            hours_diff = (current_time - created_time) / 3600

            if hours_diff >= 24:
                entry["ip"] = user_ip
                entry["created_at"] = date_time_now
                entry["status"] = "active"
                reused_token = token
                break

        # अगर पुरानी की रीयूज़ हो गई है
        if reused_token:
            collection.update_one({"_id": DB_KEY}, {"$set": {"data": current_data}}, upsert=True)
            return jsonify({
                "status": "success",
                "url": current_data[reused_token]["short_url"],
                "message": "Generation successful (Reused)"
            }), 200

        # 3. नई की (Key) बनाना (अगर कोई पुरानी या एक्सपायर की नहीं मिली)
        tracking_token = secrets.token_hex(16)
        final_token = secrets.token_hex(16)

        referer = request.headers.get('Referer') or request.headers.get('Origin')
        if referer:
            parsed_url = urlparse(referer)
            main_website_url = f"{parsed_url.scheme}://{parsed_url.netloc}/auth?token={final_token}"
        else:
            protocol = request.headers.get('X-Forwarded-Proto', 'http')
            main_website_url = f"{protocol}://{request.host}/auth?token={final_token}"

        tracking_api_url = f"https://key.lnkz.tech/?token={tracking_token}"
        api_url = f"https://arolinks.com/api?api={FA_KEY}&url={quote(tracking_api_url)}&format=json"
        
        api_response = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        json_response = api_response.json()

        if json_response.get('status') == 'success':
            shortened_url = json_response.get('shortenedUrl')

            current_data[tracking_token] = {
                "ip": user_ip,
                "created_at": date_time_now,
                "short_url": shortened_url,
                "tracking_url": tracking_api_url,
                "main_url": main_website_url,
                "final_token": final_token,
                "status": "active"
            }

            # मोंगोडीबी में डेटा सेव करना
            collection.update_one({"_id": DB_KEY}, {"$set": {"data": current_data}}, upsert=True)

            return jsonify({
                "status": "success",
                "url": shortened_url,
                "message": "Generated new key"
            }), 200
        else:
            raise Exception(json_response.get('message', 'Shortener API Failure'))

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 200

@app.route('/auth-Key/check-key/', methods=['GET', 'OPTIONS'])
def verify_handler():
    # 1. CORS Headers और OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return Response(status=200)

    # URL से 'verify' पैरामीटर लेना (जैसे: ?verify=xyz)
    key_to_check = request.args.get('verify')
    if key_to_check:
        key_to_check = key_to_check.strip()

    if not key_to_check:
        return Response("No key provided", status=400, mimetype='text/plain')

    # Database Keys
    DB_KEY = "tokens_data" # Normal 24-hour tokens
    UNLIMITED_DB_KEY = "unlimited_tokens_data" # Unlimited validity tokens

    try:
        # --- STEP 1: CHECK UNLIMITED TOKENS FIRST ---
        u_doc = collection.find_one({"_id": UNLIMITED_DB_KEY})
        u_data = u_doc.get("data", {}) if u_doc else {}
        
        if key_to_check in u_data:
            return Response("Authorized", status=200, mimetype='text/plain')

        # --- STEP 2: CHECK STANDARD 24-HOUR TOKENS ---
        doc = collection.find_one({"_id": DB_KEY})
        
        if not doc or "data" not in doc:
            return Response("No Database Found", status=404, mimetype='text/plain')

        data = doc["data"]
        found_entry = None
        
        # JSON डेटा में final_token को ढूँढें
        for tracking_key, entry in data.items():
            if entry.get("final_token") == key_to_check:
                found_entry = entry
                break # सही एंट्री मिलते ही लूप बंद कर दें

        # अगर final_token डेटाबेस में मिल गया
        if found_entry is not None:
            # --- TIME CALCULATION LOGIC ---
            current_time = datetime.now().timestamp()
            # ISO फॉर्मेट से समय को पार्स करना (पिछले कोड के अनुसार)
            created_time = datetime.fromisoformat(found_entry["created_at"]).timestamp()
            
            time_diff_seconds = current_time - created_time
            hours_diff = time_diff_seconds / 3600 # सेकंड्स को घंटों में बदलें

            # Verify Condition (Less than 24 Hours)
            if hours_diff < 24:
                return Response("Authorized", status=200, mimetype='text/plain')
            else:
                return Response("Expired", status=401, mimetype='text/plain')
        else:
            return Response("Invalid Key", status=404, mimetype='text/plain')

    except Exception as e:
        # किसी भी तरह की सर्वर एरर के लिए
        return Response("Server Error: " + str(e), status=500, mimetype='text/plain')


@app.route('/auth-Key/generate-token/app/', methods=['GET', 'POST', 'OPTIONS'])
def handler_app():
    logger.info(f"Incoming {request.method} request to /auth-Key/generate-token/app/")
    
    # OPTIONS रिक्वेस्ट के लिए 200 स्टेटस लौटाएं
    if request.method == 'OPTIONS':
        logger.debug("Handling OPTIONS request, returning 200")
        return '', 200
        
    try:
        # ऐप सिग्नेचर हेडर से लेना
        app_signature = request.headers.get('X-SN-Signature')
        logger.debug(f"Received App Signature: {app_signature}")
        
        if not app_signature:
            logger.warning("App Signature is missing in headers")
            return jsonify({
                "status": "error",
                "message": "App Signature is missing"
            }), 400

        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
        logger.debug(f"User IP identified as: {user_ip}")
            
        current_time = datetime.now().timestamp()

        # मोंगोडीबी से ऐप का डेटा पढ़ना
        logger.info(f"Fetching data from MongoDB for key: {APP_DB_KEY}")
        doc = collection.find_one({"_id": APP_DB_KEY})
        current_data = doc.get("data", {}) if doc else {}
        logger.debug(f"Total tokens found in database: {len(current_data)}")

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        date_time_now_obj = datetime.now(tz_kolkata)
        date_time_now = date_time_now_obj.isoformat()
        
        # 1. चेक करें कि क्या यूज़र (उसी ऐप सिग्नेचर) की कोई एक्टिव की (Key) है (24 घंटे से कम पुरानी)
        logger.info("Checking for an existing active session (under 24 hours)...")
        for token, entry in current_data.items():
            if entry.get("app_signature") == app_signature:
                created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                hours_diff = (current_time - created_time) / 3600
                logger.debug(f"Found token for signature {app_signature}. Age: {hours_diff:.2f} hours")

                if hours_diff < 24:
                    logger.info("Active session found. Returning existing short URL.")
                    return jsonify({
                        "status": "success",
                        "url": entry["short_url"],
                        "message": "Active session found"
                    }), 200

        # 2. एक्सपायर हो चुकी की (Key) को रीयूज़ (Reuse) करना
        logger.info("No active session found. Looking for an expired token to reuse...")
        reused_token = None

        for token, entry in current_data.items():
            created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
            hours_diff = (current_time - created_time) / 3600

            if hours_diff >= 24:
                logger.debug(f"Expired token found for reuse: {token}. Age: {hours_diff:.2f} hours")
                reused_token = token
                break

        if reused_token:
            logger.info(f"Updating reused token {reused_token} in MongoDB...")
            
            # ट्रैकिंग टोकन वही रहेगा (ताकि Arolinks काम करता रहे)
            # लेकिन हम नया 'final_token' बनाएंगे ताकि यूज़र पुरानी की इस्तेमाल न कर सके
            new_final_token = secrets.token_hex(16)
            entry = current_data[reused_token]
            
            entry["ip"] = user_ip
            entry["app_signature"] = app_signature
            entry["created_at"] = date_time_now
            entry["status"] = "active"
            entry["final_token"] = new_final_token
            
            # बायपास सिस्टम के लिए फ्लैग को रीसेट करें (ताकि उसे फिर से स्टेप 1 पूरा करना पड़े)
            if "is_tracked_url1" in entry:
                entry["is_tracked_url1"] = False

            # 🌟 चेक करें कि क्या यह पुराने सिस्टम का डेटा है (नया वर्ज़न नहीं है)
            if "shortx_url" not in entry:
                logger.info("Reused token is from legacy system. Upgrading to dual tracking...")
                tracking_api_url_2 = f"https://study.edumate.life/app/?api=2&token={reused_token}"
                shortx_api_key = "63b82b926367794c651bd6f1c95acff389ea122d"
                shortx_req_url = f"https://shortxlinks.com/api?api={shortx_api_key}&url={quote(tracking_api_url_2)}&format=json"
                
                try:
                    shortx_response = requests.get(shortx_req_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=7)
                    shortx_json = shortx_response.json()
                    
                    if shortx_json.get('status') == 'success' or 'shortenedUrl' in shortx_json:
                        entry["shortx_url"] = shortx_json.get('shortenedUrl')
                        entry["tracking_url_2"] = tracking_api_url_2
                        entry["tracking_url_1"] = f"https://study.edumate.life/app/?api=1&token={reused_token}"
                        logger.info("Successfully upgraded legacy token.")
                    else:
                        error_msg = shortx_json.get('message', 'Shortxlinks API Failure')
                        raise Exception(f"Shortxlinks Error during upgrade: {error_msg}")
                except Exception as e:
                    logger.error(f"Failed to upgrade legacy token: {str(e)}")
                    raise e

            # डेटाबेस में अपडेट करें
            collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)
            
            # वेबहुक ट्रिगर (नए फाइनल टोकन के साथ)
            webhook_payload = {
                "auth_token": new_final_token,
                "app_signature": app_signature,
                "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                "expire_time": (date_time_now_obj + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active"
            }
            logger.debug(f"Triggering webhook for reused token. Payload: {webhook_payload}")
            send_webhook_to_server1(webhook_payload)
            
            logger.info("Returning response for reused token.")
            return jsonify({
                "status": "success",
                "url": entry["short_url"], # यह पुराना Arolinks URL ही रहेगा
                "message": "Reused and upgraded expired key"
            }), 200

        # 3. नई की (Key) बनाना (डबल ट्रैकिंग सिस्टम के साथ)
        logger.info("No expired token found for reuse. Generating a brand new key...")
        tracking_token = secrets.token_hex(16)
        final_token = secrets.token_hex(16)

        # --- स्टेप 1: Shortxlinks के लिए api=2 वाला ट्रैकिंग URL बनाना और शॉर्ट करना ---
        tracking_api_url_2 = f"https://study.edumate.life/app/?api=2&token={tracking_token}"
        shortx_api_key = "63b82b926367794c651bd6f1c95acff389ea122d"
        shortx_req_url = f"https://shortxlinks.com/api?api={shortx_api_key}&url={quote(tracking_api_url_2)}&format=json"
        
        logger.info(f"Calling Shortxlinks API with api=2 tracking URL: {shortx_req_url}")
        shortx_response = requests.get(shortx_req_url, headers={'User-Agent': 'Mozilla/5.0'})
        shortx_json = shortx_response.json()
        
        if shortx_json.get('status') == 'success' or 'shortenedUrl' in shortx_json:
            shortx_url = shortx_json.get('shortenedUrl')
            logger.info(f"Successfully created Shortxlinks URL: {shortx_url}")
        else:
            error_msg = shortx_json.get('message', 'Shortxlinks API Failure')
            logger.error(f"Shortxlinks API failed: {error_msg}")
            raise Exception(f"Shortxlinks Error: {error_msg}")

        # --- स्टेप 2: Arolinks के लिए api=1 वाला ट्रैकिंग URL बनाना और शॉर्ट करना ---
        tracking_api_url_1 = f"https://study.edumate.life/app/?api=1&token={tracking_token}"
        aro_req_url = f"https://arolinks.com/api?api={FA_KEY}&url={quote(tracking_api_url_1)}&format=json"
        
        logger.info(f"Calling Arolinks API with api=1 tracking URL: {aro_req_url}")
        aro_response = requests.get(aro_req_url, headers={'User-Agent': 'Mozilla/5.0'})
        aro_json = aro_response.json()

        if aro_json.get('status') == 'success':
            aro_shortened_url = aro_json.get('shortenedUrl')
            logger.info(f"Successfully created Arolinks URL: {aro_shortened_url}")

            # डेटाबेस में सेव करना
            current_data[tracking_token] = {
                "ip": user_ip,
                "app_signature": app_signature,
                "created_at": date_time_now,
                "short_url": aro_shortened_url,             
                "tracking_url_1": tracking_api_url_1,       
                "tracking_url_2": tracking_api_url_2,       
                "shortx_url": shortx_url,                   
                "final_token": final_token,
                "is_tracked_url1": False,                   # नया फ्लैग बायपास चेक के लिए
                "status": "active"
            }

            logger.info("Saving new token data to MongoDB...")
            collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)

            # वेबहुक ट्रिगर
            webhook_payload = {
                "auth_token": final_token,
                "app_signature": app_signature,
                "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                "expire_time": (date_time_now_obj + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active"
            }
            logger.debug(f"Triggering webhook for new token. Payload: {webhook_payload}")
            send_webhook_to_server1(webhook_payload)

            logger.info("Process complete. Returning new key response.")
            return jsonify({
                "status": "success",
                "url": aro_shortened_url, 
                "message": "Generated new key with dual tracking check"
            }), 200
        else:
            error_msg = aro_json.get('message', 'Arolinks API Failure')
            logger.error(f"Arolinks API failed: {error_msg}")
            raise Exception(f"Arolinks Error: {error_msg}")

    except Exception as e:
        logger.exception(f"An unexpected error occurred in handler_app: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 200


@app.route('/auth-Key/check-key/app/', methods=['GET', 'OPTIONS'])
def verify_handler_app():
    # 1. CORS Headers और OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return Response(status=200)

    # ऐप सिग्नेचर हेडर से लेना
    app_signature = request.headers.get('X-SN-Signature')
    if not app_signature:
        return Response("App Signature Missing", status=400, mimetype='text/plain')

    # URL से 'verify' पैरामीटर लेना (जैसे: ?verify=xyz)
    key_to_check = request.args.get('verify')
    if key_to_check:
        key_to_check = key_to_check.strip()

    if not key_to_check:
        return Response("No key provided", status=400, mimetype='text/plain')

    try:
        # --- STEP 1: CHECK UNLIMITED TOKENS FIRST ---
        u_doc = collection.find_one({"_id": APP_UNLIMITED_DB_KEY})
        u_data = u_doc.get("data", {}) if u_doc else {}
        
        if key_to_check in u_data:
            return Response("Authorized", status=200, mimetype='text/plain')

        # --- STEP 2: CHECK STANDARD 24-HOUR TOKENS ---
        doc = collection.find_one({"_id": APP_DB_KEY})
        
        if not doc or "data" not in doc:
            return Response("No Database Found", status=404, mimetype='text/plain')

        data = doc["data"]
        found_entry = None
        
        # JSON डेटा में final_token को ढूँढें
        for tracking_key, entry in data.items():
            if entry.get("final_token") == key_to_check:
                found_entry = entry
                break 

        # अगर final_token डेटाबेस में मिल गया
        if found_entry is not None:
            # --- SIGNATURE MATCH LOGIC ---
            # चेक करें कि सेव किया गया सिग्नेचर भेजे गए सिग्नेचर से मैच करता है या नहीं
            if found_entry.get("app_signature") != app_signature:
                return Response("Signature Mismatch. Key cannot be shared.", status=403, mimetype='text/plain')

            # --- TIME CALCULATION LOGIC ---
            current_time = datetime.now().timestamp()
            created_time = datetime.fromisoformat(found_entry["created_at"]).timestamp()
            
            time_diff_seconds = current_time - created_time
            hours_diff = time_diff_seconds / 3600 

            # Verify Condition (Less than 24 Hours)
            if hours_diff < 24:
                return Response("Authorized", status=200, mimetype='text/plain')
            else:
                return Response("Expired", status=401, mimetype='text/plain')
        else:
            return Response("Invalid Key", status=404, mimetype='text/plain')

    except Exception as e:
        return Response("Server Error: " + str(e), status=500, mimetype='text/plain')


@app.route('/api/get_tokens', methods=['GET', 'OPTIONS'])
def get_tokens_handler():
    # OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return '', 200

    DB_KEY = "tokens_data"

    try:
        # मोंगोडीबी से पूरा डेटा प्राप्त करना
        doc = collection.find_one({"_id": DB_KEY})
        
        # अगर डेटा मौजूद है तो उसे निकालें, वरना खाली डिक्शनरी दें
        all_tokens = doc.get("data", {}) if doc else {}

        # डेटा को बिल्कुल tokens.json की तरह JSON फॉर्मेट में भेजना
        return jsonify(all_tokens), 200

    except Exception as e:
        # किसी भी तरह की एरर आने पर
        return jsonify({ 
            "status": "error", 
            "message": "डेटा लोड करने में समस्या आई: " + str(e) 
        }), 500

@app.route('/api/app/get_tokens', methods=['GET', 'OPTIONS'])
def get_app_tokens_handler():
    # OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return '', 200

    DB_KEY = APP_DB_KEY

    try:
        # मोंगोडीबी से पूरा डेटा प्राप्त करना
        doc = collection.find_one({"_id": DB_KEY})
        
        # अगर डेटा मौजूद है तो उसे निकालें, वरना खाली डिक्शनरी दें
        all_tokens = doc.get("data", {}) if doc else {}

        # डेटा को बिल्कुल tokens.json की तरह JSON फॉर्मेट में भेजना
        return jsonify(all_tokens), 200

    except Exception as e:
        # किसी भी तरह की एरर आने पर
        return jsonify({ 
            "status": "error", 
            "message": "डेटा लोड करने में समस्या आई: " + str(e) 
        }), 500

ALLOWED_REFERERS = ["shortxlinks.com", "arolinks.com"]
FALLBACK_SHORTENER_API_URL = "https://arolinks.com/api"
FALLBACK_SHORTENER_API_KEY = FA_KEY

@app.route('/app/', methods=['GET', 'OPTIONS', 'POST', 'PUT', 'DELETE'])
def app_token_handler12():
    # --- 0. फालतू रिक्वेस्ट ब्लॉक करें (OPTIONS, HEAD आदि) ---
    if request.method == 'OPTIONS':
        resp = make_response('', 204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return resp
        
    if request.method != 'GET':
        return get_html_error_page("Method Not Allowed", "This endpoint only supports GET requests.", "🛑", 405)
        
    if 'favicon.ico' in request.path:
        return make_response('', 204)

    try:
        token = request.args.get('token')
        api_param = request.args.get('api', '1') # अगर api न हो तो डिफ़ॉल्ट 1 मानें

        if not token:
            return get_html_error_page("Invalid Request", "Token is missing from the URL. Please check your link.", "❓", 400)

        # --- आईपी निकालने का लॉजिक (IPv4 को प्राथमिकता) ---
        cf_ip = request.headers.get("CF-Connecting-IP", "")
        xff_ips = request.headers.get("X-Forwarded-For", "")
        
        all_ips = []
        if cf_ip: 
            all_ips.append(cf_ip.strip())
        for ip in xff_ips.split(","):
            if ip.strip(): 
                all_ips.append(ip.strip())

        final_ip = "Unknown IP"
        ipv4 = next((ip for ip in all_ips if "." in ip), None)
        ipv6 = next((ip for ip in all_ips if ":" in ip), None)

        if ipv4:
            final_ip = ipv4
        elif ipv6:
            final_ip = ipv6

        # क्लाउडफ्लेयर हेडर से यूज़र का देश (Country) निकालना
        user_country = request.headers.get("CF-IPCountry", "XX")
        referer = request.headers.get("Referer", "")

        # आज की तारीख निकालें (IST Timezone)
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        d = datetime.now(tz_kolkata)
        today_date = d.strftime('%Y-%m-%d')

        cookie_header = request.headers.get("Cookie", "")
        has_today_cookie = f"visited_date={today_date}" in cookie_header

        # --- स्टेप 1: इंडिया ट्रैफिक चेक ---
        if user_country != "IN" and final_ip != "Unknown IP":
            return get_html_error_page(
                "Access Restricted", 
                "It looks like you are using a VPN or Proxy. Please disable it and try again.", 
                "🌍🚫", 
                403
            )

        # --- स्टेप 2: रिफ़रर चेक (अगर जरूरत हो तो अनकमेंट करें) ---
        is_valid_referer = False
        if referer:
            for allowed in ALLOWED_REFERERS:
                if allowed in referer:
                    is_valid_referer = True
                    break
      #  if not is_valid_referer:
          #  return get_html_error_page("Access Denied", "A bypass detected. Please use the original link.", "🛡️", 403)

        # --- स्टेप 3: DB से वेरिफिकेशन ---
        DB_KEY = APP_DB_KEY
        doc = collection.find_one({"_id": DB_KEY})
        db_data = doc.get("data", {}) if doc else {}
        token_data = db_data.get(token)

        # आईपी मैच चेक
        ip_matches = False
        if token_data and token_data.get("ip"):
            ip_matches = token_data["ip"] in all_ips

        # अगर टोकन नहीं मिला या आईपी मैच नहीं हुआ
        if not token_data or not ip_matches:
            return get_html_error_page("Verification Failed", "Token is invalid, expired, or IP address mismatch. Please generate a new link.", "❌", 403)

        # ==========================================
        # 🌟 नया लॉजिक: पुराने डेटा को ऑन-द-फ्लाई अपडेट करना
        # ==========================================
        
        # अगर डेटाबेस में shortx_url नहीं है, तो उसे अभी जनरेट करें (Legacy Support)
        if "shortx_url" not in token_data:
            tracking_api_url_2 = f"https://study.edumate.life/app/?api=2&token={token}"
            shortx_api_key = "63b82b926367794c651bd6f1c95acff389ea122d"
            shortx_req_url = f"https://shortxlinks.com/api?api={shortx_api_key}&url={quote(tracking_api_url_2)}&format=json"
            
            try:
                shortx_response = requests.get(shortx_req_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=7)
                shortx_json = shortx_response.json()
                
                if shortx_json.get('status') == 'success' or 'shortenedUrl' in shortx_json:
                    token_data["shortx_url"] = shortx_json.get('shortenedUrl')
                    token_data["tracking_url_2"] = tracking_api_url_2
                    
                    # डेटाबेस में नया फॉर्मेट सेव करें
                    db_data[token] = token_data
                    collection.update_one({"_id": DB_KEY}, {"$set": {"data": db_data}})
                else:
                    return get_html_error_page("API Error", "Failed to process legacy token via shortener.", "⚙️", 500)
            except Exception as e:
                return get_html_error_page("System Error", f"Error updating old token: {str(e)}", "⚙️", 500)

        # ==========================================
        # 🌟 डुअल ट्रैकिंग और बायपास प्रिवेंशन 
        # ==========================================
        
        if api_param == '1':
            # यूज़र Arolinks (Step 1) से आया है।
            db_data[token]["is_tracked_url1"] = True
            collection.update_one({"_id": DB_KEY}, {"$set": {"data": db_data}})
            
            next_shortener_url = token_data.get("shortx_url")
            if not next_shortener_url:
                return get_html_error_page("Routing Error", "Next URL not found.", "⚙️", 500)
                
            # यूज़र को तुरंत दूसरे शॉर्टनर (Shortxlinks) पर भेजें
            return redirect(next_shortener_url)

        elif api_param == '2':
            # यूज़र Shortxlinks (Step 2) से आया है।
            # चेक करें कि क्या इसने Step 1 पूरा किया था?
            if not token_data.get("is_tracked_url1"):
                original_start_url = token_data.get("short_url", "#")
                
                # बायपास पकड़े जाने पर एरर पेज दिखाएं और वापस पहले शॉर्टनर पर भेजें
                bypass_html = f"""
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <meta http-equiv="refresh" content="4;url={original_start_url}">
                    <title>Bypass Detected</title>
                    <style>
                        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap');
                        body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: #0f172a; font-family: 'Montserrat', sans-serif; }}
                        .glass-container {{ background: rgba(255, 50, 50, 0.1); backdrop-filter: blur(15px); border: 1px solid rgba(255, 50, 50, 0.3); border-radius: 24px; padding: 40px 50px; text-align: center; color: white; width: 90%; max-width: 400px; box-shadow: 0 10px 30px rgba(255,50,50,0.2); box-sizing: border-box; }}
                        h2 {{ color: #ef4444; margin-bottom: 10px; font-size: 22px; }}
                        p {{ color: #fca5a5; font-size: 14px; line-height: 1.5; }}
                        .loader {{ border: 3px solid rgba(255,255,255,0.1); border-top: 3px solid #ef4444; border-radius: 50%; width: 24px; height: 24px; animation: spin 1s linear infinite; margin: 20px auto 0; }}
                        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
                    </style>
                </head>
                <body>
                    <div class="glass-container">
                        <h2>Bypass Detected 🚨</h2>
                        <p>You skipped a mandatory step. You are being redirected to the original starting link in 3 seconds...</p>
                        <div class="loader"></div>
                    </div>
                </body>
                </html>
                """
                return make_response(bypass_html, 403)
                
            # अगर Step 1 पूरा किया है, तो आगे बढ़ें और फाइनल टोकन दिखाएं
            pass 
        else:
            return get_html_error_page("Invalid API", "Unknown API tracking parameter.", "❓", 400)

        # --- स्टेप 4: स्क्रीन पर फाइनल टोकन दिखाने वाला HTML तैयार करें ---
        final_token = token_data.get("final_token", "Error: Token Not Found")
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your Access Token</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap');
                body, html {{
                    margin: 0; padding: 0; width: 100%; height: 100%; display: flex;
                    align-items: center; justify-content: center; background: #0f172a;
                    font-family: 'Montserrat', sans-serif; overflow: hidden;
                }}
                .blob {{ position: absolute; border-radius: 50%; filter: blur(60px); z-index: 0; animation: float 8s infinite ease-in-out alternate; }}
                .blob-1 {{ width: 300px; height: 300px; background: #3b82f6; top: -100px; left: -100px; }}
                .blob-2 {{ width: 250px; height: 250px; background: #8b5cf6; bottom: -50px; right: -50px; animation-delay: -4s; }}
                
                .glass-container {{
                    position: relative; z-index: 1; background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
                    border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px;
                    padding: 40px 50px; text-align: center; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                    width: 100%; max-width: 350px; box-sizing: border-box;
                }}
                .welcome-text {{ color: #ffffff; font-size: 24px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px; }}
                .sub-text {{ color: #10b981; font-size: 14px; letter-spacing: 1px; margin-bottom: 25px; }}
                
                .key-input {{
                    width: 100%; padding: 12px 15px; border-radius: 8px;
                    border: 1px solid rgba(255, 255, 255, 0.2); background: rgba(0, 0, 0, 0.3);
                    color: #fff; font-size: 16px; outline: none; box-sizing: border-box;
                    font-family: 'Montserrat', sans-serif; text-align: center; letter-spacing: 1px;
                }}
                
                .btn {{
                    width: 100%; padding: 12px; border-radius: 8px; font-size: 14px; font-weight: 600;
                    cursor: pointer; border: none; background: linear-gradient(90deg, #3b82f6, #8b5cf6);
                    color: white; box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3); transition: all 0.3s ease;
                    font-family: 'Montserrat', sans-serif; margin-top: 15px;
                }}
                .btn:hover {{ opacity: 0.9; transform: translateY(-2px); }}
                
                @keyframes float {{
                    0% {{ transform: translate(0, 0) scale(1); }}
                    100% {{ transform: translate(30px, 50px) scale(1.1); }}
                }}
            </style>
        </head>
        <body>
            <div class="blob blob-1"></div>
            <div class="blob blob-2"></div>
            <div class="glass-container">
                <div class="welcome-text">Success ✅</div>
                <div class="sub-text">Verification Complete.</div>
                
                <input type="text" id="token-input" class="key-input" value="{final_token}" readonly>
                <button id="copy-btn" class="btn" onclick="copyToken()">Copy Key</button>
            </div>

            <script>
                function copyToken() {{
                    var copyText = document.getElementById("token-input");
                    copyText.select();
                    copyText.setSelectionRange(0, 99999); /* मोबाइल के लिए */
                    navigator.clipboard.writeText(copyText.value).then(() => {{
                        var btn = document.getElementById("copy-btn");
                        btn.innerText = "Copied! ✅";
                        btn.style.background = "linear-gradient(90deg, #10b981, #059669)";
                        setTimeout(() => {{ 
                            btn.innerText = "Copy Key"; 
                            btn.style.background = "linear-gradient(90deg, #3b82f6, #8b5cf6)";
                        }}, 2500);
                    }});
                }}
            </script>
        </body>
        </html>
        """

        response = make_response(html_content)

        # अगर आज की कुकी नहीं है तो उसे सेट करें
        if not has_today_cookie:
            response.set_cookie('visited_date', today_date, max_age=86400, path='/', httponly=True, samesite='Lax')

        return response

    except Exception as e:
        return get_html_error_page("Server Error", f"Something went wrong: {str(e)}", "⚙️", 500)

@app.route('/', methods=['GET', 'OPTIONS', 'POST', 'PUT', 'DELETE'])
def redirect_handler():
    # --- 0. फालतू रिक्वेस्ट ब्लॉक करें (OPTIONS, HEAD आदि) ---
    if request.method == 'OPTIONS':
        resp = make_response('', 204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return resp
        
    if request.method != 'GET':
        return get_html_error_page("Method Not Allowed", "This endpoint only supports GET requests.", "🛑", 405)
        
    if 'favicon.ico' in request.path:
        return make_response('', 204)

    try:
        token = request.args.get('token')
        if not token:
            return get_html_error_page("Invalid Request", "Token is missing from the URL. Please check your link.", "❓", 400)

        # --- आईपी निकालने का लॉजिक (IPv4 को प्राथमिकता) ---
        cf_ip = request.headers.get("CF-Connecting-IP", "")
        xff_ips = request.headers.get("X-Forwarded-For", "")
        
        all_ips = []
        if cf_ip: 
            all_ips.append(cf_ip.strip())
        for ip in xff_ips.split(","):
            if ip.strip(): 
                all_ips.append(ip.strip())

        final_ip = "Unknown IP"
        ipv4 = next((ip for ip in all_ips if "." in ip), None) # पहले IPv4 ढूँढें
        ipv6 = next((ip for ip in all_ips if ":" in ip), None) # फिर IPv6 ढूँढें

        if ipv4:
            final_ip = ipv4
        elif ipv6:
            final_ip = ipv6

        # क्लाउडफ्लेयर हेडर से यूज़र का देश (Country) निकालना
        user_country = request.headers.get("CF-IPCountry", "XX")
        referer = request.headers.get("Referer", "")

        # आज की तारीख निकालें (IST Timezone)
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        d = datetime.now(tz_kolkata)
        today_date = d.strftime('%Y-%m-%d')

        # कुकी चेक करें
        cookie_header = request.headers.get("Cookie", "")
        has_today_cookie = f"visited_date={today_date}" in cookie_header

        # --- स्टेप 1: इंडिया ट्रैफिक चेक ---
        if user_country != "IN" and final_ip != "Unknown IP":
            return get_html_error_page(
                "Access Restricted", 
                "It looks like you are using a VPN, Proxy. Please disable your VPN or Proxy connection and try again.", 
                "🌍🚫", 
                403
            )

        # --- स्टेप 2: रिफ़रर चेक ---
        is_valid_referer = False
        if referer:
            for allowed in ALLOWED_REFERERS:
                if allowed in referer:
                    is_valid_referer = True
                    break
                    
       # if not is_valid_referer:
          #  return get_html_error_page("Access Denied", "A bypass detected. Please use the original link.", "🛡️", 403)

        # --- स्टेप 3: DB से वेरिफिकेशन (सीधे MongoDB से) ---
        DB_KEY = "tokens_data"
        doc = collection.find_one({"_id": DB_KEY})
        db_data = doc.get("data", {}) if doc else {}
        token_data = db_data.get(token)

        # आईपी मैच चेक
        ip_matches = False
        if token_data and token_data.get("ip"):
            ip_matches = token_data["ip"] in all_ips

        redirect_url = ""
        if not token_data or not ip_matches:
            fallback_url = token_data.get("main_url") if token_data and token_data.get("main_url") else "https://your-default-fallback.com"
            redirect_url = generate_fallback_link(fallback_url, FALLBACK_SHORTENER_API_URL, FALLBACK_SHORTENER_API_KEY)
        else:
            redirect_url = token_data["main_url"]

        # --- स्टेप 4: रिडायरेक्ट रिस्पॉन्स तैयार करें और कुकी सेट करें ---
        response = make_response(redirect(redirect_url, code=302))

        # अगर आज की कुकी नहीं है तो उसे सेट करें
        if not has_today_cookie:
            response.set_cookie('visited_date', today_date, max_age=86400, path='/', httponly=True, samesite='Lax')

        return response

    except Exception as e:
        return get_html_error_page("Server Error", "Something went wrong. Please try again later.", "⚙️", 500)


# =====================================================================
# HELPER FUNCTIONS 
# =====================================================================

def get_html_error_page(title, message, icon="⚠️", status_code=400):
    """
    सभी प्रकार के एरर को सुंदर HTML फॉर्मेट में दिखाने के लिए डायनेमिक फंक्शन।
    """
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8f9fa; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; color: #333; }}
            .container {{ background-color: #fff; padding: 40px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); text-align: center; max-width: 500px; width: 90%; }}
            .icon {{ font-size: 60px; color: #dc3545; margin-bottom: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 15px; color: #212529; }}
            p {{ font-size: 16px; line-height: 1.5; color: #6c757d; margin-bottom: 25px; }}
            .btn {{ background-color: #0d6efd; color: white; border: none; padding: 12px 25px; font-size: 16px; border-radius: 5px; cursor: pointer; text-decoration: none; transition: background-color 0.3s; display: inline-block; }}
            .btn:hover {{ background-color: #0b5ed7; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">{icon}</div>
            <h1>{title}</h1>
            <p>{message}</p>
            <button class="btn" onclick="window.location.reload();">Try Again</button>
        </div>
    </body>
    </html>
    """
    resp = make_response(html, status_code)
    resp.headers['Content-Type'] = 'text/html;charset=UTF-8'
    return resp


def generate_fallback_link(destination_url, api_url, api_key):
    try:
        encoded_url = quote(destination_url)
        request_url = f"{api_url}?api={api_key}&url={encoded_url}&format=json"
        
        response = requests.get(request_url)
        data = response.json()
        
        if data and data.get('status') == 'success' and data.get('shortenedUrl'):
            return data['shortenedUrl']
        return destination_url
    except Exception:
        return destination_url


# जहाँ से मेन JSON डेटा लेना है
DATA_URL = "https://botbuilder-6861.onrender.com/get-file/bot_data.json"

def find_folder(current_node, target_id):
    """
    JSON डेटा के अंदर गहराई तक जाकर सही folder_id को खोजने वाला फंक्शन
    """
    if current_node.get("id") == target_id:
        return current_node
    
    # अगर यह फ़ोल्डर नहीं है, तो इसके अंदर खोजने की ज़रूरत नहीं है
    for item in current_node.get("items", []):
        if item.get("type") == "folder":
            result = find_folder(item, target_id)
            if result:
                return result
                
    return None
@app.route('/api/folders', methods=['GET'])
def get_folders():
    # फ्रंटएंड से folder_id प्राप्त करें, अगर न हो तो 'root' मान लें
    folder_id = request.args.get('folder_id', 'root')
    
    try:
        # बाहरी URL से डेटा लाएँ
        resp = requests.get(DATA_URL)
        raw_data = resp.json()
    except Exception as e:
        return jsonify({"error": "Failed to fetch data from source"}), 500
        
    root_node = raw_data.get("data", {})
    
    # माँगा गया फ़ोल्डर खोजें
    target_folder = find_folder(root_node, folder_id)
    
    # अगर फ़ोल्डर ही नहीं मिला, तो 205 स्टेटस भेजें
    if not target_folder:
        return Response(status=205)
        
    output_data = []
    
    # 1. अगर फ़ोल्डर का कोई डिस्क्रिप्शन है, तो उसे 'description' टाइप के रूप में सबसे ऊपर जोड़ें
    if target_folder.get("description"):
        output_data.append({
            "id": f"desc_{folder_id}",
            "name": f"About {target_folder.get('name', 'This Section')}",
            "type": "description",
            "details": target_folder.get("description")
        })
        
    # 2. अब फ़ोल्डर के अंदर के आइटम्स को प्रोसेस करें (केवल file और folder)
    valid_items_count = 0
    for item in target_folder.get("items", []):
        item_type = item.get("type")
        item_id = item.get("id")
        
        # सिर्फ 'folder' और 'file' को ही अनुमति दें
        if item_type in ["folder", "file"]:
            valid_items_count += 1
            
            # डिटेल्स सेट करें (अगर डिस्क्रिप्शन है तो वो, वरना डिफ़ॉल्ट)
            details = item.get("description")
            if not details:
                if item_type == "folder":
                    inner_items = len(item.get("items", []))
                    details = f"{inner_items} Items inside"
                else:
                    details = item.get("caption", "Document")
                    
            if item_type == "file":
                file_url = item.get("file_url")
                
                # फाइल का बेसिक डेटा
                file_data = {
                    "id": item_id,
                    "name": item.get("name", "Unnamed"),
                    "type": item_type,
                    "details": details
                }
                
                # अगर file_url है (खाली नहीं है), तो उसे सेट करें
                if file_url:
                    file_data["fileUrl"] = file_url
                else:
                    # अगर file_url नहीं है, तो open_url जनरेट करें
                    file_data["fileUrl"] = ""
                    file_data["open_url"] = f"https://t.me/Rajasthan_UniversityBot?start={item_id}"
                    
                output_data.append(file_data)
                
            else:
                output_data.append({
                    "id": item_id,
                    "name": item.get("name", "Unnamed"),
                    "type": item_type,
                    "details": details                
                })
                    
    # अगर फ़ोल्डर में कोई डिस्क्रिप्शन भी नहीं है और कोई file/folder भी नहीं है, तो 205 भेजें
    if valid_items_count == 0 and not target_folder.get("description"):
        return Response(status=205)
        
    return jsonify(output_data)

"""
@app.route('/api/folders', methods=['GET'])
def get_folders():
    # फ्रंटएंड से folder_id प्राप्त करें, अगर न हो तो 'root' मान लें
    folder_id = request.args.get('folder_id', 'root')
    
    try:
        # बाहरी URL से डेटा लाएँ
        resp = requests.get(DATA_URL)
        raw_data = resp.json()
    except Exception as e:
        return jsonify({"error": "Failed to fetch data from source"}), 500
        
    root_node = raw_data.get("data", {})
    
    # माँगा गया फ़ोल्डर खोजें
    target_folder = find_folder(root_node, folder_id)
    
    # अगर फ़ोल्डर ही नहीं मिला, तो 205 स्टेटस भेजें
    if not target_folder:
        return Response(status=205)
        
    output_data = []
    
    # 1. अगर फ़ोल्डर का कोई डिस्क्रिप्शन है, तो उसे 'description' टाइप के रूप में सबसे ऊपर जोड़ें
    if target_folder.get("description"):
        output_data.append({
            "id": f"desc_{folder_id}",
            "name": f"About {target_folder.get('name', 'This Section')}",
            "type": "description",
            "details": target_folder.get("description")
        })
        
    # 2. अब फ़ोल्डर के अंदर के आइटम्स को प्रोसेस करें (केवल file और folder)
    valid_items_count = 0
    for item in target_folder.get("items", []):
        item_type = item.get("type")
        
        # सिर्फ 'folder' और 'file' को ही अनुमति दें
        if item_type in ["folder", "file"]:
            valid_items_count += 1
            
            # डिटेल्स सेट करें (अगर डिस्क्रिप्शन है तो वो, वरना डिफ़ॉल्ट)
            details = item.get("description")
            if not details:
                if item_type == "folder":
                    inner_items = len(item.get("items", []))
                    details = f"{inner_items} Items inside"
                else:
                    details = item.get("caption", "Document")
            if item_type == "file":
                fileUrl =  item.get("file_url", "https://freetestdata.com/wp-content/uploads/2025/04/15-MB.pdf")
                output_data.append({
                "id": item.get("id"),
                "name": item.get("name", "Unnamed"),
                "type": item_type,
                "details": details,
                "fileUrl" : fileUrl
            })
            else:
                output_data.append({
                "id": item.get("id"),
                "name": item.get("name", "Unnamed"),
                "type": item_type,
                "details": details                
            })
                    
            
            
    # अगर फ़ोल्डर में कोई डिस्क्रिप्शन भी नहीं है और कोई file/folder भी नहीं है, तो 205 भेजें
    if valid_items_count == 0 and not target_folder.get("description"):
        return Response(status=205)
        
    return jsonify(output_data)
"""

@app.route('/api/subjects', methods=['GET'])
def get_subjects():
    # डिफ़ॉल्ट रूप से 'root' फ़ोल्डर को पैरेंट मानेंगे, आप इसे URL से बदल भी सकते हैं
    parent_id = request.args.get('parent_id', 'root')
    
    try:
        resp = requests.get(DATA_URL)
        raw_data = resp.json()
    except Exception as e:
        return jsonify({"error": "Failed to fetch data from source"}), 500
        
    root_node = raw_data.get("data", {})
    target_folder = find_folder(root_node, parent_id)
    
    if not target_folder:
        return Response(status=205)
        
    subjects_data = []
    
    for item in target_folder.get("items", []):
        # हम मान रहे हैं कि Subjects फ़ोल्डर के रूप में हैं
        if item.get("type") == "folder":
            subject_name = item.get("name", "Unknown")
            
            # 1. नाम के पहले 3 अक्षर निकालना (बड़े अक्षरों में)
            # अगर नाम 3 अक्षरों से छोटा है तो 'X' जोड़ देंगे (जैसे IT -> ITX)
            prefix = subject_name[:3].upper() if len(subject_name) >= 3 else subject_name.upper().ljust(3, 'X')
            
            # 2. 100-110 और 200-210 के बीच का रैंडम नंबर जनरेट करना
            possible_numbers = list(range(100, 111)) + list(range(200, 211))
            random_num = random.choice(possible_numbers)
            
            # 3. सब्जेक्ट कोड बनाना
            subject_code = f"{prefix}-{random_num}"
            
            subjects_data.append({
                "subject_id": item.get("id"),
                "subject_name": subject_name,
                "subject_code": subject_code,
                "image_url": "https://study.lnkz.tech/default.png"
            })
            
    # अगर उस फ़ोल्डर में कोई विषय नहीं मिला तो 205 स्टेटस भेजें
    if not subjects_data:
        return Response(status=205)
        
    return jsonify(subjects_data)
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
