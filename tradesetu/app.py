from flask import Flask, render_template, request, redirect, url_for, session, flash
import hashlib
import os
import re
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

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT email, owner_name FROM users WHERE id = %s', (session['user_id'],))
        user = cursor.fetchone()
        conn.close()

        if not user:
            session.clear()
            flash('Session expired. Please login again.')
            return redirect(url_for('login'))

        return render_template('dashboard.html', user=user)
    except Exception as e:
        # Log the error but don't expose it to user
        print(f"Database error in dashboard: {e}")
        flash('Something went wrong. Please try again.')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5006)