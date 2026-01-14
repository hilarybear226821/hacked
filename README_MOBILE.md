# 📱 SDR Mobile Suite - Quick Start

This guide helps you connect your Android phone to the SDR Intelligence Suite over USB/ADB.

## 🏁 Prerequisites
1.  **USB Debugging Enabled**: On your phone, go to *Settings > Developer Options* and enable **USB Debugging**.
2.  **ADB Installed**: Your laptop must have `android-tools-adb`.
3.  **Expo Go**: Install the "Expo Go" app from the Play Store.

## 🚀 Unified Startup
Run the following command on your laptop to start the backend and setup the bridge:
```bash
./mobile_suite.sh
```
This script will:
-   Kill any zombie SDR processes.
-   Start the Flask web server.
-   Map the phone's port 5000 to the laptop (ADB reverse).

## 📲 Launching the App
In a second terminal:
```bash
cd android-app
npx expo start
```
1.  Select **"open Android"** or scan the QR code.
2.  The app should automatically connect to `http://localhost:5000`.

## 🛠️ Troubleshooting
-   **Link Failure**: If you see a red banner, tap the **Settings** icon next to "SDR Command".
-   **USB/ADB**: Ensure the phone is set to `127.0.0.1`.
-   **WiFi**: Enter your laptop's IP (e.g., `10.0.0.178`).
-   **Check Logs**: Look at `backend.log` on your laptop if the server won't start.
