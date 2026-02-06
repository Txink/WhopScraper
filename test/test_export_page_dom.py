#!/usr/bin/env python3
"""
导出页面 DOM、截图、结构分析和消息数据，供本地分析和调试。

功能：
1. 导出完整 HTML 页面内容（debug/page_*.html）
2. 截取全屏截图（debug/page_*.png）
3. 分析页面结构（debug/analysis_*.txt）
4. 提取并导出消息数据到 data/origin_message.json
   - 包含完整的消息组、引用、历史记录
   - 自动去重（按 domID）
   - 按时间排序
   - 增量更新（不覆盖已有消息）
5. 显示详细的消息统计信息

运行: python test/test_export_page_dom.py  或  python -m test.test_export_page_dom
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from scraper.browser import BrowserManager
from scraper.message_extractor import EnhancedMessageExtractor


async def export_page_dom():
    """导出页面DOM和截图供本地分析"""
    print("\n" + "=" * 60)
    print("导出页面DOM和截图")
    print("=" * 60 + "\n")

    # 验证配置
    if not Config.validate():
        print("❌ 配置验证失败")
        return

    print("✅ 配置验证通过\n")

    # 创建输出目录
    output_dir = "debug"
    os.makedirs(output_dir, exist_ok=True)

    # 创建浏览器管理器
    browser = BrowserManager(
        headless=False,  # 使用非无头模式便于查看
        slow_mo=Config.SLOW_MO,
        storage_state_path=Config.STORAGE_STATE_PATH
    )

    try:
        # 启动浏览器
        print("🚀 正在启动浏览器...")
        page = await browser.start()
        print("✅ 浏览器已启动\n")

        # 获取所有需要监控的页面配置
        page_configs = Config.get_all_pages()

        if not page_configs:
            print("❌ 没有配置任何监控页面")
            return

        # 检查登录状态
        first_url = page_configs[1][0]
        print("🔐 正在检查登录状态...")
        if not await browser.is_logged_in(first_url):
            print("⚠️  需要登录...")
            success = await browser.login(
                Config.WHOP_EMAIL,
                Config.WHOP_PASSWORD,
                Config.LOGIN_URL
            )

            if not success:
                print("❌ 登录失败，请检查凭据是否正确")
                return
            print("✅ 登录成功\n")
        else:
            print("✅ 已登录\n")

        # 导航到页面
        test_url, test_type, _ = page_configs[1]
        print(f"📄 正在访问页面: [{test_type.upper()}] {test_url}")

        if not await browser.navigate(test_url):
            print(f"❌ 无法导航到页面: {test_url}")
            return

        print("✅ 页面导航成功\n")

        # 等待页面初始加载
        print("⏳ 等待页面初始加载...")
        await asyncio.sleep(3)

        # 等待用户确认
        print("\n" + "=" * 60)
        print("⚠️  重要提示")
        print("=" * 60)
        print("\n浏览器窗口已打开，请在浏览器中执行以下操作：")
        print("\n1. 📜 滚动页面到最底部，加载所有历史消息")
        print("2. ⏳ 等待所有消息完全加载")
        print("3. ✅ 确认页面内容完整")
        print("\n完成后按 [回车] 键继续导出...\n")

        # 等待用户输入
        input()

        print("\n✅ 收到确认，开始导出...\n")

        # 生成时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 导出完整HTML
        html_file = f"{output_dir}/page_{timestamp}.html"
        print(f"📝 正在导出HTML到: {html_file}")
        html_content = await page.content()
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"✅ HTML已保存 ({len(html_content)} 字符)\n")

        # 2. 截图
        screenshot_file = f"{output_dir}/page_{timestamp}.png"
        print(f"📸 正在截图到: {screenshot_file}")
        await page.screenshot(path=screenshot_file, full_page=True)
        print(f"✅ 截图已保存\n")

        # 3. 导出消息结构分析
        analysis_file = f"{output_dir}/analysis_{timestamp}.txt"
        print(f"🔍 正在分析页面结构...")

        # 使用JavaScript分析页面结构
        js_analysis = """
        () => {
            const analysis = {
                url: window.location.href,
                title: document.title,
                all_elements_count: document.querySelectorAll('*').length,

                // 查找可能的消息容器
                potential_message_containers: [],

                // 查找可能的文本内容
                text_elements: []
            };

            // 尝试多种可能的选择器
            const selectors = [
                '[class*="message"]',
                '[class*="Message"]',
                '[class*="post"]',
                '[class*="Post"]',
                '[class*="content"]',
                '[class*="Content"]',
                '[role="article"]',
                'article',
                '[data-message]',
                '[data-post]'
            ];

            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length > 0) {
                    const sample = elements[0];
                    analysis.potential_message_containers.push({
                        selector: selector,
                        count: elements.length,
                        sample_classes: sample.className,
                        sample_id: sample.id,
                        sample_attributes: Array.from(sample.attributes).map(a => `${a.name}="${a.value.substring(0, 50)}"`),
                        sample_text: sample.innerText.substring(0, 200),
                        sample_html: sample.outerHTML.substring(0, 500)
                    });
                }
            }

            // 查找包含特定关键字的元素
            const keywords = ['GILD', 'CALL', 'PUT', '止损', '出'];
            const walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text.length > 10) {
                    for (const keyword of keywords) {
                        if (text.includes(keyword)) {
                            let element = node.parentElement;
                            let depth = 0;
                            const path = [];

                            while (element && depth < 5) {
                                path.push({
                                    tag: element.tagName,
                                    class: element.className,
                                    id: element.id
                                });
                                element = element.parentElement;
                                depth++;
                            }

                            analysis.text_elements.push({
                                text: text.substring(0, 100),
                                keyword: keyword,
                                path: path
                            });
                            break;
                        }
                    }
                }
            }

            return analysis;
        }
        """

        analysis_data = await page.evaluate(js_analysis)

        with open(analysis_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("页面结构分析\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"URL: {analysis_data['url']}\n")
            f.write(f"标题: {analysis_data['title']}\n")
            f.write(f"总元素数: {analysis_data['all_elements_count']}\n\n")

            f.write("=" * 60 + "\n")
            f.write("可能的消息容器选择器\n")
            f.write("=" * 60 + "\n\n")

            for i, container in enumerate(analysis_data['potential_message_containers'], 1):
                f.write(f"{i}. 选择器: {container['selector']}\n")
                f.write(f"   数量: {container['count']}\n")
                f.write(f"   类名: {container['sample_classes']}\n")
                f.write(f"   ID: {container['sample_id']}\n")
                f.write(f"   属性:\n")
                for attr in container['sample_attributes']:
                    f.write(f"      {attr}\n")
                f.write(f"\n   示例文本:\n   {container['sample_text']}\n")
                f.write(f"\n   示例HTML:\n   {container['sample_html']}\n")
                f.write("\n" + "-" * 60 + "\n\n")

            f.write("\n" + "=" * 60 + "\n")
            f.write("包含交易关键字的元素\n")
            f.write("=" * 60 + "\n\n")

            for i, elem in enumerate(analysis_data['text_elements'][:20], 1):
                f.write(f"{i}. 关键字: {elem['keyword']}\n")
                f.write(f"   文本: {elem['text']}\n")
                f.write(f"   路径:\n")
                for j, node in enumerate(elem['path']):
                    indent = "   " * (j + 2)
                    f.write(f"{indent}<{node['tag']} class='{node['class']}' id='{node['id']}'>\n")
                f.write("\n")

        print(f"✅ 分析已保存\n")

        # 4. 提取消息并导出为JSON
        messages_file = "data/origin_message.json"
        print(f"💬 正在提取消息...")
        
        # 使用 EnhancedMessageExtractor 提取消息
        extractor = EnhancedMessageExtractor(page)
        try:
            message_groups = await extractor.extract_message_groups()
            print(f"✅ 成功提取 {len(message_groups)} 条消息\n")
            
            # 转换为字典列表
            new_messages = [msg.to_simple_dict() for msg in message_groups]
            
            # 按时间排序辅助函数
            def parse_timestamp(ts_str: str) -> datetime:
                """解析时间戳字符串（消息已经通过 normalize_timestamp 处理过）"""
                try:
                    # 尝试多种时间格式（优先匹配标准化后的格式）
                    formats = [
                        "%Y-%m-%d %H:%M:%S.%f",  # 2026-02-03 20:44:55.010 (标准化格式)
                        "%Y-%m-%d %H:%M:%S",     # 2026-02-03 20:44:55
                        "%b %d, %Y %I:%M %p",    # Jan 06, 2026 11:38 PM (未标准化的原始格式)
                    ]
                    for fmt in formats:
                        try:
                            return datetime.strptime(ts_str, fmt)
                        except ValueError:
                            continue
                    
                    # 如果标准格式都失败，尝试使用 EnhancedMessageExtractor 的标准化函数
                    # 但这种情况理论上不应该发生，因为消息已经被标准化了
                    normalized = EnhancedMessageExtractor.normalize_timestamp(ts_str, 0)
                    if normalized != ts_str:
                        # 标准化成功，尝试再次解析
                        for fmt in formats:
                            try:
                                return datetime.strptime(normalized, fmt)
                            except ValueError:
                                continue
                    
                    # 如果都失败，返回一个默认值
                    return datetime.min
                except Exception:
                    return datetime.min
            
            # 读取现有消息（如果存在）
            existing_messages = []
            existing_dom_ids = set()
            
            os.makedirs("data", exist_ok=True)
            
            if os.path.exists(messages_file):
                print(f"📖 正在读取现有消息文件...")
                try:
                    with open(messages_file, 'r', encoding='utf-8') as f:
                        existing_messages = json.load(f)
                    existing_dom_ids = {msg.get('domID') for msg in existing_messages}
                    print(f"✅ 读取到 {len(existing_messages)} 条现有消息\n")
                except Exception as e:
                    print(f"⚠️  读取现有消息失败: {e}")
                    existing_messages = []
            else:
                print(f"ℹ️  首次创建消息文件\n")
            
            # 去重：过滤掉已存在的 domID
            print(f"🔍 正在检查重复消息...")
            added_count = 0
            skipped_count = 0
            
            for msg in new_messages:
                dom_id = msg.get('domID')
                if dom_id not in existing_dom_ids:
                    existing_messages.append(msg)
                    existing_dom_ids.add(dom_id)
                    added_count += 1
                else:
                    skipped_count += 1
            
            print(f"✅ 新增消息: {added_count} 条")
            if skipped_count > 0:
                print(f"⏭️  跳过重复: {skipped_count} 条")
            print()
            
            # 按时间排序
            print("📊 正在按时间排序...")
            existing_messages.sort(key=lambda m: parse_timestamp(m.get('timestamp', '')))
            print(f"✅ 排序完成\n")
            
            # 导出为JSON
            print(f"💾 正在导出到: {messages_file}")
            with open(messages_file, 'w', encoding='utf-8') as f:
                json.dump(existing_messages, f, ensure_ascii=False, indent=2)
            print(f"✅ 消息已保存 (总计 {len(existing_messages)} 条)\n")
            
            # 显示消息统计
            print("📈 消息统计:")
            print(f"   - 本次提取: {len(new_messages)}")
            print(f"   - 新增消息: {added_count}")
            print(f"   - 总消息数: {len(existing_messages)}")
            
            # 统计位置分布
            positions = {}
            for msg in existing_messages:
                pos = msg.get('position', 'unknown')
                positions[pos] = positions.get(pos, 0) + 1
            
            print(f"   - 位置分布:")
            for pos, count in positions.items():
                print(f"     • {pos}: {count}")
            
            # 统计引用消息数量
            refer_count = sum(1 for msg in existing_messages if msg.get('refer'))
            print(f"   - 包含引用: {refer_count}")
            
            # 统计包含历史记录的消息
            history_count = sum(1 for msg in existing_messages if msg.get('history'))
            print(f"   - 包含历史: {history_count}\n")
            
        except Exception as e:
            print(f"❌ 消息提取失败: {e}")
            import traceback
            traceback.print_exc()
            print()
            messages_file = None

        print("\n" + "=" * 60)
        print("导出完成！")
        print("=" * 60)
        print(f"\n📁 输出文件:")
        print(f"   1. HTML: {html_file}")
        print(f"   2. 截图: {screenshot_file}")
        print(f"   3. 分析: {analysis_file}")
        if messages_file:
            print(f"   4. 消息: {messages_file} (增量更新)")
        print(f"\n💡 下一步:")
        print(f"   1. 打开 {html_file} 查看页面结构")
        print(f"   2. 查看 {screenshot_file} 对照实际显示")
        print(f"   3. 阅读 {analysis_file} 了解可用的选择器")
        if messages_file:
            print(f"   4. 查看 {messages_file} 了解提取的消息内容")
            print(f"   5. 根据分析结果调整 message_extractor.py 中的选择器")
        else:
            print(f"   4. 根据分析结果调整 message_extractor.py 中的选择器")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ 导出失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 关闭浏览器
        print("\n🧹 正在清理资源...")
        await browser.close()
        print("✅ 浏览器已关闭")


if __name__ == "__main__":
    asyncio.run(export_page_dom())
