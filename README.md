# Android Docker CLI (English Edition)

> Run Docker images on Android using proot --- no Docker Engine
> required.

------------------------------------------------------------------------

## 📢 Acknowledgment

This project is a fork of the original work by **@jinhan1414**.

Original Repository:  
[android-docker-cli by jinhan1414](https://github.com/jinhan1414/android-docker-cli)

All core architecture, container engine logic, and implementation were
created by the original author.

This fork focuses on:

-   🌍 Translating the entire project and documentation into full
    English
-   🧹 Improving documentation clarity and structure
-   🛠 Minor usability improvements

Huge respect and full credit to **@jinhan1414** for the original
innovation behind this project.

------------------------------------------------------------------------

## 📦 About This Project

Android Docker CLI allows you to run Docker images on Android using
`proot`, without needing a Docker Engine.

It is specifically designed to work inside the **Termux** environment
and provides a Docker-style command-line interface to manage persistent
containers.

------------------------------------------------------------------------

## 🚀 Core Features

-   Modular Python codebase (`android_docker` package)
-   Docker-style CLI (`docker` command)
-   Persistent containers (start, stop, restart)
-   `docker-compose` support
-   Local image loading (`docker load`)
-   OCI registry support
-   Android-optimized behavior
-   Persistent storage in `~/.docker_proot_cache/`

------------------------------------------------------------------------

## 🛠 Installation

### Install Latest Version

``` bash
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/main/scripts/install.sh | sh
```

### Install Specific Version

``` bash
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/v1.1.0/scripts/install.sh | sh
```

### Install via Environment Variable

``` bash
INSTALL_VERSION=v1.2.0 curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/main/scripts/install.sh | sh
```

After installation:

``` bash
docker
docker-compose
```

------------------------------------------------------------------------

## 📦 Dependencies

### Termux

``` bash
pkg update && pkg install python proot curl tar
```

### Ubuntu / Debian

``` bash
sudo apt install python3 proot curl tar
```

------------------------------------------------------------------------

## ⚡ Quick Start

``` bash
# Pull image
docker pull alpine:latest

# Run container
docker run alpine:latest echo "Hello from container"

# List containers
docker ps

# Stop container
docker stop <container_id>

# Remove container
docker rm <container_id>
```

------------------------------------------------------------------------

## 🧩 Docker Compose

``` bash
docker-compose up
docker-compose up -d
docker-compose down
```

------------------------------------------------------------------------

## 💾 Storage Location

All containers and images are stored in:

    ~/.docker_proot_cache/

------------------------------------------------------------------------

## ⚠ Limitations

-   Based on `proot` (not real containerization)
-   No kernel-level isolation
-   Limited network isolation
-   Some system calls may not be supported
-   Lower performance compared to native Docker

------------------------------------------------------------------------

## 📱 Android-Specific Notes

-   Docker whiteout files are skipped due to Android filesystem
    restrictions
-   Writable system directories are automatically mounted
-   File permission behavior may differ from standard Linux
-   Containers share the Android kernel

------------------------------------------------------------------------

## 📝 License

MIT License

------------------------------------------------------------------------

## 🙌 Credits

Original Author: **@jinhan1414**\
Fork & Full English Translation: **rawp-id**

This project exists thanks to the original implementation by the author.
