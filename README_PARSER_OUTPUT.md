# Parser输出控制

## 概述

Parser层提供了清晰的表格式输出，展示每条消息的解析结果。你可以通过环境变量控制是否显示这些输出。

## 输出格式

每个解析指令使用独立的表格框展示，类似订单卡片：

```
                                       #4 BUY - LYFT                             
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段               ┃ 值                                                  ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 时间               │ Jan 12, 2026 11:40 PM                              │
│ 期权代码           │ LYFT                                               │
│ 指令类型           │ BUY                                                │
│ 状态               │ ✅                                                  │
│ 期权类型           │ CALL                                               │
│ 行权价             │ $19.5                                              │
│ 到期日             │ 1/23                                               │
│ 价格               │ $0.58                                              │
│ 仓位大小           │ 小仓位                                              │
│ 原始消息           │ LYFT 19.5c 1/23 0.58-0.62 日内交易小仓位            │
└──────────────────┴────────────────────────────────────────────────────┘

                                       #6 SELL - 未识别                             
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 字段               ┃ 值                                                  ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 时间               │ Jan 12, 2026 11:44 PM                              │
│ 期权代码           │ 未识别                                              │
│ 指令类型           │ SELL                                               │
│ 状态               │ ✅                                                  │
│ 价格               │ $0.7                                               │
│ 卖出数量           │ 1/2                                                │
│ 原始消息           │ 0.7出一半 lyft期权 进入价内                          │
└──────────────────┴────────────────────────────────────────────────────┘
```

### 不同指令类型的字段

**BUY (买入)**:
- 期权类型 (CALL/PUT)
- 行权价
- 到期日
- 价格 / 价格区间
- 仓位大小

**SELL (卖出)**:
- 价格 / 价格区间
- 卖出数量 (1/3, 1/2, 30%, 100等)

**CLOSE (清仓)**:
- 价格 / 价格区间
- 数量: 全部

**MODIFY (修改)**:
- 止损价格 / 止损区间
- 止盈价格 / 止盈区间

## 环境变量控制

### SHOW_PARSER_OUTPUT

控制是否显示Parser层的解析结果输出。

**默认值**: `true`  
**可选值**: `true`, `false`, `1`, `0`, `yes`, `no`

### 使用方法

#### 方式1：命令行临时设置

```bash
# 显示Parser输出（默认）
python3 analyze_local_messages.py debug/page.html

# 隐藏Parser输出
SHOW_PARSER_OUTPUT=false python3 analyze_local_messages.py debug/page.html
```

#### 方式2：导出环境变量

```bash
# 设置环境变量
export SHOW_PARSER_OUTPUT=false

# 运行脚本（将使用环境变量）
python3 analyze_local_messages.py debug/page.html
```

#### 方式3：使用.env文件

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 编辑.env文件
vim .env

# 3. 设置SHOW_PARSER_OUTPUT=false

# 4. 运行脚本（需要python-dotenv库）
python3 analyze_local_messages.py debug/page.html
```

## 使用场景

### 场景1：开发调试
显示详细的Parser解析结果，用于调试和验证解析逻辑。

```bash
# 显示完整解析过程
SHOW_PARSER_OUTPUT=true python3 analyze_local_messages.py data.html
```

### 场景2：生产环境 / Broker下单
隐藏Parser输出，避免与broker下单信息冲突，保持命令行输出清晰。

```bash
# 只显示broker下单信息
SHOW_PARSER_OUTPUT=false python3 broker_trade.py
```

### 场景3：日志分析
隐藏实时输出，将解析结果写入日志文件。

```bash
# 静默模式，输出到日志
SHOW_PARSER_OUTPUT=false python3 analyze_local_messages.py data.html > parser.log 2>&1
```

## 输出列说明

| 列名 | 说明 | 示例 |
|------|------|------|
| 时间 | 消息发送时间 | Jan 12, 2026 11:40 PM |
| 代码 | 期权代码（ticker） | LYFT, CMCSA |
| 状态 | 解析状态 | ✅成功 / ❌失败 |
| 类型 | 指令类型 | BUY, SELL, CLOSE, MODIFY |
| 详情 | 完整的指令内容 | [买入] LYFT $19.5 CALL @ $0.58 (1/23) 小仓位 |

## 统计信息

表格底部会显示解析统计：

```
--------------------------------------------------------------------------------------------------------------------------------------------
解析完成: 总消息数=91, 成功=64, 失败=27, 成功率=70.3%
============================================================================================================================================
```

## 故障排查

### 问题：设置环境变量后仍显示输出

**检查**：
```bash
# 确认环境变量值
echo $SHOW_PARSER_OUTPUT

# 确保使用小写的true/false
SHOW_PARSER_OUTPUT=false python3 script.py  # ✅ 正确
SHOW_PARSER_OUTPUT=False python3 script.py  # ✅ 正确
SHOW_PARSER_OUTPUT=FALSE python3 script.py  # ✅ 正确
```

### 问题：.env文件不生效

**.env文件需要配合python-dotenv库使用**：

```bash
# 安装依赖
pip install python-dotenv

# 在脚本中加载.env
from dotenv import load_dotenv
load_dotenv()
```

**或者手动导出环境变量**：
```bash
export $(cat .env | xargs)
python3 script.py
```

## 相关文档

- `PARSER_DATA_MODEL.md` - Parser数据模型规范
- `CHANGELOG.md` - 变更日志
- `.env.example` - 环境变量配置模板
