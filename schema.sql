-- CertifyPro MySQL Database Schema

-- Drop tables in reverse order of dependencies

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    role ENUM('Administrator', 'Manager', 'Staff') NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Candidates Table
CREATE TABLE IF NOT EXISTS candidates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL,
    region VARCHAR(50) NOT NULL,
    cert_program VARCHAR(100) NOT NULL,
    registration_date DATE NOT NULL,
    status ENUM('Active', 'Inactive', 'Suspended') DEFAULT 'Active',
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Certifications Table
CREATE TABLE IF NOT EXISTS certifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cert_name VARCHAR(100) NOT NULL,
    candidate_id INT NOT NULL,
    exam_date DATE NOT NULL,
    result ENUM('Pass', 'Fail', 'Pending') DEFAULT 'Pending',
    expiry_date DATE NULL,
    status ENUM('Draft', 'Pending Manager Approval', 'Pending Admin Approval', 'Approved', 'Rejected') DEFAULT 'Draft',
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by INT,
    candidate_id INT NULL,
    cert_id INT NULL,
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE SET NULL,
    FOREIGN KEY (cert_id) REFERENCES certifications(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Workflows Table
CREATE TABLE IF NOT EXISTS workflows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cert_id INT NOT NULL,
    candidate_id INT NOT NULL,
    current_stage ENUM('Staff Draft', 'Manager Review', 'Admin Review', 'Completed', 'Rejected') DEFAULT 'Staff Draft',
    status ENUM('Pending', 'Approved', 'Rejected') DEFAULT 'Pending',
    staff_id INT NOT NULL,
    staff_notes TEXT,
    manager_id INT NULL,
    manager_status ENUM('Approved', 'Rejected', 'Pending') DEFAULT 'Pending',
    manager_notes TEXT,
    manager_approved_at TIMESTAMP NULL,
    admin_id INT NULL,
    admin_status ENUM('Approved', 'Rejected', 'Pending') DEFAULT 'Pending',
    admin_notes TEXT,
    admin_approved_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (cert_id) REFERENCES certifications(id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Reports Table
CREATE TABLE IF NOT EXISTS reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    query_parameters VARCHAR(255) NULL,
    generated_by INT NULL,
    file_path VARCHAR(255) NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (generated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert Seed Users (Default password is 'password123' hashed with pbkdf2:sha256)
-- Specifically, we'll hash them in python, but here we place dummy hashes that our Flask server will recognize or reset.
-- For standard Werkzeug hashing: 'scrypt:32768:8:1$K7pSg7G$...' 
-- We'll initialize the database and create default users programmatically if not present, which is safer!
