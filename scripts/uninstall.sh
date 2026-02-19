#!/data/data/com.termux/files/usr/bin/sh

# Uninstaller for Android Docker CLI (Termux)

INSTALL_DIR="$HOME/.android-docker-cli"
CMD_NAME="docker"
DOCKER_COMPOSE_CMD_NAME="docker-compose"
CMD_PATH="$PREFIX/bin/$CMD_NAME"
DOCKER_COMPOSE_CMD_PATH="$PREFIX/bin/$DOCKER_COMPOSE_CMD_NAME"
CACHE_DIR="$HOME/.docker_proot_cache"

echo "[INFO] Starting uninstallation of Android Docker CLI..."

# Remove docker wrapper
if [ -f "$CMD_PATH" ]; then
    rm -f "$CMD_PATH"
    echo "[INFO] Removed docker command."
fi

# Remove docker-compose wrapper
if [ -f "$DOCKER_COMPOSE_CMD_PATH" ]; then
    rm -f "$DOCKER_COMPOSE_CMD_PATH"
    echo "[INFO] Removed docker-compose command."
fi

# Remove installation directory
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "[INFO] Removed installation directory."
fi

# Remove container/image cache
if [ -d "$CACHE_DIR" ]; then
    rm -rf "$CACHE_DIR"
    echo "[INFO] Removed container and image cache."
fi

echo "[INFO] Uninstallation completed successfully."
echo "[INFO] You can verify by running: docker"
