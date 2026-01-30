# Whop 登录和消息抓取指南

本指南介绍如何使用提供的脚本来登录 Whop、保存 Cookie、并抓取页面消息。

## 📋 目录

- [快速开始](#快速开始)
- [工具说明](#工具说明)
- [详细步骤](#详细步骤)
- [常见问题](#常见问题)
- [高级用法](#高级用法)

## 🚀 快速开始

### 步骤 1: 首次登录并保存 Cookie

```bash
python3 whop_login.py
```

这个命令会：
1. 打开浏览器访问 Whop 登录页面
2. 等待您手动完成登录
3. 保存登录状态到 `storage_state.json`

### 步骤 2: 测试登录状态（可选）

```bash
python3 whop_login.py --test
```

验证保存的 Cookie 是否有效。

### 步骤 3: 开始抓取消息

```bash
python3 whop_scraper_simple.py --url "https://whop.com/your-page-url/"
```

使用保存的 Cookie 自动登录并抓取消息。

## 🛠️ 工具说明

### 1. whop_login.py - 登录助手

**功能**：帮助您手动登录 Whop 并保存登录状态（Cookie）

**主要特点**：
- ✅ 打开浏览器供您手动登录
- ✅ 保存完整的登录状态（Cookies、LocalStorage、SessionStorage）
- ✅ 测试登录状态是否有效
- ✅ 支持自定义 URL 和存储文件

**使用方法**：

```bash
# 基本用法 - 登录并保存 Cookie
python3 whop_login.py

# 测试已保存的登录状态
python3 whop_login.py --test

# 指定自定义 Whop URL
python3 whop_login.py --url "https://whop.com/custom-url/"

# 使用自定义 Cookie 文件名
python3 whop_login.py --storage "my_cookies.json"

# 测试特定页面
python3 whop_login.py --test --test-url "https://whop.com/your-page/"
```

### 2. whop_scraper_simple.py - 简单消息抓取器

**功能**：使用保存的 Cookie 自动登录并抓取 Whop 页面消息

**主要特点**：
- ✅ 自动使用保存的 Cookie 登录
- ✅ 实时监控页面消息
- ✅ 自动去重（不重复显示相同消息）
- ✅ 支持自定义监控时长
- ✅ 支持无头模式运行

**使用方法**：

```bash
# 基本用法 - 监控 30 秒
python3 whop_scraper_simple.py --url "https://whop.com/your-page/"

# 监控 60 秒
python3 whop_scraper_simple.py --url "https://whop.com/your-page/" --duration 60

# 使用无头模式（后台运行，不显示浏览器窗口）
python3 whop_scraper_simple.py --url "https://whop.com/your-page/" --headless

# 使用自定义 Cookie 文件
python3 whop_scraper_simple.py --url "https://whop.com/your-page/" --storage "my_cookies.json"

# 完整示例
python3 whop_scraper_simple.py \
  --url "https://whop.com/your-page/" \
  --duration 120 \
  --headless \
  --storage "storage_state.json"
```

## 📝 详细步骤

### 完整流程示例

#### 1. 首次使用 - 保存登录状态

```bash
# 运行登录助手
python3 whop_login.py
```

**操作步骤**：
1. 脚本会自动打开浏览器并访问 Whop 登录页面
2. 在浏览器中输入您的邮箱和密码
3. 点击登录按钮
4. 等待页面跳转到主页，确认登录成功
5. 返回终端，按回车键继续
6. 脚本会自动保存登录状态到 `storage_state.json`

**预期输出**：
```
============================================================
Whop 登录助手
============================================================
即将打开浏览器访问: https://whop.com/login/
请在浏览器中手动完成登录操作...
登录完成后，请返回终端并按回车键继续
============================================================

正在访问 https://whop.com/login/...

✅ 浏览器已打开
📝 请在浏览器中完成以下操作：
   1. 输入您的邮箱和密码
   2. 点击登录按钮
   3. 等待登录成功并跳转到主页
   4. 确认您已经成功登录后

👇 然后返回终端按回车键继续...

正在保存登录状态...
✅ 登录状态已保存到: storage_state.json

📊 已保存的信息包括:
   - Cookies
   - LocalStorage
   - SessionStorage

当前页面 URL: https://whop.com/...

正在关闭浏览器...

============================================================
✅ 完成！
============================================================
Cookie 已保存，下次运行时将自动使用 storage_state.json
您可以运行 main.py 开始自动监控和抓取
============================================================
```

#### 2. 验证登录状态（可选但推荐）

```bash
# 测试 Cookie 是否有效
python3 whop_login.py --test
```

**预期输出**：
```
============================================================
测试登录状态
============================================================
使用 cookie 文件: storage_state.json
测试 URL: https://whop.com/login/
============================================================

正在访问测试页面...
当前 URL: https://whop.com/...

✅ 登录状态有效！
   您可以使用 main.py 开始监控

浏览器将在 5 秒后关闭...
```

#### 3. 开始抓取消息

```bash
# 抓取指定页面的消息
python3 whop_scraper_simple.py --url "https://whop.com/joined/your-workspace/messages/"
```

**预期输出**：
```
============================================================
Whop 消息抓取器
============================================================
目标 URL: https://whop.com/joined/your-workspace/messages/
Cookie 文件: storage_state.json
监控时长: 30 秒
============================================================

加载已保存的登录状态...

正在访问目标页面...
当前 URL: https://whop.com/joined/your-workspace/messages/
✅ 已成功进入页面

============================================================
开始抓取消息...
============================================================

[10:30:15] 消息 #1
ID: abc123def456
内容:
AAPL $150 CALLS 本周 $2.5
------------------------------------------------------------

[10:30:17] 消息 #2
ID: xyz789uvw012
内容:
止损 1.8
------------------------------------------------------------

============================================================
✅ 抓取完成！共发现 2 条消息
============================================================
```

## ❓ 常见问题

### Q1: Cookie 文件在哪里？

**A:** 默认保存在项目根目录下的 `storage_state.json` 文件中。

```bash
# 查看 Cookie 文件
ls -la storage_state.json

# 查看文件内容（JSON 格式）
cat storage_state.json
```

### Q2: Cookie 会过期吗？

**A:** 是的，Cookie 会在一段时间后过期（通常是几天到几周）。

**解决方法**：
```bash
# 重新登录并保存 Cookie
python3 whop_login.py
```

**如何判断 Cookie 是否过期**：
- 运行抓取脚本时，如果被重定向到登录页面，说明 Cookie 已过期
- 使用测试命令：`python3 whop_login.py --test`

### Q3: 如何找到要抓取的页面 URL？

**A:** 
1. 在浏览器中手动登录 Whop
2. 导航到您想要抓取的页面（如消息页面、讨论区等）
3. 复制浏览器地址栏中的完整 URL
4. 使用该 URL 运行抓取脚本

**示例 URL 格式**：
```
https://whop.com/joined/workspace-name/messages/
https://whop.com/joined/workspace-name/discussions/
https://whop.com/joined/workspace-name/app/
```

### Q4: 抓取器找不到消息怎么办？

**A:** 脚本会尝试多种常见的消息选择器。如果找不到消息：

1. **使用非无头模式运行**（可以看到浏览器）：
   ```bash
   python3 whop_scraper_simple.py --url "your-url"
   # 不要加 --headless 参数
   ```

2. **检查页面是否正确加载**：
   - 观察浏览器窗口，确认页面内容正常显示
   - 确认没有被重定向到登录页面

3. **联系我或查看项目的其他脚本**：
   - 项目中的 `scraper/monitor.py` 提供了更复杂的消息提取逻辑
   - 可以参考 `main.py` 中的完整实现

### Q5: 如何在后台运行抓取器？

**A:** 使用无头模式和 nohup 命令：

```bash
# 使用无头模式
nohup python3 whop_scraper_simple.py \
  --url "your-url" \
  --headless \
  --duration 3600 \
  > scraper.log 2>&1 &

# 查看日志
tail -f scraper.log

# 查看运行中的进程
ps aux | grep whop_scraper

# 停止进程
kill <进程ID>
```

### Q6: 可以同时监控多个页面吗？

**A:** 可以！使用相同的 Cookie 文件启动多个抓取器实例：

```bash
# 终端 1 - 监控页面 A
python3 whop_scraper_simple.py --url "url-A" --duration 600 &

# 终端 2 - 监控页面 B
python3 whop_scraper_simple.py --url "url-B" --duration 600 &

# 终端 3 - 监控页面 C
python3 whop_scraper_simple.py --url "url-C" --duration 600 &
```

### Q7: storage_state.json 安全吗？

**A:** 该文件包含您的登录凭证，需要妥善保管：

**安全建议**：
- ✅ 不要将 `storage_state.json` 提交到 Git（已在 `.gitignore` 中）
- ✅ 不要分享该文件给他人
- ✅ 定期更换密码并重新保存 Cookie
- ✅ 使用完毕后可以删除该文件

**删除 Cookie**：
```bash
rm storage_state.json
```

## 🔧 高级用法

### 1. 使用不同的 Cookie 文件管理多个账号

```bash
# 账号 1 - 登录并保存
python3 whop_login.py --storage "account1_cookies.json"

# 账号 2 - 登录并保存
python3 whop_login.py --storage "account2_cookies.json"

# 使用账号 1 抓取
python3 whop_scraper_simple.py \
  --url "url" \
  --storage "account1_cookies.json"

# 使用账号 2 抓取
python3 whop_scraper_simple.py \
  --url "url" \
  --storage "account2_cookies.json"
```

### 2. 定时任务 - 自动抓取

使用 cron 定时运行抓取器：

```bash
# 编辑 crontab
crontab -e

# 添加定时任务（每小时运行一次，抓取 5 分钟）
0 * * * * cd /path/to/playwright && python3 whop_scraper_simple.py --url "your-url" --duration 300 --headless >> /path/to/logs/scraper.log 2>&1
```

### 3. 集成到主项目

简单抓取器主要用于测试和快速验证。对于生产环境，建议使用项目中的完整系统：

```bash
# 使用完整的监控和交易系统
python3 main.py
```

完整系统包含：
- 自动期权解析
- 风险控制
- 持仓管理
- 自动交易
- 详细日志

查看 [README.md](./README.md) 了解完整系统的使用方法。

### 4. 自定义消息提取逻辑

如果默认的消息选择器不适用，可以修改 `whop_scraper_simple.py`：

```python
# 在 _extract_messages 方法中添加自定义选择器
message_selectors = [
    # 添加您自己的选择器
    'your-custom-selector',
    '[data-your-attribute]',
    # ...其他选择器
]
```

**如何找到正确的选择器**：
1. 在浏览器中打开目标页面
2. 右键点击消息 → 检查元素
3. 查看消息的 HTML 结构和 class/id
4. 将找到的选择器添加到脚本中

## 📚 相关文档

- [项目 README](./README.md) - 完整项目说明
- [配置指南](./doc/CONFIGURATION.md) - 环境变量配置
- [使用指南](./doc/USAGE_GUIDE.md) - 完整使用教程
- [长桥集成指南](./doc/LONGPORT_INTEGRATION_GUIDE.md) - 自动交易配置

## 💡 提示

1. **首次使用**：建议先使用非无头模式，观察浏览器行为
2. **Cookie 管理**：定期测试 Cookie 是否有效（`--test` 参数）
3. **调试**：遇到问题时去掉 `--headless` 参数，观察浏览器窗口
4. **监控时长**：根据需要调整 `--duration` 参数（单位：秒）
5. **日志记录**：使用 `>` 重定向输出到日志文件

## 🎯 总结

| 任务 | 命令 | 说明 |
|------|------|------|
| 保存登录 | `python3 whop_login.py` | 打开浏览器，手动登录，保存 Cookie |
| 测试登录 | `python3 whop_login.py --test` | 验证 Cookie 是否有效 |
| 抓取消息 | `python3 whop_scraper_simple.py --url "URL"` | 使用 Cookie 自动登录并抓取消息 |
| 后台运行 | 加上 `--headless` | 无头模式，不显示浏览器窗口 |
| 自定义时长 | 加上 `--duration 秒数` | 设置监控持续时间 |

有任何问题，请参考项目文档或提交 Issue！
