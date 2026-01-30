# 📚 文档目录

本目录包含项目的所有文档。

## 文档列表

### 📖 使用指南

| 文档 | 说明 | 适用场景 |
|------|------|---------|
| [USAGE_GUIDE.md](./USAGE_GUIDE.md) | 完整使用指南 | 详细了解所有功能 |
| [CONFIGURATION.md](./CONFIGURATION.md) | 配置说明文档 | 了解所有配置项 |
| [QUICKSTART_LONGPORT.md](./QUICKSTART_LONGPORT.md) | 5分钟快速开始 | 快速上手长桥交易 |
| [SETUP_WIZARD.md](./SETUP_WIZARD.md) | 分步设置向导 | 首次配置系统 |
| [CHECKLIST.md](./CHECKLIST.md) | 启动检查清单 | 启动前自查 |

### 🔧 技术文档

| 文档 | 说明 | 适用场景 |
|------|------|---------|
| [LONGPORT_INTEGRATION_GUIDE.md](./LONGPORT_INTEGRATION_GUIDE.md) | 长桥 API 集成指南 | 了解 API 接口详情 |
| [OPTION_EXPIRY_CHECK.md](./OPTION_EXPIRY_CHECK.md) | 期权过期校验说明 | 了解过期检查机制 |
| [PROJECT_STATUS.md](./PROJECT_STATUS.md) | 项目状态报告 | 查看开发进度 |

## 快速导航

### 新手入门

1. 阅读 [README.md](../README.md) 了解项目概况
2. 查看 [CONFIGURATION.md](./CONFIGURATION.md) 了解所有配置项
3. 按照 [SETUP_WIZARD.md](./SETUP_WIZARD.md) 配置系统
4. 参考 [QUICKSTART_LONGPORT.md](./QUICKSTART_LONGPORT.md) 快速上手
5. 使用 [CHECKLIST.md](./CHECKLIST.md) 启动前检查

### 深入学习

1. [USAGE_GUIDE.md](./USAGE_GUIDE.md) - 完整功能说明
2. [LONGPORT_INTEGRATION_GUIDE.md](./LONGPORT_INTEGRATION_GUIDE.md) - API 接口详解
3. [OPTION_EXPIRY_CHECK.md](./OPTION_EXPIRY_CHECK.md) - 过期校验机制

### 开发参考

1. [PROJECT_STATUS.md](./PROJECT_STATUS.md) - 当前开发状态
2. [../CHANGELOG.md](../CHANGELOG.md) - 版本更新日志
3. [../test/README.md](../test/README.md) - 测试文件说明

## 文档结构

```
doc/
├── README.md                           # 本文件 - 文档导航
├── USAGE_GUIDE.md                      # 完整使用指南
├── CONFIGURATION.md                    # 配置说明文档
├── SETUP_WIZARD.md                     # 分步设置向导
├── QUICKSTART_LONGPORT.md              # 5分钟快速开始
├── CHECKLIST.md                        # 启动检查清单
├── LONGPORT_INTEGRATION_GUIDE.md       # 长桥 API 集成指南
├── OPTION_EXPIRY_CHECK.md              # 期权过期校验说明
└── PROJECT_STATUS.md                   # 项目状态报告
```

## 常见问题

### Q: 我应该从哪个文档开始？

**A:** 如果你是新手，建议按以下顺序阅读：
1. 主 [README.md](../README.md)
2. [SETUP_WIZARD.md](./SETUP_WIZARD.md)
3. [QUICKSTART_LONGPORT.md](./QUICKSTART_LONGPORT.md)

### Q: 如何查找特定功能的文档？

**A:** 使用文档内的搜索功能，或查看：
- 交易相关 → [LONGPORT_INTEGRATION_GUIDE.md](./LONGPORT_INTEGRATION_GUIDE.md)
- 使用方法 → [USAGE_GUIDE.md](./USAGE_GUIDE.md)
- 问题排查 → [CHECKLIST.md](./CHECKLIST.md)

### Q: 文档有更新吗？

**A:** 查看 [../CHANGELOG.md](../CHANGELOG.md) 了解最新更新。

## 贡献文档

欢迎改进文档！请遵循以下规范：

1. **清晰的标题**：使用描述性标题
2. **代码示例**：提供可运行的示例
3. **截图说明**：必要时添加图片
4. **链接检查**：确保所有链接有效
5. **中文优先**：保持中文为主要语言

### 文档模板

创建新文档时，使用以下模板：

```markdown
# 文档标题

## 概述

简要说明本文档的内容和目的。

## 目标读者

说明适合哪些读者阅读。

## 内容

### 第一部分

详细内容...

### 第二部分

详细内容...

## 示例

提供可运行的代码示例。

## 参考链接

- [相关文档](./link.md)
- [外部资源](https://example.com)

## 更新日志

- 2026-01-30: 初始版本
```

## 反馈和建议

如果您发现文档问题或有改进建议：

1. 提交 [GitHub Issue](https://github.com/your-repo/issues)
2. 直接提交 Pull Request
3. 联系项目维护者

## 许可证

所有文档遵循项目的 MIT 许可证。
