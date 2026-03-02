import asyncio
import aiohttp

class PageMonitor:
    def __init__(self, url):
        self.url = url
        self.session = aiohttp.ClientSession()

    async def monitor(self):
        try:
            async with self.session.get(self.url) as response:
                data = await response.text()
                self.handle_data(data)
        except Exception as e:
            print(f"Error monitoring {self.url}: {e}")

    def handle_data(self, data):
        # Process the data from the page
        print(f"Data from {self.url}: {data[:100]}")  # Print first 100 chars for brevity

    async def shutdown(self):
        await self.session.close()

async def main(pages):
    monitors = [PageMonitor(page).monitor() for page in pages]
    try:
        await asyncio.gather(*monitors)
    except KeyboardInterrupt:
        print('Shutting down monitors...')
        for monitor in monitors:
            await monitor.shutdown()

if __name__ == '__main__':
    pages = [
        'https://api.example.com/options',
        'https://api.example.com/stocks',
    ]
    asyncio.run(main(pages))
