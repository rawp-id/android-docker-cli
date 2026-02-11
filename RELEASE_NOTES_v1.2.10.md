# Release v1.2.10 - Supervisord Unix Socket Compatibility

- Improve Android/Termux compatibility for images that use `supervisord` with a unix control socket (`/var/run/supervisor.sock`).
- On Android, automatically patch `supervisord.conf` to use `inet_http_server` on `127.0.0.1:9001` instead of `unix_http_server`, avoiding hard-link based socket creation loops like `Unlinking stale socket /var/run/supervisor.sock`.

Install:
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/v1.2.10/scripts/install.sh | sh
```

Update:
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/main/scripts/update.sh | sh
```

