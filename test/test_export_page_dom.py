#!/usr/bin/env python3
"""
导出页面 DOM 和截图，供本地分析 / 调试选择器。
运行: python test/test_export_page_dom.py  或  python -m test.test_export_page_dom
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config, create_env_template
from scraper.browser import BrowserManager


async def export_page_dom():
    """导出页面DOM和截图供本地分析"""
    print("\n" + "=" * 60)
    print("导出页面DOM和截图")
    print("=" * 60 + "\n")

    # 验证配置
    if not Config.validate():
        print("❌ 配置验证失败")
        create_env_template()
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
        first_url = page_configs[0][0]
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
        test_url, test_type, _ = page_configs[0]
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
        from datetime import datetime
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

        print("\n" + "=" * 60)
        print("导出完成！")
        print("=" * 60)
        print(f"\n📁 输出文件:")
        print(f"   1. HTML: {html_file}")
        print(f"   2. 截图: {screenshot_file}")
        print(f"   3. 分析: {analysis_file}")
        print(f"\n💡 下一步:")
        print(f"   1. 打开 {html_file} 查看页面结构")
        print(f"   2. 查看 {screenshot_file} 对照实际显示")
        print(f"   3. 阅读 {analysis_file} 了解可用的选择器")
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
