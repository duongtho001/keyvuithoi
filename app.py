"""
License Server - Flask Web Application
Deploy this to any hosting (Render, Railway, VPS, etc.)

CONFIGURATION (Environment Variables):
- SECRET_KEY: Key for license generation
- ADMIN_USERNAME: Admin login username (default: admin)
- ADMIN_PASSWORD: Admin login password (default: admin123)
- USE_GOOGLE_SHEETS: Set to 'true' to use Google Sheets instead of SQLite
- GOOGLE_SHEET_ID: ID of Google Sheet (from URL)
- GOOGLE_SERVICE_ACCOUNT_JSON: Service account credentials JSON
"""
from flask import Flask, request, jsonify, render_template_string, session, redirect
from flask_cors import CORS
import sqlite3
import os
import hashlib
import base64
import json
import time
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret-key-in-production")

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": f"Internal Server Error: {str(error)}"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"success": False, "error": f"Exception: {str(e)}"}), 500


# Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "VFX_SECRET_2024_THOTOOL")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
# Use /tmp for database on Vercel/Serverless to avoid Read-Only error
DATABASE = os.path.join("/tmp", "licenses.db") if os.environ.get("VERCEL") else os.environ.get("DATABASE", "licenses.db")

# Google Sheets Configuration
USE_GOOGLE_SHEETS = os.environ.get("USE_GOOGLE_SHEETS", "false").lower() == "true"
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# ============= GOOGLE SHEETS BACKEND =============

gspread_client = None

def init_google_sheets():
    """Initialize Google Sheets connection."""
    global gspread_client
    if not USE_GOOGLE_SHEETS or not GOOGLE_SHEET_ID:
        return False
    
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        if GOOGLE_CREDS_JSON:
            creds_dict = json.loads(GOOGLE_CREDS_JSON)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            # Try local file
            creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        
        gspread_client = gspread.authorize(creds)
        print("✅ Google Sheets connected!")
        return True
    except Exception as e:
        print(f"❌ Google Sheets error: {e}")
        return False

def get_sheet():
    """Get the Google Sheet worksheet."""
    global gspread_client
    if not gspread_client:
        init_google_sheets()
    
    if gspread_client:
        sheet = gspread_client.open_by_key(GOOGLE_SHEET_ID)
        try:
            worksheet = sheet.worksheet("Licenses")
        except:
            worksheet = sheet.add_worksheet(title="Licenses", rows=1000, cols=10)
            worksheet.append_row(["device_id", "license_key", "expiry_date", "status", "customer_name", "notes", "created_at"])
        return worksheet
    return None

def sheets_list_licenses():
    """List all licenses from Google Sheets."""
    ws = get_sheet()
    if not ws:
        return []
    
    records = ws.get_all_records()
    licenses = []
    for i, row in enumerate(records, start=2):
        licenses.append({
            "id": i,
            "device_id": row.get("device_id", ""),
            "license_key": row.get("license_key", ""),
            "expiry_date": row.get("expiry_date", ""),
            "status": row.get("status", "active"),
            "customer_name": row.get("customer_name", ""),
            "notes": row.get("notes", ""),
            "created_at": row.get("created_at", "")
        })
    return licenses

def sheets_find_license(device_id):
    """Find a license by device ID in Google Sheets."""
    ws = get_sheet()
    if not ws:
        return None, -1
    
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if row.get("device_id", "")[:8].upper() == device_id[:8].upper():
            return row, i
    return None, -1

def sheets_add_license(data):
    """Add a license to Google Sheets."""
    ws = get_sheet()
    if not ws:
        return False
    
    # Check if exists
    existing, _ = sheets_find_license(data.get("device_id", ""))
    if existing:
        return False
    
    ws.append_row([
        data.get("device_id", "").upper(),
        data.get("license_key", ""),
        data.get("expiry_date", ""),
        data.get("status", "active"),
        data.get("customer_name", ""),
        data.get("notes", ""),
        datetime.now().isoformat()
    ])
    return True

def sheets_update_license(device_id, updates):
    """Update a license in Google Sheets."""
    ws = get_sheet()
    if not ws:
        return False
    
    row, row_num = sheets_find_license(device_id)
    if not row:
        return False
    
    # Column mapping
    col_map = {"device_id": 1, "license_key": 2, "expiry_date": 3, "status": 4, "customer_name": 5, "notes": 6}
    
    for key, col in col_map.items():
        if key in updates:
            ws.update_cell(row_num, col, updates[key])
    
    return True

def sheets_delete_license(device_id):
    """Delete a license from Google Sheets."""
    ws = get_sheet()
    if not ws:
        return False
    
    _, row_num = sheets_find_license(device_id)
    if row_num < 0:
        return False
    
    ws.delete_rows(row_num)
    return True

# ============= SQLITE DATABASE =============

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables."""
    if USE_GOOGLE_SHEETS:
        init_google_sheets()
        return
    
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            license_key TEXT,
            expiry_date TEXT,
            status TEXT DEFAULT 'active',
            customer_name TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Initialize on startup (Wrapped to prevent Vercel boot loop 500s)
STARTUP_ERROR = None
try:
    init_db()
except Exception as e:
    STARTUP_ERROR = f"Startup Error: {e}"
    print(STARTUP_ERROR)

# ============= LICENSE GENERATION =============

def generate_license_key(device_id, days=30):
    """Generate a license key for a device."""
    expiry_timestamp = int(time.time()) + (days * 24 * 60 * 60)
    
    payload = {
        "d": device_id[:8].upper(),
        "e": expiry_timestamp,
        "v": 1
    }
    
    payload_str = json.dumps(payload, separators=(',', ':'))
    check_str = payload_str + SECRET_KEY
    checksum = hashlib.md5(check_str.encode()).hexdigest()[:8]
    
    final_data = payload_str + "|" + checksum
    encoded = base64.b64encode(final_data.encode()).decode()
    encoded = encoded.replace('=', '').replace('+', 'P').replace('/', 'S')
    
    while len(encoded) % 4 != 0:
        encoded += 'X'
    
    parts = [encoded[i:i+4] for i in range(0, len(encoded), 4)]
    return '-'.join(parts[:5]).upper()

# ============= AUTH =============

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check session
        if session.get('logged_in'):
            return f(*args, **kwargs)
        
        # Check Authorization header
        auth = request.headers.get('Authorization', '')
        if auth == f"Bearer {ADMIN_PASSWORD}":
            return f(*args, **kwargs)
        
        # Check query param
        if request.args.get('token') == ADMIN_PASSWORD:
            return f(*args, **kwargs)
        
        return jsonify({"error": "Unauthorized"}), 401
    return decorated

@app.route('/api/login', methods=['POST'])
def login():
    """Login endpoint."""
    data = request.json or {}
    username = data.get('username', '')
    password = data.get('password', '')
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['logged_in'] = True
        session['username'] = username
        return jsonify({"success": True, "message": "Đăng nhập thành công!"})
    
    return jsonify({"success": False, "error": "Sai tài khoản hoặc mật khẩu"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout endpoint."""
    session.clear()
    return jsonify({"success": True})

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    """Check if user is logged in."""
    if session.get('logged_in'):
        return jsonify({"logged_in": True, "username": session.get('username')})
    if session.get('logged_in'):
        return jsonify({"logged_in": True, "username": session.get('username')})
    return jsonify({"logged_in": False})

@app.route('/api/debug', methods=['GET'])
def debug_info():
    """Debug server status."""
    return jsonify({
        "status": "online",
        "startup_error": STARTUP_ERROR,
        "database_path": DATABASE,
        "use_google_sheets": USE_GOOGLE_SHEETS,
        "has_sheet_id": bool(GOOGLE_SHEET_ID),
        "has_credentials": bool(GOOGLE_CREDS_JSON),
        "env_vercel": bool(os.environ.get("VERCEL"))
    })

# ============= SETTINGS API =============

SETTINGS_FILE = "server_settings.json"

def load_settings():
    """Load settings from file."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_settings(settings):
    """Save settings to file."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except:
        return False

def get_sheets_config():
    """Get Google Sheets config from settings or env."""
    settings = load_settings()
    return {
        "use_sheets": settings.get("use_sheets", USE_GOOGLE_SHEETS),
        "sheet_id": settings.get("sheet_id", GOOGLE_SHEET_ID),
        "credentials": settings.get("credentials", "")
    }

@app.route('/api/settings', methods=['GET'])
@require_admin
def get_settings():
    """Get current settings."""
    settings = load_settings()
    # Don't expose full credentials, just show if configured
    has_creds = bool(settings.get("credentials") or GOOGLE_CREDS_JSON)
    return jsonify({
        "use_sheets": settings.get("use_sheets", USE_GOOGLE_SHEETS),
        "sheet_id": settings.get("sheet_id", GOOGLE_SHEET_ID),
        "has_credentials": has_creds,
        "sheets_connected": gspread_client is not None
    })

@app.route('/api/settings', methods=['POST'])
@require_admin
def update_settings():
    """Update settings."""
    global USE_GOOGLE_SHEETS, GOOGLE_SHEET_ID, GOOGLE_CREDS_JSON, gspread_client
    
    data = request.json or {}
    settings = load_settings()
    
    if 'use_sheets' in data:
        settings['use_sheets'] = data['use_sheets']
        USE_GOOGLE_SHEETS = data['use_sheets']
    
    if 'sheet_id' in data:
        settings['sheet_id'] = data['sheet_id']
        GOOGLE_SHEET_ID = data['sheet_id']
    
    if 'credentials' in data and data['credentials']:
        settings['credentials'] = data['credentials']
        GOOGLE_CREDS_JSON = data['credentials']
    
    save_settings(settings)
    
    # Reinitialize Google Sheets if enabled
    if USE_GOOGLE_SHEETS:
        gspread_client = None  # Reset
        success = init_google_sheets_from_settings()
        return jsonify({
            "success": True, 
            "message": "Đã lưu! " + ("Google Sheets đã kết nối." if success else "Chưa kết nối được Google Sheets.")
        })
    
    return jsonify({"success": True, "message": "Đã lưu cài đặt!"})

@app.route('/api/settings/test-sheets', methods=['POST'])
@require_admin
def test_sheets_connection():
    """Test Google Sheets connection."""
    global gspread_client
    
    config = get_sheets_config()
    if not config['sheet_id']:
        return jsonify({"success": False, "error": "Chưa có Sheet ID"})
    
    gspread_client = None
    success = init_google_sheets_from_settings()
    
    if success:
        return jsonify({"success": True, "message": "Kết nối Google Sheets thành công!"})
    else:
        return jsonify({"success": False, "error": "Không thể kết nối. Kiểm tra lại thông tin."})

def init_google_sheets_from_settings():
    """Initialize Google Sheets from saved settings."""
    global gspread_client, USE_GOOGLE_SHEETS, GOOGLE_SHEET_ID, GOOGLE_CREDS_JSON
    
    settings = load_settings()
    sheet_id = settings.get("sheet_id") or GOOGLE_SHEET_ID
    creds_json = settings.get("credentials") or GOOGLE_CREDS_JSON
    
    if not sheet_id or not creds_json:
        return False
    
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds_dict = json.loads(creds_json) if isinstance(creds_json, str) else creds_json
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gspread_client = gspread.authorize(creds)
        
        # Update globals
        GOOGLE_SHEET_ID = sheet_id
        GOOGLE_CREDS_JSON = creds_json
        USE_GOOGLE_SHEETS = True
        
        print("✅ Google Sheets connected from settings!")
        return True
    except Exception as e:
        print(f"❌ Google Sheets error: {e}")
        return False

# ============= API ENDPOINTS =============

@app.route('/api/validate', methods=['GET'])
def validate_license():
    """Validate a device's license (public endpoint for client app)."""
    device_id = request.args.get('device_id', '').upper()
    
    if not device_id:
        return jsonify({"valid": False, "message": "Missing device_id"})
    
    conn = get_db()
    cursor = conn.execute(
        "SELECT * FROM licenses WHERE UPPER(SUBSTR(device_id, 1, 8)) = ?",
        (device_id[:8].upper(),)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"valid": False, "message": "Thiết bị chưa được kích hoạt"})
    
    if row['status'] != 'active':
        return jsonify({"valid": False, "message": "License đã bị vô hiệu hóa"})
    
    if row['expiry_date']:
        try:
            expiry = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00'))
            if expiry.replace(tzinfo=None) < datetime.now():
                return jsonify({
                    "valid": False, 
                    "message": f"License đã hết hạn ngày {expiry.strftime('%d/%m/%Y')}"
                })
            
            days_left = (expiry.replace(tzinfo=None) - datetime.now()).days
            return jsonify({
                "valid": True,
                "message": f"Còn {days_left} ngày",
                "license_key": row['license_key'],
                "expiry_date": row['expiry_date'],
                "customer_name": row['customer_name'],
                "days_left": days_left
            })
        except:
            pass
    
    return jsonify({"valid": True, "message": "Active", "license_key": row['license_key']})

@app.route('/api/licenses', methods=['GET'])
@require_admin
def list_licenses():
    """List all licenses (admin only)."""
    if USE_GOOGLE_SHEETS:
        try:
            licenses = sheets_list_licenses()
            return jsonify({"licenses": licenses, "count": len(licenses)})
        except Exception as e:
            return jsonify({"success": False, "error": f"Sheets Error: {str(e)}"}), 500

    conn = get_db()
    cursor = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    licenses = []
    for row in rows:
        licenses.append({
            "id": row['id'],
            "device_id": row['device_id'],
            "license_key": row['license_key'],
            "expiry_date": row['expiry_date'],
            "status": row['status'],
            "customer_name": row['customer_name'],
            "notes": row['notes'],
            "created_at": row['created_at']
        })
    
    return jsonify({"licenses": licenses, "count": len(licenses)})

@app.route('/api/licenses', methods=['POST'])
@require_admin
def add_license():
    """Add a new license (admin only)."""
    data = request.json or {}
    device_id = data.get('device_id', '').upper()
    
    if not device_id:
        return jsonify({"success": False, "error": "Missing device_id"}), 400
    
    days = int(data.get('days', 30))
    license_key = data.get('license_key') or generate_license_key(device_id, days)
    expiry_date = data.get('expiry_date') or (datetime.now() + timedelta(days=days)).isoformat()
    
    if USE_GOOGLE_SHEETS:
        data['device_id'] = device_id
        data['license_key'] = license_key
        data['expiry_date'] = expiry_date
        if 'status' not in data: data['status'] = 'active'
        data['customer_name'] = data.get('customer_name', '')
        data['notes'] = data.get('notes', '')
        
        try:
            if sheets_add_license(data):
                return jsonify({
                    "success": True, 
                    "message": "License created (Sheets)",
                    "license_key": license_key,
                    "expiry_date": expiry_date
                })
            else:
                return jsonify({"success": False, "error": "Could not add to Sheets. Check permissions or valid Sheet ID."}), 400
        except Exception as e:
            print(f"Sheet Error: {e}")
            return jsonify({"success": False, "error": f"Sheet Error: {str(e)}"}), 500

    try:
        conn = get_db()
        conn.execute('''
            INSERT INTO licenses (device_id, license_key, expiry_date, status, customer_name, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            device_id,
            license_key,
            expiry_date,
            data.get('status', 'active'),
            data.get('customer_name', ''),
            data.get('notes', '')
        ))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True, 
            "message": "License created",
            "license_key": license_key,
            "expiry_date": expiry_date
        })
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Device ID already exists"}), 400

@app.route('/api/licenses/<device_id>', methods=['PUT'])
@require_admin
def update_license(device_id):
    """Update a license (admin only)."""
    data = request.json or {}
    
    updates = []
    values = []
    
    if 'expiry_date' in data:
        updates.append("expiry_date = ?")
        values.append(data['expiry_date'])
    if 'status' in data:
        updates.append("status = ?")
        values.append(data['status'])
    if 'customer_name' in data:
        updates.append("customer_name = ?")
        values.append(data['customer_name'])
    if 'notes' in data:
        updates.append("notes = ?")
        values.append(data['notes'])
    if 'license_key' in data:
        updates.append("license_key = ?")
        values.append(data['license_key'])
    
    if not updates:
        return jsonify({"success": False, "error": "No updates provided"}), 400
    
    if USE_GOOGLE_SHEETS:
        if sheets_update_license(device_id, data):
            return jsonify({"success": True, "message": "License updated (Sheets)"})
        else:
            return jsonify({"success": False, "error": "Update failed (not found?)"}), 404

    values.append(device_id.upper())
    
    conn = get_db()
    cursor = conn.execute(
        f"UPDATE licenses SET {', '.join(updates)} WHERE UPPER(device_id) = ?",
        values
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    
    if affected == 0:
        return jsonify({"success": False, "error": "Device ID not found"}), 404
    
    return jsonify({"success": True, "message": "License updated"})

@app.route('/api/licenses/<device_id>', methods=['DELETE'])
@require_admin
def delete_license(device_id):
    """Delete a license (admin only)."""
    if USE_GOOGLE_SHEETS:
        if sheets_delete_license(device_id):
            return jsonify({"success": True, "message": "License deleted (Sheets)"})
        else:
            return jsonify({"success": False, "error": "Delete failed"}), 404

    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM licenses WHERE UPPER(device_id) = ?",
        (device_id.upper(),)
    )
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    
    if affected == 0:
        return jsonify({"success": False, "error": "Device ID not found"}), 404
    
    return jsonify({"success": True, "message": "License deleted"})

@app.route('/api/extend/<device_id>', methods=['POST'])
@require_admin
def extend_license(device_id):
    """Extend a license by X days (admin only)."""
    data = request.json or {}
    days = int(data.get('days', 30))
    
    if USE_GOOGLE_SHEETS:
        row, _ = sheets_find_license(device_id)
        if not row:
            return jsonify({"success": False, "error": "Device ID not found"}), 404
        
        current_expiry = datetime.now()
        if row.get('expiry_date'):
            try:
                current_expiry = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00')).replace(tzinfo=None)
                if current_expiry < datetime.now(): current_expiry = datetime.now()
            except: pass
            
        new_expiry = (current_expiry + timedelta(days=days)).isoformat()
        total_days = (datetime.fromisoformat(new_expiry) - datetime.now()).days
        new_key = generate_license_key(device_id, total_days)
        
        if sheets_update_license(device_id, {'expiry_date': new_expiry, 'license_key': new_key}):
            return jsonify({
                "success": True, 
                "message": f"Extended by {days} days (Sheets)",
                "new_expiry": new_expiry,
                "license_key": new_key
            })
        return jsonify({"success": False, "error": "Sheet update failed"}), 500

    conn = get_db()
    cursor = conn.execute(
        "SELECT expiry_date FROM licenses WHERE UPPER(device_id) = ?",
        (device_id.upper(),)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "Device ID not found"}), 404
    
    # Calculate new expiry
    current_expiry = datetime.now()
    if row['expiry_date']:
        try:
            current_expiry = datetime.fromisoformat(row['expiry_date'].replace('Z', '+00:00')).replace(tzinfo=None)
            if current_expiry < datetime.now():
                current_expiry = datetime.now()
        except:
            pass
    
    new_expiry = (current_expiry + timedelta(days=days)).isoformat()
    total_days = (datetime.fromisoformat(new_expiry) - datetime.now()).days
    new_key = generate_license_key(device_id, total_days)
    
    conn.execute(
        "UPDATE licenses SET expiry_date = ?, license_key = ? WHERE UPPER(device_id) = ?",
        (new_expiry, new_key, device_id.upper())
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True, 
        "message": f"Extended by {days} days",
        "new_expiry": new_expiry,
        "license_key": new_key
    })

# ============= WEB ADMIN INTERFACE =============

ADMIN_HTML = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔐 License Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #f1f5f9; min-height: 100vh; }
        
        button { cursor: pointer; transition: opacity 0.2s; }
        button:disabled { opacity: 0.7; cursor: not-allowed; }
        
        .header { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 24px; }
        .header .user-info { display: flex; align-items: center; gap: 15px; }
        .header .user-info span { font-size: 14px; opacity: 0.9; }
        .header .logout-btn { background: rgba(255,255,255,0.2); border: none; color: white; padding: 8px 15px; border-radius: 6px; cursor: pointer; }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        .card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        
        /* Login Page */
        .login-container { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: linear-gradient(135deg, #6366f1, #8b5cf6); }
        .login-card { background: white; padding: 40px; border-radius: 16px; width: 100%; max-width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
        .login-card h2 { text-align: center; margin-bottom: 30px; color: #1e293b; }
        .login-card .form-group { margin-bottom: 20px; }
        .login-card label { display: block; margin-bottom: 8px; font-weight: 500; color: #475569; }
        .login-card input { width: 100%; padding: 12px 15px; border: 2px solid #e2e8f0; border-radius: 8px; font-size: 14px; transition: border-color 0.3s; }
        .login-card input:focus { outline: none; border-color: #6366f1; }
        .login-card .login-btn { width: 100%; padding: 14px; background: #6366f1; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: background 0.3s; }
        .login-card .login-btn:hover { background: #4f46e5; }
        .login-card .error { color: #ef4444; font-size: 14px; margin-top: 10px; text-align: center; display: none; }
        
        .auth-section { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .auth-section input { flex: 1; min-width: 200px; padding: 10px 15px; border: 1px solid #e2e8f0; border-radius: 8px; }
        .auth-section button { padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-weight: bold; }
        
        .btn-primary { background: #6366f1; color: white; }
        .btn-success { background: #10b981; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-warning { background: #f59e0b; color: white; }
        
        .grid { display: grid; grid-template-columns: 1fr 350px; gap: 20px; }
        @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
        
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f8fafc; font-weight: 600; }
        tr:hover { background: #f8fafc; cursor: pointer; }
        tr.selected { background: #e0e7ff; }
        
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 500; color: #475569; }
        .form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; }
        
        .section-title { font-size: 14px; font-weight: 600; color: #6366f1; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e0e7ff; }
        
        .key-display { background: #ecfdf5; padding: 15px; border-radius: 8px; margin-top: 15px; }
        .key-display code { font-family: 'Consolas', monospace; font-size: 14px; word-break: break-all; }
        
        .stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
        .stat { background: #f8fafc; padding: 15px 25px; border-radius: 10px; text-align: center; }
        .stat .number { font-size: 28px; font-weight: bold; color: #6366f1; }
        .stat .label { font-size: 12px; color: #64748b; }
        
        .status-active { color: #10b981; }
        .status-disabled { color: #ef4444; }
        .status-expired { color: #f59e0b; }
        
        .status-expired { color: #f59e0b; }
        
        .toast { position: fixed; bottom: 20px; right: 20px; padding: 15px 25px; border-radius: 8px; color: white; animation: fadeIn 0.3s; z-index: 9999; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body>
    <!-- Login Page -->
    <div id="loginPage" class="login-container">
        <div class="login-card">
            <h2>🔐 Đăng Nhập Admin</h2>
            <div class="form-group">
                <label>Tài khoản</label>
                <input type="text" id="loginUsername" placeholder="admin">
            </div>
            <div class="form-group">
                <label>Mật khẩu</label>
                <input type="password" id="loginPassword" placeholder="••••••••">
            </div>
            <button class="login-btn" onclick="doLogin()">Đăng Nhập</button>
            <div id="loginError" class="error"></div>
        </div>
    </div>
    
    <!-- Main App (hidden by default) -->
    <div id="mainApp" style="display:none;">
        <div class="header">
            <h1>🔐 License Management System</h1>
            <div class="user-info">
                <span id="usernameDisplay">👤 admin</span>
                <button class="logout-btn" onclick="doLogout()">Đăng xuất</button>
            </div>
        </div>
        
        <div class="container">
            <!-- Stats -->
            <div class="stats" id="statsContainer"></div>
        
            <div class="grid">
            <!-- Table -->
            <div class="card">
                <div class="section-title">📋 License List</div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Device ID</th>
                                <th>Customer</th>
                                <th>Expiry</th>
                                <th>Status</th>
                                <th>Days Left</th>
                            </tr>
                        </thead>
                        <tbody id="licenseTable"></tbody>
                    </table>
                </div>
            </div>
            
            <!-- Actions -->
            <div>
                <!-- Add New -->
                <div class="card">
                    <div class="section-title">➕ Add New License</div>
                    <div class="form-group">
                        <label>Device ID</label>
                        <input type="text" id="newDeviceId" placeholder="4210EF496F68665F">
                    </div>
                    <div class="form-group">
                        <label>Customer Name</label>
                        <input type="text" id="newCustomer" placeholder="Tên khách hàng">
                    </div>
                    <div class="form-group">
                        <label>Duration (days)</label>
                        <select id="newDays">
                            <option value="7">7 days</option>
                            <option value="30" selected>30 days</option>
                            <option value="90">90 days</option>
                            <option value="180">180 days</option>
                            <option value="365">1 year</option>
                        </select>
                    </div>
                    <button id="btnAddLicense" class="btn-success" style="width:100%" onclick="addLicense()">➕ Add License</button>
                </div>
                
                <!-- Edit -->
                <div class="card">
                    <div class="section-title">✏️ Edit Selected</div>
                    <p id="selectedInfo" style="margin-bottom:15px; color:#64748b;">Select a license from table</p>
                    <div class="form-group">
                        <label>Extend by (days)</label>
                        <input type="number" id="extendDays" value="30">
                    </div>
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <button class="btn-warning" style="flex:1" onclick="extendLicense()">⏰ Extend</button>
                        <button class="btn-danger" style="flex:1" onclick="toggleStatus()">🔴 Toggle</button>
                    </div>
                    <button class="btn-danger" style="width:100%" onclick="deleteLicense()">🗑️ Delete</button>
                </div>
                
                <!-- Key Display -->
                <div class="card key-display" id="keyDisplay" style="display:none;">
                    <div class="section-title">🔑 License Key</div>
                    <code id="licenseKey"></code>
                    <button class="btn-primary" style="width:100%; margin-top:10px;" onclick="copyKey()">📋 Copy</button>
                </div>
                
                <!-- Settings -->
                <div class="card" style="background:#f0fdf4;">
                    <div class="section-title">⚙️ Cài đặt Google Sheets</div>
                    <div id="sheetsStatus" style="margin-bottom:10px; font-size:13px;">
                        <span id="sheetsStatusText">🔴 Chưa kết nối</span>
                    </div>
                    <div class="form-group">
                        <label>Sheet ID</label>
                        <input type="text" id="settingsSheetId" placeholder="1AbC123...">
                    </div>
                    <div class="form-group">
                        <label>Service Account JSON</label>
                        <textarea id="settingsCredentials" rows="3" style="width:100%; padding:8px; border:1px solid #e2e8f0; border-radius:6px; font-size:11px;" placeholder='{"type":"service_account",...}'></textarea>
                    </div>
                    <div style="display:flex; gap:10px;">
                        <button class="btn-success" style="flex:1" onclick="saveSettings()">💾 Lưu</button>
                        <button class="btn-primary" style="flex:1" onclick="testSheets()">🔗 Test</button>
                    </div>
                </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let licenses = [];
        let selectedDeviceId = null;
        const API_BASE = window.location.origin;
        
        // Check if already logged in
        async function checkAuth() {
            try {
                const res = await fetch(API_BASE + '/api/check-auth', {credentials: 'include'});
                const data = await res.json();
                if (data.logged_in) {
                    showMainApp(data.username);
                    loadLicenses();
                }
            } catch (e) {}
        }
        
        // Login
        async function doLogin() {
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            
            const res = await fetch(API_BASE + '/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password}),
                credentials: 'include'
            });
            const data = await res.json();
            
            if (data.success) {
                showMainApp(username);
                loadLicenses();
            } else {
                document.getElementById('loginError').textContent = data.error || 'Đăng nhập thất bại';
                document.getElementById('loginError').style.display = 'block';
            }
        }
        
        // Logout
        async function doLogout() {
            await fetch(API_BASE + '/api/logout', {method: 'POST', credentials: 'include'});
            document.getElementById('loginPage').style.display = 'flex';
            document.getElementById('mainApp').style.display = 'none';
        }
        
        function showMainApp(username) {
            document.getElementById('loginPage').style.display = 'none';
            document.getElementById('mainApp').style.display = 'block';
            document.getElementById('usernameDisplay').textContent = '👤 ' + username;
            loadSettings();
        }
        
        // Enter key to login
        document.addEventListener('DOMContentLoaded', function() {
            checkAuth();
            document.getElementById('loginPassword').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') doLogin();
            });
        });
        
        async function apiCall(endpoint, method = 'GET', data = null) {
            const options = {
                method,
                headers: {'Content-Type': 'application/json'},
                credentials: 'include'
            };
            if (data) options.body = JSON.stringify(data);
            
            const res = await fetch(API_BASE + endpoint, options);
            return res.json();
        }
        
        async function loadLicenses() {
            try {
                const data = await apiCall('/api/licenses');
                if (data.error) {
                    showToast(data.error, 'error');
                    return;
                }
                licenses = data.licenses || [];
                renderTable();
                updateStats();
            } catch (e) {
                showToast('Connection error', 'error');
            }
        }
        
        function renderTable() {
            const tbody = document.getElementById('licenseTable');
            tbody.innerHTML = '';
            
            licenses.forEach(lic => {
                let expiry = '--';
                let daysLeft = '--';
                let statusClass = 'status-active';
                
                if (lic.expiry_date) {
                    const exp = new Date(lic.expiry_date);
                    expiry = exp.toLocaleDateString('vi-VN');
                    const days = Math.ceil((exp - new Date()) / (1000*60*60*24));
                    daysLeft = days >= 0 ? days + ' ngày' : 'Hết hạn';
                    if (days < 0) statusClass = 'status-expired';
                }
                
                if (lic.status !== 'active') statusClass = 'status-disabled';
                
                const row = document.createElement('tr');
                row.className = lic.device_id === selectedDeviceId ? 'selected' : '';
                row.onclick = () => selectLicense(lic);
                row.innerHTML = `
                    <td><code>${lic.device_id}</code></td>
                    <td>${lic.customer_name || '--'}</td>
                    <td>${expiry}</td>
                    <td class="${statusClass}">${lic.status === 'active' ? '✅ Active' : '🔴 Disabled'}</td>
                    <td>${daysLeft}</td>
                `;
                tbody.appendChild(row);
            });
        }
        
        function updateStats() {
            const total = licenses.length;
            const active = licenses.filter(l => l.status === 'active').length;
            const expired = licenses.filter(l => {
                if (!l.expiry_date) return false;
                return new Date(l.expiry_date) < new Date();
            }).length;
            
            document.getElementById('statsText').textContent = `📊 ${total} licenses`;
            document.getElementById('statsContainer').innerHTML = `
                <div class="stat"><div class="number">${total}</div><div class="label">Total</div></div>
                <div class="stat"><div class="number" style="color:#10b981">${active}</div><div class="label">Active</div></div>
                <div class="stat"><div class="number" style="color:#f59e0b">${expired}</div><div class="label">Expired</div></div>
            `;
        }
        
        function selectLicense(lic) {
            selectedDeviceId = lic.device_id;
            document.getElementById('selectedInfo').textContent = 'Selected: ' + lic.device_id;
            document.getElementById('licenseKey').textContent = lic.license_key || 'No key';
            document.getElementById('keyDisplay').style.display = 'block';
            renderTable();
        }
        
        async function addLicense() {
            const device_id = document.getElementById('newDeviceId').value.trim();
            const customer_name = document.getElementById('newCustomer').value.trim();
            const days = parseInt(document.getElementById('newDays').value);
            
            if (!device_id) {
                showToast('Please enter Device ID', 'error');
                return;
            }
            if (!device_id) {
                showToast('Please enter Device ID', 'error');
                return;
            }
            
            const btn = document.getElementById('btnAddLicense');
            const originalText = btn.innerHTML;
            btn.innerHTML = '⏳ Adding...';
            btn.disabled = true;
            
            try {
                const result = await apiCall('/api/licenses', 'POST', { device_id, customer_name, days });
                
                if (result.success) {
                    showToast('✅ ' + result.message, 'success');
                    document.getElementById('licenseKey').textContent = result.license_key;
                    document.getElementById('keyDisplay').style.display = 'block';
                    document.getElementById('newDeviceId').value = '';
                    document.getElementById('newCustomer').value = '';
                    loadLicenses();
                } else {
                    showToast('❌ ' + result.error, 'error');
                }
            } catch (e) {
                showToast('❌ Network Error: ' + e.message, 'error');
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }
        
        async function extendLicense() {
            if (!selectedDeviceId) {
                showToast('Select a license first', 'error');
                return;
            }
            
            const days = parseInt(document.getElementById('extendDays').value);
            const result = await apiCall('/api/extend/' + selectedDeviceId, 'POST', { days });
            
            if (result.success) {
                showToast('Extended!', 'success');
                document.getElementById('licenseKey').textContent = result.license_key;
                loadLicenses();
            } else {
                showToast(result.error, 'error');
            }
        }
        
        async function toggleStatus() {
            if (!selectedDeviceId) {
                showToast('Select a license first', 'error');
                return;
            }
            
            const lic = licenses.find(l => l.device_id === selectedDeviceId);
            const newStatus = lic.status === 'active' ? 'disabled' : 'active';
            
            const result = await apiCall('/api/licenses/' + selectedDeviceId, 'PUT', { status: newStatus });
            
            if (result.success) {
                showToast('Status updated!', 'success');
                loadLicenses();
            } else {
                showToast(result.error, 'error');
            }
        }
        
        async function deleteLicense() {
            if (!selectedDeviceId) {
                showToast('Select a license first', 'error');
                return;
            }
            
            if (!confirm('Delete license for ' + selectedDeviceId + '?')) return;
            
            const result = await apiCall('/api/licenses/' + selectedDeviceId, 'DELETE');
            
            if (result.success) {
                showToast('Deleted!', 'success');
                selectedDeviceId = null;
                document.getElementById('selectedInfo').textContent = 'Select a license from table';
                document.getElementById('keyDisplay').style.display = 'none';
                loadLicenses();
            } else {
                showToast(result.error, 'error');
            }
        }
        
        function copyKey() {
            const key = document.getElementById('licenseKey').textContent;
            navigator.clipboard.writeText(key);
            showToast('Copied!', 'success');
        }
        
        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.style.background = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#6366f1';
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        
        // Settings functions
        async function loadSettings() {
            try {
                const data = await apiCall('/api/settings');
                if (data.sheet_id) {
                    document.getElementById('settingsSheetId').value = data.sheet_id;
                }
                updateSheetsStatus(data.sheets_connected, data.has_credentials);
            } catch (e) {}
        }
        
        function updateSheetsStatus(connected, hasCreds) {
            const el = document.getElementById('sheetsStatusText');
            const credsInput = document.getElementById('settingsCredentials');
            
            if (connected) {
                el.innerHTML = '🟢 Đã kết nối Google Sheets (OK)';
                el.style.color = '#10b981';
                // If connected via Env Vars, hide the input or show placeholder
                if (!credsInput.value) {
                    credsInput.placeholder = "✅ Đã nhận Credentials từ biến môi trường (Vercel). Không cần dán lại trừ khi muốn đổi.";
                }
            } else if (hasCreds) {
                el.innerHTML = '🟡 Có credentials, đang kết nối...';
                el.style.color = '#f59e0b';
            } else {
                el.innerHTML = '🔴 Chưa cấu hình';
                el.style.color = '#ef4444';
            }
        }
        
        async function saveSettings() {
            const sheet_id = document.getElementById('settingsSheetId').value.trim();
            const credentials = document.getElementById('settingsCredentials').value.trim();
            
            if (!sheet_id) {
                showToast('Vui lòng nhập Sheet ID', 'error');
                return;
            }
            
            const data = { use_sheets: true, sheet_id };
            if (credentials) {
                try {
                    JSON.parse(credentials);
                    data.credentials = credentials;
                } catch (e) {
                    showToast('JSON không hợp lệ!', 'error');
                    return;
                }
            }
            
            const result = await apiCall('/api/settings', 'POST', data);
            showToast(result.message || 'Đã lưu!', result.success ? 'success' : 'error');
            loadSettings();
        }
        
        async function testSheets() {
            const result = await apiCall('/api/settings/test-sheets', 'POST');
            showToast(result.message || result.error, result.success ? 'success' : 'error');
            loadSettings();
        }
    </script>
</body>
</html>
'''

@app.route('/')
def admin_page():
    """Serve the admin web interface."""
    return render_template_string(ADMIN_HTML)

@app.route('/admin')
def admin_page_alt():
    """Alternative admin URL."""
    return render_template_string(ADMIN_HTML)

# ============= MAIN =============

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
