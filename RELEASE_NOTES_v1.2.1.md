# Release v1.2.1 - 关键文件验证修复

## 🐛 Bug修复

这是v1.2.0的紧急修复版本，解决了关键文件验证过于严格导致的镜像拉取失败问题。

### 修复的问题

**关键文件验证失败** ❌ → ✅
```
ERROR - 提取后缺少关键文件: shell (checked: /bin/sh, /bin/bash, /bin/ash)
ERROR - 镜像拉取失败: m.daocloud.io/docker.io/library/nginx:alpine
```

**根本原因**：
- v1.2.0的验证逻辑要求所有镜像必须有标准的shell路径（/bin/sh, /bin/bash, /bin/ash）
- 某些镜像（如nginx:alpine）使用非标准路径或最小化布局
- 导致正常镜像被误判为无效

**解决方案**：
- ✅ Android环境使用宽松验证模式
- ✅ 只检查rootfs是否为空和基本目录结构
- ✅ 不强制要求特定的shell或lib路径
- ✅ 发出警告而不是错误，允许镜像继续运行

## 📦 安装

### 最新版本（推荐）
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/v1.2.1/scripts/install.sh | sh
```

### 使用环境变量
```bash
INSTALL_VERSION=v1.2.1 curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/main/scripts/install.sh | sh
```

### 依赖安装
```bash
# Android Termux
pkg update && pkg install python proot curl tar

# Ubuntu/Debian
sudo apt install python3 proot curl tar
```

## 🔍 验证修复

现在可以成功拉取和运行nginx:alpine镜像：

```bash
# 拉取镜像
docker pull m.daocloud.io/docker.io/library/nginx:alpine

# 运行容器
docker run -d --name test-nginx m.daocloud.io/docker.io/library/nginx:alpine

# 查看日志（应该没有权限错误）
docker logs test-nginx
```

## 📝 技术细节

### 修改的文件
- `android_docker/create_rootfs_tar.py` - `_validate_critical_files()` 方法

### 验证逻辑变更

**v1.2.0（严格模式）**：
```python
# 要求必须有以下文件之一
shells = ['/bin/sh', '/bin/bash', '/bin/ash']
# 如果都不存在 → 错误并终止
```

**v1.2.1（宽松模式 - Android环境）**：
```python
# 只检查基本结构
if not os.listdir(rootfs_dir):
    # rootfs为空 → 错误
else:
    # 检查是否有基本目录（bin, usr, lib, etc, var）
    # 如果缺少 → 警告但继续
    # 不强制要求特定文件
```

**非Android环境**：保持严格验证不变

## 🎯 影响范围

此修复影响所有使用非标准布局的Docker镜像，包括但不限于：
- nginx:alpine
- 其他Alpine Linux基础镜像
- 最小化镜像（distroless等）
- 自定义镜像

## ⚠️ 已知限制

与v1.2.0相同：
1. **Whiteout文件语义**: 层删除语义可能不完全保留，但不影响容器正常运行
2. **文件权限**: 某些文件权限操作在Android文件系统上可能无法按预期工作
3. **进程隔离**: proot提供进程隔离但不是完整的容器化

## 📊 变更统计

- **修改的文件**: 1个
- **新增代码**: 26行
- **删除代码**: 1行
- **测试**: 所有现有测试通过 ✅

## 🔗 相关链接

- [完整变更](https://github.com/jinhan1414/android-docker-cli/compare/v1.2.0...v1.2.1)
- [问题追踪](https://github.com/jinhan1414/android-docker-cli/issues)
- [文档](https://github.com/jinhan1414/android-docker-cli/blob/main/README.md)

## 🙏 致谢

感谢用户及时反馈此问题！

---

**完整提交**: f7125e4
**发布日期**: 2026-01-14
**修复版本**: v1.2.0 → v1.2.1
