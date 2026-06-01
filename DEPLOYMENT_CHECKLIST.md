# Smart Bottle Deployment Checklist

## 1. Deploy Backend First

Deploy only this folder:

```text
E:\Django\backend
```

Required production environment variables:

```text
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<strong-random-secret>
DJANGO_ALLOWED_HOSTS=<backend-domain>
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=<frontend-domain>
CSRF_TRUSTED_ORIGINS=<backend-domain>,<frontend-domain>
DATABASE_URL=<postgres-url>
DATABASE_SSL_REQUIRE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
DEVICE_INGEST_TOKEN=<strong-device-token>
ALLOW_INSECURE_DEVICE_INGEST=False
ALLOW_PUBLIC_DASHBOARD_RESET=False
ALLOW_PUBLIC_ADMIN_DASHBOARD=False
PUBLIC_APP_URL=<mobile-or-web-app-url-if-used>
```

Run after deploy:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Optional if you want old local data:

```bash
python manage.py dumpdata --exclude auth.permission --exclude contenttypes > data.json
python manage.py loaddata data.json
```

## 2. Update Raspberry Pi

On Raspberry Pi, set:

```text
SMART_BOTTLE_API_BASE_URL=https://your-backend-domain.com/api
SMART_BOTTLE_DEVICE_TOKEN=<same-as-DEVICE_INGEST_TOKEN>
SMART_BOTTLE_DEVICE_ID=bottle_01
```

Then restart `smart_bottle.py`.

## 3. Deploy Frontend Dashboard

Deploy only this folder:

```text
E:\Django\frontend
```

Set build environment variable:

```text
REACT_APP_API_BASE_URL=https://your-backend-domain.com/api/
```

Build command:

```bash
npm install
npm run build
```

Publish directory:

```text
build
```

After frontend URL is known, add it to backend:

```text
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.com
CSRF_TRUSTED_ORIGINS=https://your-backend-domain.com,https://your-frontend-domain.com
```

## 4. Build Mobile APK

Build only this folder:

```text
E:\Django\mobile-app
```

Set:

```text
EXPO_PUBLIC_API_BASE_URL=https://your-backend-domain.com/api/
```

Install and build:

```bash
npm install
npm install -g eas-cli
eas login
eas build:configure
eas build --platform android --profile preview
```

Use `preview` for APK direct install.
Use `production` for Play Store AAB.

## 5. Final Test

1. Open backend `/api/health/` if available, or `/api/data/`.
2. Run Raspberry Pi and confirm Django receives `/api/add/` and `/api/heartbeat/`.
3. Open admin dashboard and confirm bottle status is online.
4. Install APK and login.
5. Pair bottle using QR.
6. Test fill, drink, drop, low water, offline, and reconnect.
