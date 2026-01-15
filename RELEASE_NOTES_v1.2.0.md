# Release v1.2.0 - Android权限修复

## 🎉 主要更新

这个版本解决了在非root Android设备上运行Docker容器时的关键权限问题。

### 修复的问题

1. **Tar提取失败** ❌ → ✅
   ```
   tar: ./var/lib/apt/lists/.wh.auxfiles: Cannot open: Permission denied
   ```
   **解决方案**: 自动跳过whiteout文件，添加排除标志

2. **Nginx权限拒绝** ❌ → ✅
   ```
   nginx: [alert] could not open error log file: open() "/var/log/nginx/error.log" failed (13: Permission denied)
   ```
   **解决方案**: 自动创建可写系统目录并绑定挂载

## ✨ 新功能

### 1. Whiteout文件处理增强
- ✅ 自动排除`.wh.*`文件
- ✅ Python tarfile过滤器
- ✅ 智能警告日志
- ✅ 提取回退机制

### 2. 可写系统目录支持
- ✅ 自动创建`/var/log`, `/var/cache`, `/var/tmp`, `/tmp`, `/run`
- ✅ Android环境自动绑定挂载
- ✅ 容器删除时自动清理

### 3. Android环境检测增强
- ✅ 更准确的Termux检测
- ✅ 多重检测指标
- ✅ 详细调试日志

### 4. 关键文件验证
- ✅ 提取后验证shell存在
- ✅ 验证lib目录
- ✅ 清晰的错误消息

### 5. 版本特定安装
- ✅ 支持URL版本检测
- ✅ 支持`INSTALL_VERSION`环境变量
- ✅ 版本验证
- ✅ 安装后显示版本号

### 6. 增强的用户体验
- ✅ Android启动警告
- ✅ Whiteout文件跳过提示
- ✅ Android特定故障排除提示
- ✅ 详细的调试日志

## 📦 安装

### 最新版本（推荐）
```bash
curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/v1.2.0/scripts/install.sh | sh
```

### 使用环境变量
```bash
INSTALL_VERSION=v1.2.0 curl -sSL https://raw.githubusercontent.com/jinhan1414/android-docker-cli/main/scripts/install.sh | sh
```

### 依赖安装
```bash
# Android Termux
pkg update && pkg install python proot curl tar

# Ubuntu/Debian
sudo apt install python3 proot curl tar
```

## 🧪 测试

本版本包含全面的测试覆盖：

- **15个属性测试**（使用hypothesis库）
- **4个集成测试套件**
- **所有测试通过** ✅

### 运行测试
```bash
# 属性测试
python -m pytest tests/test_android_permissions.py -v

# 集成测试
python -m pytest tests/test_android_integration.py -v

# 使用测试脚本
bash scripts/run_android_tests.sh  # Linux/Mac
scripts\run_android_tests.bat      # Windows
```

## 📚 文档更新

- ✅ Android限制说明
- ✅ 常见问题故障排除
- ✅ 版本安装示例
- ✅ 中英文双语文档

## 🔍 使用示例

### 测试nginx（之前会失败）
```bash
docker pull nginx:alpine
docker run -d --name test-nginx nginx:alpine
docker logs test-nginx  # 现在应该没有权限错误
```

### 测试termix（包含whiteout文件）
```bash
docker pull ghcr.io/lukegus/termix:release-1.10.0
docker run -d --name test-termix ghcr.io/lukegus/termix:release-1.10.0
```

### 测试卷挂载
```bash
docker run -d --name test-volume -v /sdcard/test:/data alpine:latest
```

### 验证可写目录
```bash
docker run -it alpine:latest sh -c "echo test > /var/log/test.log && cat /var/log/test.log"
```

## ⚠️ 已知限制

1. **Whiteout文件语义**: 层删除语义可能不完全保留，但不影响容器正常运行
2. **文件权限**: 某些文件权限操作在Android文件系统上可能无法按预期工作
3. **进程隔离**: proot提供进程隔离但不是完整的容器化

## 📊 变更统计

- **修改的文件**: 6个核心文件
- **新增的测试文件**: 2个
- **新增的脚本**: 2个
- **测试用例**: 13个
- **代码行数**: ~940行新增/修改
- **文档更新**: 3个文件

## 🙏 致谢

感谢所有测试和反馈的用户！

## 🔗 相关链接

- [完整变更日志](https://github.com/jinhan1414/android-docker-cli/compare/v1.1.0...v1.2.0)
- [问题追踪](https://github.com/jinhan1414/android-docker-cli/issues)
- [文档](https://github.com/jinhan1414/android-docker-cli/blob/main/README.md)

## 📝 下一步

如果遇到问题，请：
1. 查看[故障排除指南](https://github.com/jinhan1414/android-docker-cli/blob/main/README.md#troubleshooting)
2. 使用`--verbose`标志查看详细日志
3. 在GitHub上[提交issue](https://github.com/jinhan1414/android-docker-cli/issues/new)

---

**完整提交**: cf84fb7
**发布日期**: 2026-01-14
