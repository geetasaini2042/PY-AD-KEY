from flask import Flask, request, jsonify, Response, redirect, make_response
from flask_cors import CORS
import requests
import secrets
from datetime import datetime
import pytz
from pymongo import MongoClient
from urllib.parse import quote, urlparse
import os
import random

# --- 1. कॉन्फ़िगरेशन (Configuration) ---
app = Flask(__name__)
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
@app.route('/auth-Key/generate-token/app1/', methods=['GET', 'POST', 'OPTIONS'])
def handler_app1():
    # OPTIONS रिक्वेस्ट के लिए 200 स्टेटस लौटाएं
    if request.method == 'OPTIONS':
        return '', 200

    try:
        # ऐप सिग्नेचर हेडर से लेना
        app_signature = request.headers.get('X-App-Signature')
        if not app_signature:
            return jsonify({
                "status": "error",
                "message": "App Signature is missing"
            }), 400

        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
            
        current_time = datetime.now().timestamp()

        # मोंगोडीबी से डेटा पढ़ना
        doc = collection.find_one({"_id": DB_KEY})
        current_data = doc.get("data", {}) if doc else {}

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        
        # 1. चेक करें कि क्या यूज़र (उसी ऐप सिग्नेचर) की कोई एक्टिव की (Key) है (24 घंटे से कम पुरानी)
        for token, entry in current_data.items():
            if entry.get("app_signature") == app_signature:
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
                entry["app_signature"] = app_signature # नया सिग्नेचर अपडेट करें
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
                "app_signature": app_signature, # सिग्नेचर डेटाबेस में सेव करें
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
"""        
@app.route('/auth-Key/generate-token/app/', methods=['GET', 'POST', 'OPTIONS'])
def handler_app():
    # OPTIONS रिक्वेस्ट के लिए 200 स्टेटस लौटाएं
    if request.method == 'OPTIONS':
        return '', 200

    try:
        # ऐप सिग्नेचर हेडर से लेना
        app_signature = request.headers.get('X-App-Signature')
        if not app_signature:
            return jsonify({
                "status": "error",
                "message": "App Signature is missing"
            }), 400

        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
            
        current_time = datetime.now().timestamp()

        # मोंगोडीबी से डेटा पढ़ना
        doc = collection.find_one({"_id": DB_KEY})
        current_data = doc.get("data", {}) if doc else {}

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        
        # 1. चेक करें कि क्या यूज़र (उसी ऐप सिग्नेचर) की कोई एक्टिव की (Key) है (24 घंटे से कम पुरानी)
        for token, entry in current_data.items():
            if entry.get("app_signature") == app_signature:
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
                entry["app_signature"] = app_signature # नया सिग्नेचर अपडेट करें
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

        tracking_api_url = f"https://key.lnkz.tech/app/?token={tracking_token}"
        api_url = f"https://arolinks.com/api?api={FA_KEY}&url={quote(tracking_api_url)}&format=json"
        
        api_response = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        json_response = api_response.json()

        if json_response.get('status') == 'success':
            shortened_url = json_response.get('shortenedUrl')

            current_data[tracking_token] = {
                "ip": user_ip,
                "app_signature": app_signature, # सिग्नेचर डेटाबेस में सेव करें
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

@app.route('/auth-Key/check-key/app/', methods=['GET', 'OPTIONS'])
def verify_handler_app():
    # 1. CORS Headers और OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return Response(status=200)

    # ऐप सिग्नेचर हेडर से लेना
    app_signature = request.headers.get('X-App-Signature')
    if not app_signature:
        return Response("App Signature Missing", status=400, mimetype='text/plain')

    # URL से 'verify' पैरामीटर लेना (जैसे: ?verify=xyz)
    key_to_check = request.args.get('verify')
    if key_to_check:
        key_to_check = key_to_check.strip()

    if not key_to_check:
        return Response("No key provided", status=400, mimetype='text/plain')

    # Database Keys
    DB_KEY = "tokens_data" 
    UNLIMITED_DB_KEY = "unlimited_tokens_data" 

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
"""
@app.route('/auth-Key/generate-token/app/', methods=['GET', 'POST', 'OPTIONS'])
def handler_app():
    # OPTIONS रिक्वेस्ट के लिए 200 स्टेटस लौटाएं
    if request.method == 'OPTIONS':
        return '', 200

    # ऐप के लिए अलग डेटाबेस की (Key)
    APP_DB_KEY = "app_tokens_data"

    try:
        # ऐप सिग्नेचर हेडर से लेना
        app_signature = request.headers.get('X-App-Signature')
        if not app_signature:
            return jsonify({
                "status": "error",
                "message": "App Signature is missing"
            }), 400

        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
        if ',' in user_ip:
            user_ip = user_ip.split(',')[0].strip()
            
        current_time = datetime.now().timestamp()

        # मोंगोडीबी से ऐप का डेटा पढ़ना (अब यह अलग डेटाबेस नाम का उपयोग करेगा)
        doc = collection.find_one({"_id": APP_DB_KEY})
        current_data = doc.get("data", {}) if doc else {}

        tz_kolkata = pytz.timezone('Asia/Kolkata')
        
        # 1. चेक करें कि क्या यूज़र (उसी ऐप सिग्नेचर) की कोई एक्टिव की (Key) है (24 घंटे से कम पुरानी)
        for token, entry in current_data.items():
            if entry.get("app_signature") == app_signature:
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
                entry["app_signature"] = app_signature # नया सिग्नेचर अपडेट करें
                entry["created_at"] = date_time_now
                entry["status"] = "active"
                reused_token = token
                break

        # अगर पुरानी की रीयूज़ हो गई है
        if reused_token:
            collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)
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

        tracking_api_url = f"https://key.lnkz.tech/app/?token={tracking_token}"
        api_url = f"https://arolinks.com/api?api={FA_KEY}&url={quote(tracking_api_url)}&format=json"
        
        api_response = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        json_response = api_response.json()

        if json_response.get('status') == 'success':
            shortened_url = json_response.get('shortenedUrl')

            current_data[tracking_token] = {
                "ip": user_ip,
                "app_signature": app_signature, # सिग्नेचर डेटाबेस में सेव करें
                "created_at": date_time_now,
                "short_url": shortened_url,
                "tracking_url": tracking_api_url,
                "main_url": main_website_url,
                "final_token": final_token,
                "status": "active"
            }

            # मोंगोडीबी में डेटा सेव करना (नए APP_DB_KEY के साथ)
            collection.update_one({"_id": APP_DB_KEY}, {"$set": {"data": current_data}}, upsert=True)

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

@app.route('/auth-Key/check-key/app/', methods=['GET', 'OPTIONS'])
def verify_handler_app():
    # 1. CORS Headers और OPTIONS रिक्वेस्ट को हैंडल करना
    if request.method == 'OPTIONS':
        return Response(status=200)

    # ऐप सिग्नेचर हेडर से लेना
    app_signature = request.headers.get('X-App-Signature')
    if not app_signature:
        return Response("App Signature Missing", status=400, mimetype='text/plain')

    # URL से 'verify' पैरामीटर लेना (जैसे: ?verify=xyz)
    key_to_check = request.args.get('verify')
    if key_to_check:
        key_to_check = key_to_check.strip()

    if not key_to_check:
        return Response("No key provided", status=400, mimetype='text/plain')

    # ऐप के लिए अलग डेटाबेस कीज़ (Database Keys)
    APP_DB_KEY = "app_tokens_data" 
    APP_UNLIMITED_DB_KEY = "app_unlimited_tokens_data" 

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

        # --- स्टेप 2: रिफ़रर चेक ---
        is_valid_referer = False
        
        if referer:
            for allowed in ALLOWED_REFERERS:
                if allowed in referer:
                    is_valid_referer = True
                    break
                    
      #  if not is_valid_referer:
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

        # अगर टोकन नहीं मिला या आईपी मैच नहीं हुआ
        if not token_data or not ip_matches:
            return get_html_error_page("Verification Failed", "Token is invalid, expired, or IP address mismatch. Please generate a new link.", "❌", 403)

        # फाइनल टोकन (App के लिए) निकालें
        final_token = token_data.get("final_token", "Error: Token Not Found")

        # --- स्टेप 4: स्क्रीन पर टोकन दिखाने वाला HTML तैयार करें ---
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
                    width: 100%; max-width: 350px;
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
                    
        if not is_valid_referer:
            return get_html_error_page("Access Denied", "A bypass detected. Please use the original link.", "🛡️", 403)

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
