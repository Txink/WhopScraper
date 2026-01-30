# 更新日志

## [2.1.0] - 2026-01-30

### 新增功能

#### 统一配置管理
- 所有配置项统一在 `.env` 文件中设置
- 新增 `doc/CONFIGURATION.md` 配置说明文档
- 详细说明每个配置项的作用、类型、默认值
- 提供多种使用场景的配置组合建议
- 新增 `LOGIN_URL` 配置项支持
- 新增 `check_config.py` 配置检查工具
  - 自动验证配置文件
  - 检查必填项
  - 评估风险参数合理性
  - 提供交易模式建议

#### 期权过期时间校验
- 在期权代码转换时自动检查到期日期
- 如果期权已过期，系统将自动拦截并跳过该指令
- 支持多种日期格式：`1/31`、`01/31`、`20260131`、`2026-01-31`、`本周`
- 提供详细的错误日志，包含过期日期和当前日期信息

### 修复问题

1. **Token 无效问题** - 更新了完整的 access token 配置
2. **日期计算错误** - 修复了 `timedelta` 的使用，正确处理跨月份日期
3. **负余额风险检查** - 添加了模拟账户负余额的特殊处理逻辑
4. **Dry Run 模式配置** - 优化了 Dry Run 模式的行为
   - 查询操作（获取持仓、订单）不受 Dry Run 影响
   - 交易操作（下单、撤单）受 Dry Run 控制
5. **持仓获取错误** - 修复了 `StockPositionsResponse` 的正确访问方式

### 改进

#### 文档结构优化
- 所有文档统一放在 `doc/` 目录
- 所有测试统一放在 `test/` 目录
- 新增 `doc/README.md` - 文档导航
- 新增 `test/README.md` - 测试说明
- 新增 `PROJECT_STRUCTURE.md` - 项目结构说明
- 新增 `run_all_tests.sh` - 一键运行所有测试
- 更新主 README.md，明确目录结构

#### 配置管理优化
- 所有配置项统一在 `.env` 文件中管理
- 新增 `doc/CONFIGURATION.md` - 详细配置说明
- 更新 `.env.example` - 完善配置模板
- 更新 `config.py` - 支持更多环境变量

#### 功能增强
- 更新 README.md，添加期权过期校验说明
- 新增 `doc/OPTION_EXPIRY_CHECK.md` 详细文档
- 新增测试文件：
  - `test/test_option_expiry.py` - 基础功能测试
  - `test/test_expiry_integration.py` - 集成测试

### 技术细节

#### 期权过期检查实现

```python
# broker/longport_broker.py
def convert_to_longport_symbol(ticker, option_type, strike, expiry):
    # 解析到期日
    expiry_date = datetime(year, month, day)
    
    # 检查是否过期
    expiry_end_of_day = expiry_date.replace(hour=23, minute=59, second=59)
    if now > expiry_end_of_day:
        raise ValueError(f"期权已过期: 到期日 {expiry_date} 早于当前日期 {now}")
    
    return symbol
```

#### 异常处理

```python
# main.py
def _handle_open_position(instruction):
    try:
        symbol = convert_to_longport_symbol(...)
    except ValueError as e:
        logger.error(f"❌ 期权代码转换失败: {e}")
        logger.warning(f"⚠️  跳过开仓指令 - {instruction.raw_message}")
        return  # 不执行后续下单操作
```

### 测试覆盖

所有测试通过：
- ✅ 配置加载测试（7个测试项）
- ✅ 基础功能测试（5个测试场景）
- ✅ 集成测试（3个实际场景）
- ✅ 长桥API集成测试（7个测试项）

### 文档更新

- [x] README.md - 添加功能特性说明、目录结构、配置说明
- [x] doc/README.md - 文档导航
- [x] doc/CONFIGURATION.md - 配置说明文档（新增）
- [x] doc/OPTION_EXPIRY_CHECK.md - 期权过期校验文档
- [x] test/README.md - 测试说明文档
- [x] PROJECT_STRUCTURE.md - 项目结构说明（新增）
- [x] CHANGELOG.md - 更新日志

### 向后兼容性

完全向后兼容，不影响现有功能。

---

## [2.0.0] - 2026-01-28

### 主要功能
- 长桥证券 API 集成
- 自动交易系统
- 持仓管理
- 风险控制
- Dry Run 模式

---

## [1.0.0] - 2026-01-20

### 初始版本
- Whop 页面监控
- 期权指令解析
- 样本管理系统
