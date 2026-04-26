from flask import Flask, render_template, request, redirect, url_for, session, flash
import hashlib
import os
import re
import random
import qrcode
from db_config import get_db_connection
from flask_wtf import CSRFProtect

app = Flask(__name__)

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
    data = f"{shipment_id}{product_id}{quantity}{price}{manufacturer_id}{previous_hash}"
    return hashlib.sha256(data.encode()).hexdigest()

def generate_qr_code(shipment_id, current_hash):
    qr_data = f"{shipment_id}|{current_hash}"
    qr = qrcode.make(qr_data)
    qr_path = os.path.join(os.getcwd(), "static", "qr_codes", f"{shipment_id}.png")
    qr.save(qr_path)
    return qr_path

def insert_shipment_into_db(shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash):
    connection = get_db_connection()
    cursor = connection.cursor()

    query = """
    INSERT INTO shipments (
        shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    values = (
        shipment_id, manufacturer_id, product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash
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
            status ENUM('CREATED','ASSIGNED','IN_TRANSIT','DELIVERED','TAMPERED') DEFAULT 'CREATED',
            previous_hash VARCHAR(256),
            current_hash VARCHAR(256) NOT NULL,
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

# Create shipments table if not exists
create_shipments_table()

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
                session['owner_name'] = user['owner_name']
                session['business_name'] = user['business_name']
                session['stakeholder'] = user['stakeholder']
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
        return redirect(url_for('login'))

    if session.get('stakeholder') != 'Manufacturer':
        return "Unauthorized", 403

    return render_template('manufacturer_dashboard.html', 
                           owner_name=session.get('owner_name'), 
                           business_name=session.get('business_name'))

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

        # Validate inputs
        if not all([product_name, product_id, quantity_str, price_per_unit_str]):
            flash('All fields are required!', 'error')
            return render_template('create_shipment.html')

        try:
            quantity = int(quantity_str)
            price_per_unit = float(price_per_unit_str)
            total_price = quantity * price_per_unit
        except ValueError:
            flash('Invalid quantity or price format!', 'error')
            return render_template('create_shipment.html')

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

            # Insert into database
            insert_shipment_into_db(shipment_id, session['user_id'], product_name, product_id, quantity, price_per_unit, total_price, previous_hash, current_hash)

            flash('Shipment created successfully!', 'success')
            return redirect(url_for('my_shipments'))
        except Exception as e:
            print("ERROR creating shipment:", e)
            flash('Error creating shipment. Please try again.', 'error')
            return render_template('create_shipment.html')

    return render_template('create_shipment.html')

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
    app.run(debug=False, host='0.0.0.0', port=5006)