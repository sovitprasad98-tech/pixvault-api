from flask import Flask, request, jsonify, redirect
import requests
import os
import uuid
import hashlib
import time
import string
import random
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────
#  FIREBASE CONFIG — quicklinkerbd project
# ─────────────────────────────────────────────────────────────────
FIREBASE_API_KEY        = os.environ.get("FIREBASE_API_KEY",        "AIzaSyCivE9gDU1ioOttKwOfdwdv5fv_kouBtS0")
FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "quicklinkerbd.appspot.com")
FIREBASE_DB_URL         = os.environ.get("FIREBASE_DB_URL",         "https://quicklinkerbd-default-rtdb.firebaseio.com")

# ⚠️ Vercel Dashboard → Settings → Environment Variables mein set karo
MASTER_KEY = os.environ.get("MASTER_KEY", "changeme123")
BASE_URL   = os.environ.get("BASE_URL",   "https://pixvault-api-3.vercel.app")


# ─────────────────────────────────────────
#  FIREBASE REALTIME DB HELPERS
# ─────────────────────────────────────────

def db_get(path):
    url = f"{FIREBASE_DB_URL}/{path}.json?auth={FIREBASE_API_KEY}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def db_set(path, data):
    url = f"{FIREBASE_DB_URL}/{path}.json?auth={FIREBASE_API_KEY}"
    try:
        res = requests.put(url, json=data, timeout=10)
        return res.status_code == 200
    except Exception:
        return False

def db_push(path, data):
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
    """Format: PV-XXXX-XXXX-XXXX-XXXX"""
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(random.choices(chars, k=4)) for _ in range(4)]
    return "PV-" + "-".join(parts)

def validate_api_key(key):
    if not key:
        return False, "API key missing"
    data = db_get(f"api_keys/{key.replace('-', '_')}")
    if not data:
        return False, "Invalid API key"
    if not data.get("active", True):
        return False, "API key is disabled"
    return True, data


# ─────────────────────────────────────────
#  URL SHORTENER
# ─────────────────────────────────────────

def generate_short_code(length=7):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

def shorten_url(long_url):
    hash_key = hashlib.md5(long_url.encode()).hexdigest()
    existing = db_get(f"url_map_reverse/{hash_key}")
    if existing:
        return f"{BASE_URL}/i/{existing}"

    code = generate_short_code()
    attempts = 0
    while db_get(f"url_map/{code}") and attempts < 5:
        code = generate_short_code()
        attempts += 1

    db_set(f"url_map/{code}", {
        "url": long_url,
        "created": datetime.utcnow().isoformat(),
        "hits": 0
    })
    db_set(f"url_map_reverse/{hash_key}", code)

    return f"{BASE_URL}/i/{code}"


# ─────────────────────────────────────────
#  FIREBASE STORAGE UPLOAD
# ─────────────────────────────────────────

def upload_to_firebase(file_bytes, filename, content_type):
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    storage_path = f"pixvault/{timestamp}_{unique_id}.{ext}"

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
        "status":  "running",
        "base_url": BASE_URL,
        "project": "quicklinkerbd",
        "endpoints": {
            "upload":       "POST /upload?key=PV-XXXX-XXXX-XXXX-XXXX",
            "redirect":     "GET  /i/{short_code}",
            "generate_key": "POST /admin/generate-key  [X-Master-Key header]",
            "list_keys":    "GET  /admin/keys           [X-Master-Key header]",
            "toggle_key":   "POST /admin/toggle-key     [X-Master-Key header]",
            "stats":        "GET  /stats?key=YOUR_KEY",
        }
    })


# ─── UPLOAD ──────────────────────────────
@app.route("/upload", methods=["POST"])
def upload_image():
    api_key = request.args.get("key") or request.headers.get("X-API-Key")
    valid, key_data = validate_api_key(api_key)
    if not valid:
        return jsonify({"success": False, "error": key_data}), 401

    file_bytes   = None
    filename     = "image.jpg"
    content_type = "image/jpeg"
    allowed      = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}

    if "image" in request.files:
        f = request.files["image"]
        if not f.filename:
            return jsonify({"success": False, "error": "No file selected"}), 400
        if f.content_type not in allowed:
            return jsonify({"success": False, "error": "Only images allowed"}), 400
        file_bytes   = f.read()
        filename     = f.filename
        content_type = f.content_type

    elif request.is_json and request.json.get("url"):
        img_url = request.json["url"]
        try:
            r = requests.get(img_url, timeout=15)
            file_bytes   = r.content
            content_type = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
            filename     = img_url.split("/")[-1].split("?")[0] or "image.jpg"
        except Exception as e:
            return jsonify({"success": False, "error": f"URL fetch failed: {str(e)}"}), 400
    else:
        return jsonify({"success": False, "error": "Send 'image' file OR JSON {\"url\": \"...\"}"}), 400

    if len(file_bytes) > 10 * 1024 * 1024:
        return jsonify({"success": False, "error": "Max file size 10MB"}), 413

    try:
        long_url, storage_path = upload_to_firebase(file_bytes, filename, content_type)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    short_url = shorten_url(long_url)

    safe_key = api_key.replace('-', '_')
    count = db_get(f"api_keys/{safe_key}/upload_count") or 0
    db_set(f"api_keys/{safe_key}/upload_count", count + 1)
    db_set(f"api_keys/{safe_key}/last_used", datetime.utcnow().isoformat())

    db_push(f"uploads/{safe_key}", {
        "filename":     filename,
        "storage_path": storage_path,
        "original_url": long_url,
        "short_url":    short_url,
        "size":         len(file_bytes),
        "uploaded_at":  datetime.utcnow().isoformat()
    })

    return jsonify({
        "success": True,
        "data": {
            "url":          short_url,
            "original_url": long_url,
            "filename":     filename,
            "size":         len(file_bytes),
            "type":         content_type
        }
    }), 200


# ─── URL REDIRECT ────────────────────────
@app.route("/i/<code>", methods=["GET"])
def redirect_url(code):
    data = db_get(f"url_map/{code}")
    if not data:
        return jsonify({"error": "Link not found"}), 404
    db_set(f"url_map/{code}/hits", data.get("hits", 0) + 1)
    return redirect(data["url"], code=302)


# ─── ADMIN: GENERATE KEY ─────────────────
@app.route("/admin/generate-key", methods=["POST"])
def generate_key():
    if request.headers.get("X-Master-Key") != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    body  = request.get_json(silent=True) or {}
    label = body.get("label", "Unnamed")
    note  = body.get("note", "")

    new_key  = generate_api_key()
    safe_key = new_key.replace('-', '_')

    db_set(f"api_keys/{safe_key}", {
        "key":          new_key,
        "label":        label,
        "note":         note,
        "active":       True,
        "upload_count": 0,
        "created":      datetime.utcnow().isoformat(),
        "last_used":    None
    })

    return jsonify({
        "success": True,
        "api_key": new_key,
        "label":   label,
        "message": "API key generated!"
    }), 201


# ─── ADMIN: LIST KEYS ────────────────────
@app.route("/admin/keys", methods=["GET"])
def list_keys():
    if request.headers.get("X-Master-Key") != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    all_keys  = db_get("api_keys") or {}
    keys_list = [
        {
            "key":          v.get("key"),
            "label":        v.get("label"),
            "active":       v.get("active"),
            "upload_count": v.get("upload_count", 0),
            "created":      v.get("created"),
            "last_used":    v.get("last_used")
        }
        for v in all_keys.values()
    ]
    keys_list.sort(key=lambda x: x.get("created", ""), reverse=True)

    return jsonify({"success": True, "total": len(keys_list), "keys": keys_list})


# ─── ADMIN: TOGGLE KEY ───────────────────
@app.route("/admin/toggle-key", methods=["POST"])
def toggle_key():
    if request.headers.get("X-Master-Key") != MASTER_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    body   = request.get_json(silent=True) or {}
    key    = body.get("key")
    active = body.get("active")

    if not key:
        return jsonify({"success": False, "error": "'key' required"}), 400

    safe_key = key.replace('-', '_')
    if not db_get(f"api_keys/{safe_key}"):
        return jsonify({"success": False, "error": "Key not found"}), 404

    db_set(f"api_keys/{safe_key}/active", active)
    return jsonify({
        "success": True,
        "key":     key,
        "active":  active,
        "message": f"Key {'enabled' if active else 'disabled'}"
    })


# ─── STATS ───────────────────────────────
@app.route("/stats", methods=["GET"])
def stats():
    api_key = request.args.get("key") or request.headers.get("X-API-Key")
    valid, key_data = validate_api_key(api_key)
    if not valid:
        return jsonify({"success": False, "error": key_data}), 401

    safe_key    = api_key.replace('-', '_')
    uploads_raw = db_get(f"uploads/{safe_key}") or {}
    uploads     = sorted(
        uploads_raw.values() if isinstance(uploads_raw, dict) else [],
        key=lambda x: x.get("uploaded_at", ""), reverse=True
    )

    return jsonify({
        "success":        True,
        "label":          key_data.get("label", "Unknown"),
        "upload_count":   key_data.get("upload_count", 0),
        "last_used":      key_data.get("last_used"),
        "recent_uploads": uploads[:10]
    })


# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
