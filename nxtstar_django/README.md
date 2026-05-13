# NxtStar Django Backend - Setup Guide

This is the Django backend for the NxtStar Telegram Bot. It provides:
- User management and verification
- Invite link generation
- Group management
- Audit logging
- Admin panel (Django admin)

## Prerequisites

- Python 3.9+
- PostgreSQL 12+
- pip or virtual environment manager

## Installation & Setup

### 1. Create Virtual Environment (if not already done)

```bash
# Using Python venv
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on macOS/Linux
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup PostgreSQL Database

#### Option A: Using PostgreSQL directly

```bash
# Connect to PostgreSQL as admin
psql -U postgres

# Create database and user
CREATE DATABASE nxtstar;
CREATE USER nxtstar WITH PASSWORD 'nxtstar';
ALTER ROLE nxtstar SET client_encoding TO 'utf8';
ALTER ROLE nxtstar SET default_transaction_isolation TO 'read committed';
ALTER ROLE nxtstar SET default_transaction_deferrable TO on;
ALTER ROLE nxtstar SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE nxtstar TO nxtstar;
\q
```

#### Option B: Using Windows PostgreSQL GUI

1. Open pgAdmin (comes with PostgreSQL)
2. Create new database named `nxtstar`
3. Create new user `nxtstar` with password `nxtstar`
4. Grant all privileges to the user

#### Option C: Docker (if you have Docker installed)

```bash
docker run --name postgres-nxtstar -e POSTGRES_PASSWORD=password -e POSTGRES_USER=postgres -e POSTGRES_DB=nxtstar -p 5432:5432 -d postgres:15
```

### 4. Update .env Configuration

Edit `.env` file with your database credentials:

```env
DB_NAME=nxtstar
DB_USER=nxtstar
DB_PASSWORD=nxtstar
DB_HOST=localhost
DB_PORT=5432
```

### 5. Run Django Migrations

```bash
python manage.py migrate
```

This will create all necessary database tables.

### 6. Create Superuser (Admin Account)

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 7. Run Development Server

```bash
python manage.py runserver 0.0.0.0:8000
```

The server will be available at:
- **Django Admin**: http://localhost:8000/admin
- **API Base**: http://localhost:8000/api

### 8. Access Django Admin

1. Go to http://localhost:8000/admin
2. Login with the superuser credentials you created
3. You can now manage:
   - **Leaders**: Create and manage group leaders
   - **Groups**: Create Telegram groups with language settings
   - **Users**: View and manage bot users
   - **Invite Links**: Monitor invite link usage
   - **Audit Log**: View all system events

## First Steps After Setup

### 1. Create a Leader (in Django Admin)

Go to **Leaders** and create a new leader:
- Display Name: "Leader Name"
- Telegram Username: "leader_username"
- Telegram User ID: (get from `@userinfobot` in Telegram)
- Mark as active

### 2. Create Groups (in Django Admin)

Go to **Groups** and create groups for each leader/language combination:
- Leader: Select the leader you created
- Chat ID: (create a Telegram group, get the ID from `@getidsbot`)
- Chat Title: "Group Name"
- Language: Select Portuguese, French, English, Spanish, or Arabic
- Mark as active

## API Endpoints

### Create/Get User
```
POST /api/users/create/
{
  "telegram_user_id": 123456789,
  "telegram_username": "username",
  "language": "en"
}
```

### Verify User
```
POST /api/users/verify/
{
  "user_id": 1,
  "nxtstar_uid": "123456"
}
```

### Generate Invite Link
```
POST /api/invites/generate/
{
  "user_id": 1,
  "language": "en"
}
```

### Get Invite Link Details
```
GET /api/invites/get/?invite_id=<uuid>
```

### Mark Invite as Used
```
POST /api/invites/mark-used/
{
  "invite_id": "<uuid>"
}
```

## Database Schema

### Tables

- **leaders**: Group leaders
- **groups**: Telegram groups
- **users**: Bot users
- **invite_links**: Personal invite links for users
- **audit_log**: Event audit trail

## Production Deployment

### Important: Security Changes

Before deploying to production:

1. Generate a strong SECRET_KEY:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

2. Update `.env`:
   ```env
   DEBUG=False
   SECRET_KEY=<generate-new-key>
   ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
   ```

3. Update database credentials

4. Collect static files:
   ```bash
   python manage.py collectstatic --noinput
   ```

5. Use production WSGI server (gunicorn):
   ```bash
   gunicorn nxtstar_project.wsgi:application --bind 0.0.0.0:8000
   ```

## Troubleshooting

### Database connection error
- Ensure PostgreSQL is running
- Check `.env` database credentials
- Verify PostgreSQL user permissions

### Migration errors
- Delete all migrations except `__init__.py` in `bot_api/migrations/`
- Run `python manage.py makemigrations`
- Run `python manage.py migrate`

### Admin panel not accessible
- Clear browser cache
- Check if Django development server is running
- Verify you're logged in with correct credentials

## Support

For issues, check:
1. PostgreSQL is running
2. Virtual environment is activated
3. `.env` file has correct credentials
4. Django server is running on port 8000
