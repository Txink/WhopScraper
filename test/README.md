# 测试文件说明

本目录包含项目的所有测试文件。

## 运行测试

所有测试都需要在项目根目录运行，并设置 `PYTHONPATH`：

```bash
cd /path/to/playwright
PYTHONPATH=. python3 test/test_name.py
```

## 测试文件列表

### 1. test_config.py

**配置加载测试**

测试所有配置项能否从 .env 文件正确加载：
- ✅ Whop 平台配置
- ✅ 浏览器配置
- ✅ 监控配置
- ✅ 默认值验证
- ✅ 类型验证
- ✅ 环境文件检查
- ✅ 配置验证

运行：
```bash
PYTHONPATH=. python3 test/test_config.py
```

### 2. test_longport_integration.py

**长桥 OpenAPI 集成测试**

测试长桥证券 API 的完整功能，包括：
- ✅ 配置加载
- ✅ 账户信息获取
- ✅ 期权代码转换
- ✅ 购买数量计算
- ✅ Dry Run 模式下单
- ✅ 获取当日订单
- ✅ 获取持仓信息

运行：
```bash
PYTHONPATH=. python3 test/test_longport_integration.py
```

### 3. test_option_expiry.py

**期权过期时间校验测试**

测试期权到期日期的校验功能：
- ✅ 已过期期权被正确拦截
- ✅ 有效期权正常处理
- ✅ 今天到期的期权仍有效
- ✅ "本周"期权自动计算
- ✅ 完整日期格式支持

运行：
```bash
PYTHONPATH=. python3 test/test_option_expiry.py
```

### 4. test_expiry_integration.py

**期权过期集成测试**

在实际场景中测试期权过期校验：
- ✅ 模拟真实交易流程
- ✅ 验证指令解析 + 过期检查的集成
- ✅ 测试错误处理和日志输出

运行：
```bash
PYTHONPATH=. python3 test/test_expiry_integration.py
```

### 5. test_position_management.py

**持仓管理测试**

测试持仓管理系统：
- ✅ 添加持仓
- ✅ 更新持仓
- ✅ 删除持仓
- ✅ 查询持仓
- ✅ 持久化存储

运行：
```bash
PYTHONPATH=. python3 test/test_position_management.py
```

### 6. test_samples.py

**样本管理测试**

测试样本收集和管理功能：
- ✅ 添加样本
- ✅ 查询样本
- ✅ 统计报告
- ✅ 导出样本

运行：
```bash
PYTHONPATH=. python3 test/test_samples.py
```

## 运行所有测试

创建一个简单的脚本运行所有测试：

```bash
#!/bin/bash
# run_all_tests.sh

cd "$(dirname "$0")/.."

echo "运行所有测试..."
echo ""

echo "1/6 配置加载测试"
PYTHONPATH=. python3 test/test_config.py
echo ""

echo "2/6 长桥 API 集成测试"
PYTHONPATH=. python3 test/test_longport_integration.py
echo ""

echo "3/6 期权过期校验测试"
PYTHONPATH=. python3 test/test_option_expiry.py
echo ""

echo "4/6 期权过期集成测试"
PYTHONPATH=. python3 test/test_expiry_integration.py
echo ""

echo "5/6 持仓管理测试"
PYTHONPATH=. python3 test/test_position_management.py
echo ""

echo "6/6 样本管理测试"
PYTHONPATH=. python3 test/test_samples.py
echo ""

echo "✅ 所有测试完成！"
```

使用方法：
```bash
chmod +x run_all_tests.sh
./run_all_tests.sh
```

## 测试环境要求

### 必需配置

1. **环境变量**：确保 `.env` 文件已正确配置
2. **长桥凭据**：测试需要有效的长桥 API 凭据
3. **Python 依赖**：安装所有依赖 `pip3 install -r requirements.txt`

### 可选配置

- 设置 `LONGPORT_DRY_RUN=true` 避免真实交易
- 使用模拟账户 `LONGPORT_MODE=paper`

## 注意事项

1. **真实交易风险**：某些测试可能触发真实交易，请确保使用模拟账户或启用 Dry Run 模式
2. **API 限流**：频繁运行测试可能触发 API 限流，请适当控制测试频率
3. **网络连接**：测试需要稳定的网络连接到长桥 API
4. **时区问题**：期权过期测试依赖系统时间，请确保系统时区设置正确

## 故障排查

### ModuleNotFoundError

```bash
ModuleNotFoundError: No module named 'broker'
```

**解决方案**：确保在项目根目录运行，并设置 `PYTHONPATH`：
```bash
cd /path/to/playwright
PYTHONPATH=. python3 test/test_name.py
```

### Token Invalid

```bash
OpenApiException: token invalid
```

**解决方案**：更新 `.env` 中的长桥 API 凭据

### 期权合约不存在

```bash
OpenApiException: security not found
```

**解决方案**：这是正常的，因为测试使用的是示例期权代码。启用 `LONGPORT_DRY_RUN=true` 可避免此错误。

## 持续集成

未来可以添加 CI/CD 配置，自动运行测试：

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: PYTHONPATH=. python3 test/test_option_expiry.py
      # ... 其他测试
```

## 贡献测试

欢迎贡献新的测试用例：

1. 在 `test/` 目录创建新的测试文件
2. 使用清晰的测试函数命名
3. 添加详细的文档字符串
4. 更新本 README.md
5. 提交 Pull Request

## 参考文档

- [长桥 OpenAPI 文档](https://open.longportapp.com/)
- [项目主 README](../README.md)
- [期权过期校验文档](../doc/OPTION_EXPIRY_CHECK.md)
