# 完整使用指南

本文档提供完整的使用流程，从配置到运行，再到监控和管理。

## 目录

- [初次设置](#初次设置)
- [日常使用](#日常使用)
- [监控和管理](#监控和管理)
- [故障排除](#故障排除)

---

## 初次设置

### 1. 安装依赖

```bash
# 克隆或下载项目
cd playwright

# 安装 Python 依赖
pip3 install -r requirements.txt

# 安装 Playwright 浏览器
python3 -m playwright install chromium
```

### 2. 配置 Whop 凭据

```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件
nano .env  # 或使用其他编辑器
```

填写 Whop 登录信息：

```env
WHOP_EMAIL=your_email@example.com
WHOP_PASSWORD=your_password
```

### 3. 配置长桥 API（模拟账户）

获取模拟账户 API 凭证：
1. 访问 [LongPort OpenAPI](https://open.longportapp.com)
2. 登录后进入「个人中心」→「模拟交易」
3. 获取 App Key、App Secret、Access Token

在 `.env` 中配置：

```env
# 使用模拟账户
LONGPORT_MODE=paper

# 模拟账户凭证
LONGPORT_PAPER_APP_KEY=你的_APP_KEY
LONGPORT_PAPER_APP_SECRET=你的_APP_SECRET
LONGPORT_PAPER_ACCESS_TOKEN=你的_ACCESS_TOKEN

# 区域设置
LONGPORT_REGION=cn

# 交易设置（模拟账户可以放心启用）
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=false
```

### 4. 测试配置

```bash
# 测试长桥连接
python3 test_longport_integration.py

# 测试持仓管理
python3 test_position_management.py

# 测试解析器
python3 main.py --test
```

如果所有测试通过，就可以开始使用了！

---

## 日常使用

### 启动系统

#### 方式 1：命令行启动

```bash
python3 main.py
```

#### 方式 2：后台运行

```bash
# 使用 nohup 后台运行
nohup python3 main.py > output.log 2>&1 &

# 查看输出
tail -f output.log

# 停止程序
ps aux | grep main.py
kill <PID>
```

#### 方式 3：使用 screen（推荐）

```bash
# 创建 screen 会话
screen -S trading

# 在 screen 中运行
python3 main.py

# 断开（保持运行）：Ctrl+A 然后 D

# 重新连接
screen -r trading

# 停止：在 screen 中按 Ctrl+C
```

### 系统启动流程

程序启动后会依次执行：

```
1. 初始化长桥交易接口
   ├─ 加载配置（模拟/真实账户）
   ├─ 连接API
   └─ 验证账户

2. 初始化持仓管理器
   ├─ 加载历史持仓
   └─ 计算当前盈亏

3. 启动风险控制器
   ├─ 自动止损止盈监控
   └─ 移动止损

4. 启动浏览器
   ├─ 自动登录 Whop
   └─ 导航到目标页面

5. 开始监控交易信号
   └─ 自动解析和执行
```

---

## 监控和管理

### 查看持仓

在程序运行时，会自动显示持仓摘要。也可以运行：

```python
from broker import PositionManager

manager = PositionManager()
manager.print_summary()
```

输出示例：

```
================================================================================
持仓摘要
================================================================================
持仓数量: 3
总市值:   $8,500.00
总盈亏:   $1,200.00
--------------------------------------------------------------------------------
🟢 AAPL250131C00150000.US
   数量: 2 张 | 成本: $2.50 | 现价: $3.20
   盈亏: $140.00 (+28.00%)
   止损: $2.00

🟢 NVDA250214C00900000.US
   数量: 3 张 | 成本: $5.50 | 现价: $6.80
   盈亏: $390.00 (+23.64%)
   止盈: $7.50

🔴 TSLA250207P00250000.US
   数量: 1 张 | 成本: $3.00 | 现价: $2.40
   盈亏: -$60.00 (-20.00%)
   止损: $2.30

================================================================================
```

### 查看订单

```python
from broker import load_longport_config, LongPortBroker

config = load_longport_config()
broker = LongPortBroker(config)

# 获取当日订单
orders = broker.get_today_orders()
for order in orders:
    print(f"{order['symbol']} {order['side']} {order['quantity']} @ {order['price']}")
```

### 手动设置止损止盈

```python
from broker import PositionManager
from broker.risk_controller import RiskController

manager = PositionManager()
risk_controller = RiskController(broker, manager)

# 按百分比设置止损止盈
risk_controller.set_stop_loss_by_percentage("AAPL250131C00150000.US", -15)  # 止损 -15%
risk_controller.set_take_profit_by_percentage("AAPL250131C00150000.US", 50)  # 止盈 +50%
```

### 手动平仓

```python
# 平仓部分持仓
order = broker.submit_option_order(
    symbol="AAPL250131C00150000.US",
    side="SELL",
    quantity=1,  # 卖出 1 张
    price=3.20,
    order_type="LIMIT"
)
```

### 查看日志

实时日志：

```bash
tail -f logs/trading.log
```

查看特定内容：

```bash
# 查看所有交易
grep "订单已提交" logs/trading.log

# 查看止损触发
grep "止损已触发" logs/trading.log

# 查看错误
grep "ERROR" logs/trading.log
```

---

## 故障排除

### 问题 1：连接长桥 API 失败

**症状**：

```
❌ 交易组件初始化失败: ConnectionError
```

**解决方案**：

1. 检查网络连接
2. 确认 `LONGPORT_REGION=cn`（中国大陆用户）
3. 验证 API 凭证是否正确
4. 检查 API 权限是否开通

### 问题 2：登录 Whop 失败

**症状**：

```
登录失败，请检查凭据是否正确
```

**解决方案**：

1. 确认 `.env` 中的邮箱密码正确
2. 尝试手动登录网页版验证账号状态
3. 检查是否需要验证码（目前不支持）
4. 删除 `storage_state.json` 重新登录

### 问题 3：订单被拒绝

**症状**：

```
❌ 订单金额过小: $50.00 < $100.00
```

**解决方案**：

调整风险控制参数：

```env
LONGPORT_MIN_ORDER_AMOUNT=50  # 降低最小下单金额
```

或调整仓位大小配置。

### 问题 4：无法解析信号

**症状**：

```
解析结果: 未能识别
```

**解决方案**：

1. 查看未解析的样本：
   ```bash
   python3 -m samples.sample_manager list --unparsed
   ```

2. 手动添加解析规则到 `parser/option_parser.py`

3. 重新测试：
   ```bash
   python3 main.py --test
   ```

### 问题 5：风险控制器未启动

**症状**：

```
ℹ️  自动交易未启用，风险控制系统待命
```

**解决方案**：

在 `.env` 中启用自动交易：

```env
LONGPORT_AUTO_TRADE=true
```

### 问题 6：持仓不更新

**解决方案**：

手动同步持仓：

```python
from broker import PositionManager, LongPortBroker, load_longport_config

config = load_longport_config()
broker = LongPortBroker(config)
manager = PositionManager()

# 从券商同步
broker_positions = broker.get_positions()
manager.sync_positions_from_broker(broker_positions)

# 查看结果
manager.print_summary()
```

---

## 高级功能

### 自定义风险参数

在 `.env` 中调整：

```env
# 仓位控制
LONGPORT_MAX_POSITION_RATIO=0.15  # 单仓位最大 15%

# 止损控制
LONGPORT_MAX_DAILY_LOSS=0.05  # 单日最大亏损 5%

# 最小下单
LONGPORT_MIN_ORDER_AMOUNT=100  # 最小 $100
```

### 切换到真实账户

⚠️ **警告**：确保在模拟账户测试至少 2-4 周！

1. 获取真实账户 API 凭证
2. 在 `.env` 中配置：

```env
# 切换到真实账户
LONGPORT_MODE=real

# 真实账户凭证
LONGPORT_REAL_APP_KEY=你的_APP_KEY
LONGPORT_REAL_APP_SECRET=你的_APP_SECRET
LONGPORT_REAL_ACCESS_TOKEN=你的_ACCESS_TOKEN

# 保守的风险参数
LONGPORT_MAX_POSITION_RATIO=0.10
LONGPORT_MAX_DAILY_LOSS=0.03
```

3. 重新启动程序

### 开启移动止损

移动止损会自动跟随价格上涨，保护盈利：

```python
from broker.risk_controller import AutoTrailingStopLoss

# 在 main.py 的 _init_trading_components 中
# 已经默认启用了 10% 回撤的移动止损
```

调整回撤百分比：

```python
self.auto_trailing = AutoTrailingStopLoss(
    risk_controller=self.risk_controller,
    trailing_pct=15.0,  # 改为 15% 回撤
    check_interval=60
)
```

---

## 安全提示

1. 🔐 **保护凭据**：永远不要将 `.env` 文件提交到 Git
2. 🧪 **先测试**：在模拟账户充分测试后再用真实账户
3. 💰 **小额开始**：真实交易从小仓位开始
4. 📉 **设置止损**：每笔交易都应该有止损
5. 👀 **定期检查**：至少每天检查一次账户和持仓
6. 📱 **设置警报**：重要操作配置通知（邮件/短信）
7. 🔄 **定期备份**：备份 `data/positions.json` 和日志

---

## 性能优化

### 减少 API 调用

```env
# 增加检查间隔（秒）
LONGPORT_CHECK_INTERVAL=60  # 默认 30
```

### 减少日志

在 `main.py` 中调整日志级别：

```python
logging.basicConfig(level=logging.WARNING)  # 只显示警告和错误
```

---

## 支持和反馈

- 📖 完整文档：[LONGPORT_INTEGRATION_GUIDE.md](./LONGPORT_INTEGRATION_GUIDE.md)
- 🚀 快速开始：[QUICKSTART_LONGPORT.md](./QUICKSTART_LONGPORT.md)
- 🐛 问题反馈：[GitHub Issues](https://github.com/your-repo/issues)
- 💬 技术讨论：[长桥 OpenAPI 社区](https://github.com/longportapp/openapi/issues)

---

**祝交易顺利！** 📈
