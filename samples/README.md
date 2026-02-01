本数据集说明

本目录包含用于测试和验证解析器的样本数据集。

## 目录结构

```
samples/data/
├── option_signals/      # 期权信号数据集
│   ├── open_position.json   # 开仓信号
│   ├── stop_loss.json       # 止损信号
│   └── take_profit.json     # 止盈信号
├── stock_signals/       # 正股信号数据集
│   ├── buy.json             # 买入信号
│   └── sell.json            # 卖出信号
└── README.md            # 本文件
```

## 数据集格式

每个JSON文件包含以下结构：

```json
{
  "description": "数据集描述",
  "category": "数据集分类",
  "samples": [
    {
      "message": "原始消息文本",
      "expected": {
        "ticker": "股票代码",
        "price": 123.45,
        ...其他预期字段
      }
    }
  ]
}
```

## 使用方式

### 1. 添加新样本

手动编辑对应的JSON文件，在 `samples` 数组中添加新条目：

```json
{
  "message": "AAPL $200 CALL $5.0",
  "expected": {
    "ticker": "AAPL",
    "strike": 200.0,
    "option_type": "CALL",
    "price": 5.0
  }
}
```

### 2. 测试解析器覆盖率

使用数据集管理器测试解析器：

```bash
# 测试期权解析器
python3 -m samples.dataset_manager test option

# 测试正股解析器
python3 -m samples.dataset_manager test stock

# 测试所有解析器
python3 -m samples.dataset_manager test all
```

### 3. 生成测试报告

```bash
python3 -m samples.dataset_manager report
```

## 数据来源

- 初始样本：从项目开发过程中收集的真实消息
- 自动收集：运行时自动收集的消息（通过 sample_manager）
- 手动添加：开发者根据新的消息格式手动添加

## 维护建议

1. **定期检查**：当解析失败时，将失败的消息添加到数据集
2. **格式规范**：确保 expected 字段包含所有关键信息
3. **分类清晰**：将样本放入正确的分类文件
4. **版本控制**：数据集文件纳入 Git 版本控制

## 注意事项

- 数据集仅用于测试，不包含真实交易数据
- 价格和股票代码为示例值
- 定期更新数据集以覆盖新的消息格式
