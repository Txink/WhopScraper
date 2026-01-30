# 配置说明文档

本文档详细说明所有配置项及其作用。

## 配置原则

✅ **所有配置都在 `.env` 文件中设置**  
✅ **无需修改代码**  
✅ **配置文件不提交到 Git**  

## 配置文件

| 文件 | 说明 | 提交到 Git |
|------|------|-----------|
| `.env.example` | 配置模板，包含所有可用配置项 | ✅ 是 |
| `.env` | 实际配置，包含真实凭据 | ❌ 否 |
| `config.py` | 配置加载模块（自动读取 .env） | ✅ 是 |

## 快速开始

```bash
# 1. 复制模板
cp .env.example .env

# 2. 编辑配置
vim .env  # 或使用任何文本编辑器

# 3. 验证配置
python3 check_config.py

# 4. 运行测试
python3 main.py --test
```

### 配置检查工具

我们提供了 `check_config.py` 工具，用于快速验证配置：

```bash
python3 check_config.py
```

**检查项目**：
- ✅ 配置文件是否存在（.env, .env.example）
- ✅ Whop 凭据是否配置
- ✅ 长桥凭据是否配置（根据账户模式）
- ✅ 风险参数是否合理
- ✅ 交易模式组合提示

**输出示例**：
```
✅ 所有配置检查通过！

下一步:
  1. 运行测试: ./run_all_tests.sh
  2. 启动系统: python3 main.py
```

## 配置项详解

### 📧 Whop 平台配置

#### WHOP_EMAIL（必填）
- **说明**：Whop 账户邮箱
- **类型**：字符串
- **示例**：`user@example.com`
- **默认值**：无
- **备注**：用于自动登录 Whop 平台

#### WHOP_PASSWORD（必填）
- **说明**：Whop 账户密码
- **类型**：字符串
- **示例**：`your_password`
- **默认值**：无
- **备注**：敏感信息，不会提交到 Git

#### TARGET_URL（可选）
- **说明**：监控的目标页面 URL
- **类型**：字符串（URL）
- **示例**：`https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/`
- **默认值**：`https://whop.com/joined/stock-and-option/-9vfxZgBNgXykNt/app/`
- **备注**：如果你的页面 URL 不同，请修改此项

#### LOGIN_URL（可选）
- **说明**：Whop 登录页面 URL
- **类型**：字符串（URL）
- **示例**：`https://whop.com/login/`
- **默认值**：`https://whop.com/login/`
- **备注**：通常不需要修改

### 🌐 浏览器设置

#### HEADLESS（可选）
- **说明**：是否以无头模式运行浏览器
- **类型**：布尔值（true/false）
- **可选值**：`true`（无头模式）、`false`（显示浏览器窗口）
- **默认值**：`false`
- **备注**：
  - `true`：后台运行，不显示浏览器窗口（适合生产环境）
  - `false`：显示浏览器窗口（适合调试）

#### SLOW_MO（可选）
- **说明**：浏览器操作延迟（毫秒）
- **类型**：整数
- **示例**：`0`、`100`、`500`
- **默认值**：`0`
- **备注**：
  - `0`：正常速度
  - `> 0`：每个操作延迟指定毫秒（用于调试，观察浏览器操作）

### 📊 监控设置

#### POLL_INTERVAL（可选）
- **说明**：轮询间隔（秒）
- **类型**：浮点数
- **示例**：`1.0`、`2.0`、`5.0`
- **默认值**：`2.0`
- **备注**：
  - 检查新消息的时间间隔
  - 建议 1.0 - 5.0 秒之间
  - 太短可能增加服务器压力，太长可能错过信号

#### STORAGE_STATE_PATH（可选）
- **说明**：Cookie 持久化存储路径
- **类型**：字符串（文件路径）
- **示例**：`storage_state.json`
- **默认值**：`storage_state.json`
- **备注**：保存登录状态，避免重复登录

#### OUTPUT_FILE（可选）
- **说明**：信号输出文件路径
- **类型**：字符串（文件路径）
- **示例**：`output/signals.json`
- **默认值**：`output/signals.json`
- **备注**：解析后的期权信号保存位置

### 💰 长桥证券配置

#### LONGPORT_MODE（必填）
- **说明**：账户模式
- **类型**：字符串
- **可选值**：
  - `paper`：模拟账户（推荐用于测试）
  - `real`：真实账户（实盘交易）
- **默认值**：`paper`
- **备注**：
  - 模拟账户：不会产生真实交易，用于测试
  - 真实账户：会产生真实交易，请谨慎使用

#### 模拟账户凭据（LONGPORT_MODE=paper 时需要）

##### LONGPORT_PAPER_APP_KEY（必填）
- **说明**：模拟账户 App Key
- **类型**：字符串
- **获取方式**：[长桥开放平台](https://open.longportapp.com/)
- **备注**：在长桥开放平台创建应用后获取

##### LONGPORT_PAPER_APP_SECRET（必填）
- **说明**：模拟账户 App Secret
- **类型**：字符串
- **获取方式**：[长桥开放平台](https://open.longportapp.com/)
- **备注**：敏感信息，请妥善保管

##### LONGPORT_PAPER_ACCESS_TOKEN（必填）
- **说明**：模拟账户 Access Token
- **类型**：字符串
- **获取方式**：[长桥开放平台](https://open.longportapp.com/)
- **备注**：
  - 完整的 JWT token（通常很长）
  - 请确保完整复制，不要截断

#### 真实账户凭据（LONGPORT_MODE=real 时需要）

##### LONGPORT_REAL_APP_KEY（必填）
##### LONGPORT_REAL_APP_SECRET（必填）
##### LONGPORT_REAL_ACCESS_TOKEN（必填）

⚠️ **警告**：真实账户配置与模拟账户类似，但会产生真实交易，请谨慎使用！

#### 通用配置

##### LONGPORT_REGION（可选）
- **说明**：API 接入点区域
- **类型**：字符串
- **可选值**：
  - `cn`：中国大陆（推荐）
  - `hk`：香港
- **默认值**：`cn`
- **备注**：建议中国大陆用户使用 `cn`

##### LONGPORT_ENABLE_OVERNIGHT（可选）
- **说明**：是否开启夜盘行情
- **类型**：布尔值
- **可选值**：`true`、`false`
- **默认值**：`false`
- **备注**：是否接收盘后交易数据

### 🛡️ 风险控制配置

#### LONGPORT_MAX_POSITION_RATIO（可选）
- **说明**：单个持仓不超过账户资金的比例
- **类型**：浮点数（0-1 之间）
- **示例**：`0.20`（20%）、`0.10`（10%）
- **默认值**：`0.20`
- **备注**：
  - `0.20` = 单个持仓不超过账户资金的 20%
  - 防止过度集中风险
  - 建议设置在 10% - 30% 之间

#### LONGPORT_MAX_DAILY_LOSS（可选）
- **说明**：单日最大亏损比例
- **类型**：浮点数（0-1 之间）
- **示例**：`0.05`（5%）、`0.10`（10%）
- **默认值**：`0.05`
- **备注**：
  - `0.05` = 单日亏损达到账户资金的 5% 时停止交易
  - 保护账户免受重大损失
  - 建议设置在 3% - 10% 之间

#### LONGPORT_MIN_ORDER_AMOUNT（可选）
- **说明**：最小下单金额（美元）
- **类型**：整数
- **示例**：`50`、`100`、`500`
- **默认值**：`100`
- **备注**：
  - 低于此金额的订单不会提交
  - 避免过小的交易
  - 根据账户大小调整

### ⚙️ 交易设置

#### LONGPORT_AUTO_TRADE（可选）
- **说明**：是否启用自动交易
- **类型**：布尔值
- **可选值**：
  - `true`：启用自动交易（自动下单）
  - `false`：仅监控模式（不下单，只记录信号）
- **默认值**：`false`
- **备注**：
  - 建议先使用 `false` 测试系统
  - 确认无误后再启用自动交易

#### LONGPORT_DRY_RUN（可选）
- **说明**：是否启用模拟模式（Dry Run）
- **类型**：布尔值
- **可选值**：
  - `true`：Dry Run 模式（不实际下单，仅打印日志）
  - `false`：正常模式（实际下单）
- **默认值**：`true`
- **备注**：
  - `true`：所有交易操作都是模拟的，不会真实提交
  - `false`：真实提交订单到长桥 API
  - 建议先用 `true` 测试，确认无误后改为 `false`

## 配置组合建议

### 🧪 测试环境（推荐新手）
```env
LONGPORT_MODE=paper
LONGPORT_AUTO_TRADE=false
LONGPORT_DRY_RUN=true
```
**效果**：模拟账户 + 仅监控 + Dry Run = 完全安全，不会有任何真实交易

### 🧩 开发调试
```env
LONGPORT_MODE=paper
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=true
HEADLESS=false
SLOW_MO=100
```
**效果**：可以看到浏览器操作，交易逻辑运行但不实际下单

### 🎯 模拟账户测试
```env
LONGPORT_MODE=paper
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false
```
**效果**：在模拟账户上真实测试交易逻辑

### 💸 生产环境（真实账户）
```env
LONGPORT_MODE=real
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false
HEADLESS=true
```
**效果**：真实账户 + 自动交易 + 后台运行

⚠️ **警告**：生产环境会产生真实交易，请确保：
1. 已在模拟账户充分测试
2. 理解所有风险控制参数
3. 设置合理的止损和仓位限制

## 配置验证

### 检查配置
```bash
# 测试解析器
python3 main.py --test

# 运行集成测试
PYTHONPATH=. python3 test/test_longport_integration.py
```

### 常见配置错误

#### 1. Token 格式错误
```
错误: token invalid
```
**解决**：确保 Access Token 完整复制，不要截断

#### 2. 凭据未配置
```
错误: 请设置 WHOP_EMAIL 和 WHOP_PASSWORD
```
**解决**：检查 `.env` 文件是否存在，配置项是否填写

#### 3. 账户模式错误
```
错误: 未找到对应的账户凭据
```
**解决**：检查 `LONGPORT_MODE` 与凭据配置是否匹配

## 安全建议

1. **不要提交 `.env` 到 Git**
   - 已自动添加到 `.gitignore`
   - 检查：`git status` 不应显示 `.env`

2. **定期更换 Token**
   - 建议每 90 天更换一次
   - 如果 Token 泄露，立即更换

3. **分离生产和测试配置**
   - 开发时使用 `.env.dev`
   - 生产时使用 `.env.prod`
   - 通过脚本切换

4. **备份配置**
   - 将 `.env` 备份到安全位置
   - 不要备份到公开的云存储

## 环境变量优先级

配置加载顺序（优先级从高到低）：

1. **系统环境变量**：`export WHOP_EMAIL=xxx`
2. **`.env` 文件**：项目根目录的 `.env` 文件
3. **默认值**：`config.py` 中定义的默认值

示例：
```bash
# .env 文件中
POLL_INTERVAL=2.0

# 运行时覆盖
POLL_INTERVAL=5.0 python3 main.py
```

## 相关文档

- [README.md](../README.md) - 项目说明
- [SETUP_WIZARD.md](./SETUP_WIZARD.md) - 设置向导
- [LONGPORT_INTEGRATION_GUIDE.md](./LONGPORT_INTEGRATION_GUIDE.md) - 长桥 API 指南

## 反馈

如有配置问题或建议，请提交 Issue 或 Pull Request。
