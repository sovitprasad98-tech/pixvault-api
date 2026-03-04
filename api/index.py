from flask import Flask, request, jsonify, redirect
import requests
import os
import uuid
import hashlib
import json
import time
import string
import random
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────
#  FIREBASE CONFIG — quicklinkerbd project
#  (Vercel env vars set hain to woh override karenge, warna
#   neeche diye default values use honge)
# ─────────────────────────────────────────────────────────────────
FIREBASE_API_KEY        = os.environ.get("FIREBASE_API_KEY",        "AIzaSyCivE9gDU1ioOttKwOfdwdv5fv_kouBtS0")
FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "quicklinkerbd.appspot.com")
FIREBASE_DB_URL         = os.environ.get("FIREBASE_DB_URL",         "https://quicklinkerbd-default-rtdb.firebaseio.com")

# ⚠️  In dono ko Vercel Dashboard me zaroor set karna!
MASTER_KEY = os.environ.get("MASTER_KEY", "changeme123")
BASE_URL   = os.environ.get("BASE_URL",   "https://pixvault-api-2.vercel.app")

# ─────────────────────────────────────────
#  FIREBASE REALTIME DB HELPERS
# ─────────────────────────────────────────

def db_get(path):
    """Firebase Realtime DB se data read karo"""
    url = f"{FIREBASE_DB_URL}/{path}.json?auth={FIREBASE_API_KEY}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def db_set(path, data):
    """Firebase Realtime DB mein data write karo"""
    url = f"{FIREBASE_DB_URL}/{path}.json?auth={FIREBASE_API_KEY}"
    try:
        res = requests.put(url, json=data, timeout=10)
        return res.status_code == 200
    except Exception:
        return False

def db_push(path, data):
    """Firebase Realtime DB mein new entry push karo"""
    url = f"{FIREBASE_DB_URL}/{path}.json?auth={FIREBASE_API_KEY}"
    try:
        res = requests.post(url, json=data, timeout=10)
        return res.json().get("name") if res.status_code == 200 else None
    except Exception:
        return None

# ─────────────────────────────────────────
#  API KEY HELPERS
# ─────────────────────────────────────────

def generate_api_key():
    """16-digit unique API key generate karo: PV-XXXX-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(random.choices(chars, k=4))
    part2 = ''.join(random.choices(chars, k=4))
    part3 = ''.join(random.choices(chars, k=4))
    part4 = ''.join(random.choices(chars, k=4))
    return f"PV-{part1}-{part2}-{part3}-{part4}"

def validate_api_key(key):
    """API key valid hai ya nahi check karo"""
    if not key:
        return False, "API key missing"
    data = db_get(f"api_keys/{key.replace('-', '_')}")
    if not data:
        return False, "Invalid API key"
    if not data.get("active", True):
        return False, "API key disabled"
    return True, data

# ─────────────────────────────────────────
#  URL SHORTENER HELPERS
# ─────────────────────────────────────────

def generate_short_code(length=7):
    """Random short code generate karo"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

def shorten_url(long_url, custom_code=None):
    """URL ko short karo aur DB mein save karo"""
    # Check karo agar URL already short hai
    existing = db_get(f"url_map_reverse/{hashlib.md5(long_url.encode()).hexdigest()}")
    if existing:
        return f"{BASE_URL}/i/{existing}"
    
    # New short code banao
    code = custom_code or generate_short_code()
    
    # Collision check
    attempts = 0
    while db_get(f"url_map/{code}") and attempts < 5:
        code = generate_short_code()
        attempts += 1

    # DB mein save karo
    db_set(f"url_map/{code}", {
        "url": long_url,
        "created": datetime.utcnow().isoformat(),
        "hits": 0
    })
    
    # Reverse map (URL → code) for dedup
    db_set(f"url_map_reverse/{hashlib.md5(long_url.encode()).hexdigest()}", code)
    
    return f"{BASE_URL}/i/{code}"

# ─────────────────────────────────────────
#  FIREBASE STORAGE UPLOAD
# ─────────────────────────────────────────

def upload_to_firebase(file_bytes, filename, content_type):
    """Firebase Storage mein image upload karo"""
    # Unique path banao
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    storage_path = f"pixvault/{timestamp}_{unique_id}.{ext}"
    
    # Firebase Storage REST API
    upload_url = (
        f"https://firebasestorage.googleapis.com/v0/b/"
        f"{FIREBASE_STORAGE_BUCKET}/o"
        f"?uploadType=media"
        f"&name={requests.utils.quote(storage_path, safe='')}"
    )
    
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(file_bytes))
    }
    
    res = requests.post(upload_url, data=file_bytes, headers=headers, timeout=30)
    
    if res.status_code not in [200, 201]:
        raise Exception(f"Firebase upload failed: {res.text}")
    
    data = res.json()
    
    # Public download URL banao
    encoded_name = requests.utils.quote(storage_path, safe='')
    download_url = (
        f"https://firebasestorage.googleapis.com/v0/b/"
        f"{FIREBASE_STORAGE_BUCKET}/o/{encoded_name}"
        f"?alt=media&token={data.get('downloadTokens', '')}"
    )
    
    return download_url, storage_path

# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "PixVault Image API",
        "version": "1.0",
        "endpoints": {
            "upload":       "POST /upload?key=YOUR_API_KEY",
            "redirect":     "GET  /i/{short_code}",
            "generate_key": "POST /admin/generate-key  (Master Key required)",
            "list_keys":    "GET  /admin/keys           (Master Key required)",
            "toggle_key":   "POST /admin/toggle-key     (Master Key required)",
            "stats":        "GET  /stats?key=YOUR_API_KEY",
        },
        "docs": "https://github.com/YOUR_USERNAME/pixvault-api"
    })


# ─── MAIN UPLOAD ENDPOINT ────────────────
@app.route("/upload", methods=["POST"])
def upload_image():
    """
    POST /upload?key=PV-XXXX-XXXX-XXXX-XXXX
    Body: multipart/form-data  → field name: 'image'
       OR JSON                 → { "url": "https://..." }  (URL se upload)
    """
    api_key = request.args.get("key") or request.headers.get("X-API-Key")
    
    # API Key validate karo
    valid, key_data = validate_api_key(api_key)
    if not valid:
        return jsonify({"success": False, "error": key_data}), 401

    file_bytes = None
    filename = "image.jpg"
    content_type = "image/jpeg"

    # ── Option 1: File upload ──
    if "image" in request.files:
        f = request.files["image"]
        if f.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}
        if f.content_type not in allowed:
            return jsonify({"success": False, "error": "Only images allowed (JPEG, PNG, GIF, WEBP, SVG)"}), 400
        
        file_bytes = f.read()
        filename = f.filename
        content_type = f.content_type

    # ── Option 2: URL se fetch karke upload ──
    elif request.is_json and request.json.get("url"):
        img_url = request.json["url"]
        try:
            r = requests.get(img_url, timeout=15)
            file_bytes = r.content
            content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
            filename = img_url.split("/")[-1].split("?")[0] or "image.jpg"
        except Exception as e:
            return jsonify({"success": False, "error": f"Could not fetch URL: {str(e)}"}), 400
    
    else:
        return jsonify({"success": False, "error": "Send 'image' file or JSON {url: ...}"}), 400

    # File size check (10MB limit)
    if len(file_bytes) > 10 * 1024 * 1024:
        return jsonify({"success": False, "error": "File too large. Max 10MB"}), 413

    # Firebase mein upload karo
    try:
        long_url, storage_path = upload_to_firebase(file_bytes, filename, content_type)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # URL short karo
    short_url = shorten_url(long_url)

    # Stats update karo
    safe_key = api_key.replace('-', '_')
    count = db_get(f"api_keys/{safe_key}/upload_count") or 0
    db_set(f"api_keys/{safe_key}/upload_count", count + 1)
    db_set(f"api_keys/{safe_key}/last_used", datetime.utcnow().isoformat())

    # Upload log save karo
    db_push(f"uploads/{safe_key}", {
        "filename": filename,
        "storage_path": storage_path,
        "original_url": long_url,
        "short_url": short_url,
        "size": len(file_bytes),
        "uploaded_at": datetime.utcnow().isoformat()
    })

    return jsonify({
        "success": True,
        "data": {
            "url": short_url,           # Short URL (use this!)
            "original_url": long_url,   # Full Firebase URL
            "filename": filename,
            "size": len(file_bytes),
            "type": content_type
        }
    }), 200


# ─── URL REDIRECT ────────────────────────
@app.route("/i/<code>", methods=["GET"])
def redirect_url(code):
    """GET /i/abc1234  →  Firebase Storage URL pe redirect"""
    data = db_get(f"url_map/{code}")
    
    if not data:
        return jsonify({"error": "Link not found or expired"}), 404
    
    # Hit count badhao
    hits = data.get("hits", 0) + 1
    db_set(f"url_map/{code}/hits", hits)
    
    return redirect(data["url"], code=302)


# ─── ADMIN: API KEY GENERATE ─────────────
@app.route("/admin/generate-key", methods=["POST"])
def generate_key():
    """
    POST /admin/generate-key
    Headers: X-Master-Key: your_master_key
    Body JSON: { "label": "My App", "note": "optional" }
    """
    master = request.headers.get("X-Master-Key")
    if master != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    body = request.get_json(silent=True) or {}
    label = body.get("label", "Unnamed")
    note  = body.get("note", "")
    
    new_key = generate_api_key()
    safe_key = new_key.replace('-', '_')
    
    db_set(f"api_keys/{safe_key}", {
        "key": new_key,
        "label": label,
        "note": note,
        "active": True,
        "upload_count": 0,
        "created": datetime.utcnow().isoformat(),
        "last_used": None
    })
    
    return jsonify({
        "success": True,
        "api_key": new_key,
        "label": label,
        "message": "API key generated successfully!"
    }), 201


# ─── ADMIN: LIST ALL KEYS ─────────────────
@app.route("/admin/keys", methods=["GET"])
def list_keys():
    master = request.headers.get("X-Master-Key")
    if master != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    all_keys = db_get("api_keys") or {}
    
    keys_list = []
    for safe_key, data in all_keys.items():
        keys_list.append({
            "key": data.get("key"),
            "label": data.get("label"),
            "note": data.get("note"),
            "active": data.get("active"),
            "upload_count": data.get("upload_count", 0),
            "created": data.get("created"),
            "last_used": data.get("last_used")
        })
    
    return jsonify({
        "success": True,
        "total": len(keys_list),
        "keys": sorted(keys_list, key=lambda x: x.get("created", ""), reverse=True)
    })


# ─── ADMIN: ENABLE/DISABLE KEY ───────────
@app.route("/admin/toggle-key", methods=["POST"])
def toggle_key():
    """
    POST /admin/toggle-key
    Body: { "key": "PV-XXXX-XXXX-XXXX-XXXX", "active": false }
    """
    master = request.headers.get("X-Master-Key")
    if master != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    body = request.get_json(silent=True) or {}
    key  = body.get("key")
    active = body.get("active")
    
    if not key:
        return jsonify({"success": False, "error": "key required"}), 400
    
    safe_key = key.replace('-', '_')
    data = db_get(f"api_keys/{safe_key}")
    
    if not data:
        return jsonify({"success": False, "error": "Key not found"}), 404
    
    db_set(f"api_keys/{safe_key}/active", active)
    
    return jsonify({
        "success": True,
        "key": key,
        "active": active,
        "message": f"Key {'enabled' if active else 'disabled'} successfully"
    })


# ─── STATS ────────────────────────────────
@app.route("/stats", methods=["GET"])
def stats():
    api_key = request.args.get("key") or request.headers.get("X-API-Key")
    
    valid, key_data = validate_api_key(api_key)
    if not valid:
        return jsonify({"success": False, "error": key_data}), 401
    
    safe_key = api_key.replace('-', '_')
    uploads = db_get(f"uploads/{safe_key}") or {}
    
    upload_list = list(uploads.values()) if isinstance(uploads, dict) else []
    upload_list.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    
    return jsonify({
        "success": True,
        "label": key_data.get("label", "Unknown"),
        "upload_count": key_data.get("upload_count", 0),
        "last_used": key_data.get("last_used"),
        "recent_uploads": upload_list[:10]
    })


# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
