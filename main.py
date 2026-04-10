from flask import Flask, request, jsonify
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
