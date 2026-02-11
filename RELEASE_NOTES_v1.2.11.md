# Release v1.2.11 - Universal Hardlink Compatibility (Android/Termux)

- Android/Termux 下默认启用 `proot --link2symlink`（若当前 proot 版本支持），将镜像/应用在运行时触发的 `link()`（硬链接）行为转换为符号链接，提升对“硬链接受限/不可用”场景的兼容性。
  - 这可以通用解决一类问题：镜像内程序依赖 `os.link()` 做原子操作（例如 `supervisord` 创建 unix socket 时可能出现的 `Unlinking stale socket /var/run/supervisor.sock` 循环）。
- `supervisord.conf` 的自动补丁逻辑改为默认关闭（如需启用，可设置 `ANDROID_DOCKER_ENABLE_IMAGE_PATCHES=1`）。

Install:
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/v1.2.11/scripts/install.sh | sh
```

Update:
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/main/scripts/update.sh | sh
```

