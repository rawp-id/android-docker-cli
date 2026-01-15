# Release v1.2.2 - 可写目录修复

## 🐛 Bug修复

这是v1.2.1的紧急修复版本，解决了可写目录绑定挂载未生效导致的权限错误问题。

### 修复的问题

**Nginx权限拒绝错误** ❌ → ✅
```
nginx: [alert] could not open error log file: open() "/var/log/nginx/error.log" failed (13: Permission denied)
2026/01/14 06:39:00 [emerg] 31595#31595: open() "/var/log/nginx/error.log" failed (13: Permission denied)
```

**根本原因**：
- v1.2.0实现了可写目录功能，但绑定挂载条件判断有误
- 代码检查 `args.rootfs_dir` 是否存在，但在直接运行容器时该参数为None
- 导致可写目录的绑定挂载从未被添加到proot命令中
- nginx等应用无法写入 `/var/log` 等系统目录

**解决方案**：
- ✅ 使用 `self.rootfs_dir` 而不是 `args.rootfs_dir` 来判断
- ✅ 在Android环境中总是创建可写目录绑定
- ✅ 修改 `_prepare_writable_directories` 参数逻辑
- ✅ 确保临时容器和持久化容器都能使用可写目录

## 📦 安装

### 最新版本（推荐）
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/v1.2.2/scripts/install.sh | sh
```

### 使用环境变量
```bash
INSTALL_VERSION=v1.2.2 curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/main/scripts/install.sh | sh
```

### 依赖安装
```bash
# Android Termux
pkg update && pkg install python proot curl tar

# Ubuntu/Debian
sudo apt install python3 proot curl tar
```

## 🔍 验证修复

现在nginx应该可以正常运行，不再有权限错误：

```bash
# 拉取镜像
docker pull m.daocloud.io/docker.io/library/nginx:alpine

# 运行容器
docker run -d --name test-nginx m.daocloud.io/docker.io/library/nginx:alpine

# 查看日志（应该没有权限错误）
docker logs test-nginx

# 应该看到类似输出：
# /docker-entrypoint.sh: Configuration complete; ready for start up
# （没有 "Permission denied" 错误）
```

## 📝 技术细节

### 修改的文件
- `android_docker/proot_runner.py` - `_build_proot_command()` 和 `_prepare_writable_directories()` 方法
- `tests/test_android_permissions.py` - 更新测试以匹配新的参数

### 代码变更

**v1.2.1（有问题的代码）**：
```python
# 只有当args.rootfs_dir存在时才添加可写目录
if hasattr(args, 'rootfs_dir') and args.rootfs_dir:
    container_dir = os.path.dirname(args.rootfs_dir)
    writable_binds = self._prepare_writable_directories(container_dir)
    default_binds.extend(writable_binds)
```

**v1.2.2（修复后的代码）**：
```python
# 在Android环境中总是添加可写目录
if self.rootfs_dir:
    writable_binds = self._prepare_writable_directories(self.rootfs_dir)
    default_binds.extend(writable_binds)
    logger.info("已启用Android可写目录支持")
```

### 可写目录列表

以下目录会被自动绑定挂载到主机侧的可写目录：
- `/var/log` - 日志文件
- `/var/cache` - 缓存文件
- `/var/tmp` - 临时文件
- `/tmp` - 临时文件
- `/run` - 运行时文件

## 🎯 影响范围

此修复影响所有需要写入系统目录的应用，包括但不限于：
- nginx - 需要写入日志
- apache - 需要写入日志和缓存
- 数据库应用 - 需要写入临时文件
- 任何需要写入 `/var/log`、`/tmp` 等目录的应用

## ⚠️ 已知限制

与v1.2.0相同：
1. **Whiteout文件语义**: 层删除语义可能不完全保留，但不影响容器正常运行
2. **文件权限**: 某些文件权限操作在Android文件系统上可能无法按预期工作
3. **进程隔离**: proot提供进程隔离但不是完整的容器化

## 📊 变更统计

- **修改的文件**: 2个
- **新增代码**: 12行
- **删除代码**: 9行
- **测试**: 所有9个测试通过 ✅

## 🔗 相关链接

- [完整变更](https://github.com/jinhan1414/android-docker-cli/compare/v1.2.1...v1.2.2)
- [问题追踪](https://github.com/jinhan1414/android-docker-cli/issues)
- [文档](https://github.com/jinhan1414/android-docker-cli/blob/main/README.md)

## 🙏 致谢

感谢用户持续反馈和测试！

## 📈 版本历史

- **v1.2.0**: 初始Android权限修复（whiteout文件、可写目录、Android检测）
- **v1.2.1**: 放宽关键文件验证，支持非标准镜像布局
- **v1.2.2**: 修复可写目录绑定挂载未生效的问题 ✅

---

**完整提交**: 9bfafe1
**发布日期**: 2026-01-14
**修复版本**: v1.2.1 → v1.2.2
