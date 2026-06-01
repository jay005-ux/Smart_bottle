# Smart Bottle Backend Deployment

This backend is prepared for both Render and AWS. The code uses environment variables for database, CORS, device ingest security, and Raspberry Pi calibration proxy settings.

## Required Environment Variables

```text
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong-secret>
DJANGO_ALLOWED_HOSTS=<your-domain>
APP_ENVIRONMENT=production
DEPLOY_PROVIDER=aws
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=https://your-dashboard-domain.com
CSRF_TRUSTED_ORIGINS=https://your-backend-domain.com,https://your-dashboard-domain.com
DATABASE_URL=postgres://user:password@host:5432/dbname
DATABASE_SSL_REQUIRE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
DEVICE_INGEST_TOKEN=<same-token-used-on-raspberry-pi>
RASPBERRY_PI_BASE_URL=http://<raspberry-pi-ip>:5001
ALLOW_INSECURE_DEVICE_INGEST=False
ALLOW_PUBLIC_DASHBOARD_RESET=False
ALLOW_PUBLIC_ADMIN_DASHBOARD=False
```

## Raspberry Pi Environment

Before running `smart_bottle.py`, set:

```text
SMART_BOTTLE_DEVICE_ID=bottle_01
SMART_BOTTLE_API_BASE_URL=https://your-backend-domain.com/api
SMART_BOTTLE_DEVICE_TOKEN=<same-as-DEVICE_INGEST_TOKEN>
```

For local testing:

```text
SMART_BOTTLE_API_BASE_URL=http://192.168.18.73:8000/api
```

Health check after deploy:

```text
GET https://your-backend-domain.com/api/health/
```

## Render

Use `render.yaml` from this folder. Render creates the web service and PostgreSQL database, then runs:

```text
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn backend.wsgi:application
```

## AWS

Recommended beginner path:

1. Put PostgreSQL on Amazon RDS.
2. Deploy this backend Docker image to Elastic Beanstalk, ECS Fargate, or App Runner.
3. Add the environment variables above.
4. Run migrations once:

```text
python manage.py migrate
```

5. Point Raspberry Pi to:

```text
SMART_BOTTLE_API_BASE_URL=https://your-aws-api-domain.com/api
```

## Device Pairing Flow

0. Parent creates account or logs in:

```text
POST /api/auth/signup/
{"username": "parent1", "password": "strong-password", "email": "parent@example.com"}
```

Use the returned token on parent/mobile requests:

```text
Authorization: Token <token>
```

1. Register device:

```text
POST /api/devices/register/
{"device_id": "bottle_01"}
```

2. Show QR payload from:

```text
GET /api/devices/bottle_01/pairing/
```

3. Mobile app scans QR and sends:

```text
POST /api/devices/pair/
{
  "device_id": "bottle_01",
  "pairing_token": "...",
  "child_name": "Child Name"
}
```

The pairing endpoint links the bottle to the authenticated parent account.
