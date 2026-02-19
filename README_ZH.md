# Android Docker CLI

[English](README.md) | Chinese

A tool to run Docker images on Android using `proot`, without needing a Docker engine. This project is designed to be used within the [Termux](https://github.com/termux/termux-app) application, providing a Docker-like command-line interface to manage persistent containers.

## Core Features

- **Modular Codebase**: All core logic is organized within the `android_docker` package.
- **Main CLI**: The main entry point is `android_docker/docker_cli.py`, providing a Docker-style CLI for full container lifecycle management.
- **Persistent Containers**: Containers have a persistent filesystem and can be started, stopped, and restarted.
- **Underlying Engine**: Uses `android_docker/proot_runner.py` to execute containers and `android_docker/create_rootfs_tar.py` to download and prepare container images.

## Installation

You can install this tool with a single command:

```bash
# Install latest version (main branch)
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/main/scripts/install.sh | sh

# Install specific version (e.g., v1.1.0)
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/v1.1.0/scripts/install.sh | sh

# Or use environment variable to specify version
INSTALL_VERSION=v1.2.0 curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/main/scripts/install.sh | sh
```

This will create an executable `docker` command in your path. After installation, you can run the tool by simply typing `docker`.

## Install Dependencies

```bash
# Android Termux
pkg update && pkg install python proot curl tar

# Ubuntu/Debian
sudo apt install python3 proot curl tar
```

## Quick Start

After installation, you can use this tool just like the standard Docker command line.

```bash
# Log in to a Docker registry (e.g., Docker Hub)
docker login

# Pull an image from a private registry after logging in
docker login your-private-registry.com
docker pull your-private-registry.com/my-image

# Pull a public image
docker pull alpine:latest

# Run a container in the foreground
docker run alpine:latest echo "Hello from container"

# Run a container in the background (detached mode)
docker run -d -e "API_KEY=sk-12345" --volume /sdcard:/data nginx:alpine

# Run a container interactively
docker run -it alpine:latest /bin/sh

# Run an Nginx container with a custom config file from the project
# This example uses the `examples/nginx.conf` file, which listens on port 8777.
docker run -d --name my-nginx -v $(pwd)/examples/nginx.conf:/etc/nginx/nginx.conf nginx:alpine

# List running containers
docker ps

# List all containers (including stopped ones)
docker ps -a

# View container logs
docker logs <container_id>
docker logs -f <container_id>  # Follow logs continuously

# Stop a container
docker stop <container_id>

# Start a stopped container
docker start <container_id>

# Restart a container
docker restart <container_id>

# Remove a container
docker rm <container_id>

# Attach to a running container
docker attach <container_id>

# Execute a command in a running container
docker exec <container_id> ls -l
docker exec -it <container_id> /bin/sh

# List cached images
docker images

# Load an image from a local tar file
docker load -i alpine.tar
docker load -i /path/to/my-image.tar

# Remove a cached image
docker rmi alpine:latest

# Log in to an image registry
docker login your-private-registry.com
```

## Loading Local Images

You can load Docker images from local tar archive files without pulling from a registry. This is useful for:
- Using pre-downloaded images
- Loading images built on other systems
- Working offline

### Requirements

The tar file must be a valid Docker image archive containing:
- `manifest.json` - Image manifest
- Layer tar files (e.g., `<hash>/layer.tar`)
- Config JSON file (e.g., `<hash>.json`)

### Usage

```bash
# Load an image from a tar file
docker load -i alpine.tar

# Load an image from a specific path
docker load -i /sdcard/Download/my-image.tar

# After loading, the image will appear in your images list
docker images
```

### Creating Docker Image Tar Files

You can create compatible tar files using standard Docker:

```bash
# On a system with Docker installed
docker save alpine:latest -o alpine.tar

# Transfer the tar file to your Android device
# Then load it
docker load -i alpine.tar
```

## Docker Compose Support

This tool includes a `docker-compose` command for managing multi-container applications.

```bash
# Start services defined in docker-compose.yml
docker-compose up

# Run in the background
docker-compose up -d

# Stop and remove services
docker-compose down
```

### Example `docker-compose.yml`

```yaml
version: '3'
services:
  web:
    image: nginx:alpine
    container_name: my-web-server
  db:
    image: redis:alpine
    container_name: my-redis-db
```

## Key Features

- ✅ **Complete Container Lifecycle**: `run`, `ps`, `stop`, `start`, `restart`, `logs`, `rm`, `attach`, `exec`.
- ✅ **Registry Authentication**: Use the `login` command to authenticate with private or public registries.
- ✅ **Local Image Loading**: Load Docker images from local tar files using `docker load`.
- ✅ **OCI Registry Support**: Pull images from OCI-compliant registries like GitHub Container Registry (ghcr.io).
- ✅ **Docker Compose Support**: Manage multi-container configurations using `docker-compose up` and `down`.
- ✅ **Docker-style CLI**: Familiar and intuitive command-line interface.
- ✅ **Persistent Storage**: Containers maintain their state and filesystem across restarts, stored in `~/.docker_proot_cache/`.
- ✅ **Android Optimized**: Specially optimized for the Termux environment.

## Troubleshooting

```bash
# Check dependencies
curl --version && tar --version && proot --version

# Use verbose logging for more information
docker --verbose run alpine:latest
```

### Common Android Issues

#### Permission Denied Errors

If you encounter permission errors, such as:
```
nginx: [alert] could not open error log file: open() "/var/log/nginx/error.log" failed (13: Permission denied)
```

**Solution**: The tool automatically creates writable system directories on Android. Make sure you're using the latest version.

#### Whiteout File Warnings

If you see warnings about `.wh.auxfiles` or similar whiteout files:
```
tar: ./var/lib/apt/lists/.wh.auxfiles: Cannot open: Permission denied
```

**Solution**: These files are automatically skipped on Android. Layer deletion semantics may not be fully preserved, but the container will run normally.

#### Extraction Failures

If image extraction fails:
- Use the `--verbose` flag to see detailed error information
- Check available disk space in Termux
- Try pulling a smaller image first (e.g., `alpine:latest`)
- Ensure all dependencies are installed: `pkg install python proot curl tar`

#### Container Startup Issues

If a container fails to start:
- Use `docker logs <container_id>` to view logs
- Verify the image is compatible with your architecture
- Some images may require specific features not available in proot
- Try running with `--verbose` for detailed debugging information

If you see errors like `chown ... Operation not permitted` or `Can't drop privilege as nonroot user` on Android/Termux:
- Please update to a newer version. Android runs enable additional compatibility behavior that allows some "start-as-root-then-drop-privileges" images to run without extra parameters.

## Limitations

- Based on `proot`, not full containerization (no kernel-level process or network isolation).
- Some system calls may not be supported.
- Performance is lower compared to native Docker.
- Limited network isolation.

### Android-Specific Limitations

- **Whiteout Files**: Due to Android permission restrictions, Docker layer deletion semantics (whiteout files) are skipped. This means files deleted from previous layers may still exist in the final container filesystem.
- **System Directories**: Writable system directories (`/var/log`, `/var/cache`, `/tmp`, etc.) are automatically bind-mounted from host storage to work around Android permission restrictions.
- **File Permissions**: Some file permission and ownership operations may not work as expected on Android filesystems.
- **Process Isolation**: proot provides process isolation but not full containerization. Containers share the same kernel with limited resource isolation.

## License

MIT License
