# Smart Bottle Parent Mobile App

This is the first Expo React Native scaffold for the parent-control mobile app.

## Run Locally

```text
npm install
npm start -- --clear
```

Then scan the Expo QR code with Expo Go.

If the phone shows a red native-module error such as `PlatformConstants could not be found`,
update Expo Go from Play Store and restart Metro with `npm start -- --clear`.

## API Configuration

For local Django:

```text
EXPO_PUBLIC_API_BASE_URL=http://192.168.18.73:8000/api/
```

For Render or AWS:

```text
EXPO_PUBLIC_API_BASE_URL=https://your-backend-domain.com/api/
```

The app currently reads:

- Parent signup/login with Django token authentication
- Secure persistent login with Expo SecureStore
- Child and bottle switching for parents with multiple profiles/devices
- Expo push notification token registration
- Notification history for hydration alerts
- QR code scanning for bottle pairing
- Child profile details during pairing
- Latest bottle state
- Filled, dropped, balance, goal, reminder and alert values
- Recent FILL / DRINK / DROP events
- 15-day goal completion data
- Parent-owned child and bottle list
- Background data refresh registration
- Automatic refresh when the app returns to foreground
- Manual sync status and refresh controls in Settings

QR payload formats supported:

```json
{"device_id":"bottle_01","pairing_token":"your-token"}
```

or a URL such as:

```text
https://your-app.com/pair?device_id=bottle_01&token=your-token
```

Local push notification testing needs:

- Real Android phone
- Expo Go updated from Play Store
- Internet access on laptop and phone
- Django backend reachable from phone

Background sync notes:

- The app asks Android/iOS to sync about every 15 minutes.
- The phone OS decides the real timing, so it may not run immediately.
- Foreground refresh is reliable: when the app is opened again, it loads fresh data.
- For best background testing, use a real phone or a development build.

Next production steps are APK/dev build testing, cloud deployment, and parent reports.
