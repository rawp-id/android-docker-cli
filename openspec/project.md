# Project Context

## Purpose
Provide a Docker-style CLI that can run OCI/Docker images on Android (Termux) using proot, without requiring a Docker engine. The tool manages image caching and a persistent container lifecycle with a familiar docker-like interface.

## Tech Stack
- Python 3 (stdlib-only runtime; argparse, logging, subprocess, json)
- proot for container-like execution on Android/Termux
- curl and tar for image downloads/extraction
- pytest + hypothesis for testing

## Project Conventions

### Code Style
- Python with snake_case functions and classes; modules under `android_docker/`
- CLI entrypoint: `android_docker/docker_cli.py`
- Use `logging` for output; keep CLI UX Docker-like
- Prefer simple, stdlib-only implementations unless justified

### Architecture Patterns
- `DockerCLI` orchestrates commands and state in `docker_cli.py`
- `ProotRunner` executes containers and manages rootfs/runtime
- `create_rootfs_tar.py` handles image download and rootfs creation
- Persistent state stored under `~/.docker_proot_cache/` (containers, config, cache)

### Testing Strategy
- Use `pytest` for unit/integration tests under `tests/`
- Use `hypothesis` for property-based checks where it helps
- Prefer tests that validate CLI behaviors and cache/state transitions

### Git Workflow
- Not documented in repo; follow maintainer guidance and existing release notes/tags

## Domain Context
- Android/Termux environment with limited permissions and no Docker daemon
- proot provides user-space isolation, not full containerization
- Docker/OCI registries supported (Docker Hub, ghcr.io, etc.)

## Important Constraints
- Must work without kernel-level container features
- Android filesystem permissions require writable bind mounts for system paths
- Whiteout semantics are limited; deleted files in layers may persist
- Keep dependencies minimal (stdlib + system tools only)

## External Dependencies
- proot binary
- curl and tar CLI tools
- Docker/OCI registries for image pulls (auth stored in cache config)
