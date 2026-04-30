# Remote Control Client

Flutter client for Remote Control. Provides a cross-platform terminal workspace that connects to the Remote Control Server, allowing you to access and manage remote CLI sessions from mobile and desktop devices.

## Supported Platforms

| Platform | Status |
|----------|--------|
| macOS    | Supported |
| Android  | Supported |
| iOS      | Supported |
| Windows  | Supported |
| Linux    | Supported |

## Prerequisites

- [Flutter](https://docs.flutter.dev/get-started/install) 3.6+ (Dart SDK 3.6+)
- Platform-specific toolchain:
  - **macOS**: Xcode
  - **iOS**: Xcode + iOS Simulator or physical device
  - **Android**: Android Studio or Android SDK command-line tools
  - **Windows**: Visual Studio with C++ desktop development workload
  - **Linux**: GTK3 development headers, clang, cmake, ninja

## Getting Started

### 1. Install dependencies

```bash
cd client
flutter pub get
```

### 2. Run on your platform

```bash
# macOS
flutter run -d macos

# Windows
flutter run -d windows

# Linux
flutter run -d linux

# Android (connected device or emulator)
flutter run -d android

# iOS (connected device or simulator)
flutter run -d ios
```

### 3. Build a release

```bash
# macOS
flutter build macos

# Windows
flutter build windows

# Linux
flutter build linux

# Android APK
flutter build apk

# iOS
flutter build ios
```

## Connecting to a Server

The client supports multiple connection modes, configured in the app settings.

### Direct Mode (recommended for development)

Use Direct mode to connect to a self-contained dev deployment without a gateway:

1. Start the dev server: `./deploy/deploy.sh --dev` (from the project root)
2. In the client, open **Settings**
3. Set the **Environment** to **Direct**
4. Enter the server **Host** (e.g., `localhost` or the server IP address)
5. Enter the **Port** (default: `8880`)
6. Save settings and log in with your credentials

### Local Mode (production with Traefik gateway)

Use Local mode when connecting through a Traefik gateway:

1. Set the **Environment** to **Local**
2. The client connects via `wss://host/rc` (default gateway path)

### Production Mode

Use Production mode for connecting to a publicly deployed server with a domain name and TLS.

## Running Tests

```bash
# Unit tests
flutter test

# Integration tests (requires a running server)
flutter test integration_test/
```

## Project Structure

```text
client/
├── lib/                 # Dart source code
├── test/                # Unit and widget tests
├── integration_test/    # Integration tests
├── android/             # Android platform files
├── ios/                 # iOS platform files
├── macos/               # macOS platform files
├── windows/             # Windows platform files
├── linux/               # Linux platform files
├── pubspec.yaml         # Flutter dependencies
└── analysis_options.yaml
```

## Dependencies

Key packages used:

- **provider** -- state management
- **web_socket_channel** -- WebSocket communication
- **xterm** -- terminal emulator widget
- **flutter_secure_storage** -- secure credential storage
- **pointycastle** + **asn1lib** -- RSA/AES encryption
- **shared_preferences** -- local settings storage
