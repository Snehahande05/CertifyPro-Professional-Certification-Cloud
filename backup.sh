#!/bin/bash
# CertifyPro Database Backup Automation Script

set -e

# Load environment variables if .env file exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Configuration
BACKUP_DIR="backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

echo "============================================="
echo "🗄️ Starting CertifyPro Database Backup"
echo "============================================="

# Detect if using MySQL RDS or SQLite
if [ ! -z "$DB_HOST" ] && [ ! -z "$DB_USER" ] && [ ! -z "$DB_PASSWORD" ]; then
    DB_NAME=${DB_NAME:-certifypro}
    DB_PORT=${DB_PORT:-3306}
    BACKUP_FILE="$BACKUP_DIR/rds_mysql_backup_${DB_NAME}_${TIMESTAMP}.sql"
    
    echo "🌐 AWS RDS MySQL Instance detected. Initiating mysqldump..."
    mysqldump -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" > "$BACKUP_FILE"
    
    # Compress the SQL backup
    gzip "$BACKUP_FILE"
    echo "✅ MySQL Database backed up and compressed to ${BACKUP_FILE}.gz"
else
    echo "⚠️ AWS RDS credentials not found in environment. Checking local SQLite database..."
    SQLITE_FILE="certifypro.db"
    
    if [ -f "$SQLITE_FILE" ]; then
        BACKUP_FILE="$BACKUP_DIR/sqlite_backup_${TIMESTAMP}.db"
        echo "💾 Backing up local SQLite database file..."
        cp "$SQLITE_FILE" "$BACKUP_FILE"
        
        # Compress SQLite copy
        gzip "$BACKUP_FILE"
        echo "✅ SQLite Database backed up and compressed to ${BACKUP_FILE}.gz"
    else
        echo "❌ Error: No database configurations found. Cannot execute backup."
        exit 1
    fi
fi

# Optional: Keep only the last 10 backups to save disk space
echo "🧹 Cleaning up old backups (retaining only the 10 most recent)..."
find "$BACKUP_DIR" -type f -name "*.gz" | sort -r | tail -n +11 | xargs rm -f || true

echo "============================================="
echo "✅ Database Backup Completed Successfully!"
echo "============================================="
