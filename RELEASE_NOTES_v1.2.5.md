# Release v1.2.5 (prerelease)

## Fixes
- Seed Android writable system directories from the extracted rootfs so nested directories like /var/log/nginx and /var/cache/nginx exist before bind mounts.
- Add tests for writable directory seeding.

## Notes
- This is a prerelease intended for testing on Android/Termux.
