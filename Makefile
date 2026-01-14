# Wireless Security Scanner - Makefile
# Build automation for HackRF + Android Phone Scanner

.PHONY: all install install-python install-android build-android test clean help

# Default target
all: build-android

# Install Python dependencies
install-python:
	@echo "Installing Python dependencies..."
	pip3 install -r requirements.txt

# Install Android tools
install-android:
	@echo "Installing Android development tools..."
	sudo apt-get update
	sudo apt-get install -y android-tools-adb android-tools-fastboot

# Build Android APK
build-android:
	@echo "Building Android APK..."
	cd android-app && ./gradlew assembleRelease
	@echo "APK created: android-app/app/build/outputs/apk/release/app-release.apk"

# Setup phone
setup-phone:
	@echo "Setting up Android phone..."
	./setup_android.sh

# Run tests
test:
	@echo "Running tests..."
	pytest tests/ -v

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	cd android-app && ./gradlew clean 2>/dev/null || true
	@echo "Clean complete"

# Full installation
install: install-python install-android
	@echo "Installation complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Build Android app: make build-android"
	@echo "  2. Setup phone: make setup-phone"
	@echo "  3. Run scanner: sudo python3 main.py --phone"

# Help
help:
	@echo "Wireless Security Scanner - Build Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  install         - Install all dependencies"
	@echo "  install-python  - Install Python dependencies only"
	@echo "  install-android - Install Android tools only"
	@echo "  build-android   - Build Android APK"
	@echo "  setup-phone     - Run phone setup script"
	@echo "  test            - Run test suite"
	@echo "  clean           - Remove build artifacts"
	@echo "  help            - Show this help message"
