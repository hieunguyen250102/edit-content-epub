#!/usr/bin/env python3
import asyncio
import json
import os
import random
import re
import sys
import platform

from playwright.async_api import async_playwright

# ==================== CẤU HÌNH ====================
NOVEL_URL = "https://sangtacviet.com/truyen/jjwxc/1/4737103/0/"
OUTPUT_FORMAT = "txt"          # "txt" hoặc "json"
CONCURRENCY = 1                # số chương tải đồng thời (1-3)
BROWSER_MODE = "cdp"           # "cdp", "persistent", "headless"
CDP_PORT = 9222
USER_DATA_DIR = ""

# ==================== TIỆN ÍCH ====================
def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def get_chrome_command_for_remote(port=9222):
    system = platform.system()
    if system == "Windows":
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        ]
        chrome = next((p for p in paths if os.path.exists(p)), "chrome.exe")
        return f'"{chrome}" --remote-debugging-port={port} --user-data-dir="%TEMP%\\chrome-sangtacviet"'
    elif system == "Linux":
        return f"google-chrome-stable --remote-debugging-port={port} --user-data-dir=/tmp/chrome-sangtacviet"
    elif system == "Darwin":
        return f'"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port={port} --user-data-dir="$TMPDIR/chrome-sangtacviet"'
    else:
        return f"google-chrome --remote-debugging-port={port} --user-data-dir=/tmp/chrome-sangtacviet"

# ==================== CRAWLER ====================
class SangTacVietDownloader:
    def __init__(self, novel_url, output_format="txt", concurrency=1,
                 browser_mode="headless", connect_url=None, user_data_dir=None):
        self.novel_url = novel_url.rstrip('/')
        self.output_format = output_format.lower()
        self.concurrency = max(1, min(concurrency, 3))
        self.browser_mode = browser_mode
        self.connect_url = connect_url
        self.user_data_dir = user_data_dir

        self.novel_title = ""
        self.chapters = []          # (chapter_url, chapter_title)

        self.playwright = None
        self.browser = None
        self.context = None

    async def start_browser(self):
        self.playwright = await async_playwright().start()

        if self.browser_mode == "cdp" and self.connect_url:
            print(f"🔌 Kết nối tới Chrome tại {self.connect_url}")
            for attempt in range(1, 6):
                try:
                    self.browser = await self.playwright.chromium.connect_over_cdp(self.connect_url)
                    if self.browser.contexts:
                        self.context = self.browser.contexts[0]
                    else:
                        self.context = await self.browser.new_context()
                    print("✅ Đã kết nối thành công.")
                    return
                except Exception as e:
                    print(f"⚠️ Lần {attempt}/5 thất bại: {e}")
                    if attempt < 5:
                        await asyncio.sleep(2)
                    else:
                        sys.exit(1)

        elif self.browser_mode == "persistent" and self.user_data_dir:
            os.makedirs(self.user_data_dir, exist_ok=True)
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
        else:
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context()

    async def get_novel_info_and_chapters(self):
        """Lấy tên truyện và danh sách chương từ host jjwxc (mặc định) qua API."""
        print(f"📖 Đang tải danh sách chương từ {self.novel_url}...")
        page = await self.context.new_page()
        try:
            await page.goto(self.novel_url, wait_until="networkidle", timeout=60000)

            # Lấy tên truyện
            title_elem = await page.query_selector('h1')
            self.novel_title = (await title_elem.inner_text()).strip() if title_elem else (await page.title()).split('|')[0].strip()
            if not self.novel_title:
                self.novel_title = "SangTacViet_Novel"
            print(f"📚 Tên truyện: {self.novel_title}")

            # Lấy host và bookid từ URL (mặc định là jjwxc)
            match = re.search(r'/truyen/([^/]+)/(\d+)', self.novel_url)
            if match:
                h_param = match.group(1)      # 'jjwxc'
                bookid_param = match.group(2) # '1'? thực tế bookid là 4737103? Xem kỹ URL: /truyen/jjwxc/1/4737103/0/ -> có 2 số: 1 và 4737103
                # URL gốc có dạng /truyen/{host}/{số thứ tự?}/{bookid}/...
                # Trong trường hợp này, bookid là 4737103 (số thứ 3)
                parts = self.novel_url.split('/')
                if len(parts) >= 6:
                    bookid_param = parts[5]  # lấy phần tử thứ 5 (4737103)
                else:
                    bookid_param = parts[4]  # fallback
            else:
                # Fallback: lấy từ biến bookinfo trong page
                bookinfo_js = await page.evaluate("() => bookinfo")
                if bookinfo_js:
                    h_param = bookinfo_js.get('host', 'jjwxc')
                    bookid_param = str(bookinfo_js.get('id', '4737103'))
                else:
                    print("❌ Không xác định được host và ID truyện.")
                    return False

            print(f"🔍 Sử dụng host: {h_param}, bookid: {bookid_param}")

            # Gọi API lấy danh sách chương (đã sửa lỗi phân trang)
            all_chapters = []
            start = 0
            limit = 100
            while True:
                api_url = f"https://sangtacviet.com/index.php?ngmar=chapterlist&h={h_param}&bookid={bookid_param}&sajax=getchapterlist&force=true&start={start}&limit={limit}"
                print(f"📡 Gọi API từ chương {start}...")
                api_response = await page.evaluate(f"""
                    async () => {{
                        const response = await fetch('{api_url}');
                        return await response.json();
                    }}
                """)
                encoded_data = api_response.get('oridata') or api_response.get('data')
                if not encoded_data:
                    break

                chapters_raw = encoded_data.split("-//-")
                new_chaps = []
                for chap_raw in chapters_raw:
                    if not chap_raw:
                        continue
                    parts = chap_raw.split("-/-")
                    if len(parts) >= 2:
                        chap_id = parts[0].strip()
                        chap_name = parts[1].strip()
                        new_chaps.append((chap_id, chap_name))

                if not new_chaps:
                    break

                all_chapters.extend(new_chaps)
                print(f"   → Đã lấy {len(new_chaps)} chương (tổng {len(all_chapters)})")

                # ✅ Tăng start bằng số chương thực tế
                start += len(new_chaps)

                if len(new_chaps) < limit:
                    break
                await asyncio.sleep(1)

            # Xây dựng URL cho từng chương (đúng định dạng /truyen/host/1/bookid/chap_id/)
            for chap_id, chap_name in all_chapters:
                chapter_url = f"https://sangtacviet.com/truyen/{h_param}/1/{bookid_param}/{chap_id}/"
                self.chapters.append((chapter_url, chap_name))

            print(f"✅ Đã tìm thấy {len(self.chapters)} chương.")
            return True

        except Exception as e:
            print(f"❌ Lỗi khi lấy danh sách chương: {e}")
            return False
        finally:
            await page.close()

    async def fetch_chapter_content(self, chapter_url, chapter_title):
        """Lấy nội dung chương bằng API readchapter (dùng cho host jjwxc)."""
        # Parse URL: /truyen/{h}/{something}/{bookid}/{chap_id}/
        # Ví dụ: /truyen/jjwxc/1/4737103/325/
        match = re.search(r'/truyen/([^/]+)/\d+/(\d+)/(\d+)/', chapter_url)
        if not match:
            print(f"  ⚠️ Không thể parse URL chương: {chapter_url}")
            return None

        h_param = match.group(1)      # 'jjwxc'
        book_id = match.group(2)      # '4737103'
        chap_id = match.group(3)      # '325'

        api_url = f"https://sangtacviet.com/index.php?bookid={book_id}&h={h_param}&c={chap_id}&ngmar=readc&sajax=readchapter&sty=1&exts="

        page = await self.context.new_page()
        try:
            response = await page.evaluate(f"""
                async () => {{
                    const response = await fetch('{api_url}');
                    return await response.json();
                }}
            """)

            content = response.get('content') or response.get('data')
            if content:
                # Làm sạch nội dung
                content = re.sub(r'^@Bạn đang đọc bản lưu trong hệ thống\s*\n?', '', content, flags=re.MULTILINE)
                content = re.sub(r'<i[^>]*>(.*?)</i>', r'\1', content)
                content = re.sub(r'<[^>]+>', '', content)
                return content.strip()
            else:
                print(f"  ⚠️ API không trả về nội dung cho chương {chapter_title}")
                return None

        except Exception as e:
            print(f"  ⚠️ Lỗi khi gọi API cho chương {chapter_title}: {e}")
            return None
        finally:
            await page.close()

    async def process_chapter(self, semaphore, chapter_url, chapter_title):
        async with semaphore:
            await asyncio.sleep(random.uniform(1, 3))
            print(f"\n🔹 [BẮT ĐẦU] {chapter_title}")
            content = await self.fetch_chapter_content(chapter_url, chapter_title)
            if not content:
                print(f"  ❌ Không lấy được nội dung")
                return

            folder = sanitize_filename(self.novel_title)
            os.makedirs(folder, exist_ok=True)
            safe_title = sanitize_filename(chapter_title)[:200]
            ext = "txt" if self.output_format == "txt" else "json"
            file_path = os.path.join(folder, f"{safe_title}.{ext}")

            with open(file_path, 'w', encoding='utf-8') as f:
                if self.output_format == "json":
                    json.dump({"title": chapter_title, "content": content}, f, ensure_ascii=False, indent=2)
                else:
                    f.write(f"{chapter_title}\n\n{content}")
            print(f"  ✅ Đã lưu: {file_path} ({len(content)} ký tự)")

    async def run(self):
        await self.start_browser()
        try:
            if not await self.get_novel_info_and_chapters():
                return
            sem = asyncio.Semaphore(self.concurrency)
            tasks = [asyncio.create_task(self.process_chapter(sem, url, title)) for url, title in self.chapters]
            await asyncio.gather(*tasks)
            print(f"\n✅ Hoàn tất! Đã xử lý {len(self.chapters)} chương.")
            print(f"📁 Thư mục: {sanitize_filename(self.novel_title)}")
        finally:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

# ==================== MAIN ====================
async def main():
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print("=== CRAWL TRUYỆN SANGTACVIET ===\n")
    print(f"NOVEL_URL = {NOVEL_URL}")
    print(f"BROWSER_MODE = {BROWSER_MODE}")

    connect_url = None
    user_data_dir = None

    if BROWSER_MODE == "cdp":
        connect_url = f"http://127.0.0.1:{CDP_PORT}"
        print("\n⚠️ Cần khởi động Chrome với remote debugging:")
        print(get_chrome_command_for_remote(CDP_PORT))
        input("\n👉 Sau khi Chrome mở và đăng nhập (nếu cần), nhấn Enter...")

    elif BROWSER_MODE == "persistent":
        if not USER_DATA_DIR:
            USER_DATA_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'sangtacviet-profile')
        user_data_dir = USER_DATA_DIR
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"📁 Dùng profile: {user_data_dir}")
        input("👉 Nhấn Enter khi đã sẵn sàng...")

    downloader = SangTacVietDownloader(
        NOVEL_URL, OUTPUT_FORMAT, CONCURRENCY,
        BROWSER_MODE, connect_url, user_data_dir
    )
    await downloader.run()

if __name__ == "__main__":
    asyncio.run(main())
