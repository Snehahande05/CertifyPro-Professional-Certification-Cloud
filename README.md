# CertifyPro Professional Certification Cloud

CertifyPro is an enterprise-grade certification management platform built with a Python Flask backend, MySQL/SQLite database integration, and AWS S3 object storage capabilities. The system implements multi-tiered Role-Based Access Control (RBAC) and approval workflows tailored for AWS EC2 and RDS cloud environments.

---

## Features

- **Role-Based Access Control (RBAC)**: Distinct permissions for `Administrator`, `Manager`, and `Staff` roles.
- **Dynamic Executive Dashboard**: High-level KPI indicators and interactive Chart.js visualizations (registrations trends, outcome outcomes, geographic distributions).
- **Candidate CRUD Module**: Search, filter, and modify candidate registration data.
- **Exam Results Lifecycles**: Record exam marks and trigger approval requests.
- **Sequential Multi-Gate Approval Workflow**: Staff &rarr; Manager Approval &rarr; Admin Approval with audit logs and custom notes.
- **Secured Document Vault**: Upload certificate and score PDF files directly to AWS S3. Uses temporary secure pre-signed download URLs.
- **CloudWatch Telemetry**: Application audit log streams and CPU/RAM/Disk metrics pushed directly to AWS CloudWatch Logs & Metrics.
- **System Monitoring Operations**: Real-time server telemetry tracking CPU, RAM, disk storage, and network bandwidth (integrated with psutil).
- **AWS Infrastructure Details**: Interactive cloud architecture blueprints and cost estimation calculators embedded in the app.

---

## Directory Structure

```text
CertifyPro/
├── app.py                  # Main Flask Router & Controller
├── db.py                   # DB connection abstraction & query translation
├── s3_client.py            # AWS S3 integration module (local fallback active)
├── cloudwatch.py           # AWS CloudWatch integration module (local fallback active)
├── schema.sql              # MySQL Database schema definition
├── Dockerfile              # Container deployment instructions
├── docker-compose.yml      # Docker Compose setup for local MySQL orchestration
├── requirements.txt        # Python library dependencies
├── deploy.sh               # Git pulls & EC2 app restart automation script
├── backup.sh               # MySQL/SQLite compression backup automation script
├── static/
│   ├── css/
│   │   └── style.css       # Main stylesheet (AWS Console inspired UI)
│   └── uploads/            # Fallback local document storage folder
└── templates/              # HTML layout components
    ├── base.html           # Main dashboard structure & navbar
    ├── login.html          # Floating glassmorphism sign-in interface
    ├── dashboard.html      # KPI widgets & Chart.js scripts
    ├── candidates.html     # Candidates directory listing & modals
    ├── certifications.html # Certifications index & detail modals
    ├── workflow.html       # Pending review gates & action dialogs
    ├── reports.html        # Export interfaces & analytics grids
    ├── print_report.html   # Report auto-print layout
    ├── documents.html      # Document Vault uploads & links
    ├── monitoring.html     # Infrastructure operations charts
    ├── users.html          # Administrator operator CRUD modal
    ├── architecture.html   # Cloud topology Mermaid.js diagram
    └── cost.html           # AWS pricing calculator panels
```

---

## Getting Started (Local Development)

### Option A: Local Run with Python (Fast Evaluation)
1. **Prerequisites**: Python 3.8+
2. **Installation**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the Application**:
   ```bash
   python app.py
   ```
   Open [http://localhost:5001](http://localhost:5001) in your browser. The database will automatically initialize and seed default users.

### Option B: Local Run with Docker Compose (MySQL Orchestration)
1. **Prerequisites**: Docker Desktop
2. **Run both Flask App and MySQL containers**:
   ```bash
   docker-compose up --build
   ```
   Open [http://localhost:5001](http://localhost:5001) in your browser. The MySQL database container will initialize and seed schemas automatically.

### Default Credentials (RBAC Testing)
Use the quick-fill buttons on the login card, or enter manually:
- **Administrator**: User: `admin` | Password: `admin123`
- **Manager**: User: `manager` | Password: `manager123`
- **Staff**: User: `staff` | Password: `staff123`

---

## AWS Cloud Production Configuration

To run CertifyPro in production with full cloud integrations, configure the following environment variables (e.g., in a `.env` file or EC2 Instance settings):

```ini
# Flask Setup
SECRET_KEY=your_production_secret_key
PORT=5001

# AWS RDS MySQL Setup
DB_HOST=certifypro-db.xxxxxxxxx.us-east-1.rds.amazonaws.com
DB_USER=admin
DB_PASSWORD=your_rds_password
DB_NAME=certifypro
DB_PORT=3306

# AWS S3 Storage Setup
S3_BUCKET=certifypro-document-vault
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1

# AWS CloudWatch Telemetry
ENABLE_CLOUDWATCH=true
```

### 1. VPC Network & Security Groups (VPC Topology)
Set up security group routing rules inside your VPC to isolate the database subnet:
- **ALB-SG (Load Balancer)**: Ingress: HTTP (80)/HTTPS (443) from `0.0.0.0/0`. Egress: Port 5001 to `EC2-SG`.
- **EC2-SG (App Server)**: Ingress: Port 5001 from `ALB-SG`, Port 22 from Administrator IP. Egress: All traffic (0.0.0.0/0) to S3, RDS, CloudWatch APIs.
- **RDS-SG (MySQL Database)**: Ingress: MySQL Port 3306 from `EC2-SG` only. Egress: Fully Closed.

### 2. IAM Policy (EC2 Instance Profile)
Assign an IAM role containing this permission policy directly to your EC2 Web App instance profile:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3BucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::certifypro-document-vault/*"
        },
        {
            "Sid": "CloudWatchLoggingAndMetrics",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*"
        }
    ]
}
```

### 3. Secure RDS connections (SSL/TLS CA bundle setup)
Encrypt database queries in transit by loading the RDS Certificate Authority certificate file:
1. Download the CA bundle on your server host:
   ```bash
   wget https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
   ```
2. Configure SSL connection parameters inside `db.py`:
   ```python
   ssl_config = {
       'ssl_ca': '/path/to/global-bundle.pem',
       'ssl_verify_cert': True
   }
   conn = mysql.connector.connect(
       host=DB_HOST,
       user=DB_USER,
       password=DB_PASSWORD,
       database=DB_NAME,
       ssl_config=ssl_config
   )
   ```

---

## Automation Scripts

### 1. `deploy.sh`
Automates deployment on an EC2 instance. Runs git pull, updates virtual environments, installs dependencies, and restarts either the Docker container or the systemd process.
```bash
chmod +x deploy.sh
./deploy.sh
```

### 2. `backup.sh`
Performs database backups. Creates compressed `.sql.gz` backups using `mysqldump` if RDS is configured, or `.db.gz` file-level copies if using SQLite local fallback. Keeps the 10 most recent backups.
```bash
chmod +x backup.sh
./backup.sh
```
Add to crontab for daily scheduled execution:
```text
0 2 * * * /path/to/backup.sh
```
