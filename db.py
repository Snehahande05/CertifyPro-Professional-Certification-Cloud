import os
import sqlite3
import mysql.connector
from mysql.connector import pooling
from werkzeug.security import generate_password_hash

# Read environment variables
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME', 'certifypro')
DB_PORT = os.getenv('DB_PORT', '3306')

# Check if MySQL is configured
USE_MYSQL = all([DB_HOST, DB_USER, DB_PASSWORD])

db_pool = None

if USE_MYSQL:
    try:
        db_pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="certifypro_pool",
            pool_size=5,
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=int(DB_PORT)
        )
        print("Connected to MySQL Database Pool successfully!")
    except Exception as e:
        print(f"Error connecting to MySQL: {e}. Falling back to SQLite.")
        USE_MYSQL = False

# SQLite database file path
SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'certifypro.db')

def get_db_connection():
    """Returns a database connection and a boolean indicating if it is MySQL."""
    if USE_MYSQL and db_pool:
        try:
            return db_pool.get_connection(), True
        except Exception as e:
            print(f"MySQL Pool connection failed: {e}. Reverting to SQLite for this connection.")
    
    # Fallback to SQLite
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn, False

def execute_query(query, params=None, is_write=False):
    """
    Executes a query and returns the results.
    Automatically handles parameter differences between SQLite (?) and MySQL (%s).
    """
    conn, is_mysql = get_db_connection()
    cursor = conn.cursor(dictionary=True) if is_mysql else conn.cursor()
    
    if not is_mysql:
        # SQLite uses ? instead of %s
        query = query.replace('%s', '?')
        # SQLite doesn't support ON UPDATE CURRENT_TIMESTAMP directly in standard SQL tables easily, but we handle it
        # Also remove INT AUTO_INCREMENT and replace with INTEGER PRIMARY KEY AUTOINCREMENT if creating tables
        if "AUTO_INCREMENT" in query:
            query = query.replace("AUTO_INCREMENT PRIMARY KEY", "PRIMARY KEY AUTOINCREMENT")
            query = query.replace("INT AUTO_INCREMENT", "INTEGER PRIMARY KEY AUTOINCREMENT")
            query = query.replace("INT", "INTEGER")
    
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
            
        if is_write:
            conn.commit()
            last_id = cursor.lastrowid
            return last_id
        else:
            if is_mysql:
                results = cursor.fetchall()
            else:
                # Convert SQLite row objects to list of dicts for consistency
                rows = cursor.fetchall()
                results = [dict(row) for row in rows]
            return results
    except Exception as e:
        print(f"Database query error: {e}")
        if is_write:
            conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def using_mysql():
    """Return True when the app is connected to MySQL/RDS."""
    return USE_MYSQL and db_pool is not None

def month_group_query(date_column):
    """Database-compatible month grouping expression."""
    if using_mysql():
        return f"DATE_FORMAT({date_column}, '%b %Y')"
    return f"strftime('%m-%Y', {date_column})"

def init_db():
    """Initializes the database by creating tables and seeding default users."""
    conn, is_mysql = get_db_connection()
    cursor = conn.cursor()
    
    # Read schema.sql contents
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
    if not os.path.exists(schema_path):
        print("schema.sql not found. Cannot initialize database.")
        return
        
    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    # Remove SQL comment lines before executing schema
    schema_sql = "\n".join(
        line for line in schema_sql.splitlines()
        if not line.strip().startswith("--")
    )
        
    if is_mysql:
        try:
            # For MySQL, we execute statements split by semicolon
            # We skip drop statements if they fail
            statements = schema_sql.split(';')
            for statement in statements:
                stmt = statement.strip()
                if stmt and not stmt.upper().startswith('DROP TABLE'):
                    try:
                        cursor.execute(stmt)
                    except Exception as err:
                        print(f"Executing statement failed: {err}")
            conn.commit()
            print("MySQL Database schema initialized successfully.")
        except Exception as e:
            print(f"Error initializing MySQL schema: {e}")
    else:
        # For SQLite, we adapt the SQL statements
        try:
            sqlite_sql = schema_sql
            # Convert MySQL syntax to SQLite syntax
            sqlite_sql = sqlite_sql.replace("AUTO_INCREMENT PRIMARY KEY", "PRIMARY KEY AUTOINCREMENT")
            sqlite_sql = sqlite_sql.replace("INT AUTO_INCREMENT", "INTEGER PRIMARY KEY AUTOINCREMENT")
            sqlite_sql = sqlite_sql.replace("ENUM('Administrator', 'Manager', 'Staff')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Active', 'Inactive', 'Suspended')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Pass', 'Fail', 'Pending')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Draft', 'Pending Manager Approval', 'Pending Admin Approval', 'Approved', 'Rejected')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Staff Draft', 'Manager Review', 'Admin Review', 'Completed', 'Rejected')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Approved', 'Rejected', 'Pending')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENUM('Pending', 'Approved', 'Rejected')", "TEXT")
            sqlite_sql = sqlite_sql.replace("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci", "")
            sqlite_sql = sqlite_sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP", "DATETIME DEFAULT CURRENT_TIMESTAMP")
            sqlite_sql = sqlite_sql.replace("TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "DATETIME DEFAULT CURRENT_TIMESTAMP")
            sqlite_sql = sqlite_sql.replace("TIMESTAMP", "DATETIME")
            sqlite_sql = sqlite_sql.replace("INT", "INTEGER")
            
            # Remove SQL comment lines
            sqlite_sql = "\n".join(
                line for line in sqlite_sql.splitlines()
                if not line.strip().startswith("--")
            )
            statements = sqlite_sql.split(';')
            for statement in statements:
                stmt = statement.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        cursor.execute(stmt)
                    except Exception as err:
                        # SQLite might complain about dropped tables that don't exist yet, which is fine
                        if "no such table" not in str(err).lower():
                            print(f"SQLite initialization warning/error: {err} for statement: {stmt[:50]}...")
            conn.commit()
            print("SQLite Database schema initialized successfully.")
        except Exception as e:
            print(f"Error initializing SQLite schema: {e}")
            
    cursor.close()
    conn.close()
    
    # Seed default users
    seed_users()

def seed_users():
    """Seeds default Administrator, Manager, and Staff users if they do not exist."""
    users = [
        {
            "username": "admin",
            "password": "admin123",
            "email": "admin@certifypro.cloud",
            "role": "Administrator",
            "full_name": "Amanda Cloud"
        },
        {
            "username": "manager",
            "password": "manager123",
            "email": "manager@certifypro.cloud",
            "role": "Manager",
            "full_name": "Marcus Director"
        },
        {
            "username": "staff",
            "password": "staff123",
            "email": "staff@certifypro.cloud",
            "role": "Staff",
            "full_name": "Sarah Operations"
        }
    ]
    
    for u in users:
        # Check if user already exists
        existing = execute_query("SELECT id FROM users WHERE username = %s", (u["username"],))
        if not existing:
            hashed = generate_password_hash(u["password"])
            execute_query(
                "INSERT INTO users (username, password_hash, email, role, full_name) VALUES (%s, %s, %s, %s, %s)",
                (u["username"], hashed, u["email"], u["role"], u["full_name"]),
                is_write=True
            )
            print(f"Seeded user: {u['username']} ({u['role']})")
