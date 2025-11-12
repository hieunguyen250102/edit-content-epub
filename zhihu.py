#!/usr/bin/env python3
import asyncio
import json
import os
import random
import re
import sys
import platform
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ==================== CẤU HÌNH CỐ ĐỊNH ====================
# URL của truyện trên Zhihu (ví dụ)
NOVEL_URL = "https://www.zhihu.com/xen/market/remix/paid_column/1898029374185365848"

# Định dạng đầu ra: "txt" hoặc "json"
OUTPUT_FORMAT = "txt"

# Số chương tải đồng thời (chỉ nên 1, tối đa 3)
CONCURRENCY = 1

# Chế độ trình duyệt: "cdp", "persistent", "headless"
BROWSER_MODE = "cdp"   # Khuyến nghị dùng "cdp" trên Windows để giữ đăng nhập

# Nếu BROWSER_MODE = "cdp" – cổng remote debugging của Chrome
CDP_PORT = 9222

# Nếu BROWSER_MODE = "persistent" – đường dẫn thư mục profile (để trống sẽ dùng mặc định)
USER_DATA_DIR = ""

# ==================== HÀM TIỆN ÍCH ====================
def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def get_chrome_command_for_remote(port=9222):
    """Trả về lệnh khởi động Chrome với remote debugging cho hệ điều hành hiện tại"""
    system = platform.system()
    if system == "Windows":
        # Các đường dẫn thường gặp của Chrome trên Windows
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        ]
        chrome_path = None
        for path in possible_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        if not chrome_path:
            chrome_path = "chrome.exe"  # fallback nếu trong PATH
        return f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="%TEMP%\\chrome-zhihu-crawl"'
    elif system == "Linux":
        return f"google-chrome-stable --remote-debugging-port={port} --user-data-dir=/tmp/chrome-zhihu"
    elif system == "Darwin":  # macOS
        return f'"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port={port} --user-data-dir="$TMPDIR/chrome-zhihu"'
    else:
        return f"google-chrome --remote-debugging-port={port} --user-data-dir=/tmp/chrome-zhihu"

# ==================== LỚP CRAWLER CHO ZHIJU ====================
class ZhihuDownloader:
    def __init__(self, novel_url, output_format="txt", concurrency=1,
                 browser_mode="headless", connect_url=None, user_data_dir=None):
        self.novel_url = novel_url.rstrip('/')
        # Trích xuất column_id từ URL
        self.column_id = self._extract_column_id(novel_url)
        if not self.column_id:
            raise ValueError("Không thể tìm thấy column_id trong URL")

        self.output_format = output_format.lower()
        self.concurrency = max(1, min(concurrency, 3))

        self.browser_mode = browser_mode
        self.connect_url = connect_url
        self.user_data_dir = user_data_dir

        self.column_title = ""
        self.chapters = []          # mỗi phần tử: (section_url, section_title, section_id)

        self.playwright = None
        self.browser = None
        self.context = None

    def _extract_column_id(self, url: str) -> str:
        """Lấy column_id từ URL dạng .../paid_column/数字  hoặc .../remix/paid_column/数字"""
        match = re.search(r'/paid_column/(\d+)', url)
        if match:
            return match.group(1)
        parsed = urlparse(url)
        path_parts = parsed.path.rstrip('/').split('/')
        for i, part in enumerate(path_parts):
            if part == 'paid_column' and i+1 < len(path_parts):
                return path_parts[i+1]
        return ""

    async def start_browser(self):
        self.playwright = await async_playwright().start()

        if self.browser_mode == "cdp" and self.connect_url:
            print(f"🔌 Kết nối tới Chrome đang chạy tại {self.connect_url}")
            try:
                self.browser = await self.playwright.chromium.connect_over_cdp(self.connect_url)
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = await self.browser.new_context()
                print("✅ Đã kết nối thành công. Sử dụng session đã đăng nhập.")
                return
            except Exception as e:
                print(f"❌ Không thể kết nối CDP: {e}")
                sys.exit(1)

        elif self.browser_mode == "persistent" and self.user_data_dir:
            print(f"📁 Sử dụng profile riêng tại: {self.user_data_dir}")
            os.makedirs(self.user_data_dir, exist_ok=True)
            # Trên Windows, không cần channel="chrome", để mặc định
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage'
                ],
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            print("✅ Đã khởi tạo trình duyệt với profile riêng.")
        else:
            print("🌐 Chạy ở chế độ headless (không profile).")
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context()

    async def fetch_html(self, url, timeout=90000, wait_for_selector=None):
        """Lấy HTML của một trang, có thể chờ selector xuất hiện."""
        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=timeout)
                await asyncio.sleep(random.uniform(1, 2))
            html = await page.content()
            return html
        finally:
            await page.close()

    async def get_column_info_and_chapters(self):
        """Lấy tiêu đề cột và danh sách chương (tự động click '查看更多章节' nếu có)."""
        print(f"📖 Đang tải danh sách chương từ {self.novel_url}...")
        page = await self.context.new_page()
        try:
            await page.goto(self.novel_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector('[class*="CatalogModule"]', timeout=30000)

            # Lấy tiêu đề cột
            title_elem = await page.query_selector('h1')
            if title_elem:
                self.column_title = (await title_elem.inner_text()).strip()
            else:
                self.column_title = f"column_{self.column_id}"
            print(f"📚 Tên cột: {self.column_title}")

            # Nhấn "查看更多章节" cho đến khi không còn
            while True:
                load_more = await page.query_selector('[class*="CatalogModule-allSection"]')
                if not load_more:
                    break
                is_visible = await load_more.is_visible()
                if not is_visible:
                    break
                print("  🔄 Nhấn '查看更多章节'...")
                await load_more.click()
                await asyncio.sleep(random.uniform(2, 3))
                await page.wait_for_selector('[class*="ChapterItem-root"]', timeout=5000)

            # Lấy danh sách chương
            chapter_items = await page.query_selector_all('[class*="ChapterItem-root"]')
            if not chapter_items:
                print("❌ Không tìm thấy chapter item nào.")
                return False

            for item in chapter_items:
                extra_attr = await item.get_attribute("data-za-extra-module")
                if not extra_attr:
                    continue
                try:
                    extra_data = json.loads(extra_attr)
                    section_id = extra_data.get("card", {}).get("content", {}).get("id")
                    if not section_id:
                        continue
                except json.JSONDecodeError:
                    continue

                title_elem = await item.query_selector('[class*="ChapterItem-title"]')
                if title_elem:
                    title_text = (await title_elem.inner_text()).strip()
                else:
                    title_text = f"Section_{section_id}"

                section_url = f"https://www.zhihu.com/market/paid_column/{self.column_id}/section/{section_id}"
                self.chapters.append((section_url, title_text, section_id))

            print(f"✅ Đã tìm thấy {len(self.chapters)} chương.")
            return True

        finally:
            await page.close()

    async def fetch_section_content(self, section_url, section_title, section_id):
        """Lấy nội dung: tất cả thẻ <p data-block-key=...> theo thứ tự."""
        html = await self.fetch_html(section_url, wait_for_selector='p[data-block-key]')
        soup = BeautifulSoup(html, 'lxml')
        paragraphs = soup.find_all('p', attrs={'data-block-key': True})
        if not paragraphs:
            print(f"  ⚠️ Không tìm thấy nội dung (p[data-block-key]) cho {section_title}")
            return None

        content_lines = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
        full_content = '\n\n'.join(content_lines)
        return full_content

    async def process_chapter(self, semaphore, section_url, section_title, section_id):
        async with semaphore:
            await asyncio.sleep(random.uniform(2, 5))
            print(f"\n🔹 [BẮT ĐẦU] {section_title}")
            try:
                content = await self.fetch_section_content(section_url, section_title, section_id)
                if not content:
                    print(f"  ❌ Không lấy được nội dung cho {section_title}")
                    return

                print(f"  📄 [LƯU NỘI DUNG GỐC] {section_title} ({len(content)} ký tự)")

                folder_name = sanitize_filename(self.column_title)
                os.makedirs(folder_name, exist_ok=True)

                safe_title = sanitize_filename(section_title)
                ext = "txt" if self.output_format == "txt" else "json"
                file_path = os.path.join(folder_name, f"{safe_title}.{ext}")

                with open(file_path, 'w', encoding='utf-8') as f:
                    if self.output_format == "json":
                        json.dump({"title": section_title, "content": content}, f, ensure_ascii=False, indent=2)
                    else:
                        f.write(f"{section_title}\n\n{content}")
                print(f"  ✅ [HOÀN THÀNH] {file_path}")

            except Exception as e:
                print(f"  ❌ [LỖI] {section_title}: {e}")

    async def run(self):
        await self.start_browser()
        try:
            if not await self.get_column_info_and_chapters():
                return
            semaphore = asyncio.Semaphore(self.concurrency)
            tasks = [
                asyncio.create_task(self.process_chapter(semaphore, url, title, sid))
                for url, title, sid in self.chapters
            ]
            await asyncio.gather(*tasks)
            print("\n========== HOÀN TẤT ==========")
            print(f"Đã xử lý {len(self.chapters)} chương.")
            print(f"Thư mục: {sanitize_filename(self.column_title)}")
        finally:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

async def main():
    # Fix cho Windows event loop (nếu cần)
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print("=== TOOL CRAWL TRUYỆN TỪ ZHIJU (LẤY NỘI DUNG GỐC) ===\n")
    print(f"📌 Cấu hình hiện tại:")
    print(f"   NOVEL_URL = {NOVEL_URL}")
    print(f"   OUTPUT_FORMAT = {OUTPUT_FORMAT}")
    print(f"   CONCURRENCY = {CONCURRENCY}")
    print(f"   BROWSER_MODE = {BROWSER_MODE}")
    if BROWSER_MODE == "cdp":
        print(f"   CDP_PORT = {CDP_PORT}")
    elif BROWSER_MODE == "persistent":
        print(f"   USER_DATA_DIR = {USER_DATA_DIR if USER_DATA_DIR else '(tự động tạo trong thư mục mặc định)'}")
    print()

    connect_url = None
    user_data_dir = None

    if BROWSER_MODE == "cdp":
        connect_url = f"http://localhost:{CDP_PORT}"
        print("⚠️ Yêu cầu: Chrome phải được khởi động với cờ remote debugging.")
        print("   Hãy làm theo các bước sau:")
        print("   1. Đóng hoàn toàn Chrome (kiểm tra trong Task Manager).")
        print("   2. Mở Command Prompt (cmd) hoặc PowerShell và chạy lệnh sau:")
        print()
        chrome_cmd = get_chrome_command_for_remote(CDP_PORT)
        print(f"   {chrome_cmd}")
        print()
        print("   3. Sau khi Chrome mở, truy cập zhihu.com và đăng nhập.")
        print("   4. Quay lại đây và nhấn Enter để tiếp tục.")
        input("👉 Nhấn Enter khi đã sẵn sàng...")

    elif BROWSER_MODE == "persistent":
        if not USER_DATA_DIR:
            # Mặc định trên Windows dùng thư mục trong AppData/Local
            default_profile = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'zhihu-crawl-profile')
            USER_DATA_DIR = default_profile
        user_data_dir = USER_DATA_DIR
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"✅ Sẽ dùng profile tại: {user_data_dir}")
        print("   Lần đầu chạy sẽ mở trình duyệt, bạn cần đăng nhập thủ công vào zhihu.com.")
        input("Nhấn Enter khi đã sẵn sàng...")

    downloader = ZhihuDownloader(
        NOVEL_URL, OUTPUT_FORMAT, CONCURRENCY,
        browser_mode=BROWSER_MODE, connect_url=connect_url,
        user_data_dir=user_data_dir
    )
    await downloader.run()

if __name__ == "__main__":
    asyncio.run(main())

#"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%TEMP%\chrome-zhihu-crawl"
