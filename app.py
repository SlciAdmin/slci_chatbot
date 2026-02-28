
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
from datetime import datetime, timezone, timedelta
from functools import wraps
from threading import Lock

# Load environment variables FIRST
from dotenv import load_dotenv
load_dotenv()

# Flask imports
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

# Web scraping
import requests
from bs4 import BeautifulSoup

# ✅ psycopg 3.x imports (Python 3.14 compatible)
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

# Email imports
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename

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
# TIMEZONE HELPER (IST - Indian Standard Time)
# ============================================================================
def get_ist_now():
    """Returns current datetime in IST (UTC+5:30) as naive datetime for DB storage"""
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).replace(tzinfo=None)

# ============================================================================
# DATABASE CONNECTION POOL - FIXED & COMPLETE
# ============================================================================
db_pool = None  # Module level variable

def get_db_pool():
    """Get database connection pool - FIXED for Render"""
    global db_pool
    if db_pool is None:
        try:
            # Try DATABASE_URL first
            database_url = os.getenv('DATABASE_URL')
            
            if database_url:
                # Fix postgres:// vs postgresql://
                if database_url.startswith('postgres://'):
                    database_url = database_url.replace('postgres://', 'postgresql://', 1)
                
                # Ensure sslmode is set
                if 'sslmode' not in database_url:
                    separator = '&' if '?' in database_url else '?'
                    database_url += f"{separator}sslmode=require"
            else:
                # Build from individual params
                database_url = (
                    f"postgresql://{DB_USER}:{DB_PASSWORD}@"
                    f"{DB_HOST}:{DB_PORT}/{DB_NAME}"
                    f"?sslmode=require"
                )
            
            print(f"🔌 Connecting to: {database_url[:50]}...")
            
            # Create pool with proper settings for Render
            db_pool = ConnectionPool(
                conninfo=database_url,
                min_size=1,
                max_size=5,
                open=True,
                timeout=30,
                max_waiting=3,
                max_lifetime=600,
                kwargs={
                    'sslmode': 'require',
                    'sslrootcert': None
                }
            )
            
            # Test immediately
            with db_pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    print("✅ Database connection successful!")
            
            return db_pool
            
        except Exception as e:
            print(f"❌ Database pool creation failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    return db_pool

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================
def init_db():
    """Create all tables if they don't exist - UPDATED: Removed DEFAULT CURRENT_TIMESTAMP"""
    try:
        print("📊 Initializing database tables...")
        
        pool = get_db_pool()
        if not pool:
            print("❌ Cannot initialize DB - no connection pool")
            return False
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Create downloads table
                cur.execute("""
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
                        download_date TIMESTAMP,
                        pdf_generated BOOLEAN DEFAULT FALSE,
                        pdf_path TEXT
                    )
                """)
                
                # Create service enquiries table
                cur.execute("""
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
                        submission_date TIMESTAMP,
                        email_sent BOOLEAN DEFAULT TRUE,
                        notes TEXT
                    )
                """)
                
                # Create fee enquiries table
                cur.execute("""
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
                        submission_date TIMESTAMP,
                        email_sent BOOLEAN DEFAULT TRUE,
                        notes TEXT
                    )
                """)
                
                # Create download stats table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS download_stats (
                        id SERIAL PRIMARY KEY,
                        state TEXT NOT NULL,
                        act_type TEXT NOT NULL,
                        download_count INTEGER DEFAULT 0,
                        last_download TIMESTAMP,
                        UNIQUE(state, act_type)
                    )
                """)
                
                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_downloads_email ON downloads(email)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_downloads_date ON downloads(download_date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_enquiries_email ON service_enquiries(email)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fee_enquiries_email ON fee_enquiries(email)")
                
                conn.commit()
                
                # Verify tables
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = cur.fetchall()
                print(f"✅ Tables in database: {[t[0] for t in tables]}")
                
        print("✅ Database tables initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# DEPRECATED CONNECTION FUNCTIONS (for backward compatibility)
# ============================================================================
def get_db_connection():
    """DEPRECATED: Use pool.connection() context manager instead"""
    global db_pool
    try:
        pool = get_db_pool()
        if pool:
            return pool.getconn()
        return None
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return None

def release_db_connection(conn):
    """DEPRECATED: Use pool.connection() context manager instead"""
    global db_pool
    if conn and db_pool:
        try:
            db_pool.putconn(conn)
        except Exception as e:
            print(f"⚠️ Error releasing connection: {e}")

# ============================================================================
# GOOGLE SHEETS CONNECTION
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
            normalized_data['timestamp'] = get_ist_now().strftime('%Y-%m-%d %H:%M:%S')
        
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
    """Log download to database"""
    try:
        pool = get_db_pool()
        if not pool:
            print("⚠️ No database pool available")
            return None
        
        # Use context manager instead of manual connection management
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO downloads 
                    (full_name, company_name, email, contact_number, designation, rating, state, act_type, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    data['fullName'], 
                    data['companyName'], 
                    data['email'], 
                    data['contactNumber'], 
                    data.get('designation', 'Not Provided'),
                    int(data.get('rating', 0)),
                    data['state'], 
                    data['actType'], 
                    ip_address, 
                    user_agent
                ))
                download_id = cur.fetchone()[0]
                
                # Update stats
                cur.execute("""
                    INSERT INTO download_stats (state, act_type, download_count, last_download)
                    VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(state, act_type) DO UPDATE 
                    SET download_count = download_stats.download_count + 1, 
                        last_download = CURRENT_TIMESTAMP
                """, (data['state'], data['actType']))
                
                conn.commit()
                print(f"✅ Download logged: ID {download_id}")
                return download_id
                
    except Exception as e:
        print(f"❌ Download logging error: {e}")
        import traceback
        traceback.print_exc()
        return None
    
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


@app.route("/test-db-connection", methods=["GET"])
def test_db_connection():
    """Test database connection"""
    try:
        print("🔍 Testing database connection...")
        print(f"DB_HOST: {DB_HOST}")
        print(f"DB_NAME: {DB_NAME}")
        print(f"DB_USER: {DB_USER}")
        
        pool = get_db_pool()
        if not pool:
            return jsonify({"status": "error", "message": "No connection pool"})
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Test basic query
                cur.execute("SELECT 1")
                result = cur.fetchone()
                
                # Check tables
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = [t[0] for t in cur.fetchall()]
                
                # Check recent service_enquiries
                cur.execute("""
                    SELECT COUNT(*) FROM service_enquiries
                """)
                count = cur.fetchone()[0]
                
                return jsonify({
                    "status": "success",
                    "connection": "OK",
                    "test_result": result,
                    "tables": tables,
                    "service_enquiries_count": count,
                    "database": DB_NAME,
                    "host": DB_HOST
                })
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500

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
    """Fetch and filter Shop and Establishment Act data for specific state - FIXED"""
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
        state_lower = state.lower().strip()
        
        # Create exact match patterns for each state
        exact_state_variations = STATE_VARIATIONS.get(state_lower, [state_lower])
        
        if tables_data:
            for table in tables_data:
                state_found = False
                filtered_rows = []
                
                for row_idx, row in enumerate(table):
                    if row_idx == 0:  # Keep header row
                        filtered_rows.append(row)
                        continue
                    
                    row_text = ' '.join(str(cell).lower() for cell in row)
                    
                    # FIX: Use exact matching instead of substring matching
                    row_words = set(re.findall(r'\b\w+\b', row_text))
                    
                    for variation in exact_state_variations:
                        variation_lower = variation.lower()
                        
                        # Check if variation exists as a whole word
                        if (variation_lower in row_words or 
                            f" {variation_lower} " in f" {row_text} " or
                            variation_lower == row_text.strip()):
                            state_found = True
                            filtered_rows.append(row)
                            break
                        
                        # Handle multi-word variations
                        if ' ' in variation_lower:
                            # For multi-word, check if all words appear in order
                            if variation_lower in row_text:
                                state_found = True
                                filtered_rows.append(row)
                                break
                
                if state_found and len(filtered_rows) > 1:
                    filtered_tables.append(filtered_rows)
        
        if not filtered_tables:
            html_output = f"""<div style="padding: 20px; text-align: center; background: #fff3cd; border-radius: 8px;">
                <i class="fas fa-info-circle" style="color: #856404;"></i>
                <p style="color: #856404; margin-top: 10px;">No specific Shop & Establishment data found for <strong>{state.title()}</strong>.<br>
                Please check our main page for more details.</p>
            </div>"""
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
        download_button = f'''<div style="text-align:right; margin:20px 0;">
            <button onclick="openDownloadModal('{state_encoded}', 'shop_establishment')" 
                style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; 
                border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; 
                display: inline-flex; align-items: center; gap: 8px;">
                <i class="fas fa-file-pdf"></i> Download PDF for {state.title()}
            </button>
        </div>'''
        
        final_html = f"""<div>
            <h3 style="color:#1a237e; margin-bottom:15px;">🏢 Shop and Establishment Act – {state.title()}</h3>
            {download_button}
            {html_output}
            <div style="margin-top:30px; font-size:12px; color:#666; text-align:center; border-top:1px solid #ccc; padding-top:15px;">
                Source: <a href="{url}" target="_blank" style="color:#667eea;">slci.in/shops-and-establishments-act/</a>
            </div>
        </div>"""
        
        return {"html": final_html, "tables_data": filtered_tables if filtered_tables else tables_data, "state": state, "act_type": "Shop_and_Establishment", "effective_date": None}
    
    except Exception as e:
        print(f"Shop Establishment Fetch Error: {str(e)}")
        return {"html": f"""<div style="padding: 20px; text-align: center; background: #f8d7da; border-radius: 8px;">
            <i class="fas fa-exclamation-triangle" style="color: #721c24;"></i>
            <p style="color: #721c24; margin-top: 10px;">Error fetching Shop & Establishment data for {state.title()}.<br>
            Please try again later.</p>
        </div>""", "tables_data": [], "state": state, "act_type": "Shop_and_Establishment", "effective_date": None}
    
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
# ============================================================================
# EMAIL FUNCTIONS - PRODUCTION READY FOR RENDER + GMAIL
# ============================================================================
# ============================================================================
# EMAIL FUNCTIONS - FIXED FOR RENDER (SMTP_SSL Port 465)
# ============================================================================

def send_service_enquiry_email(data, enquiry_id):
    """Send formatted HTML email for service enquiry - Render fixed (Port 465)"""
    try:
        sender_email = os.getenv("EMAIL_USER", "slciaiagent@gmail.com")
        sender_password = os.getenv("EMAIL_PASSWORD", "")
        receiver_email = os.getenv("EMAIL_TO", "slciaiagent@gmail.com")
        email_host = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
        email_port = int(os.getenv('EMAIL_PORT', 465))  # Default to 465
        
        print(f"📧 [EMAIL] Starting: {sender_email} → {receiver_email} via {email_host}:{email_port}")
        print(f"📧 [EMAIL] Password length: {len(sender_password) if sender_password else 0}")
        
        if not sender_password or len(sender_password.strip()) != 16:
            print("❌ [EMAIL] Invalid EMAIL_PASSWORD - must be 16-char Gmail App Password")
            return False
        
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"🔧 New Service Enquiry - {data['service']} - ID: {enquiry_id}"
        msg['Reply-To'] = data['email']
        
        html_body = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;color:#333;margin:0;padding:0}}
.container{{max-width:650px;margin:0 auto;padding:20px}}
.header{{background:linear-gradient(135deg,#1a237e 0%,#283593 100%);color:#fff;padding:25px 20px;text-align:center;border-radius:8px 8px 0 0}}
.header h2{{margin:0;font-size:22px}}
.content{{padding:25px;background:#f9f9f9;border:1px solid #e0e0e0;border-top:none}}
.field{{margin:18px 0;padding:12px 15px;background:#fff;border-left:4px solid #667eea;border-radius:0 4px 4px 0}}
.label{{font-weight:600;color:#1a237e;font-size:14px;margin-bottom:4px}}
.value{{color:#333;font-size:15px;word-break:break-word}}
.footer{{text-align:center;padding:20px;color:#666;font-size:12px;background:#f5f5f5;border-radius:0 0 8px 8px}}
.enquiry-id{{background:#667eea;color:#fff;padding:12px;text-align:center;font-size:16px;font-weight:600;margin:15px 0;border-radius:4px}}
.badge{{display:inline-block;background:#4caf50;color:#fff;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}}
</style></head><body><div class="container">
<div class="header"><h2>📋 New Service Enquiry Received</h2><span class="badge">SLCI Chatbot</span></div>
<div class="enquiry-id">🆔 Enquiry ID: {enquiry_id}</div>
<div class="content">
<div class="field"><div class="label">👤 Full Name</div><div class="value">{data['fullName']}</div></div>
<div class="field"><div class="label">🏢 Company</div><div class="value">{data['companyName']}</div></div>
<div class="field"><div class="label">📧 Email</div><div class="value"><a href="mailto:{data['email']}" style="color:#667eea">{data['email']}</a></div></div>
<div class="field"><div class="label">📞 Phone</div><div class="value"><a href="tel:{data['contactNumber']}" style="color:#667eea">{data['contactNumber']}</a></div></div>
<div class="field"><div class="label">🔧 Service</div><div class="value"><strong>{data['service']}</strong></div></div>
<div class="field"><div class="label">❓ Query</div><div class="value" style="white-space:pre-wrap">{data['query']}</div></div>
<div class="field"><div class="label">📅 Submitted</div><div class="value">{datetime.now().strftime('%d %b %Y, %I:%M %p IST')}</div></div>
</div>
<div class="footer"><p><strong>Shakti Legal Compliance India</strong></p><p>📧 contact@slci.in | 📞 +91 9999329153</p><p>🌐 www.slci.in</p></div>
</div></body></html>"""
        
        text_body = f"""SERVICE ENQUIRY #{enquiry_id}
Name: {data['fullName']} | Company: {data['companyName']}
Email: {data['email']} | Phone: {data['contactNumber']}
Service: {data['service']}
Query: {data['query']}
Time: {datetime.now().strftime('%d %b %Y, %I:%M %p IST')}
--
SLCI | www.slci.in"""
        
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        # 🔐 Use SMTP_SSL directly on port 465 (more reliable on Render)
        server = smtplib.SMTP_SSL(email_host, email_port, timeout=30)
        server.login(sender_email, sender_password.strip())
        server.send_message(msg)
        server.quit()
        
        print(f"✅ [EMAIL] SUCCESS: Sent service enquiry {enquiry_id} to {receiver_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ [EMAIL] AUTH ERROR: {e}")
        print("💡 FIX: Regenerate Gmail App Password at https://myaccount.google.com/apppasswords")
        return False
    except OSError as e:
        print(f"❌ [EMAIL] NETWORK ERROR: {e}")
        print("💡 FIX: Render may block SMTP. Try using Resend/SendGrid instead.")
        return False
    except Exception as e:
        print(f"❌ [EMAIL] ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def send_fee_enquiry_email(data, enquiry_id):
    """Send formatted HTML email for fee enquiry - Render fixed (Port 465)"""
    try:
        sender_email = os.getenv("EMAIL_USER", "slciaiagent@gmail.com")
        sender_password = os.getenv("EMAIL_PASSWORD", "")
        receiver_email = os.getenv("FEE_ENQUIRY_EMAIL", "slciaiagent@gmail.com")
        email_host = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
        email_port = int(os.getenv('EMAIL_PORT', 465))
        
        print(f"💰 [FEE EMAIL] Starting: {sender_email} → {receiver_email} via {email_host}:{email_port}")
        
        if not sender_password or len(sender_password.strip()) != 16:
            print("❌ [FEE EMAIL] Invalid EMAIL_PASSWORD")
            return False
        
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"💰 New Fee Enquiry - ID: {enquiry_id}"
        msg['Reply-To'] = data['email']
        
        html_body = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;color:#333;margin:0;padding:0}}
.container{{max-width:650px;margin:0 auto;padding:20px}}
.header{{background:linear-gradient(135deg,#1a237e 0%,#283593 100%);color:#fff;padding:25px 20px;text-align:center;border-radius:8px 8px 0 0}}
.header h2{{margin:0;font-size:22px}}
.content{{padding:25px;background:#f9f9f9;border:1px solid #e0e0e0;border-top:none}}
.field{{margin:18px 0;padding:12px 15px;background:#fff;border-left:4px solid #ff9800;border-radius:0 4px 4px 0}}
.label{{font-weight:600;color:#1a237e;font-size:14px;margin-bottom:4px}}
.value{{color:#333;font-size:15px;word-break:break-word}}
.footer{{text-align:center;padding:20px;color:#666;font-size:12px;background:#f5f5f5;border-radius:0 0 8px 8px}}
.enquiry-id{{background:#ff9800;color:#fff;padding:12px;text-align:center;font-size:16px;font-weight:600;margin:15px 0;border-radius:4px}}
.badge{{display:inline-block;background:#4caf50;color:#fff;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}}
</style></head><body><div class="container">
<div class="header"><h2>💰 New Fee Enquiry Received</h2><span class="badge">SLCI Pricing</span></div>
<div class="enquiry-id">🆔 Enquiry ID: {enquiry_id}</div>
<div class="content">
<div class="field"><div class="label">👤 Full Name</div><div class="value">{data['fullName']}</div></div>
<div class="field"><div class="label">🏢 Company</div><div class="value">{data['companyName']}</div></div>
<div class="field"><div class="label">📧 Email</div><div class="value"><a href="mailto:{data['email']}" style="color:#667eea">{data['email']}</a></div></div>
<div class="field"><div class="label">📞 Phone</div><div class="value"><a href="tel:{data['contactNumber']}" style="color:#667eea">{data['contactNumber']}</a></div></div>
<div class="field"><div class="label">📝 Requirements</div><div class="value" style="white-space:pre-wrap">{data['description']}</div></div>
<div class="field"><div class="label">📅 Submitted</div><div class="value">{datetime.now().strftime('%d %b %Y, %I:%M %p IST')}</div></div>
</div>
<div class="footer"><p><strong>Shakti Legal Compliance India</strong></p><p>📧 contact@slci.in | 📞 +91 9999329153</p><p>🌐 www.slci.in</p></div>
</div></body></html>"""
        
        text_body = f"""FEE ENQUIRY #{enquiry_id}
Name: {data['fullName']} | Company: {data['companyName']}
Email: {data['email']} | Phone: {data['contactNumber']}
Requirements: {data['description']}
Time: {datetime.now().strftime('%d %b %Y, %I:%M %p IST')}
--
SLCI | www.slci.in"""
        
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        # 🔐 Use SMTP_SSL directly on port 465
        server = smtplib.SMTP_SSL(email_host, email_port, timeout=30)
        server.login(sender_email, sender_password.strip())
        server.send_message(msg)
        server.quit()
        
        print(f"✅ [FEE EMAIL] SUCCESS: Sent fee enquiry {enquiry_id} to {receiver_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ [FEE EMAIL] AUTH ERROR: {e}")
        print("💡 FIX: Regenerate Gmail App Password")
        return False
    except OSError as e:
        print(f"❌ [FEE EMAIL] NETWORK ERROR: {e}")
        print("💡 FIX: Render may block SMTP. Try Resend/SendGrid.")
        return False
    except Exception as e:
        print(f"❌ [FEE EMAIL] ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
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
            if se_data and se_data.get("html"):  # Check if data exists
                return jsonify({"response": se_data["html"], "state": state, "act_type": "shop_establishment"})
            else:
                # No data found for the specified state - show spelling/format error
                return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
                    <h4 style="color:#856404; margin-top:0;">⚠️ No Data Found</h4>
                    <p style="color:#856404; margin-bottom:0;">We couldn't find Shop & Establishment Act data for "<strong>{state}</strong>".</p>
                    <p style="color:#856404; margin-top:10px; margin-bottom:0;">Please check your spelling or try formatting like:</p>
                    <ul style="color:#856404; margin-top:5px;">
                        <li>"Shop & Establishment Act of Delhi"</li>
                        <li>"Shop and Establishment Act Maharashtra"</li>
                        <li>"SEA Act Karnataka"</li>
                    </ul>
                </div>"""})
        
        if "all states" in user_message or "list all" in user_message:
            se_data = fetch_shop_establishment("all_states")
            return jsonify({"response": se_data["html"], "state": "All States", "act_type": "shop_establishment"})
        
        # If no state detected but query is about shop establishment
        return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
            <h4 style="color:#856404; margin-top:0;">⚠️ Please Specify a State</h4>
            <p style="color:#856404; margin-bottom:0;">Please mention the state name in your query.</p>
            <p style="color:#856404; margin-top:10px; margin-bottom:0;">Example: "Shop & Establishment Act of Delhi"</p>
        </div>"""})
    
    # Holiday list queries
    if "holiday" in user_message:
        state, url = detect_state(user_message, "holiday_list")
        if state:
            holiday_data = fetch_holiday_list(state)
            if holiday_data and holiday_data.get("html"):  # Check if data exists
                return jsonify({"response": holiday_data["html"], "state": state, "act_type": "holiday_list"})
            else:
                # No data found for the specified state - show spelling/format error
                return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
                    <h4 style="color:#856404; margin-top:0;">⚠️ No Holiday Data Found</h4>
                    <p style="color:#856404; margin-bottom:0;">We couldn't find holiday list for "<strong>{state}</strong>".</p>
                    <p style="color:#856404; margin-top:10px; margin-bottom:0;">Please check your spelling or try formatting like:</p>
                    <ul style="color:#856404; margin-top:5px;">
                        <li>"Holiday list of Maharashtra"</li>
                        <li>"Holidays in Delhi 2024"</li>
                        <li>"Public holidays Karnataka"</li>
                    </ul>
                </div>"""})
        
        # If no state detected but query is about holidays
        return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
            <h4 style="color:#856404; margin-top:0;">⚠️ Please Specify a State</h4>
            <p style="color:#856404; margin-bottom:0;">Please mention the state name in your query.</p>
            <p style="color:#856404; margin-top:10px; margin-bottom:0;">Example: "Holiday list of Maharashtra"</p>
        </div>"""})
    
    # Working hours queries
    if "working hours" in user_message or "working hour" in user_message:
        state, url = detect_state(user_message, "working_hours")
        if state:
            wh_data = fetch_working_hours(state)
            if wh_data and wh_data.get("html"):  # Check if data exists
                return jsonify({"response": wh_data["html"], "state": state, "act_type": "working_hours"})
            else:
                # No data found for the specified state - show spelling/format error
                return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
                    <h4 style="color:#856404; margin-top:0;">⚠️ No Working Hours Data Found</h4>
                    <p style="color:#856404; margin-bottom:0;">We couldn't find working hours information for "<strong>{state}</strong>".</p>
                    <p style="color:#856404; margin-top:10px; margin-bottom:0;">Please check your spelling or try formatting like:</p>
                    <ul style="color:#856404; margin-top:5px;">
                        <li>"Working hours of Delhi"</li>
                        <li>"Working hours in Maharashtra"</li>
                        <li>"Shop working hours Karnataka"</li>
                    </ul>
                </div>"""})
        
        # If no state detected but query is about working hours
        return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
            <h4 style="color:#856404; margin-top:0;">⚠️ Please Specify a State</h4>
            <p style="color:#856404; margin-bottom:0;">Please mention the state name in your query.</p>
            <p style="color:#856404; margin-top:10px; margin-bottom:0;">Example: "Working hours of Delhi"</p>
        </div>"""})
    
    # Minimum wages queries
    if "minimum wage" in user_message or "minimum wages" in user_message:
        state, url = detect_state(user_message, "minimum_wages")
        if state:
            wages_data = fetch_minimum_wages(state)
            if wages_data and wages_data.get("html"):  # Check if data exists
                return jsonify({"response": wages_data["html"], "state": state, "act_type": "minimum_wages"})
            else:
                # No data found for the specified state - show spelling/format error
                return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
                    <h4 style="color:#856404; margin-top:0;">⚠️ No Minimum Wages Data Found</h4>
                    <p style="color:#856404; margin-bottom:0;">We couldn't find minimum wages information for "<strong>{state}</strong>".</p>
                    <p style="color:#856404; margin-top:10px; margin-bottom:0;">Please check your spelling or try formatting like:</p>
                    <ul style="color:#856404; margin-top:5px;">
                        <li>"Minimum wages of Delhi"</li>
                        <li>"Minimum wage rate Maharashtra"</li>
                        <li>"Minimum wages Karnataka 2024"</li>
                    </ul>
                </div>"""})
        
        # If no state detected but query is about minimum wages
        return jsonify({"response": f"""<div style="padding:15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">
            <h4 style="color:#856404; margin-top:0;">⚠️ Please Specify a State</h4>
            <p style="color:#856404; margin-bottom:0;">Please mention the state name in your query.</p>
            <p style="color:#856404; margin-top:10px; margin-bottom:0;">Example: "Minimum wages of Delhi"</p>
        </div>"""})
        # New Labour Codes queries
        # New Labour Codes queries
    labour_code_keywords = ["new labour codes", "new labor codes", "labour codes", "labor codes", "new labour laws", 
                            "new labor laws", "code on social security", "social security code", "industrial relations code", 
                            "code on wages", "wages code", "occupational safety code", "osh code", "labour code 2020"]
    
    if any(phrase in user_message for phrase in labour_code_keywords):
        # Check for specific code mentions
        specific_code = None
        for code_key, code_data in NEW_LABOUR_CODES.items():
            for keyword in code_data["keywords"]:
                if keyword in user_message:
                    specific_code = code_key
                    break
            if specific_code:
                break
        
        # If specific code mentioned, show that code details with download button
        if specific_code:
            code_data = NEW_LABOUR_CODES[specific_code]
            comparison_features = "".join([f"<li style='margin:5px 0; color:#555;'><i class='fas fa-check-circle' style='color:#28a745; margin-right:8px;'></i>{feature}</li>" for feature in LABOUR_CODE_COMPARISON["features"]])
            
            # Generate Drive button HTML if drive_url exists
            drive_button = ""
            if code_data.get('drive_url'):
                drive_button = f"""
                <a href="{code_data['drive_url']}" target="_blank" style="flex:1; background: linear-gradient(135deg, #4285F4 0%, #0F9D58 100%); color: white; border: none; padding: 15px 20px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 10px; text-decoration: none; transition: all 0.3s ease;">
                    <i class="fab fa-google-drive"></i> View on Google Drive
                </a>
                """
            
            labour_code_html = f"""<div style="font-family: Arial, sans-serif; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%); color: white; padding: 20px;">
                    <h3 style="margin:0; display: flex; align-items: center; gap: 10px;"><i class="fas fa-file-code"></i> {code_data['title']}</h3>
                </div>
                <div style="padding: 20px;">
                    <div style="background: #e8f5e9; border-left: 4px solid #28a745; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                        <i class="fas fa-calendar-check" style="color:#28a745; margin-right:8px;"></i>
                        <strong style="color:#1b5e20;">Effective Date:</strong> <span style="color:#28a745;">{code_data['effective_date']}</span>
                    </div>
                    <p style="color:#555; line-height:1.6; margin-bottom:20px;">{code_data['description']}</p>
                    
                    <h4 style="color:#1b5e20; margin:20px 0 10px;">📊 Complete Analysis of Labour Code Changes</h4>
                    <ul style="list-style:none; padding:0;">{comparison_features}</ul>
                    
                    <div style="display: flex; gap: 15px; margin-top: 25px; flex-wrap: wrap;">
                        <button onclick="openLabourCodeDownloadModal('{specific_code}')" 
                            style="flex:1; background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%); color: white; border: none; padding: 15px 20px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 10px; transition: all 0.3s ease;">
                            <i class="fas fa-file-pdf"></i> Download via Form
                        </button>
                        <button onclick="openComparisonDownloadModal()" 
                            style="flex:1; background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%); color: white; border: none; padding: 15px 20px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 10px; transition: all 0.3s ease;">
                            <i class="fas fa-chart-bar"></i> Download Comparison PDF
                        </button>
                    </div>
                    
                    {f'''
                    <div style="display: flex; gap: 15px; margin-top: 15px; flex-wrap: wrap;">
                        {drive_button}
                    </div>
                    ''' if drive_button else ''}
                    
                    <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px; text-align: center;">
                        <p style="margin:0; color:#666;"><i class="fas fa-globe"></i> Source: <a href="{code_data['url']}" target="_blank" style="color:#2e7d32;">slci.in/new-labour-codes/</a></p>
                    </div>
                </div>
            </div>"""
            
            return jsonify({"response": labour_code_html, "show_labour_codes": True, "specific_code": specific_code})
        
        # Otherwise show all 4 codes as dropdown options
        else:
            codes_list = ""
            for code_key, code_data in NEW_LABOUR_CODES.items():
                codes_list += f"""
                <div onclick="openLabourCodeModal('{code_key}')" style="background: white; padding: 15px; border-radius: 8px; margin-bottom: 10px; cursor: pointer; border-left: 4px solid #2e7d32; box-shadow: 0 2px 5px rgba(0,0,0,0.05); transition: all 0.3s ease; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <i class="fas fa-file-pdf" style="color:#dc3545; font-size: 20px;"></i>
                        <strong style="color:#2e7d32;">{code_data['title']}</strong>
                    </div>
                    <i class="fas fa-chevron-right" style="color:#2e7d32;"></i>
                </div>
                """
            
            # Add Google Drive links for available PDFs
            drive_links = ""
            for code_key, code_data in NEW_LABOUR_CODES.items():
                if code_data.get('drive_url'):
                    drive_links += f"""
                    <div style="margin-bottom: 8px;">
                        <a href="{code_data['drive_url']}" target="_blank" style="color: #2e7d32; text-decoration: none; display: flex; align-items: center; gap: 8px; padding: 8px; background: #f5f5f5; border-radius: 5px;">
                            <i class="fab fa-google-drive" style="color: #4285F4;"></i>
                            <span><strong>{code_data['title']}</strong> - View on Drive</span>
                        </a>
                    </div>
                    """
            
            labour_code_overview = f"""<div style="font-family: Arial, sans-serif; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #2e7d32 0%, #1b5e20 100%); color: white; padding: 20px;">
                    <h3 style="margin:0;"><i class="fas fa-balance-scale" style="margin-right:10px;"></i> New Labour Codes 2025</h3>
                </div>
                <div style="padding: 20px;">
                    <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                        <i class="fas fa-info-circle" style="color:#856404; margin-right:8px;"></i>
                        <strong style="color:#856404;">4 New Codes replacing 44+ old labour laws</strong>
                        <p style="color:#856404; margin:5px 0 0;">Implemented from 21st November 2025</p>
                    </div>
                    
                    <h4 style="color:#2e7d32; margin-bottom:15px;">📋 Select a Code to View Details:</h4>
                    <div style="margin-bottom: 20px;">
                        {codes_list}
                    </div>
                    
                    <h4 style="color:#2e7d32; margin:20px 0 10px;">🔗 Quick Access to PDFs:</h4>
                    <div style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                        {drive_links if drive_links else '<p style="color:#666;">Google Drive links will be added soon.</p>'}
                    </div>
                    
                    <div style="display: flex; gap: 15px; margin-top: 20px; flex-wrap: wrap;">
                        <button onclick="openComparisonDownloadModal()" 
                            style="flex:1; background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%); color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 8px;">
                            <i class="fas fa-chart-bar"></i> Download Complete Comparison
                        </button>
                    </div>
                    
                    <p style="margin-top: 20px; text-align: center; color: #666; font-size: 12px;">
                        Click any code above to view full details. PDFs are available on Google Drive for direct download.
                    </p>
                </div>
            </div>"""
            
            return jsonify({"response": labour_code_overview, "show_labour_codes": True})
    
    # Rest of your code remains the same...
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
    return jsonify({"response": """<div style="padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #0d6efd;"><p style="margin: 0; color: #333;">Thank you for contacting <strong>Shakti Legal Compliance India</strong>.</p><p style="margin-top: 8px; color: #555;">For detailed assistance regarding your query, please contact our team.</p><div style="margin-top: 10px; color: #444;">📞 <strong>Phone:</strong> +91 9999329153<br>📧 <strong>Email:</strong> contact@slci.in</div></div>"""})
def generate_enquiry_id(prefix="ENQ"):
    """Generate a unique enquiry ID"""
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(3).upper()
    return f"{prefix}-{date_part}-{random_part}"

@app.route("/check-recent-data", methods=["GET"])
def check_recent_data():
    """Check recent data in all tables"""
    try:
        pool = get_db_pool()
        result = {}
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Check service_enquiries
                cur.execute("""
                    SELECT id, enquiry_id, full_name, email, submission_date 
                    FROM service_enquiries 
                    ORDER BY id DESC 
                    LIMIT 5
                """)
                result['service_enquiries'] = [
                    {"id": r[0], "enquiry_id": r[1], "name": r[2], "email": r[3], "time": str(r[4])}
                    for r in cur.fetchall()
                ]
                
                # Check fee_enquiries
                cur.execute("""
                    SELECT id, enquiry_id, full_name, email, submission_date 
                    FROM fee_enquiries 
                    ORDER BY id DESC 
                    LIMIT 5
                """)
                result['fee_enquiries'] = [
                    {"id": r[0], "enquiry_id": r[1], "name": r[2], "email": r[3], "time": str(r[4])}
                    for r in cur.fetchall()
                ]
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# ============================================================================
# FIXED ENQUIRY ROUTES - Database First, Email Second
# ============================================================================

@app.route("/submit-service-enquiry", methods=["POST"])
def submit_service_enquiry():
    """Handle service enquiry submission - FIXED: Database first, email second, IST Time"""
    conn = None
    try:
        data = request.json
        print(f"📝 Received service enquiry: {data}")
        
        # Validate required fields
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'service', 'query']
        for field in required_fields:
            if not data.get(field):
                print(f"❌ Missing field: {field}")
                return jsonify({"success": False, "error": f"Missing {field}"}), 400
        
        # Validate email
        if not validate_email(data['email']):
            return jsonify({"success": False, "error": "Invalid email format"}), 400
        
        # Validate phone
        if not validate_phone(data['contactNumber']):
            return jsonify({"success": False, "error": "Invalid phone number"}), 400
        
        # Generate enquiry ID
        enquiry_id = generate_enquiry_id("SER")
        
        # ========================================================================
        # STEP 1: Insert into database FIRST with IST Time (independent of email)
        # ========================================================================
        db_success = False
        ist_time = get_ist_now()  # ✅ Get IST Time (UTC+5:30)
        
        try:
            pool = get_db_pool()
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO service_enquiries 
                            (enquiry_id, full_name, company_name, email, contact_number, 
                             service, query, ip_address, status, submission_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            enquiry_id,
                            data['fullName'],
                            data['companyName'],
                            data['email'],
                            data['contactNumber'],
                            data['service'],
                            data['query'],
                            request.remote_addr,
                            'pending',
                            ist_time  # ✅ IST Time pass kiya
                        ))
                        conn.commit()
                        db_success = True
                        print(f"✅ Database insert successful: {enquiry_id} at {ist_time} IST")
            else:
                print("⚠️ No database pool available")
        except Exception as e:
            print(f"❌ Database insert error: {e}")
            import traceback
            traceback.print_exc()
        
        # STEP 2: Send email (don't fail if email fails) - Updated with IST Time
        email_sent = False
        try:
            email_sent = send_service_enquiry_email(data, enquiry_id, ist_time)  # ✅ Pass IST time to email
        except Exception as e:
            print(f"❌ Email error (continuing anyway): {e}")
        
        # STEP 3: Log to Google Sheets - Updated with IST Time
        try:
            sheet_data = {
                'timestamp': ist_time.strftime('%Y-%m-%d %H:%M:%S'),  # ✅ IST Time for Google Sheets
                'enquiry_id': enquiry_id,
                'full_name': data['fullName'],
                'company_name': data['companyName'],
                'email': data['email'],
                'contact_number': data['contactNumber'],
                'service': data['service'],
                'query': data['query'],
                'ip_address': request.remote_addr,
                'status': 'pending'
            }
            append_to_google_sheet("Service_Enquiries", sheet_data)
        except Exception as e:
            print(f"⚠️ Google Sheets error: {e}")
        
        if db_success:
            return jsonify({
                "success": True, 
                "message": "Enquiry submitted successfully", 
                "enquiryId": enquiry_id
            })
        else:
            return jsonify({
                "success": False, 
                "error": "Database error - please try again"
            }), 500
            
    except Exception as e:
        print(f"❌ Service Enquiry Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    
@app.route("/download-labour-code/<code_key>", methods=["GET"])
def download_labour_code(code_key):
    """Download labour code PDF - logs to database and redirects to Google Drive"""
    try:
        download_id = request.args.get('id')
        
        if code_key not in NEW_LABOUR_CODES:
            return jsonify({"error": "Invalid labour code"}), 404
        
        code_data = NEW_LABOUR_CODES[code_key]
        
        # Log the download in database
        try:
            pool = get_db_pool()
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        # Update download stats for this labour code
                        cur.execute("""
                            INSERT INTO download_stats (state, act_type, download_count, last_download)
                            VALUES (%s, %s, 1, %s)
                            ON CONFLICT(state, act_type) DO UPDATE 
                            SET download_count = download_stats.download_count + 1, 
                                last_download = %s
                        """, ("India", f"labour_code_{code_key}", get_ist_now(), get_ist_now()))
                        conn.commit()
                        print(f"✅ Labour code download logged: {code_key}")
        except Exception as e:
            print(f"⚠️ Could not log download: {e}")
        
        # If we have a direct download URL, redirect to it
        if code_data.get('download_url'):
            return redirect(code_data['download_url'])
        # Otherwise redirect to drive view URL
        elif code_data.get('drive_url'):
            return redirect(code_data['drive_url'])
        else:
            # Fallback to generating PDF
            return generate_labour_code_pdf(code_key, download_id)
        
    except Exception as e:
        print(f"Labour Code Download Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/download-labour-code-comparison", methods=["GET"])
def download_labour_code_comparison():
    """Download complete labour code comparison PDF"""
    try:
        download_id = request.args.get('id')
        
        # Log the download
        try:
            pool = get_db_pool()
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO download_stats (state, act_type, download_count, last_download)
                            VALUES (%s, %s, 1, %s)
                            ON CONFLICT(state, act_type) DO UPDATE 
                            SET download_count = download_stats.download_count + 1, 
                                last_download = %s
                        """, ("India", "labour_code_comparison", get_ist_now(), get_ist_now()))
                        conn.commit()
                        print(f"✅ Labour code comparison download logged")
        except Exception as e:
            print(f"⚠️ Could not log download: {e}")
        
        # Create comprehensive comparison tables
        tables_data = []
        
        # Overview table
        overview_table = [["Labour Code", "Old Laws Replaced", "Effective Date"]]
        for code_key, code_data in NEW_LABOUR_CODES.items():
            overview_table.append([code_data['title'], "Multiple old acts", code_data['effective_date']])
        tables_data.append(overview_table)
        
        # Features table
        features_table = [["Feature Category", "Details"]]
        for feature in LABOUR_CODE_COMPARISON["features"]:
            features_table.append([feature.split(":")[0] if ":" in feature else feature, 
                                  feature.split(":")[1] if ":" in feature else "Comprehensive update"])
        tables_data.append(features_table)
        
        # Detailed analysis table
        detailed_table = [
            ["Aspect", "Old System", "New System"],
            ["Number of Laws", "44+ separate acts", "4 consolidated codes"],
            ["Wage Definition", "Varying definitions", "Uniform definition across codes"],
            ["Social Security", "Limited coverage", "Universal social security"],
            ["Working Hours", "State-specific variations", "Standardized hours"],
            ["Compliance", "Multiple registrations", "Single registration portal"],
            ["Inspections", "Physical inspections", "Web-based inspections"]
        ]
        tables_data.append(detailed_table)
        
        # Google Drive links table
        drive_table = [["Labour Code", "Google Drive Link"]]
        for code_key, code_data in NEW_LABOUR_CODES.items():
            if code_data.get('drive_url'):
                drive_table.append([code_data['title'], code_data['drive_url']])
        if len(drive_table) > 1:
            tables_data.append(drive_table)
        
        # Create PDF
        pdf_file = create_pdf_file("India", "Complete Labour Code Comparison", tables_data, 
                                   "November 2025", download_id)
        
        filename = "labour_codes_comparison.pdf"
        return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)
        
    except Exception as e:
        print(f"Labour Code Comparison Download Error: {str(e)}")
        return jsonify({"error": str(e)}), 500


def generate_labour_code_pdf(code_key, download_id=None):
    """Generate PDF for labour code (fallback if no Drive link)"""
    code_data = NEW_LABOUR_CODES[code_key]
    
    # Create PDF data structure
    tables_data = []
    
    # Main details table
    details_table = [
        ["Code Name", code_data['title']],
        ["Effective Date", code_data['effective_date']],
        ["Description", code_data['description']],
        ["Source", "slci.in/new-labour-codes/"]
    ]
    tables_data.append(details_table)
    
    # Add comparison features as a table
    features_table = [["Key Features", "Status"]]
    for feature in LABOUR_CODE_COMPARISON["features"]:
        features_table.append([feature, "✓ Included"])
    tables_data.append(features_table)
    
    # Add Google Drive info if available
    if code_data.get('drive_url'):
        drive_table = [
            ["Google Drive Link", "Access PDF"],
            ["URL", code_data['drive_url']]
        ]
        tables_data.append(drive_table)
    
    # Create PDF
    pdf_file = create_pdf_file("India", code_data['title'], tables_data, 
                               code_data['effective_date'], download_id)
    
    filename = f"{code_key.replace('_', '_')}_notification.pdf"
    return send_file(pdf_file, mimetype='application/pdf', as_attachment=True, download_name=filename)

@app.route("/submit-fee-enquiry", methods=["POST"])
def submit_fee_enquiry():
    """Handle fee enquiry submission - FIXED: Database first, email second, IST Time"""
    try:
        data = request.json
        print(f"💰 Received fee enquiry: {data}")
        
        # Validate required fields
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'description']
        for field in required_fields:
            if not data.get(field):
                print(f"❌ Missing field: {field}")
                return jsonify({"success": False, "error": f"Missing {field}"}), 400
        
        # Validate email
        if not validate_email(data['email']):
            return jsonify({"success": False, "error": "Invalid email format"}), 400
        
        # Validate phone
        if not validate_phone(data['contactNumber']):
            return jsonify({"success": False, "error": "Invalid phone number"}), 400
        
        # Generate enquiry ID
        enquiry_id = generate_enquiry_id("FEE")
        
        # ========================================================================
        # STEP 1: Insert into database FIRST with IST Time
        # ========================================================================
        db_success = False
        ist_time = get_ist_now()  # ✅ Get IST Time (UTC+5:30)
        
        try:
            pool = get_db_pool()
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO fee_enquiries 
                            (enquiry_id, full_name, company_name, email, contact_number, 
                             description, ip_address, status, submission_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            enquiry_id,
                            data['fullName'],
                            data['companyName'],
                            data['email'],
                            data['contactNumber'],
                            data['description'],
                            request.remote_addr,
                            'pending',
                            ist_time  # ✅ IST Time pass kiya
                        ))
                        conn.commit()
                        db_success = True
                        print(f"✅ Database insert successful: {enquiry_id} at {ist_time} IST")
            else:
                print("⚠️ No database pool available")
        except Exception as e:
            print(f"❌ Database insert error: {e}")
            import traceback
            traceback.print_exc()
        
        # STEP 2: Send email - Updated with IST Time
        try:
            send_fee_enquiry_email(data, enquiry_id, ist_time)  # ✅ Pass IST time to email
        except Exception as e:
            print(f"❌ Email error (continuing anyway): {e}")
        
        # STEP 3: Log to Google Sheets - Updated with IST Time
        try:
            sheet_data = {
                'timestamp': ist_time.strftime('%Y-%m-%d %H:%M:%S'),  # ✅ IST Time for Google Sheets
                'enquiry_id': enquiry_id,
                'full_name': data['fullName'],
                'company_name': data['companyName'],
                'email': data['email'],
                'contact_number': data['contactNumber'],
                'description': data['description'],
                'ip_address': request.remote_addr,
                'status': 'pending'
            }
            append_to_google_sheet("Fee_Enquiries", sheet_data)
        except Exception as e:
            print(f"⚠️ Google Sheets error: {e}")
        
        if db_success:
            return jsonify({
                "success": True, 
                "message": "Fee enquiry submitted successfully", 
                "enquiryId": enquiry_id
            })
        else:
            return jsonify({
                "success": False, 
                "error": "Database error - please try again"
            }), 500
            
    except Exception as e:
        print(f"❌ Fee Enquiry Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/request-download", methods=["POST"])
def request_download():
    """Step 1: Validate form, log to DB, return download token - UPDATED with IST Time and Labour Codes"""
    try:
        data = request.json
        print(f"📥 Received download request: {data}")
        
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        required_fields = ['fullName', 'companyName', 'email', 'contactNumber', 'state', 'actType']
        for field in required_fields:
            if not data.get(field):
                print(f"❌ Missing field: {field}")
                return jsonify({"success": False, "error": f"Missing field: {field}"}), 400
        
        # Set defaults
        if 'designation' not in data:
            data['designation'] = 'Not Provided'
        if 'rating' not in data:
            data['rating'] = 0
        
        download_token = f"DL{secrets.token_hex(8)}"
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent')
        
        # ========================================================================
        # Log to database with IST Time
        # ========================================================================
        download_id = None
        ist_time = get_ist_now()  # ✅ Get IST Time (UTC+5:30)
        
        try:
            pool = get_db_pool()
            if pool:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO downloads 
                            (full_name, company_name, email, contact_number, designation, 
                             rating, state, act_type, ip_address, user_agent, download_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            data['fullName'], 
                            data['companyName'], 
                            data['email'], 
                            data['contactNumber'], 
                            data.get('designation', 'Not Provided'),
                            int(data.get('rating', 0)),
                            data['state'], 
                            data['actType'], 
                            ip_address, 
                            user_agent,
                            ist_time  # ✅ IST Time pass kiya
                        ))
                        download_id = cur.fetchone()[0]
                        
                        # Update stats with IST Time
                        cur.execute("""
                            INSERT INTO download_stats (state, act_type, download_count, last_download)
                            VALUES (%s, %s, 1, %s)
                            ON CONFLICT(state, act_type) DO UPDATE 
                            SET download_count = download_stats.download_count + 1, 
                                last_download = %s
                        """, (data['state'], data['actType'], ist_time, ist_time))
                        
                        conn.commit()
                        print(f"✅ Download logged: ID {download_id} at {ist_time} IST")
            else:
                print("⚠️ No database pool available")
        except Exception as e:
            print(f"❌ Download logging error: {e}")
            import traceback
            traceback.print_exc()
        
        # Store in pending even if DB failed (for PDF generation)
        with pending_lock:
            pending_downloads[download_token] = {
                'data': data, 
                'download_id': download_id, 
                'created_at': get_ist_now(),  # ✅ Returns naive datetime in IST
                'ip': ip_address
            }
        
        # ========================================================================
        # Generate appropriate download URL based on actType
        # ========================================================================
        if download_id:
            download_url = None
            
            # Check if this is a labour code download
            if data['actType'].startswith('labour_code_'):
                code_key = data['actType'].replace('labour_code_', '')
                if code_key == 'comparison':
                    download_url = f"/download-labour-code-comparison?id={download_id}"
                else:
                    download_url = f"/download-labour-code/{code_key}?id={download_id}"
            else:
                # Regular PDF generation through token
                download_url = f"/generate-pdf/{download_token}"
            
            return jsonify({
                "success": True, 
                "downloadId": download_id, 
                "downloadToken": download_token,
                "downloadUrl": download_url,
                "message": "Form submitted successfully"
            })
        else:
            return jsonify({
                "success": False, 
                "error": "Database error - please try again"
            }), 500
        
    except Exception as e:
        print(f"❌ Download Request Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# Add this endpoint to check database status
@app.route("/db-status", methods=["GET"])
def db_status():
    """Check database connection and show recent entries"""
    try:
        pool = get_db_pool()
        if not pool:
            return jsonify({
                "status": "error",
                "message": "No database pool"
            }), 500
        
        result = {
            "status": "connected",
            "database": DB_NAME,
            "host": DB_HOST,
            "tables": {},
            "recent_entries": {}
        }
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Get all tables
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = [t[0] for t in cur.fetchall()]
                result["tables"]["list"] = tables
                
                # Get counts
                for table in ['downloads', 'service_enquiries', 'fee_enquiries', 'download_stats']:
                    if table in tables:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cur.fetchone()[0]
                        result["tables"][f"{table}_count"] = count
                        
                        # Get recent entries (last 5)
                        cur.execute(f"""
                            SELECT * FROM {table} 
                            ORDER BY id DESC 
                            LIMIT 5
                        """)
                        columns = [desc[0] for desc in cur.description]
                        rows = cur.fetchall()
                        
                        recent = []
                        for row in rows:
                            row_dict = {}
                            for i, col in enumerate(columns):
                                value = row[i]
                                # Convert datetime to string
                                if hasattr(value, 'isoformat'):
                                    value = value.isoformat()
                                row_dict[col] = str(value) if value is not None else None
                            recent.append(row_dict)
                        
                        result["recent_entries"][table] = recent
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

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
# ============================================================================
# NEW LABOUR CODES DATA
# ============================================================================
# ============================================================================
# NEW LABOUR CODES DATA - Updated with Google Drive Links
# ============================================================================
NEW_LABOUR_CODES = {
    "social_security": {
        "title": "Code on Social Security 2020",
        "url": "https://www.slci.in/new-labour-codes/",
        "drive_url": "https://drive.google.com/file/d/1OHxyV0mvZ2XzbD8vfTWH1YjzsLn5BwDo/view",
        "download_url": "https://drive.google.com/uc?export=download&id=1OHxyV0mvZ2XzbD8vfTWH1YjzsLn5BwDo",
        "description": "Official notification regarding the implementation of the Code on Social Security 2020, issued on 21st November 2025. Provides key updates for employers, HR professionals, and employees about social security compliance, benefits, and legal obligations under the latest labour laws in India.",
        "effective_date": "21st November 2025",
        "keywords": ["social security", "social security code", "code on social security", "social security 2020"]
    },
    "industrial_relations": {
        "title": "Industrial Relations Code 2020",
        "url": "https://www.slci.in/new-labour-codes/",
        "drive_url": "https://drive.google.com/file/d/1DsrojQwuBKbBR0BeO1e926He1b3MFrp9/view",
        "download_url": "https://drive.google.com/uc?export=download&id=1DsrojQwuBKbBR0BeO1e926He1b3MFrp9",
        "description": "Official notifications regarding the implementation of the Industrial Relations Code 2020, issued on 21st November 2025. Provides key updates for employers, HR professionals, and employees on legal compliance and industrial relations management in India.",
        "effective_date": "21st November 2025",
        "keywords": ["industrial relations", "industrial relations code", "ir code", "industrial relations 2020"]
    },
    "code_on_wages": {
        "title": "Code on Wages 2019",
        "url": "https://www.slci.in/new-labour-codes/",
        "drive_url": "https://drive.google.com/file/d/1waBwWLNYYfva0TSb-HAQbBkI1AKE3YSA/view",
        "download_url": "https://drive.google.com/uc?export=download&id=1waBwWLNYYfva0TSb-HAQbBkI1AKE3YSA",
        "description": "Official notification for the implementation of the Code on Wages 2019, issued on 21st November 2025. Provides clear guidance on wage regulations, helping employers, HR teams, and employees understand their rights and compliance requirements under the latest labour laws in India.",
        "effective_date": "21st November 2025",
        "keywords": ["code on wages", "wages code", "wage code", "wages 2019"]
    },
    "occupational_safety": {
        "title": "Occupational Safety, Health & Working Conditions Code 2020",
        "url": "https://www.slci.in/new-labour-codes/",
        "drive_url": "",  # Add when available
        "download_url": "",  # Add when available
        "description": "Official notification for the implementation of the Occupational Safety, Health, and Working Conditions Code 2020, issued on 21st November 2025. Helps employers, HR teams, and workers stay informed about workplace safety standards, health regulations, and legal compliance requirements under the new labour code.",
        "effective_date": "21st November 2025",
        "keywords": ["occupational safety", "safety code", "health and safety", "working conditions", "osh code"]
    }
}

# Comparison document data
LABOUR_CODE_COMPARISON = {
    "title": "Complete Analysis of Labour Code Changes",
    "description": "This comprehensive document provides detailed comparison between old and new labour codes, including:",
    "features": [
        "Comparison of 44+ old laws vs 4 new consolidated codes",
        "Detailed analysis of wage definitions and components",
        "Social security coverage and benefits comparison",
        "Working hours and leave policy changes",
        "Compliance and inspection regime updates",
        "Impact on employers and employees",
        "Implementation guidelines and timelines"
    ]
}

STATE_MINIMUM_WAGE_URLS = {
    "daman and diu": "https://www.slci.in/daman-and-diu/",
    "arunchal pradesh": "https://www.slci.in/arunachal-pradesh/",
    "dadra and nagar haveli": "https://www.slci.in/dadra-and-nagar-haveli/",
    "andaman and nicobar": "https://www.slci.in/andaman-and-nicobar-islands/",
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
    "punjab": ["punjab"],
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
    "email": "contact@slci.in",
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
    "website": "www.slci.in | Blog: www.slci.in/blog | Knowledge Centre: www.slci.in/knowledge-centre",
    "new labour codes": "The New Labour Codes are four consolidated codes replacing 44+ old labour laws, implemented from 21st November 2025. They cover: Code on Social Security 2020, Industrial Relations Code 2020, Code on Wages 2019, and Occupational Safety, Health & Working Conditions Code 2020."
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
    "holiday list": ["holiday", "holiday list", "public holiday", "national holiday", "bank holiday", "leaves"],
    "shop establishment": ["shop and establishment", "shop establishment act", "sea act", "commercial establishment", "shop license"],
    "pricing": ["pricing", "price", "cost", "fee", "fees", "charges", "how much", "quotation", "quote", "package", "plans", "subscription"],
    "fees": ["fees", "fee structure", "service fees", "consulting fees", "charges", "professional fees"],
    "cost": ["cost", "cost of services", "how much does it cost", "pricing details", "service cost"],
    "website": ["website", "site", "web", "url", "online", "portal"],
    "new labour codes":["new labour codes", "labour codes", "new labor codes", "labor codes", "new labour laws", "new labor laws", "labour code", "labor code", "code on social security", "social security code", "industrial relations code", "code on wages", "occupational safety code"]
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
# HEALTH CHECK ENDPOINT (Add this BEFORE the startup code)
# ============================================================================
@app.route("/db-check", methods=["GET"])
def db_check():
    """Simple database check endpoint"""
    try:
        pool = get_db_pool()
        if not pool:
            return jsonify({"status": "error", "message": "No database pool"}), 500
        
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # Check if tables exist
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = [t[0] for t in cur.fetchall()]
                
                # Get counts
                counts = {}
                for table in ['downloads', 'service_enquiries', 'fee_enquiries', 'download_stats']:
                    if table in tables:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        counts[table] = cur.fetchone()[0]
                    else:
                        counts[table] = 0
                
                return jsonify({
                    "status": "healthy" if tables else "no_tables",
                    "database": DB_NAME,
                    "host": DB_HOST,
                    "tables": tables,
                    "counts": counts
                })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# ============================================================================
# APPLICATION STARTUP - THIS RUNS ON BOTH RENDER AND LOCAL
# ============================================================================

# This runs when the module is imported (on Render with gunicorn)
print("=" * 60)
print("🚀 SLCI Chatbot Initializing...")
print("=" * 60)
print(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"🐍 Python Version: {sys.version}")
print(f"🌍 Environment: {'Render' if os.environ.get('RENDER') else 'Local'}")
print("=" * 60)

# Initialize database immediately on module load (works on Render)
try:
    print("📊 Initializing database...")
    db_result = init_db()
    if db_result:
        print("✅ Database initialized successfully")
    else:
        print("⚠️ Database initialization returned False")
except Exception as e:
    print(f"❌ Database initialization error: {e}")
    import traceback
    traceback.print_exc()

# Check Ollama connection
try:
    if check_ollama_connection():
        print(f"✅ Ollama connected: {OLLAMA_MODEL}")
    else:
        print("⚠️ Ollama not available - using keyword responses")
except Exception as e:
    print(f"⚠️ Ollama check failed: {e}")

# Check Google Sheets
if GOOGLE_SHEET_ENABLED:
    print(f"✅ Google Sheets enabled: {GOOGLE_SHEET_ID}")
    if os.path.exists(GOOGLE_CREDENTIALS_PATH):
        print(f"✅ Credentials found: {GOOGLE_CREDENTIALS_PATH}")
    else:
        print(f"⚠️ Credentials file missing: {GOOGLE_CREDENTIALS_PATH}")
else:
    print("ℹ️ Google Sheets disabled")

print("=" * 60)
print("✅ Initialization complete! Ready to handle requests.")
print("=" * 60)

# ============================================================================
# MAIN ENTRY POINT - This runs ONLY when executing python app.py directly
# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    
    print("\n" + "=" * 60)
    print("🚀 Starting Flask Development Server")
    print("=" * 60)
    print(f"📍 Port: {port}")
    print(f"🔧 Debug Mode: {debug_mode}")
    print(f"🌐 URL: http://0.0.0.0:{port}")
    print("=" * 60 + "\n")
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=debug_mode)