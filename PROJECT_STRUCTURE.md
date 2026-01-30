# 项目结构说明

本文档说明项目的目录组织和文件结构。

## 🎯 设计原则

1. **文档集中管理**：所有文档统一放在 `doc/` 目录
2. **测试独立存放**：所有测试文件放在 `test/` 目录
3. **代码模块化**：功能代码按模块组织
4. **配置分离**：配置文件与代码分离

## 📁 目录结构

```
playwright/
│
├── 📄 主要文件
│   ├── config.py              # 配置模块
│   ├── main.py                # 主程序入口
│   ├── requirements.txt       # Python 依赖
│   ├── .env                   # 环境变量（需自行创建）
│   ├── .env.example           # 环境变量模板
│   ├── .gitignore             # Git 忽略配置
│   ├── README.md              # 项目说明文档
│   ├── CHANGELOG.md           # 版本更新日志
│   ├── PROJECT_STRUCTURE.md   # 本文件 - 项目结构说明
│   ├── check_config.py        # 配置检查工具
│   └── run_all_tests.sh       # 测试运行脚本
│
├── 📚 doc/                    # 文档目录
│   ├── README.md              # 文档导航
│   ├── USAGE_GUIDE.md         # 完整使用指南
│   ├── CONFIGURATION.md       # 配置说明文档
│   ├── SETUP_WIZARD.md        # 分步设置向导
│   ├── QUICKSTART_LONGPORT.md # 5分钟快速开始
│   ├── CHECKLIST.md           # 启动检查清单
│   ├── LONGPORT_INTEGRATION_GUIDE.md  # 长桥 API 集成指南
│   ├── OPTION_EXPIRY_CHECK.md # 期权过期校验说明
│   └── PROJECT_STATUS.md      # 项目状态报告
│
├── 🧪 test/                   # 测试目录
│   ├── README.md              # 测试说明
│   ├── test_longport_integration.py   # 长桥 API 集成测试
│   ├── test_option_expiry.py          # 期权过期时间测试
│   ├── test_expiry_integration.py     # 期权过期集成测试
│   ├── test_position_management.py    # 持仓管理测试
│   └── test_samples.py                # 样本管理测试
│
├── 🔧 broker/                 # 券商接口模块
│   ├── __init__.py
│   ├── config_loader.py       # 配置加载器
│   ├── longport_broker.py     # 长桥交易接口
│   ├── position_manager.py    # 持仓管理器
│   └── risk_controller.py     # 风险控制器
│
├── 🕷️ scraper/                # 页面抓取模块
│   ├── __init__.py
│   ├── browser.py             # Playwright 浏览器管理
│   └── monitor.py             # 实时监控逻辑
│
├── 📝 parser/                 # 解析模块
│   ├── __init__.py
│   └── option_parser.py       # 期权指令正则解析器
│
├── 📦 models/                 # 数据模型
│   ├── __init__.py
│   └── instruction.py         # 指令数据模型
│
├── 🗂️ samples/               # 样本管理
│   ├── __init__.py
│   ├── sample_manager.py      # 样本管理器
│   ├── samples.json           # 样本数据库
│   └── initial_samples.json   # 初始样本示例
│
├── 💾 data/                   # 数据目录
│   └── positions.json         # 持仓数据
│
├── 📋 logs/                   # 日志目录
│   ├── README.md
│   └── trading.log            # 交易日志
│
└── 📤 output/                 # 输出目录
    └── signals.json           # 解析后的信号输出
```

## 📚 文档目录 (doc/)

### 用途
集中管理所有项目文档，便于查找和维护。

### 文件说明

| 文件 | 用途 | 目标读者 |
|------|------|---------|
| README.md | 文档导航 | 所有用户 |
| USAGE_GUIDE.md | 完整使用指南 | 深度用户 |
| CONFIGURATION.md | 配置说明（所有配置项详解） | 所有用户 |
| SETUP_WIZARD.md | 分步设置向导 | 新手用户 |
| QUICKSTART_LONGPORT.md | 快速上手 | 急需使用者 |
| CHECKLIST.md | 启动检查清单 | 运维人员 |
| LONGPORT_INTEGRATION_GUIDE.md | API 集成指南 | 开发人员 |
| OPTION_EXPIRY_CHECK.md | 过期校验说明 | 开发人员 |
| PROJECT_STATUS.md | 项目状态 | 产品经理 |

### 访问方式
```bash
# 查看文档目录
ls doc/

# 阅读文档
cat doc/USAGE_GUIDE.md
```

## 🧪 测试目录 (test/)

### 用途
集中管理所有测试文件，确保代码质量。

### 文件说明

| 文件 | 测试内容 | 运行时间 |
|------|---------|---------|
| README.md | 测试说明文档 | - |
| test_longport_integration.py | 长桥 API 功能 | ~3秒 |
| test_option_expiry.py | 期权过期检查 | ~2秒 |
| test_expiry_integration.py | 过期检查集成 | ~2秒 |
| test_position_management.py | 持仓管理 | ~1秒 |
| test_samples.py | 样本管理 | ~1秒 |

### 运行方式
```bash
# 运行所有测试
./run_all_tests.sh

# 运行单个测试
PYTHONPATH=. python3 test/test_longport_integration.py
```

## 🔧 代码模块

### broker/ - 券商接口
处理所有与券商 API 相关的功能。

**核心文件**：
- `longport_broker.py` - 长桥 API 封装
- `position_manager.py` - 持仓管理
- `risk_controller.py` - 风险控制

### scraper/ - 页面抓取
使用 Playwright 监控 Whop 页面。

**核心文件**：
- `browser.py` - 浏览器管理
- `monitor.py` - 消息监控

### parser/ - 指令解析
解析期权交易指令。

**核心文件**：
- `option_parser.py` - 正则表达式解析器

### models/ - 数据模型
定义数据结构。

**核心文件**：
- `instruction.py` - 指令数据模型

### samples/ - 样本管理
收集和管理消息样本。

**核心文件**：
- `sample_manager.py` - 样本管理器
- `samples.json` - 样本数据库

## 💾 数据目录

### data/
存储应用数据。

**文件**：
- `positions.json` - 持仓数据

### logs/
存储运行日志。

**文件**：
- `trading.log` - 交易日志

### output/
存储输出结果。

**文件**：
- `signals.json` - 解析后的信号

## 🔒 配置文件

### .env
环境变量配置（敏感信息，不提交到 Git）。

### .env.example
环境变量模板，供参考使用。

### config.py
Python 配置模块，加载和验证配置。

## 📜 工具脚本

### check_config.py
配置检查工具，验证 `.env` 配置是否正确。

**使用方法**：
```bash
python3 check_config.py
```

**功能**：
- 检查配置文件是否存在
- 验证必填项是否已设置
- 检查配置类型是否正确
- 评估风险参数合理性
- 提供交易模式组合建议

### run_all_tests.sh
一键运行所有测试的脚本。

**使用方法**：
```bash
chmod +x run_all_tests.sh
./run_all_tests.sh
```

## 🎯 最佳实践

### 1. 文档管理
- ✅ 所有文档放在 `doc/` 目录
- ✅ 使用清晰的文件名
- ✅ 在 `doc/README.md` 中添加索引
- ✅ 保持文档同步更新

### 2. 测试管理
- ✅ 所有测试放在 `test/` 目录
- ✅ 使用 `test_` 前缀命名
- ✅ 在 `test/README.md` 中添加说明
- ✅ 使用 `run_all_tests.sh` 批量运行

### 3. 代码组织
- ✅ 按功能模块划分目录
- ✅ 每个模块有 `__init__.py`
- ✅ 保持模块职责单一
- ✅ 使用清晰的命名

### 4. 数据管理
- ✅ 敏感数据不提交到 Git
- ✅ 使用 `.gitignore` 保护隐私
- ✅ 定期备份重要数据
- ✅ 使用 JSON 格式存储

## 🚀 快速开始

### 新手指南
1. 阅读 [README.md](./README.md)
2. 查看 [doc/SETUP_WIZARD.md](./doc/SETUP_WIZARD.md)
3. 运行测试验证安装

### 开发者指南
1. 了解目录结构（本文档）
2. 阅读 [doc/LONGPORT_INTEGRATION_GUIDE.md](./doc/LONGPORT_INTEGRATION_GUIDE.md)
3. 运行 `./run_all_tests.sh` 验证环境

## 📝 维护指南

### 添加新文档
1. 在 `doc/` 目录创建 Markdown 文件
2. 更新 `doc/README.md` 添加索引
3. 在主 `README.md` 中添加链接（如需要）

### 添加新测试
1. 在 `test/` 目录创建测试文件
2. 使用 `test_` 前缀命名
3. 更新 `test/README.md` 添加说明
4. 更新 `run_all_tests.sh` 添加测试

### 添加新模块
1. 创建模块目录
2. 添加 `__init__.py`
3. 在主 `README.md` 更新项目结构
4. 编写相应的测试文件

## 🔗 相关链接

- [README.md](./README.md) - 项目主页
- [doc/README.md](./doc/README.md) - 文档导航
- [test/README.md](./test/README.md) - 测试说明
- [CHANGELOG.md](./CHANGELOG.md) - 更新日志

## 📧 反馈

如有结构改进建议，请提交 Issue 或 Pull Request。
