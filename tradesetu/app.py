from multiprocessing import resource_sharer
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
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

if not app.config['SECRET_KEY']:
    raise RuntimeError(
        "SECRET_KEY is missing. Check your local .env file."
    )
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = (
    os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['WTF_CSRF_ENABLED'] = True

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Rate limiting for login attempts (simple in-memory approach)
login_attempts = {}


def hash_password(password, salt=None):
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password, method="scrypt"), None


def verify_password(password, hash_val, salt):
    from werkzeug.security import check_password_hash

    if not hash_val:
        return False

    # New password hashes use Werkzeug scrypt.
    if hash_val.startswith("scrypt:"):
        return check_password_hash(hash_val, password)

    # Legacy SHA-256 + salt verification for existing accounts.
    if not salt:
        return False

    computed_hash = hashlib.sha256(
        (password + salt).encode()
    ).hexdigest()

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

# Database schema is managed in Supabase, not at Flask startup.

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
        app.logger.exception(f"Error logging audit action: {e}")

# Create shipments table if not exists

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
            app.logger.exception(f"Database error during registration: {e}")
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
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()
            conn.close()


            if user and verify_password(password, user['password_hash'], user['salt']):
                # Upgrade legacy password hashes after successful verification.
                if not user['password_hash'].startswith('scrypt:'):
                    new_hash, new_salt = hash_password(password)

                    with get_db_connection() as update_conn:
                        with update_conn.cursor() as update_cursor:
                            update_cursor.execute(
                                """
                                UPDATE users
                                SET password_hash = %s, salt = %s
                                WHERE id = %s
                                """,
                                (new_hash, new_salt, user['id'])
                            )

                # Regenerate session data after successful authentication.
                session.clear()
                session['user_id'] = user['id']
                session['business_name'] = user['business_name']
                session['owner_name'] = user.get('owner_name')
                session['role'] = str(user.get('stakeholder') or '').strip().lower()

                return redirect(url_for('dashboard'))





            else:
                flash('Invalid email or password')
                return redirect(url_for('login'))
        except Exception as e:
            # Log the error but don't expose it to user
            app.logger.exception(f"Database error: {e}")
            flash('Something went wrong. Please try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    role = session.get('role', '').lower()

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
    cursor = connection.cursor()

    # Fetch shipments assigned to this distributor
    cursor.execute(
        "SELECT * FROM shipments WHERE distributor_id = %s ORDER BY created_at DESC",
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
    cursor = connection.cursor()
    cursor.execute(
        "SELECT * FROM shipments WHERE storage_id = %s ORDER BY created_at DESC",
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
def verify_hash():
    try:
        if (
            'user_id' not in session
            or str(session.get('role', '')).strip().lower()
            not in ['distributor', 'storage', 'retailer']
        ):
            return {'status': 'unauthorized'}, 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {'status': 'invalid_data'}, 400

        qr_hash = data.get('qr_hash')
        shipment_id = data.get('shipment_id')

        if not isinstance(qr_hash, str) or not isinstance(shipment_id, str):
            return {'status': 'invalid_data'}, 400

        qr_hash = qr_hash.strip().replace('\n', '').replace('\r', '').lower()
        shipment_id = shipment_id.strip()

        if not qr_hash or not shipment_id:
            return {'status': 'invalid_data'}, 400

        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM shipments WHERE shipment_id = %s",
                    (shipment_id,)
                )
                shipment = cursor.fetchone()
        finally:
            connection.close()

        if not shipment:
            return {'status': 'not_found'}, 404

        role = str(session.get('role', '')).strip().lower()
        user_id = session['user_id']

        if role == 'distributor' and shipment['distributor_id'] != user_id:
            return {'status': 'not_found'}, 404
        elif role == 'storage' and shipment['storage_id'] != user_id:
            return {'status': 'not_found'}, 404
        elif role == 'retailer' and shipment['retailer_id'] != user_id:
            return {'status': 'not_found'}, 404

        stored_hash = shipment['current_hash']
        if not isinstance(stored_hash, str):
            return {'status': 'tampered'}, 200

        stored_hash = stored_hash.strip().lower()

        if qr_hash == stored_hash:
            return {'status': 'valid'}, 200

        return {'status': 'tampered'}, 200

    except Exception:
        app.logger.exception("Shipment hash verification failed")
        return {'status': 'server_error'}, 500


@app.route('/verify_storage_qty', methods=['POST'])
def verify_storage_qty():
    if 'user_id' not in session or session.get('role', '').lower() != 'storage':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {'message': 'Invalid JSON data'}, 400

    shipment_id = data.get("shipment_id")
    received_qty = data.get("received_qty")

    if not isinstance(shipment_id, str) or not shipment_id.strip():
        return {'message': 'Invalid shipment ID'}, 400

    shipment_id = shipment_id.strip()

    if not shipment_id or received_qty is None:
        return {'message': 'Invalid data'}, 400

    try:
        received_qty = int(received_qty)
    except (ValueError, TypeError):
        return {'message': 'Invalid quantity'}, 400

    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['storage_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return {'message': 'Shipment not found'}, 404
    if shipment['status'] != 'IN_TRANSIT':
        cursor.close()
        connection.close()
        return {'message': 'Shipment is not awaiting storage verification'}, 409

    stored_qty = int(shipment['quantity'])
    new_status = 'AT_STORAGE' if received_qty == stored_qty else 'TAMPERED'

    cursor.execute("""
            UPDATE shipments
            SET status = %s
            WHERE shipment_id = %s
        AND storage_id = %s
        AND status = 'IN_TRANSIT'
    """, (new_status, shipment_id, session['user_id']))

    if cursor.rowcount != 1:
        connection.rollback()
        cursor.close()
        connection.close()
        return {
            'message': 'Shipment changed during storage verification',
            'success': False
        }, 409

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
    cursor = connection.cursor()
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
        AND storage_id = %s
        AND status = 'AT_STORAGE'
    """, (
        delivery_name,
        delivery_phone,
        shipment_id,
        session['user_id']
    ))

    if cursor.rowcount != 1:
        connection.rollback()
        cursor.close()
        connection.close()
        flash('Shipment could not be dispatched. Please refresh and try again.', 'error')
        return redirect('/storage_dashboard')

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
def verify_quantity():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {'message': 'Invalid JSON data'}, 400

    shipment_id = data.get("shipment_id")
    received_qty = data.get("received_qty")

    if not isinstance(shipment_id, str) or not shipment_id.strip():
        return {'message': 'Invalid shipment ID'}, 400

    shipment_id = shipment_id.strip()

    if not shipment_id or received_qty is None:
        return {'message': 'Invalid data'}, 400

    # Convert quantity
    try:
        received_qty = int(received_qty)
    except (ValueError, TypeError):
        return {'message': 'Invalid quantity'}, 400

    # Fetch shipment from DB
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return {'message': 'Shipment not found'}, 404

    # Only verify shipments awaiting distributor verification.
    if shipment['status'] != 'ASSIGNED':
        cursor.close()
        connection.close()
        return {'message': 'Shipment is not awaiting verification'}, 409

    stored_qty = int(shipment['quantity'])

    if received_qty == stored_qty:
        new_status = 'IN_TRANSIT'
    else:
        new_status = 'TAMPERED'

    cursor.execute("""
        UPDATE shipments
        SET status = %s
        WHERE shipment_id = %s
        AND distributor_id = %s
        AND status = 'ASSIGNED'
    """, (new_status, shipment_id, session['user_id']))

    if cursor.rowcount != 1:
        connection.rollback()
        cursor.close()
        connection.close()
        return {'message': 'Shipment changed or could not be verified'}, 409

    connection.commit()
    cursor.close()
    connection.close()

    if new_status == 'IN_TRANSIT':
        return {'message': 'Verification Successful - Shipment IN_TRANSIT'}, 200

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
    cursor = connection.cursor()
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

        # Update database only if ownership and status still match.
    query = """
    UPDATE shipments
    SET transporter_name = %s,
        vehicle_number = %s,
        driver_name = %s,
        driver_phone = %s,
        dispatch_date = NOW()
    WHERE shipment_id = %s
      AND distributor_id = %s
      AND status = 'IN_TRANSIT'
    """

    cursor.execute(query, (
        transporter_name,
        vehicle_number,
        driver_name,
        driver_phone,
        shipment_id,
        session['user_id']
    ))

    if cursor.rowcount != 1:
        connection.rollback()
        cursor.close()
        connection.close()
        flash('Shipment changed or could not be updated. Please refresh and try again.', 'error')
        return redirect(url_for('distributor_dashboard'))

    connection.commit()
    cursor.close()
    connection.close()

    flash('Transport details added successfully')
    return redirect(url_for('distributor_dashboard'))


@app.route('/assign_storage', methods=['POST'])
def assign_storage():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized'}, 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {'message': 'Invalid JSON data'}, 400

    shipment_id = data.get('shipment_id')
    storage_id = data.get('storage_id')

    if not isinstance(shipment_id, str) or not shipment_id.strip():
        return {'message': 'Invalid shipment ID'}, 400

    shipment_id = shipment_id.strip()

    try:
        storage_id = int(storage_id)
        if storage_id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return {'message': 'Invalid storage selection'}, 400

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # Confirm the selected account is an active storage facility.
        cursor.execute("""
            SELECT id
            FROM users
            WHERE id = %s
              AND LOWER(TRIM(stakeholder)) = 'storage'
              AND is_active = TRUE
        """, (storage_id,))
        storage = cursor.fetchone()

        if not storage:
            return {'message': 'Invalid or inactive storage facility'}, 400

        # Assign storage only to this distributor's shipment in the correct state.
        cursor.execute("""
            UPDATE shipments
            SET storage_id = %s
            WHERE shipment_id = %s
              AND distributor_id = %s
              AND status = 'IN_TRANSIT'
        """, (storage_id, shipment_id, session['user_id']))

        if cursor.rowcount != 1:
            connection.rollback()
            return {
                'message': 'Shipment not found or not eligible for storage assignment'
            }, 409

        connection.commit()

    except Exception:
        connection.rollback()
        app.logger.exception("Error assigning storage facility")
        return {'message': 'Unable to assign storage facility'}, 500

    finally:
        cursor.close()
        connection.close()

    log_audit_action(
        shipment_id,
        "STORAGE_ASSIGNED",
        "Storage facility assigned for shipment storage",
        session['user_id'],
        'distributor'
    )

    return {'status': 'success'}, 200



@app.route('/verify_inline', methods=['POST'])
def verify_inline():
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return {'message': 'Unauthorized', 'success': False}, 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {'message': 'Invalid JSON data', 'success': False}, 400

    shipment_id = data.get('shipment_id')
    qr_data = data.get('qr_data')
    received_qty = data.get('received_qty')

    if not isinstance(shipment_id, str) or not shipment_id.strip():
        return {'message': 'Invalid shipment ID', 'success': False}, 400
    shipment_id = shipment_id.strip()

    if not isinstance(qr_data, str) or '|' not in qr_data:
        return {'message': 'Invalid QR data', 'success': False}, 400

    qr_shipment_id, qr_hash = qr_data.split('|', 1)
    if qr_shipment_id != shipment_id or not qr_hash:
        return {'message': 'Wrong or invalid QR data', 'success': False}, 400

    try:
        received_qty = int(received_qty)
        if received_qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        return {'message': 'Invalid quantity entered', 'success': False}, 400

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT * FROM shipments WHERE shipment_id = %s",
            (shipment_id,)
        )
        shipment = cursor.fetchone()

        if not shipment or shipment['distributor_id'] != session['user_id']:
            return {'message': 'Unauthorized or shipment not found', 'success': False}, 403

        if shipment['status'] != 'ASSIGNED':
            return {'message': 'Shipment is not awaiting verification', 'success': False}, 409

        expected_hash = generate_shipment_hash(
            shipment['shipment_id'],
            shipment['product_id'],
            str(shipment['quantity']),
            str(shipment['price_per_unit']),
            str(shipment['manufacturer_id']),
            shipment['previous_hash'] or '0'
        )

        # Verify both the stored shipment hash and the QR hash.
        if expected_hash != shipment['current_hash'] or qr_hash != shipment['current_hash']:
            new_status = 'TAMPERED'
            message = 'Tampered Data Detected - Hash Mismatch'
            success = False
            status_code = 400
        elif received_qty != int(shipment['quantity']):
            new_status = 'TAMPERED'
            message = 'Quantity Mismatch - Possible Tampering'
            success = False
            status_code = 400
        else:
            new_status = 'IN_TRANSIT'
            message = 'Verification Successful - Shipment IN_TRANSIT'
            success = True
            status_code = 200

        cursor.execute("""
            UPDATE shipments
            SET status = %s
            WHERE shipment_id = %s
              AND distributor_id = %s
              AND status = 'ASSIGNED'
        """, (new_status, shipment_id, session['user_id']))

        if cursor.rowcount != 1:
            connection.rollback()
            return {
                'message': 'Shipment changed during verification',
                'success': False
            }, 409

        connection.commit()
        return {'message': message, 'success': success}, status_code

    except (ValueError, TypeError):
        connection.rollback()
        return {'message': 'Invalid stored shipment quantity', 'success': False}, 500
    except Exception:
        connection.rollback()
        app.logger.exception("Error verifying shipment")
        return {'message': 'Unable to verify shipment', 'success': False}, 500
    finally:
        cursor.close()
        connection.close()



@app.route('/verify/<shipment_id>', methods=['GET', 'POST'])
def verify_shipment(shipment_id):
    if 'user_id' not in session or session.get('role', '').lower() != 'distributor':
        return redirect(url_for('login'))

    # Clear any previous verification before starting a new attempt.
    if request.method == 'POST':
        session.pop('verified_shipment', None)

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT * FROM shipments WHERE shipment_id = %s",
            (shipment_id,)
        )
        shipment = cursor.fetchone()

        if not shipment or shipment['distributor_id'] != session['user_id']:
            return "Shipment not found or unauthorized", 404

        verification_message = None
        verification_status = None
        hash_valid = None

        if request.method == 'POST':
            if shipment['status'] != 'ASSIGNED':
                verification_message = "Shipment is not awaiting verification"
                verification_status = "error"
                hash_valid = False
            else:
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
                    new_status = 'TAMPERED'
                    verification_message = "Data Tampering Detected - Hash Mismatch"
                    verification_status = "tampered"
                else:
                    received_quantity_str = request.form.get('received_quantity')
                    try:
                        received_quantity = int(received_quantity_str)
                        if received_quantity < 0:
                            raise ValueError
                    except (ValueError, TypeError):
                        verification_message = "Invalid quantity entered"
                        verification_status = "error"
                    else:
                        if received_quantity != int(shipment['quantity']):
                            new_status = 'TAMPERED'
                            verification_message = "Quantity Mismatch - Possible Tampering"
                            verification_status = "tampered"
                        else:
                            new_status = None
                            verification_message = "Verification Successful"
                            verification_status = "verified"

                if verification_status == "tampered":
                    cursor.execute("""
                        UPDATE shipments
                        SET status = %s
                        WHERE shipment_id = %s
                          AND distributor_id = %s
                          AND status = 'ASSIGNED'
                    """, (new_status, shipment_id, session['user_id']))

                    if cursor.rowcount != 1:
                        connection.rollback()
                        verification_message = "Shipment changed during verification. Please retry."
                        verification_status = "error"
                    else:
                        connection.commit()
                        shipment['status'] = 'TAMPERED'

                elif verification_status == "verified":
                    session['verified_shipment'] = shipment_id

        else:
            # GET only displays the verification form.
            hash_valid = None

        return render_template(
            'verify.html',
            shipment=shipment,
            hash_valid=hash_valid,
            verification_message=verification_message,
            verification_status=verification_status
        )

    except Exception:
        connection.rollback()
        app.logger.exception("Error verifying shipment")
        return "Unable to verify shipment right now", 500
    finally:
        cursor.close()
        connection.close()


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
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM shipments WHERE shipment_id = %s", (shipment_id,))
    shipment = cursor.fetchone()

    if not shipment or shipment['distributor_id'] != session['user_id']:
        cursor.close()
        connection.close()
        return "Unauthorized", 403

    # Update only if the shipment is still assigned to this distributor.
    cursor.execute("""
        UPDATE shipments
        SET status = 'IN_TRANSIT'
        WHERE shipment_id = %s
          AND distributor_id = %s
          AND status = 'ASSIGNED'
    """, (shipment_id, session['user_id']))

    if cursor.rowcount != 1:
        connection.rollback()
        cursor.close()
        connection.close()
        session.pop('verified_shipment', None)
        flash('Shipment is no longer available for acceptance.', 'error')
        return redirect(url_for('distributor_dashboard'))

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


    if session.get("role", "").lower() != "retailer":
        return "Unauthorized"

    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch shipments assigned to this retailer
    cursor.execute(
        "SELECT * FROM shipments WHERE retailer_id = %s ORDER BY created_at DESC",
        (session['user_id'],)
    )
    shipments = cursor.fetchall()

    # Fetch audit logs for each shipment
    for shipment in shipments:
        cursor.execute(
            "SELECT * FROM audit_logs WHERE shipment_id = %s ORDER BY created_at ASC",
            (shipment['shipment_id'],)
        )
        shipment['audit_logs'] = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('retailer_dashboard.html', shipments=shipments)


@app.route('/mark_delivered', methods=['POST'])
def mark_delivered():
    if 'user_id' not in session or session.get('role', '').lower() != 'retailer':
        return {'status': 'error', 'message': 'Unauthorized'}, 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {'status': 'error', 'message': 'Invalid JSON data'}, 400

    shipment_id = data.get('shipment_id')
    if not isinstance(shipment_id, str) or not shipment_id.strip():
        return {'status': 'error', 'message': 'Shipment ID required'}, 400

    shipment_id = shipment_id.strip()

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT status
            FROM shipments
            WHERE shipment_id = %s AND retailer_id = %s
            """,
            (shipment_id, session['user_id'])
        )
        shipment = cursor.fetchone()

        if not shipment:
            return {'status': 'error', 'message': 'Shipment not found'}, 404

        if shipment['status'] != 'OUT_FOR_DELIVERY':
            return {
                'status': 'error',
                'message': 'Shipment not ready for delivery'
            }, 409

        cursor.execute(
            """
            UPDATE shipments
            SET status = 'DELIVERED'
            WHERE shipment_id = %s
              AND retailer_id = %s
              AND status = 'OUT_FOR_DELIVERY'
            """,
            (shipment_id, session['user_id'])
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return {
                'status': 'error',
                'message': 'Shipment changed during delivery confirmation'
            }, 409

        connection.commit()

    except Exception:
        connection.rollback()
        app.logger.exception("Error marking shipment delivered")
        return {
            'status': 'error',
            'message': 'Unable to confirm delivery'
        }, 500
    finally:
        cursor.close()
        connection.close()

    log_audit_action(
        shipment_id,
        "DELIVERY_COMPLETED",
        "Shipment successfully delivered and verified by retailer",
        session['user_id'],
        'retailer'
    )

    return {
        'status': 'success',
        'message': 'Shipment marked as delivered'
    }, 200


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/create_shipment', methods=['GET', 'POST'])
def create_shipment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':


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
            cursor = connection.cursor()
            cursor.execute("""
    SELECT id AS user_id, business_name AS name
    FROM users
    WHERE LOWER(TRIM(stakeholder)) = 'retailer'
      AND is_active = TRUE
    ORDER BY business_name
""")
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
            cursor = connection.cursor()
            cursor.execute("""
    SELECT id AS user_id, business_name AS name
    FROM users
    WHERE LOWER(TRIM(stakeholder)) = 'retailer'
      AND is_active = TRUE
    ORDER BY business_name
""")
            retailers = cursor.fetchall()
            cursor.close()
            connection.close()
            return render_template('create_shipment.html', retailers=retailers)

        # Generate a unique shipment ID
        shipment_id = generate_shipment_id()

        try:
            # Get previous hash
            connection = get_db_connection()
            cursor = connection.cursor()
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
            app.logger.exception("ERROR creating shipment:", e)
            flash('Error creating shipment. Please try again.', 'error')
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("""
    SELECT id AS user_id, business_name AS name
    FROM users
    WHERE LOWER(TRIM(stakeholder)) = 'retailer'
      AND is_active = TRUE
    ORDER BY business_name
""")
            retailers = cursor.fetchall()
            cursor.close()
            connection.close()
            return render_template('create_shipment.html', retailers=retailers)

    # GET request - fetch retailers
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("""
    SELECT id AS user_id, business_name AS name
    FROM users
    WHERE LOWER(TRIM(stakeholder)) = 'retailer'
      AND is_active = TRUE
    ORDER BY business_name
""")
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

                # Validate that the selected account is an active distributor.
                connection = get_db_connection()
                cursor = connection.cursor()

                cursor.execute(
                    """
                    SELECT pan_tan_id
                    FROM users
                    WHERE id = %s
                    AND LOWER(TRIM(stakeholder)) = 'distributor'
                    AND is_active = TRUE
                    """,
                    (distributor_id,)
                )
                distributor = cursor.fetchone()

                if not distributor:
                    cursor.close()
                    connection.close()
                    flash('Invalid distributor selection.', 'error')
                    return redirect(url_for('my_shipments'))

                distributor_pan = distributor['pan_tan_id']

                # Update shipment
                update_query = """
                UPDATE shipments
                SET distributor_id = %s, distributor_pan = %s, status = 'ASSIGNED'
                WHERE shipment_id = %s
                AND manufacturer_id = %s
                AND status = 'CREATED'
                """

                cursor.execute(
                    update_query,
                    (distributor_id, distributor_pan, shipment_id, session['user_id'])
                )

                if cursor.rowcount != 1:
                    connection.rollback()
                    cursor.close()
                    connection.close()
                    return {
                        'message': 'Shipment changed during verification',
                        'success': False
                    }, 409

                connection.commit()

                cursor.close()
                connection.close()

                flash('Distributor assigned successfully!', 'success')
            except Exception as e:
                app.logger.exception("ERROR assigning distributor:", e)
                flash('Error assigning distributor. Please try again.', 'error')
        else:
            flash('Invalid shipment or distributor selection.', 'error')

        return redirect(url_for('my_shipments'))

    # GET request - fetch shipments and distributors
    manufacturer_id = session['user_id']
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch shipments
    shipment_query = """
    SELECT shipment_id, product_name, quantity, status, current_hash, distributor_id, distributor_pan
    FROM shipments WHERE manufacturer_id = %s ORDER BY created_at DESC
    """
    cursor.execute(shipment_query, (manufacturer_id,))
    shipments = cursor.fetchall()

    # Recreate QR images if the deployment filesystem has lost them.
    qr_folder = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "static",
        "qr_codes",
    )
    os.makedirs(qr_folder, exist_ok=True)

    for shipment in shipments:
        qr_path = os.path.join(
            qr_folder,
            f"{shipment['shipment_id']}.png",
        )
        if not os.path.exists(qr_path):
            generate_qr_code(
                shipment['shipment_id'],
                shipment['current_hash'],
            )

    # Fetch distributors
    distributor_query = "SELECT id, business_name, pan_tan_id FROM users WHERE stakeholder = 'Distributor'"
    cursor.execute(distributor_query)
    distributors = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template('my_shipments.html', shipments=shipments, distributors=distributors)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5003)
