# ============================================================================
# SLCI Chatbot - Flask App (Python 3.14.3 Compatible)
# All original functionality preserved + psycopg 3.x for Python 3.14 support
# ============================================================================
import sys
import os
import re
import io
import json
import hashlib
import hmac
import secrets
import time
import smtplib
from datetime import datetime
from functools import wraps
from threading import Lock

# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

# Flask imports
from flask import Flask, render_template, request, jsonify, send_file

# Web scraping
import requests
from bs4 import BeautifulSoup

# ✅ psycopg 3.x imports (Python 3.14 compatible - replaces psycopg2)
import psycopg
from psycopg_pool import ConnectionPool

# PDF Generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# ============================================================================
# APP INITIALIZATION
# ============================================================================
app = Flask(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here-change-in-production')

# PostgreSQL Configuration
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'postgres')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')

# Ollama Configuration
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'mistral')
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', '5'))

# Company Configuration
COMPANY_NAME = "Shakti Legal Compliance India"
COMPANY_LOGO_PATH = "static/logo.png"

# Fee Enquiry Configuration
FEE_ENQUIRY_EMAIL = os.getenv("FEE_ENQUIRY_EMAIL", "slciaiagent@gmail.com")

# Google Sheets Configuration
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '1HGdvknpocedMbjMHxzRAye4qe3hnNEJry-h_ECE23pk')
GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH', 'credentials.json')
GOOGLE_SHEET_ENABLED = os.getenv('GOOGLE_SHEET_ENABLED', 'true').lower() == 'true'

# ============================================================================
# DATABASE CONNECTION POOL (psycopg 3.x compatible)
# ============================================================================
db_pool = None

def get_db_pool():
    """Get database connection pool - psycopg 3.x compatible"""
    global db_pool
    if db_pool is None:
        try:
            conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
            db_pool = ConnectionPool(
                conninfo=conninfo,
                min_size=1,
                max_size=10,
                open=True
            )
            print("✅ Database pool created successfully")
        except Exception as e:
            print(f"⚠️ Database pool creation failed: {e}")
            print("⚠️ App will run without database (check DB credentials)")
            return None
    return db_pool

def get_db_connection():
    """Get database connection from pool - psycopg 3.x compatible"""
    try:
        pool = get_db_pool()
        if pool:
            return pool.getconn()
        return None
    except Exception as e:
        print(f"Database connection error: {str(e)}")
        return None

def release_db_connection(conn):
    """Release connection back to pool - psycopg 3.x compatible"""
    if conn and db_pool:
        try:
            db_pool.putconn(conn)
        except Exception as e:
            print(f"Error releasing connection: {str(e)}")

def init_db():
    """Initialize database tables - psycopg 3.x compatible"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            print("⚠️ Skipping DB initialization - no connection")
            return
        with conn.cursor() as cursor:
            # Create downloads table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                company_name TEXT NOT NULL,
                email TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                designation TEXT NOT NULL,
                rating INTEGER NOT NULL,
                state TEXT NOT NULL,
                act_type TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pdf_generated BOOLEAN DEFAULT FALSE,
                pdf_path TEXT,
                UNIQUE(email, state, act_type, download_date)
            )
            ''')
            # Create service enquiries table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS service_enquiries (
                id SERIAL PRIMARY KEY,
                enquiry_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                company_name TEXT NOT NULL,
                email TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                service TEXT NOT NULL,
                query TEXT NOT NULL,
                ip_address TEXT,
                status TEXT DEFAULT 'pending',
                submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                email_sent BOOLEAN DEFAULT TRUE,
                notes TEXT
            )
            ''')
            # Create fee enquiries table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS fee_enquiries (
                id SERIAL PRIMARY KEY,
                enquiry_id TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                company_name TEXT NOT NULL,
                email TEXT NOT NULL,
                contact_number TEXT NOT NULL,
                description TEXT NOT NULL,
                ip_address TEXT,
                status TEXT DEFAULT 'pending',
                submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                email_sent BOOLEAN DEFAULT TRUE,
                notes TEXT
            )
            ''')
            # Create indexes for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_email ON downloads(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_date ON downloads(download_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_state ON downloads(state)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_downloads_act ON downloads(act_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_enquiries_email ON service_enquiries(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_enquiries_date ON service_enquiries(submission_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_enquiries_status ON service_enquiries(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_fee_enquiries_email ON fee_enquiries(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_fee_enquiries_date ON fee_enquiries(submission_date)')
            # Create statistics table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS download_stats (
                id SERIAL PRIMARY KEY,
                state TEXT NOT NULL,
                act_type TEXT NOT NULL,
                download_count INTEGER DEFAULT 0,
                last_download TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(state, act_type)
            )
            ''')
            conn.commit()
            print("✅ Database tables initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization error: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)

# ============================================================================
# GOOGLE SHEETS CONNECTION - PRODUCTION READY (gspread 5.x compatible)
# ============================================================================
gs_client = None
gs_lock = Lock()

def get_google_sheet_client():
    """Get Google Sheets client - Fixed for production use"""
    global gs_client
    if gs_client is None and GOOGLE_SHEET_ENABLED:
        try:
            if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
                print(f"❌ Google credentials file NOT FOUND: {os.path.abspath(GOOGLE_CREDENTIALS_PATH)}")
                return None
            try:
                with open(GOOGLE_CREDENTIALS_PATH, 'r') as f:
                    f.read(1)
            except PermissionError:
                print(f"❌ Permission denied reading: {GOOGLE_CREDENTIALS_PATH}")
                return None
            except Exception as e:
                print(f"❌ Cannot read credentials file: {e}")
                return None
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.file'
            ]
            creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
            gs_client = gspread.authorize(creds)
            try:
                spreadsheet = gs_client.open_by_key(GOOGLE_SHEET_ID)
                print(f"✅ Google Sheets connected: {spreadsheet.title}")
                print(f"   Service Account: {creds.service_account_email}")
                return gs_client
            except gspread.exceptions.SpreadsheetNotFound:
                print(f"❌ Spreadsheet NOT FOUND or NOT SHARED: {GOOGLE_SHEET_ID}")
                gs_client = None
                return None
            except gspread.exceptions.APIError as e:
                print(f"❌ Google Sheets API Error: {e}")
                gs_client = None
                return None
        except Exception as e:
            print(f"❌ Google Sheets init error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            gs_client = None
            return None
    return gs_client

def _get_sheet_headers(sheet_name):
    """Return headers for each sheet type"""
    headers_map = {
        "Downloads": ["Timestamp", "Full Name", "Company Name", "Email", "Contact Number", "Designation", "Rating", "State", "Act Type", "IP Address", "Download ID"],
        "Service_Enquiries": ["Timestamp", "Enquiry ID", "Full Name", "Company Name", "Email", "Contact Number", "Service", "Query", "IP Address", "Status"],
        "Fee_Enquiries": ["Timestamp", "Enquiry ID", "Full Name", "Company Name", "Email", "Contact Number", "Description", "IP Address", "Status"],
        "Enquiries": ["Timestamp", "Full Name", "Company Name", "Email", "Contact Number", "Query"]
    }
    return headers_map.get(sheet_name, ["Timestamp"])

def append_to_google_sheet(sheet_name, data_row):
    """Append data row to Google Sheet - Production ready with retry logic"""
    if not GOOGLE_SHEET_ENABLED:
        return False
    try:
        client = get_google_sheet_client()
        if not client:
            print("⚠️ Google Sheets client unavailable - skipping sheet logging")
            return False
        try:
            spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"❌ Spreadsheet not found: {GOOGLE_SHEET_ID}")
            return False
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=2000, cols=30)
            print(f"✅ Created new worksheet: {sheet_name}")
        headers = _get_sheet_headers(sheet_name)
        if headers and not worksheet.row_values(1):
            worksheet.append_row(headers, value_input_option='USER_ENTERED')
            print(f"✅ Added headers to {sheet_name}")
        normalized_data = {}
        for key, value in data_row.items():
            normalized_key = key.lower().replace(' ', '_')
            normalized_data[normalized_key] = value if value is not None else ''
        if 'timestamp' not in normalized_data:
            normalized_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet_headers = [h.lower().replace(' ', '_') for h in worksheet.row_values(1)]
        row_values = []
        for header in sheet_headers:
            value = normalized_data.get(header, '')
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            row_values.append(str(value).strip())
        with gs_lock:
            for attempt in range(3):
                try:
                    worksheet.append_row(row_values, value_input_option='USER_ENTERED')
                    print(f"✅ Data logged to Google Sheet: {sheet_name}")
                    return True
                except gspread.exceptions.APIError as e:
                    if "Quota exceeded" in str(e) or "Rate limit" in str(e):
                        wait_time = 2 ** attempt
                        print(f"⚠️ Rate limited. Waiting {wait_time}s before retry {attempt+1}/3...")
                        time.sleep(wait_time)
                        continue
                    raise
                except Exception as e:
                    print(f"⚠️ Append attempt {attempt+1} failed: {e}")
                    if attempt == 2:
                        raise
                    time.sleep(1)
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Spreadsheet not found: {GOOGLE_SHEET_ID}")
        return False
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ Worksheet not found: {sheet_name}")
        return False
    except gspread.exceptions.APIError as e:
        print(f"❌ Google Sheets API Error: {e}")
        return False
    except PermissionError as e:
        print(f"❌ File Permission Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Google Sheets append error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

@app.route("/debug-sheets", methods=["GET"])
def debug_sheets():
    """Comprehensive Google Sheets diagnostic endpoint"""
    result = {
        "GOOGLE_SHEET_ENABLED": GOOGLE_SHEET_ENABLED,
        "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
        "GOOGLE_CREDENTIALS_PATH": os.path.abspath(GOOGLE_CREDENTIALS_PATH),
        "credentials_file_exists": False,
        "credentials_valid": False,
        "service_account_email": None,
        "project_id": None,
        "client_initialized": False,
        "spreadsheet_accessible": False,
        "sheets_api_enabled": None,
        "errors": []
    }
    if os.path.exists(GOOGLE_CREDENTIALS_PATH):
        result["credentials_file_exists"] = True
        try:
            with open(GOOGLE_CREDENTIALS_PATH, 'r', encoding='utf-8') as f:
                creds = json.load(f)
                result["service_account_email"] = creds.get("client_email")
                result["project_id"] = creds.get("project_id")
                result["credentials_valid"] = True
        except Exception as e:
            result["errors"].append(f"Credentials parse error: {e}")
    else:
        result["errors"].append(f"Credentials file not found: {GOOGLE_CREDENTIALS_PATH}")
    if result["credentials_valid"]:
        try:
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.file']
            creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
            client = gspread.authorize(creds)
            result["client_initialized"] = True
            try:
                spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
                result["spreadsheet_accessible"] = True
                result["spreadsheet_title"] = spreadsheet.title
                result["worksheets"] = [w.title for w in spreadsheet.worksheets()]
                result["sheets_api_enabled"] = True
            except gspread.exceptions.APIError as e:
                err = e.response.json() if hasattr(e, 'response') else {}
                if err.get('code') == 403 and 'SERVICE_DISABLED' in str(err.get('message', '')):
                    result["sheets_api_enabled"] = False
                    result["errors"].append("Google Sheets API is DISABLED in project")
                    result["enable_api_url"] = f"https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project={result['project_id']}"
                else:
                    result["errors"].append(f"Spreadsheet access error: {err.get('message', str(e))}")
            except Exception as e:
                result["errors"].append(f"Spreadsheet error: {e}")
        except Exception as e:
            result["errors"].append(f"Client init error: {e}")
    return jsonify(result)

# ============================================================================
# DATABASE LOGGING FUNCTIONS - WITH GOOGLE SHEETS INTEGRATION
# ============================================================================
def log_download_request(data, ip_address, user_agent):
    """Log download to DB AND Google Sheets - psycopg 3.x compatible"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        with conn.cursor() as cursor:
            cursor.execute('''
            INSERT INTO downloads (full_name, company_name, email, contact_number, designation, rating, state, act_type, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (data['fullName'], data['companyName'], data['email'], data['contactNumber'], data['designation'], int(data['rating']), data['state'], data['actType'], ip_address, user_agent))
            cursor.execute('''
            INSERT INTO download_stats (state, act_type, download_count, last_download)
            VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(state, act_type) DO UPDATE SET download_count = download_stats.download_count + 1, last_download = CURRENT_TIMESTAMP
            ''', (data['state'], data['actType']))
            conn.commit()
            download_id = cursor.lastrowid if hasattr(cursor, 'lastrowid') else None
        try:
            sheet_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'full_name': data['fullName'],
                'company_name': data['companyName'],
                'email': data['email'],
                'contact_number': data['contactNumber'],
                'designation': data['designation'],
                'rating': str(data['rating']),
                'state': data['state'],
                'act_type': data['actType'],
                'ip_address': ip_address,
                'download_id': str(download_id) if download_id else ''
            }
            from threading import Thread
            Thread(target=append_to_google_sheet, args=("Downloads", sheet_data), daemon=True).start()
        except Exception as e:
            print(f"⚠️ Google Sheets logging failed (non-critical): {e}")
        return download_id
    except psycopg.errors.UniqueViolation as e:
        print(f"Warning: Duplicate download request from {data['email']}")
        if conn:
            conn.rollback()
        return None
    except Exception as e:
        print(f"Database error: {str(e)}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            release_db_connection(conn)

def get_download_statistics():
    """Get download statistics - psycopg 3.x compatible"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return {'total': 0, 'today': 0}
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) as total FROM downloads')
            total = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) as count FROM downloads WHERE DATE(download_date) = CURRENT_DATE')
            today = cursor.fetchone()[0]
        return {'total': total, 'today': today}
    except Exception as e:
        print(f"Statistics error: {str(e)}")
        return {'total': 0, 'today': 0}
    finally:
        if conn:
            release_db_connection(conn)

# ============================================================================
# CONNECTION & STATE DETECTION
# ============================================================================
def check_ollama_connection():
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False

def detect_state(message, act_type="minimum_wages"):
    """Improved state detection with better matching for all act types"""
    message_lower = message.lower()
    state_patterns = [r'(?:of|for|in)\s+([a-zA-Z\s]+?)(?:\?|$|\.)', r'([a-zA-Z\s]+?)\s+(?:state|act|rules|law)', r'what is .*? (?:act|rules|law) (?:of|for|in) ([a-zA-Z\s]+)']
    extracted_state = None
    for pattern in state_patterns:
        match = re.search(pattern, message_lower)
        if match:
            extracted_state = match.group(1).strip()
            break
    if act_type == "minimum_wages":
        url_dict = STATE_MINIMUM_WAGE_URLS
        for state in url_dict.keys():
            if state in message_lower:
                return state, STATE_MINIMUM_WAGE_URLS[state]
        for state, variations in STATE_VARIATIONS.items():
            for variation in variations:
                if variation in message_lower or (extracted_state and variation in extracted_state):
                    return state, STATE_MINIMUM_WAGE_URLS.get(state, STATE_MINIMUM_WAGE_URLS.get(state.lower()))
    elif act_type == "holiday_list":
        for state, url in STATE_HOLIDAY_URLS.items():
            if state in message_lower or (extracted_state and state in extracted_state):
                return state, url
            for variation in STATE_VARIATIONS.get(state, []):
                if variation in message_lower:
                    return state, url
    elif act_type == "working_hours":
        for state, url in STATE_WORKING_HOURS_URLS.items():
            if state in message_lower or (extracted_state and state in extracted_state):
                return state, url
            for variation in STATE_VARIATIONS.get(state, []):
                if variation in message_lower:
                    return state, url
    elif act_type == "shop_establishment":
        for state in STATE_VARIATIONS.keys():
            if state in message_lower:
                return state, SHOP_ESTABLISHMENT_MAIN_URL
        for state, variations in STATE_VARIATIONS.items():
            for variation in variations:
                if variation in message_lower:
                    return state, SHOP_ESTABLISHMENT_MAIN_URL
        if extracted_state:
            for state in STATE_VARIATIONS.keys():
                if state in extracted_state.lower():
                    return state, SHOP_ESTABLISHMENT_MAIN_URL
                for variation in STATE_VARIATIONS[state]:
                    if variation in extracted_state.lower():
                        return state, SHOP_ESTABLISHMENT_MAIN_URL
    return None, None

# ============================================================================
# TEMPORARY STORAGE FOR PENDING DOWNLOADS
# ============================================================================
pending_downloads = {}
pending_lock = Lock()

# ============================================================================
# DOWNLOAD REQUEST ROUTE
# ============================================================================
@app.route("/request-download", methods=["POST"])
def request_download():
    """Step 1: Validate form, log to DB, return download token (JSON)"""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'state', 'actType']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Missing field: {field}"}), 400
        if 'designation' not in data:
            data['designation'] = 'Not Provided'
        if 'rating' not in data:
            data['rating'] = 0
        download_token = f"DL{secrets.token_hex(8)}"
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent')
        download_id = log_download_request(data, ip_address, user_agent)
        with pending_lock:
            pending_downloads[download_token] = {'data': data, 'download_id': download_id, 'created_at': datetime.now(), 'ip': ip_address}
        return jsonify({"success": True, "downloadId": download_id, "downloadToken": download_token, "message": "Form submitted successfully"})
    except Exception as e:
        print(f"Download Request Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# PDF GENERATION ROUTE
# ============================================================================
@app.route("/generate-pdf/<token>", methods=["GET"])
def generate_pdf(token):
    """Step 2: Generate and serve PDF using validated token"""
    try:
        with pending_lock:
            if token not in pending_downloads:
                return jsonify({"error": "Invalid or expired download token"}), 404
            pending_data = pending_downloads[token]
            if (datetime.now() - pending_data['created_at']).total_seconds() > 600:
                del pending_downloads[token]
                return jsonify({"error": "Download token expired"}), 410
            form_data = pending_data['data']
            download_id = pending_data['download_id']
            del pending_downloads[token]
        state = form_data['state'].lower().replace('_', ' ')
        act_type = form_data['actType'].lower()
        pdf_data = None
        if act_type == 'minimum_wages':
            pdf_data = fetch_minimum_wages(state)
        elif act_type == 'holiday_list':
            pdf_data = fetch_holiday_list(state)
        elif act_type == 'working_hours':
            pdf_data = fetch_working_hours(state)
        elif act_type == 'shop_establishment':
            pdf_data = fetch_shop_establishment(state)
        else:
            return jsonify({"error": "Invalid act type"}), 400
        if not pdf_data or not pdf_data.get('tables_data'):
            return jsonify({"error": "No data found to generate PDF"}), 404
        pdf_file = create_pdf_file(state, pdf_data.get("act_type", act_type), pdf_data.get("tables_data", []), pdf_data.get("effective_date"), download_id)
        filename = f"{act_type}_{state.replace(' ', '_')}.pdf"
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"PDF Generation Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# PDF CREATION FUNCTION
# ============================================================================
def create_pdf_file(state, act_type, tables_data, effective_date, download_id=None):
    """Generate PDF with consistent header, watermark, and footer for ALL act types"""
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=40, bottomMargin=50)
    elements = []
    styles = getSampleStyleSheet()
    build_pdf_header(elements, styles)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading2'], fontSize=16, alignment=TA_CENTER, spaceAfter=10, textColor=colors.HexColor('#283593'), fontName='Helvetica-Bold')
    date_style = ParagraphStyle('DateStyle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, spaceAfter=20, textColor=colors.HexColor('#2e7d32'), fontName='Helvetica-Bold')
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, textColor=colors.white, fontName='Helvetica-Bold')
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER, fontName='Helvetica')
    display_name = act_type.replace('_', ' ').title()
    elements.append(Paragraph(f"<b>{display_name} – {state.title()}</b>", title_style))
    if effective_date:
        elements.append(Paragraph(f"<b>Effective Date: {effective_date}</b>", date_style))
    elements.append(Spacer(1, 10))
    if tables_data:
        for table_data in tables_data:
            if not table_data:
                continue
            pdf_table_data = []
            for row_idx, row in enumerate(table_data):
                pdf_row = []
                for cell in row:
                    cell_text = str(cell).strip()
                    if cell_text:
                        if row_idx == 0:
                            pdf_row.append(Paragraph(cell_text, header_style))
                        else:
                            pdf_row.append(Paragraph(cell_text, cell_style))
                    else:
                        pdf_row.append("")
                pdf_table_data.append(pdf_row)
            col_count = len(table_data[0]) if table_data else 0
            col_widths = [doc.width / col_count] * col_count if col_count else [doc.width]
            pdf_table = Table(pdf_table_data, colWidths=col_widths, repeatRows=1)
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ])
            for i in range(1, len(table_data)):
                if i % 2 == 0:
                    table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f5f7fa'))
            pdf_table.setStyle(table_style)
            elements.append(pdf_table)
            elements.append(Spacer(1, 15))
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER, textColor=colors.grey)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Generated on {datetime.now().strftime('%d %B %Y | %I:%M %p')}", footer_style))
    elements.append(Paragraph("Shakti Legal Compliance India | www.slci.in", footer_style))
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    return output

# ============================================================================
# DATA EXTRACTION HELPERS
# ============================================================================
def extract_effective_date(soup):
    date_patterns = [r'Effective from Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})', r'📋 Effective from Date:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})', r'Effective[:\s]+from[:\s]+Date[:\s]*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})', r'w\.e\.f[.\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', r'Effective Date[:\s]*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})']
    all_elements = soup.find_all(['div', 'p', 'span', 'h1', 'h2', 'h3', 'h4', 'li', 'td', 'th'])
    for element in all_elements:
        element_text = element.get_text()
        for pattern in date_patterns:
            match = re.search(pattern, element_text, re.IGNORECASE)
            if match:
                return clean_date(match.group(1))
    return None

def clean_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    if re.search(r'\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}', date_str):
        return date_str
    if '/' in date_str or '-' in date_str:
        separator = '/' if '/' in date_str else '-'
        parts = date_str.split(separator)
        if len(parts) == 3:
            if len(parts[2]) == 2:
                parts[2] = '20' + parts[2]
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return date_str

def extract_table_data(soup):
    tables_data = []
    tables = soup.find_all("table")
    for table in tables:
        table_rows = []
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all(["td", "th"])
            if cols:
                row_data = []
                for col in cols:
                    cell_text = col.get_text(strip=True)
                    cell_text = ' '.join(cell_text.split())
                    cell_text = cell_text.replace('[dl_btn]', '').strip()
                    row_data.append(cell_text)
                table_rows.append(row_data)
        if table_rows:
            tables_data.append(table_rows)
    return tables_data

# ============================================================================
# PDF WATERMARK & HEADER
# ============================================================================
def add_watermark(canvas, doc):
    canvas.saveState()
    try:
        if os.path.exists(COMPANY_LOGO_PATH):
            img = ImageReader(COMPANY_LOGO_PATH)
            page_width, page_height = doc.pagesize
            watermark_width = page_width * 0.65
            watermark_height = watermark_width
            x = (page_width - watermark_width) / 2
            y = (page_height - watermark_height) / 2
            canvas.setFillAlpha(0.06)
            canvas.drawImage(img, x, y, width=watermark_width, height=watermark_height, preserveAspectRatio=True, mask='auto')
    except Exception as e:
        print(f"Watermark Error: {e}")
    canvas.restoreState()

def build_pdf_header(elements, styles):
    try:
        header_data = []
        if os.path.exists(COMPANY_LOGO_PATH):
            logo = Image(COMPANY_LOGO_PATH, width=50, height=50)
        else:
            logo = Paragraph("", styles['Normal'])
        company_style = ParagraphStyle('CompanyHeader', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a237e'), spaceAfter=0, leftIndent=10)
        company_name = Paragraph(f"<b>{COMPANY_NAME}</b>", company_style)
        header_data.append([logo, company_name])
        table = Table(header_data, colWidths=[60, 400])
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (0, 0), (0, 0), 'LEFT'), ('ALIGN', (1, 0), (1, 0), 'LEFT'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
        elements.append(table)
        divider = Table([[""]], colWidths=[460])
        divider.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a237e'))]))
        elements.append(divider)
        elements.append(Spacer(1, 15))
    except Exception as e:
        print("Header Error:", e)

# ============================================================================
# DATA FETCHING FUNCTIONS
# ============================================================================
def fetch_minimum_wages(state):
    try:
        url = STATE_MINIMUM_WAGE_URLS.get(state)
        if not url:
            return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        effective_date = extract_effective_date(soup)
        tables_data = extract_table_data(soup)
        html_output = ""
        tables = soup.find_all("table")
        if tables:
            for idx, table in enumerate(tables, 1):
                rows = table.find_all("tr")
                html_output += f"<h4 style='margin:15px 0 10px;'>Table {idx}</h4>"
                html_output += '<table class="minimum-wage-table">'
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    html_output += "<tr>"
                    for col in cols:
                        text = col.get_text(strip=True)
                        tag = "th" if col.name == "th" else "td"
                        html_output += f"<{tag}>{text}</{tag}>"
                    html_output += "</tr>"
                html_output += "</table>"
        else:
            html_output = "<p>No wage data table found.</p>"
        date_header = f'<div class="effective-date-banner"><div class="date-content"><i class="fas fa-calendar-check"></i><span class="date-label">EFFECTIVE DATE:</span><span class="date-value">{effective_date or "Check on website"}</span></div></div>' if effective_date else '<div class="effective-date-banner warning"><div class="date-content"><i class="fas fa-exclamation-triangle"></i><span class="date-label">EFFECTIVE DATE:</span><span class="date-value">Check on website</span></div></div>'
        state_url_encoded = state.replace(' ', '_')
        download_button = f'<div style="margin: 20px 0; text-align: right;"><button onclick="openDownloadModal(\'{state_url_encoded}\', \'minimum_wages\')" class="download-pdf-btn"><i class="fas fa-file-pdf"></i> Download as PDF</button></div>'
        final_html = f"""<div><h3 style="margin-bottom:15px;">Minimum Wages – {state.title()}</h3>{date_header}{download_button}{html_output}<div style="margin-top:20px; font-size:12px; color:#666; text-align:center; border-top:1px solid #ccc; padding-top:15px;">Source: <a href="{url}" target="_blank">slci.in/minimum-wages/{state}</a></div></div>"""
        return {"html": final_html, "effective_date": effective_date, "tables_data": tables_data, "state": state, "act_type": "Minimum_Wages"}
    except Exception as e:
        print(f"Error fetching wages for {state}: {str(e)}")
        return {"html": f"<p>Error fetching wages data for {state.title()}.</p>", "effective_date": None, "tables_data": []}

def fetch_holiday_list(state):
    try:
        url = STATE_HOLIDAY_URLS.get(state)
        if not url:
            return None
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        tables_data = extract_table_data(soup)
        tables = soup.find_all("table")
        html_output = ""
        if tables:
            for idx, table in enumerate(tables, 1):
                rows = table.find_all("tr")
                html_output += f"<h4>Holiday Table {idx}</h4>"
                html_output += '<table class="minimum-wage-table">'
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    html_output += "<tr>"
                    for col in cols:
                        text = col.get_text(strip=True)
                        tag = "th" if col.name == "th" else "td"
                        html_output += f"<{tag}>{text}</{tag}>"
                    html_output += "</tr>"
                html_output += "</table>"
        else:
            html_output = "<p>No holiday table found.</p>"
        download_state = state.replace(" ", "_")
        download_button = f'<div style="text-align:right; margin:15px 0;"><button onclick="openDownloadModal(\'{download_state}\', \'holiday_list\')" class="download-pdf-btn"><i class="fas fa-file-pdf"></i> Download Holiday List PDF</button></div>'
        final_html = f"""<div><h3>Holiday List – {state.title()}</h3>{download_button}{html_output}<div style="margin-top:20px; font-size:12px; color:#666;">Source: <a href="{url}" target="_blank">{url}</a></div></div>"""
        return {"html": final_html, "tables_data": tables_data, "state": state, "act_type": "Holiday_List", "effective_date": None}
    except Exception as e:
        print(f"Holiday Fetch Error: {e}")
        return None

def fetch_working_hours(state):
    try:
        url = STATE_WORKING_HOURS_URLS.get(state)
        if not url:
            return None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        effective_date = extract_effective_date(soup)
        tables_data = extract_table_data(soup)
        tables = soup.find_all("table")
        html_output = ""
        if tables:
            for idx, table in enumerate(tables, 1):
                rows = table.find_all("tr")
                html_output += f"<h4>Working Hours – Table {idx}</h4>"
                html_output += '<table class="minimum-wage-table">'
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    html_output += "<tr>"
                    for col in cols:
                        text = col.get_text(strip=True)
                        tag = "th" if col.name == "th" else "td"
                        html_output += f"<{tag}>{text}</{tag}>"
                    html_output += "</tr>"
                html_output += "</table>"
        else:
            html_output = "<p>No working hours table found.</p>"
        state_encoded = state.replace(" ", "_")
        download_button = f'<div style="text-align:right; margin:15px 0;"><button onclick="openDownloadModal(\'{state_encoded}\', \'working_hours\')" class="download-pdf-btn"><i class="fas fa-file-pdf"></i> Download Working Hours PDF</button></div>'
        date_header = f'<div class="effective-date-banner"><div class="date-content"><i class="fas fa-calendar-check"></i><span class="date-label">EFFECTIVE DATE:</span><span class="date-value">{effective_date}</span></div></div>' if effective_date else '<div class="effective-date-banner warning"><div class="date-content"><i class="fas fa-exclamation-triangle"></i><span class="date-label">EFFECTIVE DATE:</span><span class="date-value">Check on website</span></div></div>'
        final_html = f"""<div><h3>Working Hours – {state.title()}</h3>{date_header}{download_button}{html_output}<div style="margin-top:20px; font-size:12px; color:#666; text-align:center; border-top:1px solid #ccc; padding-top:15px;">Source: <a href="{url}" target="_blank">{url}</a></div></div>"""
        return {"html": final_html, "tables_data": tables_data, "state": state, "act_type": "Working_Hours", "effective_date": effective_date}
    except Exception as e:
        print(f"Working Hours Fetch Error: {e}")
        return None

def fetch_shop_establishment(state):
    """Fetch and filter Shop and Establishment Act data for specific state"""
    try:
        url = SHOP_ESTABLISHMENT_MAIN_URL
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        tables_data = extract_table_data(soup)
        html_output = ""
        if state is None or state.lower() == "all_states":
            html_output = "<h4>Select a State:</h4><ul style='columns:2; list-style-type:none; padding:0;'>"
            for s in sorted(STATE_VARIATIONS.keys()):
                html_output += f"<li style='padding:8px; margin:5px; background:#f5f5f5; border-radius:5px;'>📍 {s.title()}</li>"
            html_output += "</ul>"
            return {"html": html_output, "tables_data": [], "state": "All States", "act_type": "Shop_and_Establishment", "effective_date": None}
        filtered_tables = []
        state_lower = state.lower()
        if tables_data:
            for table in tables_data:
                state_found = False
                filtered_rows = []
                for row in table:
                    if row == table[0]:
                        filtered_rows.append(row)
                        continue
                    row_text = ' '.join(str(cell).lower() for cell in row)
                    if state_lower in row_text:
                        state_found = True
                        filtered_rows.append(row)
                    else:
                        for variation in STATE_VARIATIONS.get(state_lower, []):
                            if variation in row_text:
                                state_found = True
                                filtered_rows.append(row)
                                break
                if state_found and len(filtered_rows) > 1:
                    filtered_tables.append(filtered_rows)
        if not filtered_tables:
            html_output = f"""<div style="padding: 20px; text-align: center; background: #fff3cd; border-radius: 8px;"><i class="fas fa-info-circle" style="color: #856404;"></i><p style="color: #856404; margin-top: 10px;">No specific Shop & Establishment data found for <strong>{state.title()}</strong>.<br>Please check our main page for more details.</p></div>"""
        else:
            for idx, table_rows in enumerate(filtered_tables, 1):
                html_output += f"<h4 style='color:#1a237e; margin:20px 0 10px;'>Shop & Establishment Act – {state.title()}</h4>"
                html_output += '<table class="minimum-wage-table" style="width:100%; border-collapse:collapse;">'
                for row_idx, row in enumerate(table_rows):
                    html_output += "<tr>"
                    for col in row:
                        cell_text = str(col).strip()
                        tag = "th" if row_idx == 0 else "td"
                        bg_color = "#1a237e" if row_idx == 0 else "transparent"
                        text_color = "white" if row_idx == 0 else "#333"
                        html_output += f"<{tag} style='border:1px solid #ddd; padding:8px; background-color:{bg_color}; color:{text_color}; text-align:left;'>{cell_text}</{tag}>"
                    html_output += "</tr>"
                html_output += "</table>"
        state_encoded = state.replace(" ", "_")
        download_button = f'''<div style="text-align:right; margin:20px 0;"><button onclick="openDownloadModal('{state_encoded}', 'shop_establishment')" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; display: inline-flex; align-items: center; gap: 8px;"><i class="fas fa-file-pdf"></i> Download PDF for {state.title()}</button></div>'''
        final_html = f"""<div><h3 style="color:#1a237e; margin-bottom:15px;">🏢 Shop and Establishment Act – {state.title()}</h3>{download_button}{html_output}<div style="margin-top:30px; font-size:12px; color:#666; text-align:center; border-top:1px solid #ccc; padding-top:15px;">Source: <a href="{url}" target="_blank" style="color:#667eea;">slci.in/shops-and-establishments-act/</a></div></div>"""
        return {"html": final_html, "tables_data": filtered_tables if filtered_tables else tables_data, "state": state, "act_type": "Shop_and_Establishment", "effective_date": None}
    except Exception as e:
        print(f"Shop Establishment Fetch Error: {str(e)}")
        return {"html": f"""<div style="padding: 20px; text-align: center; background: #f8d7da; border-radius: 8px;"><i class="fas fa-exclamation-triangle" style="color: #721c24;"></i><p style="color: #721c24; margin-top: 10px;">Error fetching Shop & Establishment data for {state.title()}.<br>Please try again later.</p></div>""", "tables_data": [], "state": state, "act_type": "Shop_and_Establishment", "effective_date": None}

def get_fast_response(query):
    try:
        prompt = f"Question about Indian labor law: {query}\nShort answer:"
        payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.3, "max_tokens": 100, "num_predict": 100}}
        response = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=5)
        if response.status_code == 200:
            result = response.json()
            if result and 'response' in result:
                return result['response'].strip()
        return None
    except:
        return None

# ============================================================================
# EMAIL FUNCTIONS
# ============================================================================
def send_service_enquiry_email(data, enquiry_id):
    """Send formatted HTML email for service enquiry"""
    try:
        sender_email = os.getenv("EMAIL_USER", "slciaiagent@gmail.com")
        sender_password = os.getenv("EMAIL_PASSWORD", "")
        receiver_email = os.getenv("EMAIL_TO", "slciaiagent@gmail.com")
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"New Service Enquiry - {data['service']} - {enquiry_id}"
        html_body = f"""<!DOCTYPE html><html><head><style>body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}.container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}.header {{ background: linear-gradient(135deg, #1a237e 0%, #283593 100%); color: white; padding: 20px; text-align: center; }}.content {{ padding: 20px; background: #f9f9f9; }}.field {{ margin: 15px 0; padding: 10px; background: white; border-left: 4px solid #667eea; }}.label {{ font-weight: bold; color: #1a237e; }}.value {{ margin-top: 5px; }}.footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}.enquiry-id {{ background: #667eea; color: white; padding: 10px; text-align: center; font-size: 18px; }}</style></head><body><div class="container"><div class="header"><h2>📋 New Service Enquiry Received</h2></div><div class="enquiry-id">Enquiry ID: {enquiry_id}</div><div class="content"><div class="field"><div class="label">👤 Full Name:</div><div class="value">{data['fullName']}</div></div><div class="field"><div class="label">🏢 Company Name:</div><div class="value">{data['companyName']}</div></div><div class="field"><div class="label">📧 Email:</div><div class="value">{data['email']}</div></div><div class="field"><div class="label">📞 Contact Number:</div><div class="value">{data['contactNumber']}</div></div><div class="field"><div class="label">🔧 Service Interested In:</div><div class="value"><strong>{data['service']}</strong></div></div><div class="field"><div class="label">❓ Query:</div><div class="value">{data['query']}</div></div><div class="field"><div class="label">📅 Submitted On:</div><div class="value">{datetime.now().strftime('%d %B %Y at %I:%M %p')}</div></div></div><div class="footer"><p>This is an automated message from SLCI Chatbot System</p><p>© {datetime.now().year} Shakti Legal Compliance India</p></div></div></body></html>"""
        text_body = f"""New Service Enquiry Received\n============================\nEnquiry ID: {enquiry_id}\nFull Name: {data['fullName']}\nCompany Name: {data['companyName']}\nEmail: {data['email']}\nContact Number: {data['contactNumber']}\nService: {data['service']}\nQuery:\n{data['query']}\nSubmitted On: {datetime.now().strftime('%d %B %Y at %I:%M %p')}\nThis is an automated message from SLCI Chatbot System"""
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        server = smtplib.SMTP(os.getenv('EMAIL_HOST', 'smtp.gmail.com'), int(os.getenv('EMAIL_PORT', 587)))
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent successfully for enquiry {enquiry_id}")
        return True
    except Exception as e:
        print(f"❌ Email Error: {str(e)}")
        return False

def send_fee_enquiry_email(data, enquiry_id):
    """Send formatted HTML email for fee enquiry"""
    try:
        sender_email = os.getenv("EMAIL_USER", "slciaiagent@gmail.com")
        sender_password = os.getenv("EMAIL_PASSWORD", "")
        receiver_email = os.getenv("FEE_ENQUIRY_EMAIL", "slciaiagent@gmail.com")
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"💰 New Fee Enquiry - {enquiry_id}"
        html_body = f"""<!DOCTYPE html><html><head><style>body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}.container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}.header {{ background: linear-gradient(135deg, #1a237e 0%, #283593 100%); color: white; padding: 20px; text-align: center; }}.content {{ padding: 20px; background: #f9f9f9; }}.field {{ margin: 15px 0; padding: 10px; background: white; border-left: 4px solid #ff9800; }}.label {{ font-weight: bold; color: #1a237e; }}.value {{ margin-top: 5px; }}.footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}.enquiry-id {{ background: #ff9800; color: white; padding: 10px; text-align: center; font-size: 18px; }}</style></head><body><div class="container"><div class="header"><h2>💰 New Fee Enquiry Received</h2></div><div class="enquiry-id">Enquiry ID: {enquiry_id}</div><div class="content"><div class="field"><div class="label">👤 Full Name:</div><div class="value">{data['fullName']}</div></div><div class="field"><div class="label">🏢 Company Name:</div><div class="value">{data['companyName']}</div></div><div class="field"><div class="label">📧 Email:</div><div class="value">{data['email']}</div></div><div class="field"><div class="label">📞 Contact Number:</div><div class="value">{data['contactNumber']}</div></div><div class="field"><div class="label">📝 Description/Requirements:</div><div class="value">{data['description']}</div></div><div class="field"><div class="label">📅 Submitted On:</div><div class="value">{datetime.now().strftime('%d %B %Y at %I:%M %p')}</div></div></div><div class="footer"><p>This is an automated message from SLCI Chatbot System</p><p>© {datetime.now().year} Shakti Legal Compliance India</p></div></div></body></html>"""
        text_body = f"""New Fee Enquiry Received\n========================\nEnquiry ID: {enquiry_id}\nFull Name: {data['fullName']}\nCompany Name: {data['companyName']}\nEmail: {data['email']}\nContact Number: {data['contactNumber']}\nDescription:\n{data['description']}\nSubmitted On: {datetime.now().strftime('%d %B %Y at %I:%M %p')}\nThis is an automated message from SLCI Chatbot System"""
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        server = smtplib.SMTP(os.getenv('EMAIL_HOST', 'smtp.gmail.com'), int(os.getenv('EMAIL_PORT', 587)))
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Fee enquiry email sent successfully for enquiry {enquiry_id}")
        return True
    except Exception as e:
        print(f"❌ Fee Enquiry Email Error: {str(e)}")
        return False

# ============================================================================
# FLASK ROUTES
# ============================================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/test-sheets", methods=["GET"])
def test_sheets():
    """Test Google Sheets connection"""
    try:
        client = get_google_sheet_client()
        if not client:
            return jsonify({"status": "failed", "error": "Client not initialized"})
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        worksheets = spreadsheet.worksheets()
        test_sheet = spreadsheet.worksheet("Test_Sheet") if any(w.title == "Test_Sheet" for w in worksheets) else spreadsheet.add_worksheet("Test_Sheet", 10, 5)
        test_sheet.append_row(["Test", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "Success!"], value_input_option='USER_ENTERED')
        return jsonify({"status": "success", "spreadsheet": spreadsheet.title, "worksheets": [w.title for w in worksheets], "message": "Test row appended successfully"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "").lower().strip()
    if not user_message:
        return jsonify({"response": "Please type a message. How can I help you?"})
    
    # Shop & Establishment queries
    if "shop and establishment" in user_message or "shop establishment" in user_message or "shop & establishment" in user_message or "sea act" in user_message:
        state, _ = detect_state(user_message, "shop_establishment")
        if state:
            se_data = fetch_shop_establishment(state)
            return jsonify({"response": se_data["html"], "state": state, "act_type": "shop_establishment"})
        if "all states" in user_message or "list all" in user_message:
            se_data = fetch_shop_establishment("all_states")
            return jsonify({"response": se_data["html"], "state": "All States", "act_type": "shop_establishment"})
        common_states = ["Delhi", "Maharashtra", "Karnataka", "Tamil Nadu", "Uttar Pradesh"]
        suggestions = "".join([f"<li style='padding:5px;'>📍 {state}</li>" for state in common_states])
        return jsonify({"response": f"""<div style="padding:15px;"><h4 style="color:#1a237e;">Please specify a state</h4><p>Example: "Shop & Establishment Act of Delhi"</p><p>Common states:</p><ul style="list-style-type:none; padding:0;">{suggestions}</ul></div>"""})
    
    # Holiday list queries
    if "holiday" in user_message:
        state, url = detect_state(user_message, "holiday_list")
        if state:
            holiday_data = fetch_holiday_list(state)
            if holiday_data:
                return jsonify({"response": holiday_data["html"], "state": state, "act_type": "holiday_list"})
        common_states = ["Delhi", "Maharashtra", "Karnataka", "Tamil Nadu", "West Bengal"]
        suggestions = "".join([f"<li style='padding:5px;'>📅 {state}</li>" for state in common_states])
        return jsonify({"response": f"""<div style="padding:15px;"><h4 style="color:#1a237e;">Please specify a state for Holiday List</h4><p>Example: "Holiday list of Maharashtra"</p><p>Common states:</p><ul style="list-style-type:none; padding:0;">{suggestions}</ul></div>"""})
    
    # Working hours queries
    if "working hours" in user_message or "working hour" in user_message:
        state, url = detect_state(user_message, "working_hours")
        if state:
            wh_data = fetch_working_hours(state)
            if wh_data:
                return jsonify({"response": wh_data["html"], "state": state, "act_type": "working_hours"})
        common_states = ["Delhi", "Maharashtra", "Karnataka", "Gujarat", "Telangana"]
        suggestions = "".join([f"<li style='padding:5px;'>⏰ {state}</li>" for state in common_states])
        return jsonify({"response": f"""<div style="padding:15px;"><h4 style="color:#1a237e;">Please specify a state for Working Hours</h4><p>Example: "Working hours of Delhi"</p><p>Common states:</p><ul style="list-style-type:none; padding:0;">{suggestions}</ul></div>"""})
    
    # Minimum wages queries
    if "minimum wage" in user_message or "minimum wages" in user_message:
        state, url = detect_state(user_message, "minimum_wages")
        if state:
            wages_data = fetch_minimum_wages(state)
            if wages_data:
                return jsonify({"response": wages_data["html"], "state": state, "act_type": "minimum_wages"})
        common_states = ["Delhi", "Maharashtra", "Karnataka", "Tamil Nadu", "Uttar Pradesh"]
        suggestions = "".join([f"<li style='padding:5px;'>💰 {state}</li>" for state in common_states])
        return jsonify({"response": f"""<div style="padding:15px;"><h4 style="color:#1a237e;">Please specify a state for Minimum Wages</h4><p>Example: "Minimum wages of Delhi"</p><p>Common states:</p><ul style="list-style-type:none; padding:0;">{suggestions}</ul></div>"""})
    
    # Services list query
    service_keywords = ["services of slci", "what does slci do", "your services", "services you offer", "list of services", "slci services"]
    if any(phrase in user_message for phrase in service_keywords):
        services_html = """<div style="font-family: Arial, sans-serif; padding: 15px; background: linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%); border-radius: 10px; max-height: 500px; overflow-y: auto;"><h4 style="color: #1a237e; margin-bottom: 15px; display: flex; align-items: center; gap: 8px;"><i class="fas fa-briefcase" style="color: #667eea;"></i> Our Services</h4><div style="display: grid; grid-template-columns: 1fr; gap: 15px;">"""
        for service in SERVICES_DATA:
            services_html += f"""<div style="background: white; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea; box-shadow: 0 2px 5px rgba(0,0,0,0.05);"><div style="display: flex; align-items: flex-start; gap: 10px; flex-direction: column;"><h5 style="margin: 0; color: #1a237e; font-size: 16px;">{service['title']}</h5><p style="margin: 5px 0 0; color: #555; font-size: 14px; line-height: 1.5;">{service['description']}</p><button onclick="openServiceModal('{service['title']}')" style="background: #667eea; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-size: 13px; transition: all 0.3s; align-self: flex-start; margin-top: 10px;"><i class="fas fa-envelope"></i> Enquire</button></div></div>"""
        services_html += """</div><p style="margin-top: 15px; color: #666; font-size: 12px; text-align: center;">Click "Enquire" button next to any service to get detailed information</p></div>"""
        return jsonify({"response": services_html, "show_services": True})
    
    # Predefined responses using keywords
    for key, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in user_message:
                response_text = RESPONSES.get(key, "")
                if key in ["pricing", "fees", "cost"]:
                    return jsonify({"response": response_text, "show_fee_button": True})
                if key in ["epf", "esi"]:
                    enriched_response = f"""<div style="font-family: Arial, sans-serif;"><p>{response_text}</p><div style="margin-top: 15px; background: #f5f7fa; padding: 15px; border-radius: 8px;"><h4 style="color: #1a237e;">Related Services:</h4><ul style="list-style-type: none; padding: 0;"><li style="margin: 5px 0;">✅ Registration of Employees</li><li style="margin: 5px 0;">✅ Generation of Challans</li><li style="margin: 5px 0;">✅ Monthly Compliance Reports</li></ul></div></div>"""
                    return jsonify({"response": enriched_response})
                return jsonify({"response": response_text})
    
    # Try Ollama for unknown queries
    if check_ollama_connection():
        ollama_response = get_fast_response(user_message)
        if ollama_response:
            return jsonify({"response": ollama_response})
    
    # Fallback response
    return jsonify({"response": """<div style="padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #0d6efd;"><p style="margin: 0; color: #333;">Thank you for contacting <strong>Shakti Legal Compliance India</strong>.</p><p style="margin-top: 8px; color: #555;">For detailed assistance regarding your query, please contact our team.</p><div style="margin-top: 10px; color: #444;">📞 <strong>Phone:</strong> +91 9999329153<br>📧 <strong>Email:</strong> info@slci-india.com</div></div>"""})

def generate_enquiry_id(prefix="ENQ"):
    """Generate a unique enquiry ID"""
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(3).upper()
    return f"{prefix}-{date_part}-{random_part}"

@app.route("/submit-service-enquiry", methods=["POST"])
def submit_service_enquiry():
    """Handle service enquiry submission with validation, email, and database logging"""
    conn = None
    try:
        data = request.json
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'service', 'query']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Missing {field}"}), 400
        if not validate_email(data['email']):
            return jsonify({"success": False, "error": "Invalid email format"}), 400
        if not validate_phone(data['contactNumber']):
            return jsonify({"success": False, "error": "Invalid phone number"}), 400
        enquiry_id = generate_enquiry_id()
        email_sent = send_service_enquiry_email(data, enquiry_id)
        if email_sent:
            conn = get_db_connection()
            if conn:
                with conn.cursor() as cursor:
                    cursor.execute('''INSERT INTO service_enquiries (enquiry_id, full_name, company_name, email, contact_number, service, query, ip_address) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', (enquiry_id, data['fullName'], data['companyName'], data['email'], data['contactNumber'], data['service'], data['query'], request.remote_addr))
                    conn.commit()
            sheet_data = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'enquiry_id': enquiry_id, 'full_name': data['fullName'], 'company_name': data['companyName'], 'email': data['email'], 'contact_number': data['contactNumber'], 'service': data['service'], 'query': data['query'], 'ip_address': request.remote_addr, 'status': 'pending'}
            append_to_google_sheet("Service_Enquiries", sheet_data)
            return jsonify({"success": True, "message": "Enquiry submitted successfully", "enquiryId": enquiry_id})
        else:
            return jsonify({"success": False, "error": "Failed to send email. Please try again."}), 500
    except Exception as e:
        print(f"Service Enquiry Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if conn:
            release_db_connection(conn)

@app.route("/submit-fee-enquiry", methods=["POST"])
def submit_fee_enquiry():
    """Handle fee enquiry submission with validation, email, and database logging"""
    conn = None
    try:
        data = request.json
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'description']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Missing {field}"}), 400
        if not validate_email(data['email']):
            return jsonify({"success": False, "error": "Invalid email format"}), 400
        if not validate_phone(data['contactNumber']):
            return jsonify({"success": False, "error": "Invalid phone number"}), 400
        enquiry_id = generate_enquiry_id()
        email_sent = send_fee_enquiry_email(data, enquiry_id)
        if email_sent:
            conn = get_db_connection()
            if conn:
                with conn.cursor() as cursor:
                    cursor.execute('''INSERT INTO fee_enquiries (enquiry_id, full_name, company_name, email, contact_number, description, ip_address) VALUES (%s, %s, %s, %s, %s, %s, %s)''', (enquiry_id, data['fullName'], data['companyName'], data['email'], data['contactNumber'], data['description'], request.remote_addr))
                    conn.commit()
            sheet_data = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'enquiry_id': enquiry_id, 'full_name': data['fullName'], 'company_name': data['companyName'], 'email': data['email'], 'contact_number': data['contactNumber'], 'description': data['description'], 'ip_address': request.remote_addr, 'status': 'pending'}
            append_to_google_sheet("Fee_Enquiries", sheet_data)
            return jsonify({"success": True, "message": "Fee enquiry submitted successfully", "enquiryId": enquiry_id})
        else:
            return jsonify({"success": False, "error": "Failed to send email. Please try again."}), 500
    except Exception as e:
        print(f"Fee Enquiry Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if conn:
            release_db_connection(conn)

@app.route("/download/<state>/<act_type>")
def download_data(state, act_type):
    try:
        download_id = request.args.get('id')
        state_key = state.replace('_', ' ')
        if act_type == 'holiday_list':
            holiday_data = fetch_holiday_list(state_key)
            if not holiday_data:
                return jsonify({"error": "State not found"}), 404
            pdf_file = create_pdf_file(state_key, holiday_data.get("act_type", act_type), holiday_data.get("tables_data", []), holiday_data.get("effective_date"), download_id)
            filename = f"Holiday_List_{state}.pdf"
            return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
        elif act_type == 'minimum_wages':
            matched_state = None
            for key in STATE_MINIMUM_WAGE_URLS.keys():
                if key == state_key or key.replace(' ', '_') == state:
                    matched_state = key
                    break
            if not matched_state:
                return jsonify({"error": "State not found"}), 404
            act_data = fetch_minimum_wages(matched_state)
            if not act_data:
                return jsonify({"error": "No data available"}), 404
            pdf_file = create_pdf_file(matched_state, act_data.get("act_type", act_type), act_data.get("tables_data", []), act_data.get("effective_date"), download_id)
            filename = f"Minimum_Wages_{matched_state.replace(' ', '_')}.pdf"
            return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
        elif act_type == 'working_hours':
            matched_state = None
            for key in STATE_WORKING_HOURS_URLS.keys():
                if key == state_key or key.replace(' ', '_') == state:
                    matched_state = key
                    break
            if not matched_state:
                return jsonify({"error": "State not found"}), 404
            wh_data = fetch_working_hours(matched_state)
            if not wh_data:
                return jsonify({"error": "No data available"}), 404
            pdf_file = create_pdf_file(matched_state, wh_data.get("act_type", act_type), wh_data.get("tables_data", []), wh_data.get("effective_date"), download_id)
            filename = f"Working_Hours_{matched_state.replace(' ', '_')}.pdf"
            return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
        elif act_type == 'shop_establishment':
            matched_state = None
            for key in STATE_VARIATIONS.keys():
                if key == state_key or key.replace(' ', '_') == state:
                    matched_state = key
                    break
            if not matched_state:
                matched_state = state_key
            se_data = fetch_shop_establishment(matched_state)
            if not se_data:
                return jsonify({"error": "No data available"}), 404
            pdf_file = create_pdf_file(matched_state, se_data.get("act_type", act_type), se_data.get("tables_data", []), se_data.get("effective_date"), download_id)
            filename = f"Shop_Establishment_{matched_state.replace(' ', '_')}.pdf"
            return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
        else:
            return jsonify({"error": "Invalid act type"}), 404
    except Exception as e:
        print(f"Download error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/submit-enquiry", methods=["POST"])
def submit_enquiry():
    """Handle general enquiry submission"""
    try:
        data = request.json
        required = ['fullName', 'email', 'contactNumber', 'query']
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Missing {field}"}), 400
        if not validate_email(data['email']):
            return jsonify({"success": False, "error": "Invalid email"}), 400
        if not validate_phone(data['contactNumber']):
            return jsonify({"success": False, "error": "Invalid phone"}), 400
        sheet_data = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'full_name': data['fullName'], 'email': data['email'], 'contact_number': data['contactNumber'], 'query': data['query']}
        append_to_google_sheet("Enquiries", sheet_data)
        return jsonify({"success": True, "message": "Enquiry submitted successfully!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/check-ollama", methods=["GET"])
def check_ollama_status():
    is_running = check_ollama_connection()
    return jsonify({"status": "connected" if is_running else "disconnected", "model": OLLAMA_MODEL if is_running else None})

@app.route("/states/<act_type>", methods=["GET"])
def get_states(act_type):
    if act_type == 'minimum_wages':
        states = list(STATE_MINIMUM_WAGE_URLS.keys())
    elif act_type == 'holiday_list':
        states = list(STATE_HOLIDAY_URLS.keys())
    elif act_type == 'working_hours':
        states = list(STATE_WORKING_HOURS_URLS.keys())
    elif act_type == 'shop_establishment':
        states = list(STATE_VARIATIONS.keys())
    else:
        states = []
    return jsonify({"states": states, "act_type": act_type})

@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "python_version": sys.version})

# ============================================================================
# STATE URL DICTIONARIES (Complete List)
# ============================================================================
STATE_MINIMUM_WAGE_URLS = {
    "delhi": "https://www.slci.in/minimum-wages/delhi/",
    "andhra pradesh": "https://www.slci.in/minimum-wages/andhra-pradesh/",
    "assam": "https://www.slci.in/minimum-wages/assam/",
    "bihar": "https://www.slci.in/minimum-wages/bihar/",
    "chandigarh": "https://www.slci.in/minimum-wages/chandigarh/",
    "chhattisgarh": "https://www.slci.in/minimum-wages/chhattisgarh/",
    "goa": "https://www.slci.in/minimum-wages/goa/",
    "gujarat": "https://www.slci.in/minimum-wages/gujarat/",
    "haryana": "https://www.slci.in/minimum-wages/haryana/",
    "himachal pradesh": "https://www.slci.in/minimum-wages/himachal-pradesh/",
    "jammu and kashmir": "https://www.slci.in/minimum-wages/jammu-and-kashmir/",
    "jharkhand": "https://www.slci.in/minimum-wages/jharkhand/",
    "karnataka": "https://www.slci.in/minimum-wages/karnataka/",
    "kerala": "https://www.slci.in/minimum-wages/kerala/",
    "ladakh": "https://www.slci.in/minimum-wages/ladakh/",
    "madhya pradesh": "https://www.slci.in/minimum-wages/madhya-pradesh/",
    "maharashtra": "https://www.slci.in/minimum-wages/maharashtra/",
    "manipur": "https://www.slci.in/minimum-wages/manipur/",
    "meghalaya": "https://www.slci.in/minimum-wages/meghalaya/",
    "mizoram": "https://www.slci.in/minimum-wages/mizoram/",
    "nagaland": "https://www.slci.in/minimum-wages/nagaland/",
    "odisha": "https://www.slci.in/minimum-wages/odisha/",
    "puducherry": "https://www.slci.in/minimum-wages/puducherry/",
    "punjab": "https://www.slci.in/minimum-wages/punjab/",
    "rajasthan": "https://www.slci.in/minimum-wages/rajasthan/",
    "sikkim": "https://www.slci.in/minimum-wages/sikkim/",
    "tamil nadu": "https://www.slci.in/minimum-wages/tamil-nadu/",
    "telangana": "https://www.slci.in/minimum-wages/telangana/",
    "tripura": "https://www.slci.in/minimum-wages/tripura/",
    "uttar pradesh": "https://www.slci.in/minimum-wages/uttar-pradesh/",
    "uttarakhand": "https://www.slci.in/minimum-wages/uttarakhand/",
    "west bengal": "https://www.slci.in/minimum-wages/west-bengal/"
}

STATE_HOLIDAY_URLS = {
    "andaman and nicobar": "https://www.slci.in/andaman-and-nicobar-islands-holiday-list/",
    "andhra pradesh": "https://www.slci.in/andhra-pradesh-holiday-list/",
    "arunachal pradesh": "https://www.slci.in/arunachal-pradesh-holiday-list/",
    "assam": "https://www.slci.in/assam-holiday-list/",
    "bihar": "https://www.slci.in/bihar-holiday-list/",
    "chandigarh": "https://www.slci.in/chandigarh-holiday-list/",
    "chhattisgarh": "https://www.slci.in/chhattisgarh-holiday-list/",
    "daman and diu": "https://www.slci.in/daman-and-diu-holiday-list/",
    "delhi": "https://www.slci.in/delhi-holiday-list/",
    "goa": "https://www.slci.in/goa-holiday-list/",
    "gujarat": "https://www.slci.in/gujarat-holiday-list/",
    "haryana": "https://www.slci.in/haryana-holiday-list/",
    "himachal pradesh": "https://www.slci.in/himachal-pradesh-holiday-list/",
    "jammu and kashmir": "https://www.slci.in/jammu-and-kashmir-holiday-list/",
    "jharkhand": "https://www.slci.in/jharkhand-holiday-list/",
    "karnataka": "https://www.slci.in/karnataka-holiday-list/",
    "kerala": "https://www.slci.in/kerala-holiday-list/",
    "maharashtra": "https://www.slci.in/maharashtra-holiday-list/",
    "manipur": "https://www.slci.in/manipur-holiday-list/",
    "meghalaya": "https://www.slci.in/meghalaya-holiday-list/",
    "mizoram": "https://www.slci.in/mizoram-holiday-list/",
    "madhya pradesh": "https://www.slci.in/madhya-pradesh-holiday-list/",
    "nagaland": "https://www.slci.in/nagaland-holiday-list/",
    "odisha": "https://www.slci.in/odisha-holiday-list/",
    "puducherry": "https://www.slci.in/puducherry-holiday-list/",
    "punjab": "https://www.slci.in/punjab-holiday-list/",
    "rajasthan": "https://www.slci.in/rajasthan-holiday-list/",
    "sikkim": "https://www.slci.in/sikkim-holiday-list/",
    "tamil nadu": "https://www.slci.in/tamil-nadu-holiday-list/",
    "telangana": "https://www.slci.in/telangana-holiday-list/",
    "tripura": "https://www.slci.in/tripura-holiday-list/",
    "uttar pradesh": "https://www.slci.in/uttar-pradesh-holiday-list/",
    "uttarakhand": "https://www.slci.in/uttarakhand-holiday-list/",
    "west bengal": "https://www.slci.in/west-bengal-holiday-list/"
}

STATE_WORKING_HOURS_URLS = {
    "andaman and nicobar": "https://www.slci.in/andaman-and-nicobar-islands-working-hours/",
    "andhra pradesh": "https://www.slci.in/andhra-pradesh-working-hours/",
    "assam": "https://www.slci.in/assam-working-hours/",
    "bihar": "https://www.slci.in/bihar-working-hours/",
    "chandigarh": "https://www.slci.in/chandigarh-working-hours/",
    "chhattisgarh": "https://www.slci.in/chhattisgarh-working-hours/",
    "dadra and nagar haveli": "https://www.slci.in/dadra-and-nagar-haveli-working-hours/",
    "daman and diu": "https://www.slci.in/daman-and-diu-working-hours/",
    "delhi": "https://www.slci.in/delhi-working-hours/",
    "goa": "https://www.slci.in/goa-working-hours/",
    "gujarat": "https://www.slci.in/gujarat-working-hours/",
    "haryana": "https://www.slci.in/haryana-working-hours/",
    "himachal pradesh": "https://www.slci.in/himachal-pradesh-working-hours/",
    "jammu and kashmir": "https://www.slci.in/jammu-and-kashmir-working-hours/",
    "jharkhand": "https://www.slci.in/jharkhand-working-hours/",
    "karnataka": "https://www.slci.in/karnataka-working-hours/",
    "kerala": "https://www.slci.in/kerala-working-hours/",
    "maharashtra": "https://www.slci.in/maharashtra-working-hours/",
    "manipur": "https://www.slci.in/manipur-working-hours/",
    "meghalaya": "https://www.slci.in/meghalaya-working-hours/",
    "madhya pradesh": "https://www.slci.in/madhya-pradesh-working-hours/",
    "nagaland": "https://www.slci.in/nagaland-working-hours/",
    "odisha": "https://www.slci.in/odisha-working-hours/",
    "puducherry": "https://www.slci.in/puducherry-working-hours/",
    "punjab": "https://www.slci.in/punjab-working-hours/",
    "rajasthan": "https://www.slci.in/rajasthan-working-hours/",
    "sikkim": "https://www.slci.in/sikkim-working-hours/",
    "telangana": "https://www.slci.in/telangana-working-hours/",
    "tamil nadu": "https://www.slci.in/tamil-nadu-working-hours/",
    "tripura": "https://www.slci.in/tripura-working-hours/",
    "uttar pradesh": "https://www.slci.in/uttar-pradesh-working-hours/",
    "uttarakhand": "https://www.slci.in/uttarakhand-working-hours/",
    "west bengal": "https://www.slci.in/west-bengal-working-hours/"
}

SHOP_ESTABLISHMENT_MAIN_URL = "https://www.slci.in/shops-and-establishments-act/"

STATE_VARIATIONS = {
    "andaman and nicobar": ["andaman", "nicobar", "andaman and nicobar", "andaman & nicobar"],
    "andhra pradesh": ["andhra pradesh", "andhra", "visakhapatnam", "vizag"],
    "assam": ["assam", "guwahati", "dispur"],
    "bihar": ["bihar", "patna", "gaya"],
    "chandigarh": ["chandigarh"],
    "chhattisgarh": ["chhattisgarh", "raipur", "bilaspur"],
    "dadra and nagar haveli": ["dadra", "nagar haveli", "dadra and nagar haveli"],
    "daman and diu": ["daman", "diu", "daman and diu"],
    "delhi": ["delhi", "dilli", "nct of delhi", "new delhi"],
    "goa": ["goa", "panaji", "panjim", "margao"],
    "gujarat": ["gujarat", "ahmedabad", "surat", "vadodara", "baroda"],
    "haryana": ["haryana", "gurgaon", "gurugram", "faridabad", "panipat"],
    "himachal pradesh": ["himachal pradesh", "hp", "shimla", "manali"],
    "jammu and kashmir": ["jammu and kashmir", "j&k", "srinagar", "jammu"],
    "jharkhand": ["jharkhand", "ranchi", "jamshedpur"],
    "karnataka": ["karnataka", "bangalore", "bengaluru", "mysore", "mangalore"],
    "kerala": ["kerala", "kochi", "trivandrum", "thiruvananthapuram", "calicut"],
    "madhya pradesh": ["madhya pradesh", "mp", "bhopal", "indore", "gwalior"],
    "maharashtra": ["maharashtra", "mumbai", "pune", "nagpur", "thane"],
    "manipur": ["manipur", "imphal"],
    "meghalaya": ["meghalaya", "shillong"],
    "mizoram": ["mizoram", "aizawl"],
    "nagaland": ["nagaland", "kohima", "dimapur"],
    "odisha": ["odisha", "orissa", "bhubaneswar", "cuttack"],
    "pondicherry": ["pondicherry", "puducherry"],
    "punjab": ["punjab", "chandigarh", "ludhiana", "amritsar", "jalandhar"],
    "rajasthan": ["rajasthan", "jaipur", "jodhpur", "udaipur", "kota"],
    "sikkim": ["sikkim", "gangtok"],
    "tamil nadu": ["tamil nadu", "tamilnadu", "chennai", "madras", "coimbatore"],
    "telangana": ["telangana", "hyderabad", "secunderabad"],
    "tripura": ["tripura", "agartala"],
    "uttar pradesh": ["uttar pradesh", "up", "lucknow", "kanpur", "agra", "varanasi"],
    "uttarakhand": ["uttarakhand", "dehradun", "haridwar", "nainital"],
    "west bengal": ["west bengal", "bengal", "kolkata", "calcutta", "howrah"]
}

# ============================================================================
# UPDATED SERVICES DATA (With Descriptions)
# ============================================================================
SERVICES_DATA = [
    {"title": "Labour Law Compliances", "description": "SLCI is a specialist Labour Law Compliance firm with over three decades of experience, helping businesses ensure 100% statutory compliance and risk-free operations through audits, SOP guidance, and periodic compliance support. We provide expert assistance across EPF, ESI, Minimum Wages, Gratuity, POSH, Contract Labour, and other key enactments."},
    {"title": "Labour Law Auditing", "description": "SLCI provides comprehensive Auditing & Assurance services to identify statutory compliance gaps, uncover risk exposures, and prevent costly penalties. Our audits include document checklists, critical analysis, detailed reports, and customized risk-elimination strategies."},
    {"title": "Labour Law Consultation", "description": "SLCI offers expert Labour Law Consultancy, delivering practical and long-term solutions for statutory compliance, due diligence, and risk-free business operations. We support startups, growing businesses, and organizations undergoing mergers or expansions across all industries."},
    {"title": "HR Solution", "description": "SLCI provides comprehensive HR Consulting services, helping businesses design compliant, structured, and cost-effective HR policies and systems. We assist with HR, Leave, POSH, and Work From Home policies, CTC structuring, ICC formation, and NDA agreements."},
    {"title": "ESI & EPF", "description": "SLCI provides end-to-end ESI & EPF Compliance services, ensuring accurate contributions, timely filings, and complete statutory adherence. Our support includes employee registration, UAN generation, challans, KYC approvals, inspections, and automated monthly reports."},
    {"title": "Payroll Compliance", "description": "SLCI provides customised Payroll Compliance solutions, ensuring accurate wage structuring, statutory compliance, and error-free payroll processing. Our technology-driven system offers real-time tracking, digital records, and dedicated payroll support."},
    {"title": "Recruitment", "description": "Identifying and hiring the right talent aligned with your company's skills, culture, and business objectives."},
    {"title": "Background Verification", "description": "Verifying candidate credentials, employment history, and records to ensure authenticity and reduce hiring risks."},
    {"title": "Staffing", "description": "Providing skilled manpower solutions to meet short-term, long-term, or project-based workforce requirements."}
]

# ============================================================================
# ESI & EPF INFORMATION
# ============================================================================
ESI_EPF_INFO = {
    "overview": """<div style="font-family: Arial, sans-serif; line-height: 1.6;"><h4 style="color: #1a237e; margin-bottom: 15px;">ESI and EPF Compliance Services</h4><p>We at SLCI have in-house experts and consultants along with high tech and unique software that ensures 100% compliance to legislations. We holistically guide our clients and educate them about protocols of ESI and EPF with aid of frequent educational webinars.</p><p>We have a fully automated tech-driven system that helps us complete all ESI and EPF compliances well in time. SLCI ensures all its clients are updated with latest amendments and provides a monthly calendar checklist for ease of remembering the important dates.</p></div>""",
    "services": ["Registration of Employees", "Generation of UAN no.", "KYC Digital Approvals", "Generation of Challans", "Other online support services including changes in any employee details", "Guidance and Maintenance of Statutory Records and submission of Statutory returns from time to time", "To provide support in ESI and provident fund inspections in the completion of Statutory provisions", "Fully automated support wherein monthly reports are sent out to our clients"]
}

# ============================================================================
# PREDEFINED RESPONSES
# ============================================================================
RESPONSES = {
    "what is slci": "SLCI (Shakti Legal Compliance India) is a premier legal compliance consultancy firm established to help businesses navigate complex Indian labor laws and regulations.",
    "full form of slci": "SLCI stands for Shakti Legal Compliance India. 'Shakti' represents strength in Sanskrit.",
    "contact number": "📞 Mobile: +91 9999329153 | Mobile :- 8373917131",
    "email": "info@slci-india.com",
    "address": """<div style="background: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #667eea;"><h3 style="color: #667eea; margin-top: 0;">📍 Our Office Address</h3><p style="color: #333; font-size: 16px; line-height: 1.6; margin: 15px 0;">83, DSIDC COMPLEX,<br>Okhla I Rd, Pocket C,<br>Okhla Phase I, Okhla Industrial Estate,<br>New Delhi, Delhi 110020</p><div style="margin: 20px 0; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);"><iframe src="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3502.1234567890123!2d77.2818578!3d28.525507!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x390ce1b166f71281%3A0x78602061339ccb61!2sShakti%20Legal%20Compliance%20India%20(SLCI)!5e0!3m2!1sen!2sin!4v1234567890123!5m2!1sen!2sin" width="100%" height="300" style="border:0;" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe></div><div style="text-align: center; margin-top: 20px;"><a href="https://www.google.com/maps/place/Shakti+Legal+Compliance+India+(SLCI)/@28.5253303,77.2827107,18z/data=!3m1!4b1!4m6!3m5!1s0x390ce1b166f71281:0x78602061339ccb61!8m2!3d28.525507!4d77.2818578!16s%2Fg%2F11j0ww1tn5?entry=ttu" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 30px; text-decoration: none; border-radius: 25px; font-weight: 600; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4); transition: all 0.3s ease;">🗺️ Click here to open in Google Maps</a></div></div>""",
    "timing": """<div style="background: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #667eea;"><h3 style="color: #667eea; margin-top: 0;">🕒 Office Timing</h3><p style="color: #333; font-size: 16px; line-height: 1.8; margin: 15px 0;"><strong>Monday - Saturday:</strong> 9:00 AM to 6:00 PM<br><strong>Sunday:</strong> Closed</p><p style="color: #666; font-size: 14px; margin-top: 15px; font-style: italic;">* We recommend scheduling appointments in advance for personalized consultation.</p></div>""",
    "why slci": """<div style="background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%); padding: 25px; border-radius: 12px; border: 1px solid #667eea30;"><h3 style="color: #667eea; margin-top: 0;">✨ Why Choose SLCI?</h3><div style="margin: 20px 0;"><p style="color: #333; font-size: 18px; font-weight: 600; margin: 10px 0;">🏆 38+ Years of Experience in the Field of Law</p><p style="color: #555; font-size: 15px; line-height: 1.7; margin: 15px 0;">We help clients achieve their goals by providing <strong>high-quality, ethically sound legal counsel</strong> and <strong>strategic advice</strong> tailored to your business needs.</p></div><div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0;"><div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08);"><strong style="color: #667eea;">✅</strong> Expert Legal Team</div><div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08);"><strong style="color: #667eea;">✅</strong> Pan-India Coverage</div><div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08);"><strong style="color: #667eea;">✅</strong> 24/7 Support</div><div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08);"><strong style="color: #667eea;">✅</strong> Cost-Effective Solutions</div></div><p style="color: #667eea; font-weight: 500; margin-top: 20px; text-align: center;">🤝 Your Compliance Partner for Growth & Peace of Mind</p></div>""",
    "minimum wages": "Minimum wages vary by state. Please specify a state (e.g., 'Minimum wages of Delhi').",
    "working hours": "Working hours vary by state. Please specify a state (e.g., 'Working hours of Delhi').",
    "holiday list": "Holiday lists vary by state. Please specify a state (e.g., 'Holiday list of Maharashtra').",
    "shop establishment": "Shop and Establishment Act rules vary by state. Please specify a state (e.g., 'Shop and Establishment Act of Delhi') or ask for the general list.",
    "epf": "EPF is mandatory for establishments with 20+ employees. Employee contribution: 12% of Basic + DA",
    "esi": "ESI applies to establishments with 10+ employees. Total contribution: 4% of wages",
    "gratuity": "Gratuity is payable after 5 years of continuous service. Formula: (Last salary × 15 × Years) / 26",
    "bonus": "Annual bonus of 8.33% to 20% of salary under Payment of Bonus Act",
    "pricing": "Our service fees are customized based on your business size, industry, and compliance requirements. Please click the button below to submit your enquiry. Our team will provide a detailed quotation within 24 hours.",
    "fees": "Our service fees are customized based on your business size, industry, and compliance requirements. Please click the button below to submit your enquiry, and our team will provide a detailed quotation within 24 hours.",
    "cost": "Our service fees are customized based on your business size, industry, and compliance requirements. Please click the button below to submit your enquiry, and our team will provide a detailed quotation within 24 hours.",
    "website": "www.slci.in | Blog: www.slci.in/blog | Knowledge Centre: www.slci.in/knowledge-centre"
}

# ============================================================================
# KEYWORDS FOR INTENT DETECTION
# ============================================================================
KEYWORDS = {
    "what is slci": ["what is slci", "about slci", "tell me about slci", "slci meaning", "who is slci"],
    "full form of slci": ["full form", "stands for", "slci full form", "slci expansion"],
    "contact number": ["contact number", "phone number", "call", "helpline", "mobile", "telephone", "whatsapp"],
    "email": ["email", "mail", "email id", "email address", "write to us"],
    "address": ["address", "location", "office", "headquarter", "noida", "delhi office", "where are you"],
    "timing": ["timing", "office hours", "working hours", "open time", "close time", "what time", "business hours", "monday to saturday", "9 to 6"],
    "why slci": ["why slci", "why choose slci", "why does slci work", "why work with slci", "slci advantage", "slci benefits", "why trust slci", "slci experience", "slci expertise"],
    "minimum wages": ["minimum wage", "wages", "wage rate", "salary", "minimum salary"],
    "epf": ["epf", "provident fund", "pf", "pension", "employee provident fund"],
    "esi": ["esi", "insurance", "employee state", "medical", "esi scheme"],
    "gratuity": ["gratuity", "gratuity amount", "gratuity calculation"],
    "bonus": ["bonus", "annual bonus", "bonus act"],
    "working hours": ["working hours", "work hours", "daily hours", "shift timing"],
    "holiday list": ["holiday", "holiday list", "public holiday", "national holiday", "bank holiday"],
    "shop establishment": ["shop and establishment", "shop establishment act", "sea act", "commercial establishment", "shop license"],
    "pricing": ["pricing", "price", "cost", "fee", "fees", "charges", "how much", "quotation", "quote", "package", "plans", "subscription"],
    "fees": ["fees", "fee structure", "service fees", "consulting fees", "charges", "professional fees"],
    "cost": ["cost", "cost of services", "how much does it cost", "pricing details", "service cost"],
    "website": ["website", "site", "web", "url", "online", "portal"]
}

# ============================================================================
# INPUT VALIDATION & SANITIZATION
# ============================================================================
def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    clean_phone = re.sub(r'[\s\-\(\)\+]', '', phone)
    pattern = r'^[6-9]\d{9}$'
    return re.match(pattern, clean_phone) is not None

def sanitize_input(text):
    if not text:
        return text
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return text.strip()

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    
    # Initialize database
    init_db()
    
    # Check services
    if check_ollama_connection():
        print(f"✅ Connected to Ollama: {OLLAMA_MODEL}")
    else:
        print("⚠️ Ollama not available - using keyword responses")
    
    if GOOGLE_SHEET_ENABLED:
        print(f"✅ Google Sheets enabled: {GOOGLE_SHEET_ID}")
        if os.path.exists(GOOGLE_CREDENTIALS_PATH):
            print(f"✅ Credentials found: {GOOGLE_CREDENTIALS_PATH}")
        else:
            print(f"⚠️ Credentials file missing: {GOOGLE_CREDENTIALS_PATH}")
    
    print(f"🚀 Starting Flask server on port {port} (Python {sys.version})")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)