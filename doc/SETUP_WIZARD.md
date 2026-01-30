# 🚀 配置向导

## 当前状态

✅ Python 依赖已安装  
✅ .env 文件已创建  
⬜ 需要配置长桥 API 凭证  

---

## 下一步：配置长桥 API

### 选项 1：使用模拟账户（推荐新手）⭐

1. **获取模拟账户凭证**
   - 访问：https://open.longportapp.com
   - 登录后进入「个人中心」→「模拟交易」
   - 复制以下信息：
     - App Key
     - App Secret  
     - Access Token

2. **编辑 .env 文件**
   ```bash
   nano .env  # 或使用其他编辑器
   ```

3. **填入凭证**（找到长桥配置部分）
   ```env
   # 账户模式
   LONGPORT_MODE=paper
   
   # 模拟账户凭证
   LONGPORT_PAPER_APP_KEY=粘贴你的_APP_KEY
   LONGPORT_PAPER_APP_SECRET=粘贴你的_APP_SECRET
   LONGPORT_PAPER_ACCESS_TOKEN=粘贴你的_ACCESS_TOKEN
   
   # 交易设置
   LONGPORT_AUTO_TRADE=true
   LONGPORT_DRY_RUN=false
   ```

4. **保存并测试**
   ```bash
   python3 test_longport_integration.py
   ```

---

### 选项 2：先跳过长桥配置，只测试信号解析

如果您暂时不想配置长桥 API，可以：

```bash
# 只测试信号解析功能
python3 main.py --test
```

这会测试期权指令解析器，不需要 API 凭证。

---

### 选项 3：使用真实账户（需谨慎）⚠️

**警告**：建议先在模拟账户测试至少 2-4 周！

配置类似选项 1，但使用：
```env
LONGPORT_MODE=real
LONGPORT_REAL_APP_KEY=...
LONGPORT_REAL_APP_SECRET=...
LONGPORT_REAL_ACCESS_TOKEN=...
```

---

## 快速测试（无需长桥 API）

如果您想先看看系统如何工作，可以：

```bash
# 测试信号解析
python3 main.py --test
```

这会显示如何解析各种期权交易信号，例如：
- "INTC - $48 CALLS 本周 $1.2"
- "止损 0.95"
- "1.75出三分之一"

---

## 遇到问题？

### Q: 没有长桥账户怎么办？
A: 
1. 先测试信号解析：`python3 main.py --test`
2. 下载 LongPort App 开户（模拟账户免费）
3. 申请 OpenAPI 权限

### Q: 可以使用其他券商吗？
A: 当前仅集成了长桥，但您可以：
1. 只使用信号监控和解析功能
2. 手动执行交易
3. 或自己集成其他券商 API

### Q: 如何查看已配置的凭证？
A: 
```bash
# 检查（不会显示完整内容）
grep LONGPORT .env | grep -v "^#"
```

---

## 配置完成后

运行完整测试：
```bash
python3 test_longport_integration.py
```

如果看到类似输出，说明配置成功：
```
✅ 配置加载成功！
✅ 账户信息获取成功
✅ 期权代码转换测试完成
...
✅ 所有测试完成！
```

---

## 需要帮助？

- 📖 详细指南：[USAGE_GUIDE.md](./USAGE_GUIDE.md)
- ⚡ 快速开始：[doc/QUICKSTART_LONGPORT.md](./doc/QUICKSTART_LONGPORT.md)
- ✅ 检查清单：[CHECKLIST.md](./CHECKLIST.md)

**现在就开始配置吧！** 🎯
