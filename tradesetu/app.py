from flask import Flask, render_template, request, redirect, url_for, session, flash
import hashlib
import os
import re
import random
import qrcode
from db_config import get_db_connection
from flask_wtf import CSRFProtect

app = Flask(__name__)

# Static folder configuration
app.config['STATIC_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static')
app.config['STATIC_URL_PATH'] = '/static'

# Security Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'supersecretkey123456789abcdef')  # Use strong secret in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True when using HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['WTF_CSRF_ENABLED'] = True

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Rate limiting for login attempts (simple in-memory approach)
login_attempts = {}

def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16).hex()
    hash_obj = hashlib.sha256((password + salt).encode())
    return hash_obj.hexdigest(), salt

def verify_password(password, hash_val, salt):
    computed_hash, _ = hash_password(password, salt)
    return computed_hash == hash_val

def check_rate_limit(identifier, max_attempts=5, window_seconds=60):
    """Simple rate limiting for login attempts"""
    import time
    current_time = time.time()

    if identifier not in login_attempts:
        login_attempts[identifier] = []

    # Clean old attempts
    login_attempts[identifier] = [
        attempt for attempt in login_attempts[identifier]
        if current_time - attempt < window_seconds
    ]

    if len(login_attempts[identifier]) >= max_attempts:
        return False

    login_attempts[identifier].append(current_time)
    return True

def generate_shipment_id():
    return f"SHP{random.randint(100000, 999999)}"

def generate_shipment_hash(shipment_id, product_id, quantity, price, manufacturer_id, previous_hash):
    data_string = f"{shipment_id}|{product_id}|{quantity}|{price}|{manufacturer_id}|{previous_hash}"
    return hashlib.sha256(data_string.encode()).hexdigest()

def generate_qr_code(shipment_id, current_hash):
    # GET BASE DIRECTORY
    base_dir = os.path.abspath(os.path.dirname(__file__))

    # DEFINE QR FOLDER PATH
    qr_folder = os.path.join(base_dir, "static", "qr_codes")

    # CREATE FOLDER IF NOT EXISTS
    if not os.path.exists(qr_folder):
        os.makedirs(qr_folder)

    # CREATE QR DATA
    qr_data = f"{shipment_id}|{current_hash}"

    # GENERATE QR
    qr = qrcode.make(qr_data)

    # SAVE USING ABSOLUTE PATH
    file_path = os.path.join(qr_folder, f"{shipment_id}.png")
    qr.save(file_path)

    # DEBUG PRINT (VERY IMPORTANT)
    print("QR SAVED AT:", file_path)

    # VERIFY FILE EXISTS
    print("FILE EXISTS:", os.path.exists(file_path))

    return file_path

def insert_shipment_into_db(shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash, delivery_address=None, city=None, state=None, pincode=None, retailer_id=None):
    connection = get_db_connection()
    cursor = connection.cursor()

    query = """
    INSERT INTO shipments (
        shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash, delivery_address, city, state, pincode, retailer_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    values = (
        shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash, delivery_address, city, state, pincode, retailer_id
    )

    cursor.execute(query, values)
    connection.commit()
    cursor.close()
    connection.close()

def create_shipments_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        create_table_query = """
        CREATE TABLE IF NOT EXISTS shipments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            shipment_id VARCHAR(100) UNIQUE NOT NULL,
            manufacturer_id INT NOT NULL,
            product_name VARCHAR(150) NOT NULL,
            product_id VARCHAR(100) NOT NULL,
            quantity INT NOT NULL,
            price_per_unit DECIMAL(10,2) NOT NULL,
            total_price DECIMAL(12,2) NOT NULL,
            distributor_id INT DEFAULT NULL,
            distributor_pan VARCHAR(100),
            retailer_id INT DEFAULT NULL,
            status ENUM('CREATED','ASSIGNED','IN_TRANSIT','AT_STORAGE','OUT_FOR_DELIVERY','DELIVERED','TAMPERED') DEFAULT 'CREATED',
            previous_hash VARCHAR(256),
            current_hash VARCHAR(256) NOT NULL,
            transporter_name VARCHAR(100),
            vehicle_number VARCHAR(50),
            driver_name VARCHAR(100),
            driver_phone VARCHAR(20),
            dispatch_date DATETIME,
            storage_id INT DEFAULT NULL,
            delivery_address TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            pincode VARCHAR(10),
            delivery_name VARCHAR(100),
            delivery_phone VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (manufacturer_id) REFERENCES users(id)
        );
        """

        cursor.execute(create_table_query)
        connection.commit()
        cursor.close()
        connection.close()
        print("Shipments table created or already exists.")
    except Exception as e:
        print(f"Error creating shipments table: {e}")

def alter_shipments_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # Check and add new columns
        columns_to_add = [
            ("transporter_name", "VARCHAR(100)"),
            ("vehicle_number", "VARCHAR(50)"),
            ("driver_name", "VARCHAR(100)"),
            ("driver_phone", "VARCHAR(20)"),
            ("dispatch_date", "DATETIME"),
            ("storage_id", "INT DEFAULT NULL"),
            ("retailer_id", "INT DEFAULT NULL"),
            ("delivery_address", "TEXT"),
            ("city", "VARCHAR(100)"),
            ("state", "VARCHAR(100)"),
            ("pincode", "VARCHAR(10)")
        ]

        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE shipments ADD COLUMN {col_name} {col_type}")
                print(f"Added column {col_name}")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    print(f"Column {col_name} already exists")
                else:
                    print(f"Error adding column {col_name}: {e}")

        # Ensure AT_STORAGE is part of the enum if not already present
        try:
            cursor.execute("ALTER TABLE shipments MODIFY status ENUM('CREATED','ASSIGNED','IN_TRANSIT','AT_STORAGE','OUT_FOR_DELIVERY','DELIVERED','TAMPERED') DEFAULT 'CREATED'")
            print("Updated status enum to include AT_STORAGE and OUT_FOR_DELIVERY")
        except Exception as e:
            print(f"Status enum update may already exist or failed: {e}")

        # Add delivery columns
        delivery_columns = [
            ("delivery_name", "VARCHAR(100)"),
            ("delivery_phone", "VARCHAR(20)")
        ]
        
        for col_name, col_type in delivery_columns:
            try:
                cursor.execute(f"ALTER TABLE shipments ADD COLUMN {col_name} {col_type}")
                print(f"Added column {col_name}")
            except Exception as e:
                if "Duplicate column name" in str(e):
                    print(f"Column {col_name} already exists")
                else:
                    print(f"Error adding column {col_name}: {e}")

        connection.commit()
        cursor.close()
        connection.close()
        print("Shipments table alteration completed.")
    except Exception as e:
        print(f"Error altering shipments table: {e}")

def create_audit_logs_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        create_table_query = """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            shipment_id VARCHAR(100),
            action VARCHAR(100),
            description TEXT,
            performed_by INT,
            role VARCHAR(50),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (performed_by) REFERENCES users(id)
        );
        """

        cursor.execute(create_table_query)
        connection.commit()
        cursor.close()
        connection.close()
        print("Audit logs table created or already exists.")
    except Exception as e:
        print(f"Error creating audit logs table: {e}")

def log_audit_action(shipment_id, action, description, performed_by, role):
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        query = """
        INSERT INTO audit_logs (shipment_id, action, description, performed_by, role)
        VALUES (%s, %s, %s, %s, %s)
        """

        cursor.execute(query, (shipment_id, action, description, performed_by, role))
        connection.commit()
        cursor.close()
        connection.close()
    except Exception as e:
        print(f"Error logging audit action: {e}")

# Create shipments table if not exists
create_shipments_table()
alter_shipments_table()
create_audit_logs_table()

@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors securely"""
    flash('Something went wrong. Please try again.')
    
    return redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    flash('Page not found.')
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        owner_name = request.form.get('owner_name', '').strip()
        business_name = request.form.get('business_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        location = request.form.get('location', '').strip()
        stakeholder = request.form.get('stakeholder', '').strip()
        pan_tan_id = request.form.get('pan_tan_id', '').strip()

        # Backend validation - check all required fields
        errors = []
        if not owner_name:
            errors.append('Owner name is required')
        if not business_name:
            errors.append('Business name is required')
        if not email:
            errors.append('Email is required')
        elif not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            errors.append('Please enter a valid email address')
        if not password:
            errors.append('Password is required')
        elif len(password) < 6:
            errors.append('Password must be at least 6 characters long')
        if not confirm_password:
            errors.append('Please confirm your password')
        elif password != confirm_password:
            errors.append('Passwords do not match')
        if not location:
            errors.append('Location is required')
        if not stakeholder:
            errors.append('Stakeholder type is required')
        if not pan_tan_id:
            errors.append('PAN/TAN ID is required')

        if errors:
            for error in errors:
                flash(error)
            return redirect(url_for('register'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            if cursor.fetchone():
                flash('Email already registered')
                conn.close()
                return redirect(url_for('register'))

            password_hash, salt = hash_password(password)
            cursor.execute('''
                INSERT INTO users (owner_name, business_name, email, password_hash, salt, location, stakeholder, pan_tan_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (owner_name, business_name, email, password_hash, salt, location, stakeholder, pan_tan_id))
            conn.commit()
            conn.close()
            flash('Registered Successfully. Please login.')
            return redirect(url_for('login'))
        except Exception as e:
            # Log the error but don't expose it to user
            print(f"Database error during registration: {e}")
            flash('Something went wrong. Please try again.')
            return redirect(url_for('register'))
    return render_template('register.html')

@app.before_request
def require_login():
    allowed_routes = ['index', 'login', 'register', 'static']
    if 'user_id' not in session and request.endpoint not in allowed_routes:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Rate limiting check
        client_ip = request.remote_addr
        rate_limit_key = f"{client_ip}_{email}" if email else client_ip

        if not check_rate_limit(rate_limit_key):
            flash('Too many login attempts. Please try again later.')
            return redirect(url_for('login'))

        # Backend validation
        if not email:
            flash('Email is required')
            return redirect(url_for('login'))
        if not password:
            flash('Password is required')
            return redirect(url_for('login'))

        # Basic email format validation
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            flash('Please enter a valid email address')
            return redirect(url_for('login'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()
            conn.close()

            if user and verify_password(password, user['password_hash'], user['salt']):
                session['user_id'] = user['id']
                session['business_name'] = user['business_name']
                session['role'] = str(user.get('stakeholder') or '').strip().lower()
                print('Logged in as:', repr(session.get('role')))
                print("SESSION ROLE:", session.get("role"))
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password')
                return redirect(url_for('login'))
        except Exception as e:
            # Log the error but don't expose it to user
            print(f"Database error: {e}")
            flash('Something went wrong. Please try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    role = session.get('role', '').lower()
    print('SESSION ROLE:', role)

    if role == 'manufacturer':
        return redirect(url_for('manufacturer_dashboard'))
    elif role == 'distributor':
        return redirect(url_for('distributor_dashboard'))
    elif role == 'storage':
        return redirect(url_for('storage_dashboard'))
    elif role == 'retailer':
        return redirect(url_for('retailer_dashboard'))
    else:
        return 'Unauthorized Access'

@app.route('/manufacturer_dashboard')
def manufacturer_dashboard():
    if session.get('role', '').lower() != 'manufacturer':
        return 'Unauthorized'

    return render_template('manufacturer_dashboard.html',
                           owner_name=session.get('owner_name'),
                           business_name=session.get('business_name'))

@app.route('/distributor_dashboard')
def distributor_dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    if session.get('role', '').lower() != 'distributor':
        return 'Unauthorized'

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Fetch shipments assigned to this distributor
    cursor.execute(
        "SELECT * FROM shipments WHERE distributor_id = %s",
        (session['user_id'],)
    )
    shipments = cursor.fetchall()
    
    # Fetch storage users
    cursor.execute(
        "SELECT id as user_id, business_name as name FROM users WHERE stakeholder = 'storage'"
    )
    storage_users = cursor.fetchall()
    
    cursor.close()
    connection.close()

    return render_template('distributor_dashboard.html', shipments=shipments, storage_users=storage_users)

@app.route('/storage_dashboard')
def storage_dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    if session.get('role', '').lower() != 'storage':
        return 'Unauthorized'

    # Fetch shipments assigned to this storage facility
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM shipments WHERE storage_id = %s",
        (session['user_id'],)
    )
    shipments = cursor.fetchall()
    cursor.close()
    connection.close()

    return render_template('storage_dashboard.html', shipments=shipments)

@app.route('/scan_qr')
def scan_qr():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return redirect(url_for('login'))
    return render_template('scan_qr.html')

@app.route('/verify_hash', methods=['POST'])
@csrf.exempt
def verify_hash():
    try:
        print("=== QR VERIFICATION REQUEST ===")
        if 'user_id' not in session or session.get('role', '').lower() not in ['distributor', 'storage', 'retailer']:
            print("❌ UNAUTHORIZED - No session or wrong role")
            return {'status': 'unauthorized'}, 403

        data = request.get_json()
        print("REQUEST DATA:", data)
        
        qr_hash = data.get("qr_hash")
        shipment_id = data.get("shipment_id")

        if not qr_hash or not shipment_id:
            print("❌ MISSING DATA - qr_hash:", repr(qr_hash), "shipment_id:", repr(shipment_id))
            return {'status': 'invalid_data'}, 400

        # BACKEND CLEANING (double safety)
        original_qr_hash = qr_hash
        qr_hash = qr_hash.strip()
        qr_hash = qr_hash.replace("\n", "").replace("\r", "")
        qr_hash = qr_hash.lower()  # Ensure lowercase

        print("CLEANED QR HASH:", repr(qr_hash))
        print("ORIGINAL LENGTH:", len(original_qr_hash), "CLEANED LENGTH:", len(qr_hash))

        # FETCH FROM DATABASE
        print("FETCHING SHIPMENT:", shipment_id)
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
        shipment = cursor.fetchone()
        cursor.close()
        connection.close()

        if not shipment:
            print("❌ SHIPMENT NOT FOUND")
            return {'status': 'not_found'}, 404

        if session.get('role', '').lower() == 'distributor':
            if shipment['distributor_id'] != session['user_id']:
                print("❌ NOT AUTHORIZED FOR THIS SHIPMENT")
                return {'status': 'not_found'}, 404
        elif session.get('role', '').lower() == 'storage':
            if shipment['storage_id'] != session['user_id']:
                print("❌ STORAGE NOT AUTHORIZED FOR THIS SHIPMENT")
                return {'status': 'not_found'}, 404
        elif session.get('role', '').lower() == 'retailer':
            if shipment['retailer_id'] != session['user_id']:
                print("❌ RETAILER NOT AUTHORIZED FOR THIS SHIPMENT")
                return {'status': 'not_found'}, 404

        stored_hash = shipment['current_hash']
        original_stored = stored_hash
        
        # CLEAN STORED HASH
        stored_hash = stored_hash.strip()
        stored_hash = stored_hash.lower()  # Ensure lowercase

        print("STORED HASH:", repr(stored_hash))
        print("ORIGINAL STORED LENGTH:", len(original_stored), "CLEANED LENGTH:", len(stored_hash))

        # FINAL COMPARISON
        print("COMPARISON:")
        print("  QR:", repr(qr_hash))
        print("  DB:", repr(stored_hash))
        print("  EQUAL:", qr_hash == stored_hash)

        if qr_hash == stored_hash:
            print("✅ VERIFICATION SUCCESSFUL")
            return {"status": "valid"}
        else:
            print("❌ VERIFICATION FAILED")
            return {"status": "tampered"}
            
    except Exception as e:
        print("❌ EXCEPTION IN VERIFY_HASH:", str(e))
        import traceback
        traceback.print_exc()
        return {'status': 'server_error'}, 500

@app.route('/verify_storage_qty', methods=['POST'])
@csrf.exempt
def verify_storage_qty():
    if 'user_id' not in session or session.get('role', '').lower() != 'storage':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json()
    shipment_id = data.get("shipment_id")
    received_qty = data.get("received_qty")

    if not shipment_id or received_qty is None:
        return {'message': 'Invalid data'}, 400

    try:
        received_qty = int(received_qty)
    except (ValueError, TypeError):
        return {'message': 'Invalid quantity'}, 400

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['storage_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return {'message': 'Shipment not found'}, 404

    stored_qty = int(shipment['quantity'])
    new_status = 'AT_STORAGE' if received_qty == stored_qty else 'TAMPERED'

    cursor.execute("UPDATE shipments SET status = %s WHERE shipment_id = %s", (new_status, shipment_id))
    connection.commit()

    # Log the storage verification
    log_audit_action(
        shipment_id,
        "STORAGE_VERIFIED" if new_status == 'AT_STORAGE' else "STORAGE_TAMPERED",
        f"Storage verification: received {received_qty} units, expected {stored_qty} units",
        session['user_id'],
        'storage'
    )

    cursor.close()
    connection.close()

    return {'message': 'Storage verification ' + ('successful' if new_status == 'AT_STORAGE' else 'failed')}, 200

@app.route('/dispatch_delivery', methods=['POST'])
def dispatch_delivery():
    if 'user_id' not in session or session.get('role', '').lower() != 'storage':
        flash('Unauthorized access', 'error')
        return redirect('/login')

    shipment_id = request.form.get('shipment_id')
    delivery_name = request.form.get('delivery_name')
    delivery_phone = request.form.get('delivery_phone')

    if not shipment_id or not delivery_name or not delivery_phone:
        flash('All fields are required', 'error')
        return redirect('/storage_dashboard')

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['storage_id'] != session['user_id'] or shipment['status'] != 'AT_STORAGE':
        cursor.close()
        connection.close()
        flash('Shipment not found or not ready for dispatch', 'error')
        return redirect('/storage_dashboard')

    cursor.execute("""
        UPDATE shipments 
        SET status = 'OUT_FOR_DELIVERY', 
            delivery_name = %s, 
            delivery_phone = %s 
        WHERE shipment_id = %s
    """, (delivery_name, delivery_phone, shipment_id))
    
    connection.commit()

    # Log the delivery dispatch
    log_audit_action(
        shipment_id,
        "DELIVERY_DISPATCHED",
        f"Shipment dispatched for delivery by {delivery_name} ({delivery_phone})",
        session['user_id'],
        'storage'
    )

    cursor.close()
    connection.close()

    flash('Shipment dispatched for delivery successfully', 'success')
    return redirect('/storage_dashboard')

@app.route('/verify_quantity', methods=['POST'])
@csrf.exempt
def verify_quantity():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json()
    shipment_id = data.get("shipment_id")
    received_qty = data.get("received_qty")

    if not shipment_id or received_qty is None:
        return {'message': 'Invalid data'}, 400

    # Convert quantity
    try:
        received_qty = int(received_qty)
    except (ValueError, TypeError):
        return {'message': 'Invalid quantity'}, 400

    # Fetch shipment from DB
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return {'message': 'Shipment not found'}, 404

    # Compare quantity
    stored_qty = int(shipment['quantity'])

    if received_qty == stored_qty:
        # Update status to IN_TRANSIT
        cursor.execute("UPDATE shipments SET status = 'IN_TRANSIT' WHERE shipment_id = %s", (shipment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return {'message': 'Verification Successful - Shipment IN_TRANSIT'}, 200
    else:
        # Update status to TAMPERED
        cursor.execute("UPDATE shipments SET status = 'TAMPERED' WHERE shipment_id = %s", (shipment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return {'message': 'Quantity Mismatch - Possible Tampering Detected'}, 200

@app.route('/add_transport', methods=['POST'])
def add_transport():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        flash('Unauthorized access')
        return redirect(url_for('login'))

    shipment_id = request.form.get("shipment_id")
    transporter_name = request.form.get("transporter_name")
    vehicle_number = request.form.get("vehicle_number")
    driver_name = request.form.get("driver_name")
    driver_phone = request.form.get("driver_phone")

    if not all([shipment_id, transporter_name, vehicle_number, driver_name, driver_phone]):
        flash('All fields are required')
        return redirect(url_for('distributor_dashboard'))

    # Verify shipment belongs to logged-in distributor and is IN_TRANSIT
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s AND distributor_id = %s", (shipment_id, session['user_id']))
    shipment = cursor.fetchone()

    if not shipment:
        cursor.close()
        connection.close()
        flash('Shipment not found')
        return redirect(url_for('distributor_dashboard'))

    if shipment['status'] != 'IN_TRANSIT':
        cursor.close()
        connection.close()
        flash('Can only add transport details for IN_TRANSIT shipments')
        return redirect(url_for('distributor_dashboard'))

    # Update database
    query = """
    UPDATE shipments SET
        transporter_name = %s,
        vehicle_number = %s,
        driver_name = %s,
        driver_phone = %s,
        dispatch_date = NOW()
    WHERE shipment_id = %s
    """

    cursor.execute(query, (
        transporter_name,
        vehicle_number,
        driver_name,
        driver_phone,
        shipment_id
    ))

    connection.commit()
    cursor.close()
    connection.close()

    flash('Transport details added successfully')
    return redirect(url_for('distributor_dashboard'))

@app.route('/assign_storage', methods=['POST'])
@csrf.exempt
def assign_storage():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json()
    shipment_id = data.get("shipment_id")
    storage_id = data.get("storage_id")

    if not shipment_id or not storage_id:
        return {'message': 'Invalid data'}, 400

    # Verify shipment belongs to logged-in distributor and is IN_TRANSIT
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s AND distributor_id = %s", (shipment_id, session['user_id']))
    shipment = cursor.fetchone()

    if not shipment:
        cursor.close()
        connection.close()
        return {'message': 'Shipment not found'}, 404

    if shipment['status'] != 'IN_TRANSIT':
        cursor.close()
        connection.close()
        return {'message': 'Can only assign storage for IN_TRANSIT shipments'}, 400

    # Update storage_id
    cursor.execute("UPDATE shipments SET storage_id = %s WHERE shipment_id = %s", (storage_id, shipment_id))
    connection.commit()

    # Log the storage assignment
    log_audit_action(
        shipment_id,
        "STORAGE_ASSIGNED",
        f"Storage facility assigned for shipment storage",
        session['user_id'],
        'distributor'
    )

    cursor.close()
    connection.close()

    return {"status": "success"}, 200

@app.route('/verify_inline', methods=['POST'])
def verify_inline():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized', 'success': False}, 403

    data = request.get_json()

    shipment_id = data.get("shipment_id")
    qr_data = data.get("qr_data")
    received_qty = data.get("received_qty")

    # VALIDATE QR
    if not qr_data or "|" not in qr_data:
        return {"message": "Invalid QR data"}

    qr_shipment_id, qr_hash = qr_data.split("|")

    if qr_shipment_id != shipment_id:
        return {"message": "Wrong QR for this shipment"}

    # CONVERT QTY
    try:
        received_qty = int(received_qty)
    except (ValueError, TypeError):
        return {"message": "Invalid quantity entered"}

    # Fetch shipment from database
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return {'message': 'Unauthorized or shipment not found', 'success': False}, 403

    # STEP 1: Hash Verification
    expected_hash = generate_shipment_hash(
        shipment['shipment_id'],
        shipment['product_id'],
        str(shipment['quantity']),
        str(shipment['price_per_unit']),
        str(shipment['manufacturer_id']),
        shipment['previous_hash'] or '0'
    )

    if expected_hash != shipment['current_hash']:
        cursor.execute("UPDATE shipments SET status = 'TAMPERED' WHERE shipment_id = %s", (shipment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return {'message': 'Tampered Data Detected - Hash Mismatch', 'success': False}, 400

    # STEP 2: Quantity Verification
    try:
        stored_qty = int(shipment['quantity'])
    except (ValueError, TypeError):
        cursor.close()
        connection.close()
        return {'message': 'Error reading stored quantity', 'success': False}, 500

    if received_qty != stored_qty:
        cursor.execute("UPDATE shipments SET status = 'TAMPERED' WHERE shipment_id = %s", (shipment_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return {'message': 'Quantity Mismatch - Possible Tampering', 'success': False}, 400

    # STEP 3: Verification Success - Update status to IN_TRANSIT
    cursor.execute("UPDATE shipments SET status = 'IN_TRANSIT' WHERE shipment_id = %s", (shipment_id,))
    connection.commit()
    cursor.close()
    connection.close()

    return {'message': 'Verification Successful - Shipment IN_TRANSIT', 'success': True}, 200

@app.route('/verify/<shipment_id>', methods=['GET', 'POST'])
def verify_shipment(shipment_id):
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return redirect(url_for('login'))

    # Fetch shipment
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return "Unauthorized", 403

    verification_message = None
    verification_status = None
    hash_valid = None

    # ONLY verify on POST request
    if request.method == 'POST':
        # STEP 1: Hash Verification
        expected_hash = generate_shipment_hash(
            shipment['shipment_id'],
            shipment['product_id'],
            str(shipment['quantity']),
            str(shipment['price_per_unit']),
            str(shipment['manufacturer_id']),
            shipment['previous_hash'] or '0'
        )

        hash_valid = expected_hash == shipment['current_hash']

        if not hash_valid:
            # Mark as TAMPERED due to hash mismatch
            cursor.execute("UPDATE shipments SET status = 'TAMPERED' WHERE shipment_id = %s", (shipment_id,))
            connection.commit()
            verification_message = "Data Tampering Detected - Hash Mismatch"
            verification_status = "tampered"
            shipment['status'] = 'TAMPERED'
        else:
            # STEP 2: Quantity Verification (only if hash is valid)
            received_quantity_str = request.form.get('received_quantity')
            try:
                received_quantity = int(received_quantity_str)
            except (ValueError, TypeError):
                verification_message = "Invalid quantity entered"
                verification_status = "error"
            else:
                if received_quantity != shipment['quantity']:
                    # Mark as TAMPERED due to quantity mismatch
                    cursor.execute("UPDATE shipments SET status = 'TAMPERED' WHERE shipment_id = %s", (shipment_id,))
                    connection.commit()
                    verification_message = "Quantity Mismatch - Possible Tampering"
                    verification_status = "tampered"
                    shipment['status'] = 'TAMPERED'
                else:
                    # STEP 3: Verification Success
                    verification_message = "Verification Successful"
                    verification_status = "verified"
                    session['verified_shipment'] = shipment_id
    else:
        # GET request: Just display the form, do NOT perform verification
        hash_valid = True  # Assume valid until proven otherwise on POST

    cursor.close()
    connection.close()

    return render_template('verify.html', 
                           shipment=shipment, 
                           hash_valid=hash_valid,
                           verification_message=verification_message,
                           verification_status=verification_status)

@app.route('/accept_shipment', methods=['POST'])
def accept_shipment():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return redirect(url_for('login'))

    shipment_id = request.form.get('shipment_id')
    if not shipment_id:
        return "Shipment ID required", 400

    # Check if verified
    if session.get('verified_shipment') != shipment_id:
        flash("Please verify the shipment before accepting.")
        return redirect(url_for('distributor_dashboard'))

    # Fetch shipment and verify ownership
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return "Unauthorized", 403

    # Update status to IN_TRANSIT
    cursor.execute("UPDATE shipments SET status = 'IN_TRANSIT' WHERE shipment_id = %s", (shipment_id,))
    connection.commit()

    # Log the shipment acceptance
    log_audit_action(
        shipment_id,
        "SHIPMENT_ACCEPTED",
        f"Shipment accepted by distributor for transport",
        session['user_id'],
        'distributor'
    )

    # Clear verification flag
    session.pop('verified_shipment', None)

    cursor.close()
    connection.close()

    flash("Shipment accepted successfully.")
    return redirect(url_for('distributor_dashboard'))

@app.route('/retailer_dashboard')
def retailer_dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    print("SESSION ROLE:", session.get("role"))
    if session.get("role", "").lower() != "retailer":
        return "Unauthorized"
    
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Fetch shipments assigned to this retailer
    cursor.execute(
        "SELECT * FROM shipments WHERE retailer_id = %s ORDER BY created_at DESC",
        (session['user_id'],)
    )
    shipments = cursor.fetchall()
    
    # Fetch audit logs for each shipment
    for shipment in shipments:
        cursor.execute(
            "SELECT * FROM audit_logs WHERE shipment_id = %s ORDER BY timestamp ASC",
            (shipment['shipment_id'],)
        )
        shipment['audit_logs'] = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return render_template('retailer_dashboard.html', shipments=shipments)

@app.route('/mark_delivered', methods=['POST'])
@csrf.exempt
def mark_delivered():
    if 'user_id' not in session or session.get('role', '').lower() != 'retailer':
        return {'status': 'error', 'message': 'Unauthorized'}, 403
    
    data = request.get_json()
    shipment_id = data.get('shipment_id')
    
    if not shipment_id:
        return {'status': 'error', 'message': 'Shipment ID required'}, 400
    
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Security check: Verify shipment belongs to retailer and is OUT_FOR_DELIVERY
    cursor.execute(
        "SELECT * FROM shipments WHERE shipment_id = %s AND retailer_id = %s",
        (shipment_id, session['user_id'])
    )
    shipment = cursor.fetchone()
    
    if not shipment:
        cursor.close()
        connection.close()
        return {'status': 'error', 'message': 'Shipment not found'}, 404
    
    if shipment['status'] != 'OUT_FOR_DELIVERY':
        cursor.close()
        connection.close()
        return {'status': 'error', 'message': 'Shipment not ready for delivery'}, 400
    
    # Update status to DELIVERED
    cursor.execute(
        "UPDATE shipments SET status = 'DELIVERED' WHERE shipment_id = %s",
        (shipment_id,)
    )
    connection.commit()

    # Log the delivery completion
    log_audit_action(
        shipment_id,
        "DELIVERY_COMPLETED",
        f"Shipment successfully delivered and verified by retailer",
        session['user_id'],
        'retailer'
    )

    cursor.close()
    connection.close()
    
    return {'status': 'success', 'message': 'Shipment marked as delivered'}

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/create_shipment', methods=['GET', 'POST'])
def create_shipment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        print("Form data received:", request.form)  # Debug

        product_name = request.form.get('product_name')
        product_id = request.form.get('product_id')
        quantity_str = request.form.get('quantity')
        price_per_unit_str = request.form.get('price_per_unit')
        delivery_address = request.form.get('delivery_address')
        city = request.form.get('city')
        state = request.form.get('state')
        pincode = request.form.get('pincode')
        retailer_id_str = request.form.get('retailer_id')

        # Validate inputs
        if not all([product_name, product_id, quantity_str, price_per_unit_str, delivery_address, city, state, pincode, retailer_id_str]):
            flash('All fields including retailer selection are required!', 'error')
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id as user_id, business_name as name FROM users WHERE stakeholder = 'retailer'")
            retailers = cursor.fetchall()
            cursor.close()
            connection.close()
            return render_template('create_shipment.html', retailers=retailers)

        try:
            quantity = int(quantity_str)
            price_per_unit = float(price_per_unit_str)
            total_price = quantity * price_per_unit
            retailer_id = int(retailer_id_str)
        except ValueError:
            flash('Invalid quantity, price, or retailer format!', 'error')
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id as user_id, business_name as name FROM users WHERE stakeholder = 'retailer'")
            retailers = cursor.fetchall()
            cursor.close()
            connection.close()
            return render_template('create_shipment.html', retailers=retailers)

        # Generate a unique shipment ID
        shipment_id = generate_shipment_id()

        try:
            # Get previous hash
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT current_hash FROM shipments ORDER BY id DESC LIMIT 1")
            last_shipment = cursor.fetchone()
            previous_hash = last_shipment['current_hash'] if last_shipment else "0"
            cursor.close()
            connection.close()

            # Generate current hash
            current_hash = generate_shipment_hash(shipment_id, product_id, str(quantity), str(price_per_unit), str(session['user_id']), previous_hash)

            # Generate QR code
            generate_qr_code(shipment_id, current_hash)

            # Insert into database with delivery address and retailer
            insert_shipment_into_db(shipment_id, session['user_id'], product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash, delivery_address, city, state, pincode, retailer_id)

            # Log the shipment creation
            log_audit_action(
                shipment_id,
                "SHIPMENT_CREATED",
                f"Shipment created for {product_name} ({quantity} units) to {city}, {state}",
                session['user_id'],
                session.get('role', 'manufacturer')
            )

            flash('Shipment created successfully!', 'success')
            return redirect(url_for('my_shipments'))
        except Exception as e:
            print("ERROR creating shipment:", e)
            flash('Error creating shipment. Please try again.', 'error')
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id as user_id, business_name as name FROM users WHERE stakeholder = 'retailer'")
            retailers = cursor.fetchall()
            cursor.close()
            connection.close()
            return render_template('create_shipment.html', retailers=retailers)

    # GET request - fetch retailers
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT id as user_id, business_name as name FROM users WHERE stakeholder = 'retailer'")
    retailers = cursor.fetchall()
    cursor.close()
    connection.close()
    return render_template('create_shipment.html', retailers=retailers)

@app.route('/my_shipments', methods=['GET', 'POST'])
def my_shipments():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        shipment_id = request.form.get('shipment_id')
        distributor_id = request.form.get('distributor_id')

        if shipment_id and distributor_id:
            try:
                # Get distributor PAN
                connection = get_db_connection()
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT pan_tan_id FROM users WHERE id = %s", (distributor_id,))
                distributor = cursor.fetchone()
                distributor_pan = distributor['pan_tan_id'] if distributor else None

                # Update shipment
                update_query = """
                UPDATE shipments 
                SET distributor_id = %s, distributor_pan = %s, status = 'ASSIGNED' 
                WHERE shipment_id = %s AND manufacturer_id = %s
                """
                cursor.execute(update_query, (distributor_id, distributor_pan, shipment_id, session['user_id']))
                connection.commit()
                cursor.close()
                connection.close()

                flash('Distributor assigned successfully!', 'success')
            except Exception as e:
                print("ERROR assigning distributor:", e)
                flash('Error assigning distributor. Please try again.', 'error')
        else:
            flash('Invalid shipment or distributor selection.', 'error')

        return redirect(url_for('my_shipments'))

    # GET request - fetch shipments and distributors
    manufacturer_id = session['user_id']
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Fetch shipments
    shipment_query = """
    SELECT shipment_id, product_name, quantity, status, current_hash, distributor_id, distributor_pan 
    FROM shipments WHERE manufacturer_id = %s ORDER BY created_at DESC
    """
    cursor.execute(shipment_query, (manufacturer_id,))
    shipments = cursor.fetchall()

    # Fetch distributors
    distributor_query = "SELECT id, business_name, pan_tan_id FROM users WHERE stakeholder = 'Distributor'"
    cursor.execute(distributor_query)
    distributors = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('my_shipments.html', shipments=shipments, distributors=distributors)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5003)