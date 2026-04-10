from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import secrets
from datetime import datetime
import pytz
from pymongo import MongoClient
from urllib.parse import quote, urlparse
import os

app = Flask(__name__)
# CORS हैंडलिंग
CORS(app, resources={r"/*": {"origins": "*"}})

# मोंगोडीबी यूआरआई (आप इसे एनवायरनमेंट वेरिएबल के रूप में सेट कर सकते हैं)
DT_MON = os.getenv("DT_MON", "mongodb://localhost:27017/") 
API_KEY = os.getenv("API_KEY", "") 
client = MongoClient(DT_MON)
db = client['tokens_database']
collection = db['kv_store']
DB_KEY = "tokens_data"

@app.route('/api/handler', methods=['GET', 'POST', 'OPTIONS'])
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

        tracking_api_url = f"https://w.lnkz.tech/?token={tracking_token}"
        api_url = f"https://shortxlinks.com/api?api={API_KEY}&url={quote(tracking_api_url)}&format=json"
        
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

@app.route('/api/verify', methods=['GET', 'OPTIONS'])
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
