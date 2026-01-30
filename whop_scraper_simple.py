"""
简单的 Whop 页面抓取示例
使用保存的 cookie 自动登录并抓取消息
"""
import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright


class WhopScraper:
    """Whop 页面抓取器（优化版，支持智能去重）"""
    
    def __init__(
        self,
        target_url: str,
        storage_file: str = "storage_state.json",
        headless: bool = False,
        min_message_length: int = 3,
        show_stats: bool = True
    ):
        """
        初始化抓取器
        
        Args:
            target_url: 要抓取的 Whop 页面 URL
            storage_file: Cookie 文件路径
            headless: 是否无头模式运行
            min_message_length: 最小消息长度（字符数），短于此长度的消息将被过滤
            show_stats: 是否显示去重统计信息
        """
        self.target_url = target_url
        self.storage_file = storage_file
        self.headless = headless
        self.min_message_length = min_message_length
        self.show_stats = show_stats
        
    async def scrape_messages(self, duration: int = 30, output_file: str = None):
        """
        抓取页面消息
        
        Args:
            duration: 监控持续时间（秒），默认 30 秒
            output_file: 输出文件路径（可选），将唯一消息保存到文件
        """
        # 检查 cookie 文件是否存在
        if not os.path.exists(self.storage_file):
            print(f"❌ 找不到 cookie 文件: {self.storage_file}")
            print("请先运行登录命令: python3 whop_login.py")
            return
        
        print("=" * 60)
        print("Whop 消息抓取器（智能去重版）")
        print("=" * 60)
        print(f"目标 URL: {self.target_url}")
        print(f"Cookie 文件: {self.storage_file}")
        print(f"监控时长: {duration} 秒")
        print(f"最小消息长度: {self.min_message_length} 字符")
        print(f"去重模式: 开启（内容哈希 + ID 双重去重）")
        print("=" * 60)
        
        async with async_playwright() as p:
            # 启动浏览器
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--window-size=1920,1080',
                ]
            )
            
            # 使用保存的 cookie 创建上下文
            print("\n加载已保存的登录状态...")
            context = await browser.new_context(
                storage_state=self.storage_file,
                viewport={'width': 1920, 'height': 1080},
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            )
            
            page = await context.new_page()
            
            # 访问目标页面
            print(f"\n正在访问目标页面...")
            try:
                # 使用更宽松的等待策略，增加超时时间
                await page.goto(
                    self.target_url,
                    wait_until='domcontentloaded',  # 等待 DOM 加载完成即可
                    timeout=60000  # 60 秒超时
                )
            except Exception as e:
                print(f"⚠️  页面加载警告: {e}")
                print("尝试继续...")
            
            # 等待页面完全渲染
            await asyncio.sleep(3)
            
            current_url = page.url
            print(f"当前 URL: {current_url}")
            
            # 检查是否需要重新登录
            if 'login' in current_url.lower():
                print("\n❌ Cookie 已过期，需要重新登录")
                print("请运行: python3 whop_login.py")
                await context.close()
                await browser.close()
                return
            
            print("✅ 已成功进入页面")
            
            # 提取页面消息
            print("\n" + "=" * 60)
            print("开始抓取消息...")
            print("=" * 60)
            
            seen_message_ids = set()      # 已见过的消息 ID
            seen_message_hashes = set()   # 已见过的消息内容哈希（用于去重）
            unique_messages = []          # 存储唯一消息（用于保存到文件）
            message_count = 0
            duplicate_count = 0           # 去重计数
            filtered_count = 0            # 过滤掉的短消息计数
            start_time = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start_time < duration:
                messages = await self._extract_messages(page)
                
                for msg in messages:
                    msg_id = msg['id']
                    msg_text = msg['text']
                    
                    # 跳过空消息或太短的消息（过滤噪音）
                    if not msg_text or len(msg_text.strip()) < self.min_message_length:
                        filtered_count += 1
                        continue
                    
                    # 使用内容哈希进行去重（避免不同 ID 的相同内容）
                    import hashlib
                    content_hash = hashlib.md5(msg_text.strip().encode()).hexdigest()
                    
                    # 跳过已见过的消息（基于 ID 或内容）
                    if msg_id in seen_message_ids or content_hash in seen_message_hashes:
                        duplicate_count += 1
                        continue
                    
                    seen_message_ids.add(msg_id)
                    seen_message_hashes.add(content_hash)
                    message_count += 1
                    
                    # 保存到列表（用于后续保存到文件）
                    if output_file:
                        unique_messages.append({
                            'id': msg_id,
                            'text': msg_text,
                            'timestamp': datetime.now().isoformat()
                        })
                    
                    # 打印消息
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    print(f"\n[{timestamp}] 消息 #{message_count}")
                    print(f"ID: {msg_id}")
                    print(f"内容:\n{msg_text}")
                    print("-" * 60)
                
                # 等待一段时间再检查
                await asyncio.sleep(2)
            
            print("\n" + "=" * 60)
            print(f"✅ 抓取完成！")
            print("=" * 60)
            
            if self.show_stats:
                print(f"📊 统计信息：")
                print(f"   - 唯一消息：{message_count} 条")
                if duplicate_count > 0:
                    print(f"   - 去重过滤：{duplicate_count} 条")
                if filtered_count > 0:
                    print(f"   - 噪音过滤：{filtered_count} 条（< {self.min_message_length} 字符）")
                total_processed = message_count + duplicate_count + filtered_count
                if total_processed > message_count:
                    print(f"   - 总处理数：{total_processed} 条")
                    efficiency = (message_count / total_processed * 100) if total_processed > 0 else 0
                    print(f"   - 去重效率：{efficiency:.1f}%")
            else:
                print(f"共发现 {message_count} 条唯一消息")
            
            # 保存到文件
            if output_file and unique_messages:
                try:
                    import json
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(unique_messages, f, ensure_ascii=False, indent=2)
                    print(f"\n💾 已保存 {len(unique_messages)} 条唯一消息到: {output_file}")
                except Exception as e:
                    print(f"\n⚠️  保存文件失败: {e}")
            
            print("=" * 60)
            
            # 关闭浏览器
            await context.close()
            await browser.close()
    
    async def _extract_messages(self, page) -> list[dict]:
        """
        从页面提取消息（优化版，避免重复提取）
        
        Args:
            page: Playwright 页面对象
            
        Returns:
            消息列表（已去重）
        """
        # 按优先级排序的选择器列表
        # 优先使用更具体的选择器，避免重复
        message_selectors = [
            # Whop 特定选择器（通常以 post_ 开头）
            '[id^="post_"]',
            '[data-message-id]',
            # 通用消息选择器
            '[class*="Post"][class*="content"]',
            '[class*="message"][class*="content"]',
            'article[class*="post"]',
            'article',
            # 备用选择器
            '[class*="Post"]',
            '[class*="post"]',
            '[class*="Message"]',
            '[class*="message"]',
            '.prose',
        ]
        
        messages = []
        messages_by_content = {}  # 用于内容去重
        
        for selector in message_selectors:
            try:
                elements = await page.query_selector_all(selector)
                temp_messages = []
                
                for element in elements:
                    try:
                        text = await element.inner_text()
                        text = text.strip()
                        
                        # 过滤太短的消息
                        if not text or len(text) < self.min_message_length:
                            continue
                        
                        # 尝试获取消息 ID（优先级：data-message-id > id > 哈希）
                        msg_id = await element.get_attribute('data-message-id')
                        if not msg_id:
                            msg_id = await element.get_attribute('id')
                        if not msg_id:
                            # 使用文本的哈希作为 ID
                            import hashlib
                            msg_id = hashlib.md5(text.encode()).hexdigest()[:12]
                        
                        # 使用内容哈希进行去重
                        import hashlib
                        content_hash = hashlib.md5(text.encode()).hexdigest()
                        
                        # 如果内容未见过，添加到临时列表
                        if content_hash not in messages_by_content:
                            messages_by_content[content_hash] = {
                                'id': msg_id,
                                'text': text
                            }
                            temp_messages.append({
                                'id': msg_id,
                                'text': text
                            })
                    except Exception:
                        continue
                
                # 如果找到消息，使用这个选择器的结果并停止
                if temp_messages:
                    messages = temp_messages
                    break
                    
            except Exception:
                continue
        
        # 如果上面的方法没找到消息，尝试使用 JavaScript
        if not messages:
            messages = await self._extract_messages_js(page)
            # 对 JS 提取的结果也进行去重和长度过滤
            unique_messages = []
            seen_hashes = set()
            for msg in messages:
                import hashlib
                content_hash = hashlib.md5(msg['text'].encode()).hexdigest()
                if content_hash not in seen_hashes and len(msg['text'].strip()) >= self.min_message_length:
                    seen_hashes.add(content_hash)
                    unique_messages.append(msg)
            messages = unique_messages
        
        return messages
    
    async def _extract_messages_js(self, page) -> list[dict]:
        """使用 JavaScript 提取消息（备用方法，已内置去重）"""
        js_code = f"""
        () => {{
            const messages = [];
            const seenContent = new Set();
            const minLength = {self.min_message_length};
            
            // 按优先级排序的选择器
            const selectors = [
                '[id^="post_"]',
                '[data-message-id]',
                '[class*="Post"][class*="content"]',
                'article[class*="post"]',
                'article',
                '[class*="Post"]',
                '[class*="post"]',
                '[class*="Message"]',
                '[class*="message"]',
                '.prose'
            ];
            
            for (const selector of selectors) {{
                const elements = document.querySelectorAll(selector);
                const tempMessages = [];
                
                for (const el of elements) {{
                    const text = el.innerText?.trim();
                    
                    // 过滤太短的消息
                    if (!text || text.length < minLength) continue;
                    
                    // 使用内容去重
                    if (seenContent.has(text)) continue;
                    seenContent.add(text);
                    
                    // 获取消息 ID
                    const id = el.getAttribute('data-message-id') || 
                               el.id || 
                               btoa(text.substring(0, 50)).substring(0, 12);
                    
                    tempMessages.push({{ id, text }});
                }}
                
                // 如果找到消息，使用这个选择器的结果并停止
                if (tempMessages.length > 0) {{
                    return tempMessages;
                }}
            }}
            
            return messages;
        }}
        """
        
        try:
            return await page.evaluate(js_code)
        except Exception as e:
            print(f"JavaScript 提取失败: {e}")
            return []


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='简单的 Whop 页面抓取器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:

  抓取指定页面的消息（监控 30 秒）:
    python3 whop_scraper_simple.py --url https://whop.com/your-page-url/

  监控 60 秒:
    python3 whop_scraper_simple.py --url https://whop.com/your-page-url/ --duration 60

  使用无头模式运行:
    python3 whop_scraper_simple.py --url https://whop.com/your-page-url/ --headless

  自定义最小消息长度（过滤更多噪音）:
    python3 whop_scraper_simple.py --url URL --min-length 20

  不显示统计信息（简洁输出）:
    python3 whop_scraper_simple.py --url URL --no-stats

  保存唯一消息到文件:
    python3 whop_scraper_simple.py --url URL --output messages.json

  完整示例（所有功能）:
    python3 whop_scraper_simple.py --url URL --duration 300 --headless --min-length 15 --output messages.json

特性:
  - 智能去重：自动过滤重复消息（基于内容哈希）
  - 噪音过滤：过滤太短的消息（默认 < 10 字符）
  - 统计信息：显示去重效率和过滤统计

注意:
  - 运行前请先使用 whop_login.py 保存登录状态
  - 如果 cookie 过期，需要重新运行 whop_login.py
        """
    )
    
    parser.add_argument(
        '--url',
        type=str,
        required=True,
        help='要抓取的 Whop 页面 URL'
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        default=30,
        help='监控持续时间（秒），默认 30 秒'
    )
    
    parser.add_argument(
        '--storage',
        type=str,
        default='storage_state.json',
        help='Cookie 文件路径（默认: storage_state.json）'
    )
    
    parser.add_argument(
        '--headless',
        action='store_true',
        help='使用无头模式运行'
    )
    
    parser.add_argument(
        '--min-length',
        type=int,
        default=10,
        help='最小消息长度（字符数），短于此长度的消息将被过滤（默认: 10）'
    )
    
    parser.add_argument(
        '--no-stats',
        action='store_true',
        help='不显示去重统计信息'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        help='保存唯一消息到 JSON 文件（例如: messages.json）'
    )
    
    args = parser.parse_args()
    
    scraper = WhopScraper(
        target_url=args.url,
        storage_file=args.storage,
        headless=args.headless,
        min_message_length=args.min_length,
        show_stats=not args.no_stats
    )
    
    await scraper.scrape_messages(
        duration=args.duration,
        output_file=args.output
    )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n操作已取消")
