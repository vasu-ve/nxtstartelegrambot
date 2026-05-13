#!/usr/bin/env python
"""
PostgreSQL Database Setup Script for NxtStar Django Backend

This script helps you set up the PostgreSQL database.
It creates the database and user if they don't exist.

Usage:
    python setup_db.py
"""

import os
import sys
import subprocess

def run_command(cmd):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)

def main():
    print("=" * 60)
    print("NxtStar PostgreSQL Database Setup")
    print("=" * 60)
    
    # Get configuration from .env
    from dotenv import load_dotenv
    load_dotenv()
    
    db_name = os.getenv("DB_NAME", "nxtstar")
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "password")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    postgres_user = "postgres"
    
    print(f"\nDatabase Configuration:")
    print(f"  Database Name: {db_name}")
    print(f"  Database User: {db_user}")
    print(f"  Database Host: {db_host}")
    print(f"  Database Port: {db_port}")
    
    # Try to connect to PostgreSQL
    print(f"\nAttempting to connect to PostgreSQL at {db_host}:{db_port}...")
    
    connect_cmd = f'psql -U {postgres_user} -h {db_host} -p {db_port} -c "SELECT 1;"'
    returncode, stdout, stderr = run_command(connect_cmd)
    
    if returncode != 0:
        print(f"✗ Could not connect to PostgreSQL: {stderr}")
        print("\nPlease ensure PostgreSQL is running and accessible.")
        print(f"On Windows, check that PostgreSQL service is started.")
        print(f"Try connecting manually: psql -U {postgres_user} -h {db_host}")
        sys.exit(1)
    
    print("✓ Connected to PostgreSQL successfully")
    
    # Create database
    print(f"\n1. Creating database '{db_name}'...")
    create_db_cmd = f'psql -U {postgres_user} -h {db_host} -p {db_port} -c "CREATE DATABASE {db_name};"'
    returncode, stdout, stderr = run_command(create_db_cmd)
    
    if "already exists" in stderr:
        print(f"✓ Database '{db_name}' already exists")
    elif returncode == 0:
        print(f"✓ Database '{db_name}' created successfully")
    else:
        print(f"✗ Failed to create database: {stderr}")
        sys.exit(1)
    
    # Create user
    print(f"\n2. Creating database user '{db_user}'...")
    create_user_cmd = f'psql -U {postgres_user} -h {db_host} -p {db_port} -c "CREATE USER {db_user} WITH PASSWORD \'{db_password}\';"'
    returncode, stdout, stderr = run_command(create_user_cmd)
    
    if "already exists" in stderr:
        print(f"✓ User '{db_user}' already exists")
        # Try to reset password
        alter_user_cmd = f'psql -U {postgres_user} -h {db_host} -p {db_port} -c "ALTER USER {db_user} WITH PASSWORD \'{db_password}\';"'
        run_command(alter_user_cmd)
    elif returncode == 0:
        print(f"✓ User '{db_user}' created successfully")
    else:
        print(f"✗ Failed to create user: {stderr}")
        sys.exit(1)
    
    # Grant privileges
    print(f"\n3. Granting privileges to user '{db_user}'...")
    grant_cmd = f'psql -U {postgres_user} -h {db_host} -p {db_port} -d {db_name} -c "GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"'
    returncode, stdout, stderr = run_command(grant_cmd)
    
    if returncode == 0:
        print(f"✓ Privileges granted successfully")
    else:
        print(f"✗ Failed to grant privileges: {stderr}")
    
    # Additional user settings
    print(f"\n4. Configuring user settings...")
    settings_cmd = f'''psql -U {postgres_user} -h {db_host} -p {db_port} -c "
    ALTER ROLE {db_user} SET client_encoding TO 'utf8';
    ALTER ROLE {db_user} SET default_transaction_isolation TO 'read committed';
    ALTER ROLE {db_user} SET default_transaction_deferrable TO on;
    ALTER ROLE {db_user} SET timezone TO 'UTC';
    "'''
    returncode, stdout, stderr = run_command(settings_cmd)
    
    if returncode == 0:
        print(f"✓ User settings configured successfully")
    else:
        print(f"✗ Failed to configure settings (non-critical): {stderr}")
    
    print("\n" + "=" * 60)
    print("✓ Database setup completed successfully!")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"1. Update Django migrations: python manage.py migrate")
    print(f"2. Create a superuser: python manage.py createsuperuser")
    print(f"3. Run development server: python manage.py runserver")
    print(f"4. Access admin at: http://localhost:8000/admin")

if __name__ == "__main__":
    main()
