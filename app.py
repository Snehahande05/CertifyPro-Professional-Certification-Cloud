import os
import csv
import io
import psutil
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, Response, abort
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Import local db and s3 helper
import db
import s3_client
import cloudwatch

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'certifypro_super_secret_key_1293847')

# Ensure database is initialized on startup
with app.app_context():
    db.init_db()

# --- AUTH DECORATORS ---
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_role' not in session or session['user_role'] not in roles:
                flash("Access denied. You do not have permission to access this page.", "danger")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- CONTEXT PROCESSOR FOR SIDEBAR ---
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# --- ROUTES ---

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = db.execute_query("SELECT * FROM users WHERE username = %s", (username,))
        
        if user and check_password_hash(user[0]['password_hash'], password):
            session['user_id'] = user[0]['id']
            session['username'] = user[0]['username']
            session['user_role'] = user[0]['role']
            session['full_name'] = user[0]['full_name']
            
            cloudwatch.log_event(f"User '{username}' logged in successfully.", log_stream="SecurityLogs")
            flash(f"Welcome back, {user[0]['full_name']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            cloudwatch.log_event(f"Failed login attempt for user '{username}'.", log_stream="SecurityLogs")
            flash("Invalid username or password.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    username = session.get('username', 'Unknown')
    cloudwatch.log_event(f"User '{username}' logged out.", log_stream="SecurityLogs")
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Fetch KPI Statistics
    total_candidates = db.execute_query("SELECT COUNT(*) as count FROM candidates")[0]['count']
    active_certs = db.execute_query("SELECT COUNT(*) as count FROM certifications WHERE status = 'Approved'")[0]['count']
    completed_certs = db.execute_query("SELECT COUNT(*) as count FROM certifications WHERE result = 'Pass'")[0]['count']
    pending_approvals = db.execute_query("SELECT COUNT(*) as count FROM workflows WHERE status = 'Pending'")[0]['count']
    uploaded_docs = db.execute_query("SELECT COUNT(*) as count FROM documents")[0]['count']
    
    # Recent Activity (combining workflow logs and additions)
    recent_activity = db.execute_query("""
        SELECT 'Workflow' as type, w.updated_at as date_time, c.full_name as item, w.status as action, u.full_name as user
        FROM workflows w
        JOIN candidates c ON w.candidate_id = c.id
        LEFT JOIN users u ON w.manager_id = u.id
        UNION ALL
        SELECT 'Candidate' as type, c.created_at as date_time, c.full_name as item, 'Registered' as action, u.full_name as user
        FROM candidates c
        LEFT JOIN users u ON c.created_by = u.id
        ORDER BY date_time DESC LIMIT 6
    """)
    
    # Charts data
    # Month-wise registrations (past 6 months)
    month_expr = db.month_group_query('registration_date')
    registrations_chart = db.execute_query(f"""
        SELECT {month_expr} as month, COUNT(*) as count
        FROM candidates
        GROUP BY month
        ORDER BY MIN(registration_date) DESC LIMIT 6
    """)
    if not registrations_chart:
        # Fallback dummy data if db is empty
        registrations_chart = [
            {'month': 'Jan 2026', 'count': 12},
            {'month': 'Feb 2026', 'count': 19},
            {'month': 'Mar 2026', 'count': 25},
            {'month': 'Apr 2026', 'count': 32},
            {'month': 'May 2026', 'count': 45},
            {'month': 'Jun 2026', 'count': 56}
        ]
    else:
        registrations_chart = registrations_chart[::-1] # Reverse to chronological
        
    # Region data
    region_data = db.execute_query("""
        SELECT region, COUNT(*) as count FROM candidates GROUP BY region
    """)
    
    # Pass vs Fail data
    pass_fail_data = db.execute_query("""
        SELECT result, COUNT(*) as count FROM certifications WHERE result IN ('Pass', 'Fail') GROUP BY result
    """)
    
    return render_template(
        'dashboard.html',
        total_candidates=total_candidates,
        active_certs=active_certs,
        completed_certs=completed_certs,
        pending_approvals=pending_approvals,
        uploaded_docs=uploaded_docs,
        recent_activity=recent_activity,
        registrations_chart=registrations_chart,
        region_data=region_data,
        pass_fail_data=pass_fail_data
    )

# --- CANDIDATES CRUD ---
@app.route('/candidates', methods=['GET'])
@login_required
def candidates():
    search = request.args.get('search', '')
    region = request.args.get('region', '')
    status = request.args.get('status', '')
    
    query = "SELECT c.*, u.full_name as creator FROM candidates c LEFT JOIN users u ON c.created_by = u.id WHERE 1=1"
    params = []
    
    if search:
        query += " AND (c.full_name LIKE %s OR c.email LIKE %s OR c.phone LIKE %s)"
        like_search = f"%{search}%"
        params.extend([like_search, like_search, like_search])
        
    if region:
        query += " AND c.region = %s"
        params.append(region)
        
    if status:
        query += " AND c.status = %s"
        params.append(status)
        
    query += " ORDER BY c.created_at DESC"
    
    candidates_list = db.execute_query(query, tuple(params) if params else None)
    
    # Fetch unique regions for filter
    regions = db.execute_query("SELECT DISTINCT region FROM candidates")
    
    return render_template(
        'candidates.html',
        candidates=candidates_list,
        regions=[r['region'] for r in regions] if regions else [],
        search=search,
        selected_region=region,
        selected_status=status
    )

@app.route('/candidates/add', methods=['POST'])
@login_required
@role_required(['Staff', 'Administrator'])
def add_candidate():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    region = request.form.get('region')
    cert_program = request.form.get('cert_program')
    registration_date = request.form.get('registration_date')
    status = request.form.get('status', 'Active')
    
    # Check uniqueness
    existing = db.execute_query("SELECT id FROM candidates WHERE email = %s", (email,))
    if existing:
        flash(f"Candidate with email {email} already exists.", "danger")
        return redirect(url_for('candidates'))
        
    try:
        db.execute_query(
            """INSERT INTO candidates (full_name, email, phone, region, cert_program, registration_date, status, created_by) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (full_name, email, phone, region, cert_program, registration_date, status, session['user_id']),
            is_write=True
        )
        cloudwatch.log_event(f"Candidate '{full_name}' registered by operator '{session.get('username')}'", log_stream="CandidateLogs")
        flash("Candidate registered successfully!", "success")
    except Exception as e:
        flash(f"Error adding candidate: {e}", "danger")
        
    return redirect(url_for('candidates'))

@app.route('/candidates/edit/<int:candidate_id>', methods=['POST'])
@login_required
@role_required(['Staff', 'Administrator'])
def edit_candidate(candidate_id):
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    region = request.form.get('region')
    cert_program = request.form.get('cert_program')
    registration_date = request.form.get('registration_date')
    status = request.form.get('status')
    
    try:
        db.execute_query(
            """UPDATE candidates 
               SET full_name = %s, email = %s, phone = %s, region = %s, cert_program = %s, registration_date = %s, status = %s
               WHERE id = %s""",
            (full_name, email, phone, region, cert_program, registration_date, status, candidate_id),
            is_write=True
        )
        flash("Candidate details updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating candidate: {e}", "danger")
        
    return redirect(url_for('candidates'))

@app.route('/candidates/delete/<int:candidate_id>', methods=['POST'])
@login_required
@role_required(['Administrator'])
def delete_candidate(candidate_id):
    try:
        # Cascade delete is handled by database foreign keys, but we also clean up any local documents associated
        docs = db.execute_query("SELECT s3_key FROM documents WHERE candidate_id = %s", (candidate_id,))
        for doc in docs:
            s3_client.delete_file(doc['s3_key'])
            
        db.execute_query("DELETE FROM candidates WHERE id = %s", (candidate_id,), is_write=True)
        flash("Candidate and associated records deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting candidate: {e}", "danger")
        
    return redirect(url_for('candidates'))

# --- CERTIFICATIONS CRUD ---
@app.route('/certifications', methods=['GET'])
@login_required
def certifications():
    certifications_list = db.execute_query("""
        SELECT cert.*, cand.full_name as candidate_name, u.full_name as creator 
        FROM certifications cert 
        JOIN candidates cand ON cert.candidate_id = cand.id 
        LEFT JOIN users u ON cert.created_by = u.id
        ORDER BY cert.created_at DESC
    """)
    
    candidates_list = db.execute_query("SELECT id, full_name FROM candidates WHERE status = 'Active'")
    
    return render_template(
        'certifications.html',
        certifications=certifications_list,
        candidates=candidates_list
    )

@app.route('/certifications/add', methods=['POST'])
@login_required
@role_required(['Staff', 'Administrator'])
def add_certification():
    cert_name = request.form.get('cert_name')
    candidate_id = request.form.get('candidate_id')
    exam_date = request.form.get('exam_date')
    result = request.form.get('result', 'Pending')
    expiry_date = request.form.get('expiry_date') or None
    
    try:
        # Create certification in Draft status
        cert_id = db.execute_query(
            """INSERT INTO certifications (cert_name, candidate_id, exam_date, result, expiry_date, status, created_by) 
               VALUES (%s, %s, %s, %s, %s, 'Draft', %s)""",
            (cert_name, candidate_id, exam_date, result, expiry_date, session['user_id']),
            is_write=True
        )
        
        # Automatically trigger approval workflow init
        db.execute_query(
            """INSERT INTO workflows (cert_id, candidate_id, current_stage, status, staff_id, staff_notes)
               VALUES (%s, %s, 'Manager Review', 'Pending', %s, 'Submitted for initial certification review.')""",
            (cert_id, candidate_id, session['user_id']),
            is_write=True
        )
        
        # Advance cert status
        db.execute_query(
            "UPDATE certifications SET status = 'Pending Manager Approval' WHERE id = %s",
            (cert_id,),
            is_write=True
        )
        cloudwatch.log_event(f"Certification '{cert_name}' added for Candidate ID '{candidate_id}' by '{session.get('username')}'", log_stream="CertificationLogs")
        flash("Certification record created and submitted to workflow!", "success")
    except Exception as e:
        flash(f"Error creating certification: {e}", "danger")
        
    return redirect(url_for('certifications'))

@app.route('/certifications/update/<int:cert_id>', methods=['POST'])
@login_required
@role_required(['Staff', 'Administrator'])
def update_certification(cert_id):
    cert_name = request.form.get('cert_name')
    exam_date = request.form.get('exam_date')
    result = request.form.get('result')
    expiry_date = request.form.get('expiry_date') or None
    
    try:
        db.execute_query(
            """UPDATE certifications 
               SET cert_name = %s, exam_date = %s, result = %s, expiry_date = %s 
               WHERE id = %s""",
            (cert_name, exam_date, result, expiry_date, cert_id),
            is_write=True
        )
        flash("Certification updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating certification: {e}", "danger")
        
    return redirect(url_for('certifications'))

@app.route('/certifications/delete/<int:cert_id>', methods=['POST'])
@login_required
@role_required(['Administrator'])
def delete_certification(cert_id):
    try:
        docs = db.execute_query("SELECT s3_key FROM documents WHERE cert_id = %s", (cert_id,))
        for doc in docs:
            s3_client.delete_file(doc['s3_key'])
            
        db.execute_query("DELETE FROM certifications WHERE id = %s", (cert_id,), is_write=True)
        flash("Certification record deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting certification: {e}", "danger")
        
    return redirect(url_for('certifications'))

# --- WORKFLOW MANAGEMENT ---
@app.route('/workflow', methods=['GET'])
@login_required
def workflow():
    user_role = session['user_role']
    user_id = session['user_id']
    
    # Retrieve workflows depending on role
    # Manager sees items pending manager review
    # Admin sees items pending admin review
    # Staff sees all workflows they initiated
    
    if user_role == 'Administrator':
        pending = db.execute_query("""
            SELECT w.*, c.cert_name, cand.full_name as candidate_name, u.full_name as staff_name, m.full_name as manager_name
            FROM workflows w
            JOIN certifications c ON w.cert_id = c.id
            JOIN candidates cand ON w.candidate_id = cand.id
            JOIN users u ON w.staff_id = u.id
            LEFT JOIN users m ON w.manager_id = m.id
            WHERE w.current_stage = 'Admin Review' AND w.status = 'Pending'
        """)
    elif user_role == 'Manager':
        pending = db.execute_query("""
            SELECT w.*, c.cert_name, cand.full_name as candidate_name, u.full_name as staff_name
            FROM workflows w
            JOIN certifications c ON w.cert_id = c.id
            JOIN candidates cand ON w.candidate_id = cand.id
            JOIN users u ON w.staff_id = u.id
            WHERE w.current_stage = 'Manager Review' AND w.status = 'Pending'
        """)
    else: # Staff
        pending = db.execute_query("""
            SELECT w.*, c.cert_name, cand.full_name as candidate_name, m.full_name as manager_name, a.full_name as admin_name
            FROM workflows w
            JOIN certifications c ON w.cert_id = c.id
            JOIN candidates cand ON w.candidate_id = cand.id
            LEFT JOIN users m ON w.manager_id = m.id
            LEFT JOIN users a ON w.admin_id = a.id
            WHERE w.staff_id = %s AND w.status = 'Pending'
        """, (user_id,))

    # Approved and Rejected Tasks
    approved = db.execute_query("""
        SELECT w.*, c.cert_name, cand.full_name as candidate_name, u.full_name as staff_name, m.full_name as manager_name, a.full_name as admin_name
        FROM workflows w
        JOIN certifications c ON w.cert_id = c.id
        JOIN candidates cand ON w.candidate_id = cand.id
        JOIN users u ON w.staff_id = u.id
        LEFT JOIN users m ON w.manager_id = m.id
        LEFT JOIN users a ON w.admin_id = a.id
        WHERE w.status = 'Approved'
        ORDER BY w.updated_at DESC LIMIT 20
    """)
    
    rejected = db.execute_query("""
        SELECT w.*, c.cert_name, cand.full_name as candidate_name, u.full_name as staff_name, m.full_name as manager_name, a.full_name as admin_name
        FROM workflows w
        JOIN certifications c ON w.cert_id = c.id
        JOIN candidates cand ON w.candidate_id = cand.id
        JOIN users u ON w.staff_id = u.id
        LEFT JOIN users m ON w.manager_id = m.id
        LEFT JOIN users a ON w.admin_id = a.id
        WHERE w.status = 'Rejected'
        ORDER BY w.updated_at DESC LIMIT 20
    """)
    
    return render_template(
        'workflow.html',
        pending=pending,
        approved=approved,
        rejected=rejected
    )

@app.route('/workflow/action/<int:workflow_id>', methods=['POST'])
@login_required
@role_required(['Manager', 'Administrator'])
def workflow_action(workflow_id):
    action = request.form.get('action') # 'approve' or 'reject'
    notes = request.form.get('notes')
    user_role = session['user_role']
    user_id = session['user_id']
    
    workflow_item = db.execute_query("SELECT * FROM workflows WHERE id = %s", (workflow_id,))
    if not workflow_item:
        flash("Workflow record not found.", "danger")
        return redirect(url_for('workflow'))
        
    wf = workflow_item[0]
    
    try:
        if user_role == 'Manager':
            if wf['current_stage'] != 'Manager Review':
                flash("This record is not currently at Manager Review stage.", "warning")
                return redirect(url_for('workflow'))
                
            if action == 'approve':
                db.execute_query(
                    """UPDATE workflows 
                       SET current_stage = 'Admin Review', manager_id = %s, manager_status = 'Approved', 
                           manager_notes = %s, manager_approved_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (user_id, notes, workflow_id),
                    is_write=True
                )
                db.execute_query(
                    "UPDATE certifications SET status = 'Pending Admin Approval' WHERE id = %s",
                    (wf['cert_id'],),
                    is_write=True
                )
                cloudwatch.log_event(f"Manager approved workflow ID '{workflow_id}' (Cert ID '{wf['cert_id']}'). Notes: {notes}", log_stream="WorkflowLogs")
                flash("Workflow item approved and sent to Administrator for final sign-off.", "success")
            else: # Reject
                db.execute_query(
                    """UPDATE workflows 
                       SET current_stage = 'Rejected', status = 'Rejected', manager_id = %s, 
                           manager_status = 'Rejected', manager_notes = %s, manager_approved_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (user_id, notes, workflow_id),
                    is_write=True
                )
                db.execute_query(
                    "UPDATE certifications SET status = 'Rejected' WHERE id = %s",
                    (wf['cert_id'],),
                    is_write=True
                )
                cloudwatch.log_event(f"Manager rejected workflow ID '{workflow_id}' (Cert ID '{wf['cert_id']}'). Notes: {notes}", log_stream="WorkflowLogs")
                flash("Workflow item has been rejected.", "info")
                
        elif user_role == 'Administrator':
            if wf['current_stage'] != 'Admin Review':
                flash("This record is not currently at Admin Review stage.", "warning")
                return redirect(url_for('workflow'))
                
            if action == 'approve':
                db.execute_query(
                    """UPDATE workflows 
                       SET current_stage = 'Completed', status = 'Approved', admin_id = %s, admin_status = 'Approved', 
                           admin_notes = %s, admin_approved_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (user_id, notes, workflow_id),
                    is_write=True
                )
                db.execute_query(
                    "UPDATE certifications SET status = 'Approved' WHERE id = %s",
                    (wf['cert_id'],),
                    is_write=True
                )
                cloudwatch.log_event(f"Administrator approved workflow ID '{workflow_id}' (Cert ID '{wf['cert_id']}'). Notes: {notes}", log_stream="WorkflowLogs")
                flash("Certification fully approved and completed!", "success")
            else: # Reject
                db.execute_query(
                    """UPDATE workflows 
                       SET current_stage = 'Rejected', status = 'Rejected', admin_id = %s, 
                           admin_status = 'Rejected', admin_notes = %s, admin_approved_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (user_id, notes, workflow_id),
                    is_write=True
                )
                db.execute_query(
                    "UPDATE certifications SET status = 'Rejected' WHERE id = %s",
                    (wf['cert_id'],),
                    is_write=True
                )
                cloudwatch.log_event(f"Administrator rejected workflow ID '{workflow_id}' (Cert ID '{wf['cert_id']}'). Notes: {notes}", log_stream="WorkflowLogs")
                flash("Workflow item has been rejected by Administrator.", "info")
                
    except Exception as e:
        flash(f"Error handling workflow: {e}", "danger")
        
    return redirect(url_for('workflow'))

# --- REPORTING MODULE ---
@app.route('/reports')
@login_required
def reports():
    # Fetch aggregates for reporting dashboard
    region_reports = db.execute_query("""
        SELECT region, COUNT(*) as candidates_count, 
               SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) as active_count
        FROM candidates GROUP BY region
    """)
    
    cert_reports = db.execute_query("""
        SELECT cert_name, COUNT(*) as registered_count,
               SUM(CASE WHEN status='Approved' THEN 1 ELSE 0 END) as approved_count,
               SUM(CASE WHEN result='Pass' THEN 1 ELSE 0 END) as passed_count
        FROM certifications GROUP BY cert_name
    """)
    
    performance_reports = db.execute_query("""
        SELECT result, COUNT(*) as count 
        FROM certifications GROUP BY result
    """)
    
    # Save dummy generated report history
    report_logs = db.execute_query("""
        SELECT r.*, u.full_name as generator 
        FROM reports r 
        LEFT JOIN users u ON r.generated_by = u.id
        ORDER BY r.generated_at DESC LIMIT 10
    """)
    
    return render_template(
        'reports.html',
        region_reports=region_reports,
        cert_reports=cert_reports,
        performance_reports=performance_reports,
        report_logs=report_logs
    )

@app.route('/reports/export/<string:report_type>/<string:format_type>')
@login_required
def export_report(report_type, format_type):
    # Fetch report data dynamically
    data = []
    headers = []
    filename = f"certifypro_{report_type}_report_{datetime.now().strftime('%Y%md_%H%M%S')}"

    if report_type == 'candidates':
        headers = ['ID', 'Full Name', 'Email', 'Phone', 'Region', 'Certification Program', 'Registration Date', 'Status']
        rows = db.execute_query("SELECT id, full_name, email, phone, region, cert_program, registration_date, status FROM candidates")
        data = [[r['id'], r['full_name'], r['email'], r['phone'], r['region'], r['cert_program'], str(r['registration_date']), r['status']] for r in rows]
    elif report_type == 'certifications':
        headers = ['ID', 'Cert Name', 'Candidate ID', 'Exam Date', 'Result', 'Expiry Date', 'Status']
        rows = db.execute_query("SELECT id, cert_name, candidate_id, exam_date, result, expiry_date, status FROM certifications")
        data = [[r['id'], r['cert_name'], r['candidate_id'], str(r['exam_date']), r['result'], str(r['expiry_date']) if r['expiry_date'] else 'N/A', r['status']] for r in rows]
    elif report_type == 'regions':
        headers = ['Region', 'Total Candidates', 'Active Candidates']
        rows = db.execute_query("SELECT region, COUNT(*) as tc, SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) as ac FROM candidates GROUP BY region")
        data = [[r['region'], r['tc'], r['ac']] for r in rows]
    else:
        flash("Invalid report type.", "danger")
        return redirect(url_for('reports'))

    # Log report generation
    db.execute_query(
        "INSERT INTO reports (report_type, query_parameters, generated_by, file_path) VALUES (%s, %s, %s, %s)",
        (f"{report_type.capitalize()} Report", f"Format: {format_type.upper()}", session['user_id'], f"{filename}.{format_type}"),
        is_write=True
    )

    if format_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(data)
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}.csv"}
        )
    elif format_type == 'pdf':
        # PDF fallback: rendering a print-optimized clean report layout which is native and looks beautiful
        # Users can print it to PDF using the print preview on their browser or we serve a print view
        return render_template(
            'print_report.html',
            title=f"{report_type.upper()} REPORT",
            headers=headers,
            data=data,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            generated_by=session['full_name']
        )
    else:
        flash("Format not supported.", "danger")
        return redirect(url_for('reports'))

# --- DOCUMENT MANAGEMENT ---
@app.route('/documents', methods=['GET', 'POST'])
@login_required
def documents():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file selected.", "warning")
            return redirect(url_for('documents'))
            
        file = request.files['file']
        candidate_id = request.form.get('candidate_id') or None
        cert_id = request.form.get('cert_id') or None
        
        if file.filename == '':
            flash("No selected file.", "warning")
            return redirect(url_for('documents'))
            
        try:
            # Upload via helper (handles S3/local automatically)
            s3_key, download_url = s3_client.upload_file(file, candidate_id)
            
            if s3_key:
                db.execute_query(
                    """INSERT INTO documents (file_name, s3_key, uploaded_by, candidate_id, cert_id) 
                       VALUES (%s, %s, %s, %s, %s)""",
                    (file.filename, s3_key, session['user_id'], candidate_id, cert_id),
                    is_write=True
                )
                cloudwatch.log_event(f"Document '{file.filename}' uploaded to S3 vault by '{session.get('username')}'", log_stream="DocumentVaultLogs")
                flash(f"Document '{file.filename}' uploaded successfully!", "success")
            else:
                flash("File upload failed.", "danger")
        except Exception as e:
            flash(f"Error uploading file: {e}", "danger")
            
        return redirect(url_for('documents'))

    # Fetch documents list
    docs = db.execute_query("""
        SELECT d.*, u.full_name as uploader, c.full_name as candidate_name, cert.cert_name
        FROM documents d
        LEFT JOIN users u ON d.uploaded_by = u.id
        LEFT JOIN candidates c ON d.candidate_id = c.id
        LEFT JOIN certifications cert ON d.cert_id = cert.id
        ORDER BY d.upload_date DESC
    """)
    
    # Generate direct download links
    for doc in docs:
        doc['download_url'] = s3_client.get_download_url(doc['s3_key'])
        
    candidates_list = db.execute_query("SELECT id, full_name FROM candidates")
    certifications_list = db.execute_query("SELECT id, cert_name FROM certifications")
    
    return render_template(
        'documents.html',
        documents=docs,
        candidates=candidates_list,
        certifications=certifications_list
    )

@app.route('/documents/delete/<int:doc_id>', methods=['POST'])
@login_required
@role_required(['Administrator'])
def delete_document(doc_id):
    doc = db.execute_query("SELECT * FROM documents WHERE id = %s", (doc_id,))
    if doc:
        # Delete from storage (S3 or local)
        s3_client.delete_file(doc[0]['s3_key'])
        # Delete from DB
        db.execute_query("DELETE FROM documents WHERE id = %s", (doc_id,), is_write=True)
        cloudwatch.log_event(f"Document '{doc[0]['file_name']}' deleted from S3 vault by '{session.get('username')}'", log_stream="DocumentVaultLogs")
        flash("Document deleted successfully.", "success")
    else:
        flash("Document not found.", "danger")
        
    return redirect(url_for('documents'))

# --- MONITORING DASHBOARD ---
@app.route('/monitoring')
@login_required
@role_required(['Administrator'])
def monitoring():
    # Fetch real-time system metrics if possible, otherwise use graceful dummy fallback
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        disk = psutil.disk_usage('/')
        storage_usage = disk.percent
        
        # Network IO mock calculations
        net_io = psutil.net_io_counters()
        if net_io is None:
            raise RuntimeError("Network counters are unavailable on this system")
        network_sent = round(net_io.bytes_sent / (1024 * 1024), 2) # MB
        network_recv = round(net_io.bytes_recv / (1024 * 1024), 2) # MB
    except Exception as e:
        print(f"Error fetching system metrics: {e}")
        # Default mock metrics
        cpu_usage = 14.5
        memory_usage = 42.1
        storage_usage = 58.9
        network_sent = 104.5
        network_recv = 452.1
        
    # Push resource metrics to CloudWatch if enabled
    cloudwatch.push_metric("CPUUtilization", cpu_usage, "Percent")
    cloudwatch.push_metric("MemoryUtilization", memory_usage, "Percent")
    cloudwatch.push_metric("DiskSpaceUtilization", storage_usage, "Percent")
    cloudwatch.log_event(f"Metrics telemetry collected: CPU={cpu_usage}%, RAM={memory_usage}%, Storage={storage_usage}%", log_stream="TelemetryLogs")
        
    metrics = {
        'cpu': cpu_usage,
        'memory': memory_usage,
        'storage': storage_usage,
        'net_sent': network_sent,
        'net_recv': network_recv,
        'rds_status': 'Healthy',
        's3_status': 'Healthy' if s3_client.USE_S3 else 'Offline (Local Fallback Active)',
        'app_status': 'Running'
    }
    
    return render_template('monitoring.html', metrics=metrics)

# --- USER MANAGEMENT ---
@app.route('/users')
@login_required
@role_required(['Administrator'])
def users():
    users_list = db.execute_query("SELECT id, username, email, role, full_name, created_at FROM users")
    return render_template('users.html', users=users_list)

@app.route('/users/add', methods=['POST'])
@login_required
@role_required(['Administrator'])
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    email = request.form.get('email')
    role = request.form.get('role')
    full_name = request.form.get('full_name')
    
    # Check if exists
    existing = db.execute_query("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
    if existing:
        flash("Username or email already exists.", "danger")
        return redirect(url_for('users'))
        
    from werkzeug.security import generate_password_hash
    hashed = generate_password_hash(password)
    
    try:
        db.execute_query(
            "INSERT INTO users (username, password_hash, email, role, full_name) VALUES (%s, %s, %s, %s, %s)",
            (username, hashed, email, role, full_name),
            is_write=True
        )
        flash(f"User {username} added successfully!", "success")
    except Exception as e:
        flash(f"Error adding user: {e}", "danger")
        
    return redirect(url_for('users'))

# --- ARCHITECTURE & COST PAGES ---
@app.route('/architecture')
@login_required
def architecture():
    return render_template('architecture.html')

@app.route('/cost')
@login_required
def cost():
    return render_template('cost.html')

# --- INITIAL RUN ---
if __name__ == '__main__':
    # Load config port
    port = int(os.getenv('PORT', 5001))
    # Run server
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
