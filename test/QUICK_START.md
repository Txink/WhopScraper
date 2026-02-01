# 测试快速开始指南

## 🚨 重要提示

所有测试都需要设置 `PYTHONPATH` 才能正确导入 `broker` 模块。

## ✅ 正确运行方法

### 方法1: 使用 PYTHONPATH（推荐）

```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=. python3 test/broker/test_order_management.py
```

### 方法2: 使用快捷脚本

```bash
cd /Users/txink/Documents/code/playwright
./run_order_test.sh
```

### 方法3: 使用 test/run_tests.py

```bash
cd /Users/txink/Documents/code/playwright
python3 test/run_tests.py
```

## 常见测试命令

### 订单管理测试（新功能）⭐

```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=. python3 test/broker/test_order_management.py
```

测试内容：
- ✅ 带固定止损的订单（trigger_price）
- ✅ 跟踪止损订单（trailing_percent）
- ✅ 订单修改（价格和数量）
- ✅ 订单撤销
- ✅ 订单详情查询

### 长桥集成测试（包含期权链查询）

```bash
PYTHONPATH=. python3 test/broker/test_longport_integration.py
```

测试内容：
- ✅ 配置加载
- ✅ 账户信息获取
- ✅ 期权链查询（到期日、行权价、报价）
- ✅ 期权代码转换
- ✅ Dry Run 下单
- ✅ 订单和持仓查询

### 配置验证测试

```bash
PYTHONPATH=. python3 test/test_config.py
```

### 持仓管理测试

```bash
PYTHONPATH=. python3 test/broker/test_position_management.py
```

## ❌ 错误示例

### 错误：不要直接运行

```bash
# ❌ 错误 - 会报 ModuleNotFoundError
python3 test/broker/test_order_management.py
```

错误信息：
```
ModuleNotFoundError: No module named 'broker'
```

### 正确：使用 PYTHONPATH

```bash
# ✅ 正确
cd /Users/txink/Documents/code/playwright
PYTHONPATH=. python3 test/broker/test_order_management.py
```

## 为什么需要 PYTHONPATH？

Python 需要知道在哪里查找 `broker` 模块。项目结构如下：

```
playwright/
├── broker/              # broker 模块在这里
│   ├── __init__.py
│   └── longport_broker.py
├── test/
│   └── broker/
│       └── test_order_management.py
└── ...
```

测试文件在 `test/broker/` 中，但 `broker` 模块在项目根目录。
设置 `PYTHONPATH=.` 告诉 Python 在当前目录（项目根目录）查找模块。

## 创建永久别名（可选）

如果您经常运行测试，可以在 `~/.zshrc` 或 `~/.bashrc` 中添加：

```bash
# 长桥测试别名
alias lp-test='cd /Users/txink/Documents/code/playwright && PYTHONPATH=. python3'

# 使用方法
lp-test test/broker/test_order_management.py
lp-test test/broker/test_longport_integration.py
```

重新加载配置：
```bash
source ~/.zshrc  # 或 source ~/.bashrc
```

## 运行所有测试

```bash
cd /Users/txink/Documents/code/playwright
python3 test/run_tests.py
```

这会运行所有测试套件并生成详细报告。

## 测试输出示例

成功的测试输出：

```
✅ 订单提交成功:
  订单ID: 1202577800121298944
  买入价格: $5.00
  止损触发价: $3.00

✅ 订单修改成功:
  订单ID: 1202577800121298944
  新数量: 2
  新价格: $4.50

✅ 订单已撤销: 1202577800121298944
```

## 故障排查

### 问题1: ModuleNotFoundError: No module named 'broker'

**原因**: 未设置 PYTHONPATH

**解决**:
```bash
cd /Users/txink/Documents/code/playwright
PYTHONPATH=. python3 test/...
```

### 问题2: 找不到 .env 文件

**原因**: 不在项目根目录

**解决**:
```bash
cd /Users/txink/Documents/code/playwright  # 必须在根目录
PYTHONPATH=. python3 test/...
```

### 问题3: API 认证失败

**原因**: .env 文件配置不正确

**解决**: 检查 .env 文件中的长桥 API 凭据

```bash
# 验证配置
python3 check_config.py
```

## 更多帮助

- 📖 [完整测试文档](./README.md)
- 📖 [订单管理功能文档](../docs/order_management.md)
- 📖 [长桥集成指南](../doc/LONGPORT_INTEGRATION_GUIDE.md)
