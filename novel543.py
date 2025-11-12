#!/usr/bin/env python3
import asyncio
import random
import re
import os
import sys
from urllib.parse import urljoin

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

# ==================== CẤU HÌNH CỐ ĐỊNH (SỬA TRỰC TIẾP TRONG FILE) ====================
# URL của truyện (bắt buộc)
NOVEL_URL = "https://www.novel543.com/0722247746/"   # <--- NHẬP URL CỦA BẠN VÀO ĐÂY

# Có dịch hay không? True = có dịch (cần LM Studio), False = lưu nguyên bản tiếng Trung
ENABLE_TRANSLATION = False

# Định dạng đầu ra: "txt" hoặc "json"
OUTPUT_FORMAT = "txt"

# Số chương tải & xử lý đồng thời (chỉ nên 1, tối đa 3)
CONCURRENCY = 1

# Chế độ trình duyệt: "cdp", "persistent", "headless"
BROWSER_MODE = "cdp"

# Nếu BROWSER_MODE = "cdp" – cổng remote debugging của Chrome
CDP_PORT = 9222

# Nếu BROWSER_MODE = "persistent" – đường dẫn thư mục profile (để trống sẽ dùng mặc định)
USER_DATA_DIR = ""   # ví dụ: "/home/ten/.config/chrome-crawl"

# ==================== CẤU HÌNH LM STUDIO ====================
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"
MODEL_NAME = "qwen2.5-7b-instruct"

# ==================== HÀM DỊCH ====================
async def translate_text(text_to_translate: str):
    if not text_to_translate or not text_to_translate.strip():
        return ""
    try:
        client = AsyncOpenAI(base_url=LM_STUDIO_BASE_URL, api_key=LM_STUDIO_API_KEY)
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Bạn là dịch giả chuyên nghiệp, dịch Trung -> Việt, giữ nguyên xuống dòng, chỉ trả về bản dịch."},
                {"role": "user", "content": f"Dịch đoạn sau sang tiếng Việt:\n\n{text_to_translate}"}
            ],
            temperature=0.3,
            max_tokens=2048
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  Lỗi dịch: {e}")
        return f"[LỖI DỊCH] {text_to_translate}"

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", filename)

# ==================== LỚP CRAWLER CHÍNH ====================
class NovelDownloader:
    def __init__(self, novel_url, output_format="txt", concurrency=1,
                 browser_mode="headless", connect_url=None, user_data_dir=None):
        self.novel_url = novel_url.rstrip('/')
        self.chapter_list_url = self.novel_url + "/dir"
        self.output_format = output_format.lower()
        self.concurrency = max(1, min(concurrency, 3))

        self.browser_mode = browser_mode
        self.connect_url = connect_url
        self.user_data_dir = user_data_dir

        self.novel_title_cn = ""
        self.chapters = []

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        self.playwright = None
        self.browser = None
        self.context = None

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
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                channel="chrome",
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage'
                ],
                viewport={'width': 1920, 'height': 1080},
                user_agent=self.headers['User-Agent'],
                extra_http_headers={k: v for k, v in self.headers.items() if k != 'User-Agent'}
            )
            print("✅ Đã khởi tạo trình duyệt với profile riêng.")
        else:
            print("🌐 Chạy ở chế độ headless (không profile).")
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                user_agent=self.headers['User-Agent'],
                extra_http_headers={k: v for k, v in self.headers.items() if k != 'User-Agent'}
            )

    async def fetch_html(self, url, timeout=90000, retries=3, wait_for_content=False):
        for attempt in range(retries):
            page = await self.context.new_page()
            try:
                await asyncio.sleep(random.uniform(1.5, 4.0))
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                if wait_for_content:
                    try:
                        await page.wait_for_selector('div.chapter-content', timeout=15000)
                        await page.wait_for_timeout(random.randint(1000, 2000))
                    except:
                        pass
                html = await page.content()
                return html
            except Exception as e:
                print(f"    Lần thử {attempt+1}/{retries} thất bại: {e}")
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(5)
            finally:
                await page.close()

    async def get_novel_info_and_chapters(self):
        print(f"📖 Đang tải danh sách chương từ {self.chapter_list_url}...")
        html = await self.fetch_html(self.chapter_list_url)
        
        soup = BeautifulSoup(html, 'lxml')

        title_tag = soup.find('h1')
        if title_tag:
            self.novel_title_cn = title_tag.text.strip()
            print(f"Tên truyện (tiếng Trung): {self.novel_title_cn}")
        else:
            self.novel_title_cn = "Unknown_Title"

        chaplist_div = soup.find('div', class_='chaplist')
        if not chaplist_div:
            print("❌ Không tìm thấy div.chaplist. Kiểm tra lại URL hoặc kết nối.")
            return False

        all_uls = chaplist_div.find_all('ul')
        if not all_uls:
            print("❌ Không tìm thấy ul nào trong div.chaplist.")
            return False
        
        chapter_ul = None
        for ul in all_uls:
            if ul.get('class') and 'all' in ul.get('class'):
                chapter_ul = ul
                break
        if not chapter_ul and len(all_uls) >= 2:
            chapter_ul = all_uls[1]
        elif not chapter_ul:
            chapter_ul = all_uls[-1]

        if not chapter_ul:
            print("❌ Không tìm thấy ul chứa danh sách chương.")
            return False

        all_links = chapter_ul.find_all('a', href=True)
        if not all_links:
            print("❌ Không tìm thấy link chương nào trong ul.")
            return False

        chapter_links = []
        for a_tag in all_links:
            href = a_tag['href']
            if href.endswith('.html'):
                full_url = urljoin(self.novel_url, href)
                title = a_tag.get_text(strip=True)
                if not title:
                    title = f"Chapter {len(chapter_links)+1}"
                chapter_links.append((full_url, title))

        if not chapter_links:
            print("❌ Không tìm thấy đường dẫn chương hợp lệ.")
            return False

        self.chapters = chapter_links
        print(f"✅ Đã tìm thấy {len(self.chapters)} chương.")
        return True

    async def process_chapter(self, semaphore, chapter_url, chapter_title_cn):
        async with semaphore:
            await asyncio.sleep(random.uniform(2, 5))
            print(f"\n🔹 [BẮT ĐẦU] {chapter_title_cn}")
            try:
                html = await self.fetch_html(chapter_url, wait_for_content=True)
                soup = BeautifulSoup(html, 'lxml')
                
                # Tìm div chứa nội dung
                content_div = soup.find('div', class_='chapter-content')
                if not content_div:
                    # Thử tìm theo cách khác
                    content_div = soup.find('div', class_='content py-5')
                
                if not content_div:
                    print(f"  ⚠️ Không tìm thấy nội dung {chapter_title_cn}")
                    return
                
                # LOẠI BỎ CÁC THẺ QUẢNG CÁO VÀ KHÔNG CẦN THIẾT
                for tag in content_div.find_all(['script', 'ins', 'iframe', 'div.adBlock', 'div.gadBlock']):
                    tag.decompose()
                
                # LẤY NỘI DUNG CHÍNH - cách 1: lấy text từ div.content bên trong
                main_content = content_div.find('div', class_='content')
                if main_content:
                    # Lấy text, giữ cấu trúc xuống dòng
                    original_text = main_content.get_text(separator='\n', strip=True)
                else:
                    # Fallback: lấy tất cả text trong chapter-content
                    original_text = content_div.get_text(separator='\n', strip=True)
                
                # Loại bỏ dòng "溫馨提示" nếu có
                lines = original_text.split('\n')
                filtered_lines = [line for line in lines if '溫馨提示' not in line and '站內信' not in line]
                original_text = '\n'.join(filtered_lines)
                
                if not original_text or len(original_text) < 50:  # Nếu nội dung quá ngắn -> có thể sai
                    print(f"  ⚠️ Nội dung quá ngắn hoặc trống: {len(original_text)} ký tự")
                    # Debug: in ra cấu trúc để kiểm tra
                    print(f"  Debug: class của content_div: {content_div.get('class')}")
                    return
                
                # Phần còn lại giữ nguyên
                if ENABLE_TRANSLATION:
                    print(f"  🔄 [ĐANG DỊCH] {chapter_title_cn}")
                    final_content = await translate_text(original_text)
                else:
                    print(f"  📄 [KHÔNG DỊCH] {chapter_title_cn}")
                    final_content = original_text
                
                # Lưu file...
                safe_title = sanitize_filename(chapter_title_cn)
                folder_name = sanitize_filename(f"{self.novel_title_cn}")
                os.makedirs(folder_name, exist_ok=True)
                
                ext = "txt" if self.output_format == "txt" else "json"
                file_path = os.path.join(folder_name, f"{safe_title}.{ext}")
                with open(file_path, 'w', encoding='utf-8') as f:
                    if self.output_format == "json":
                        import json
                        json.dump({"title": chapter_title_cn, "content": final_content}, f, ensure_ascii=False, indent=2)
                    else:
                        f.write(f"{chapter_title_cn}\n\n{final_content}")
                print(f"  ✅ [HOÀN THÀNH] {file_path}")
                
            except Exception as e:
                print(f"  ❌ [LỖI] {chapter_title_cn}: {e}")

    async def run(self):
        await self.start_browser()
        try:
            if not await self.get_novel_info_and_chapters():
                return
            semaphore = asyncio.Semaphore(self.concurrency)
            tasks = [asyncio.create_task(self.process_chapter(semaphore, url, title))
                     for url, title in self.chapters]
            await asyncio.gather(*tasks)
            print("\n========== HOÀN TẤT ==========")
            print(f"Đã xử lý {len(self.chapters)} chương.")
            print(f"Thư mục: {sanitize_filename(f'{self.novel_title_cn}')}")
        finally:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

def get_default_chrome_profile_path():
    home = os.path.expanduser("~")
    for path in [
        os.path.join(home, ".config", "google-chrome"),
        os.path.join(home, ".config", "chromium")
    ]:
        if os.path.exists(path):
            return path
    return None

async def main():
    print("=== TOOL CRAWL & DỊCH TRUYỆN TỪ NOVEL543.COM ===\n")
    print(f"📌 Cấu hình hiện tại:")
    print(f"   NOVEL_URL = {NOVEL_URL}")
    print(f"   ENABLE_TRANSLATION = {ENABLE_TRANSLATION}")
    print(f"   OUTPUT_FORMAT = {OUTPUT_FORMAT}")
    print(f"   CONCURRENCY = {CONCURRENCY}")
    print(f"   BROWSER_MODE = {BROWSER_MODE}")
    if BROWSER_MODE == "cdp":
        print(f"   CDP_PORT = {CDP_PORT}")
    elif BROWSER_MODE == "persistent":
        print(f"   USER_DATA_DIR = {USER_DATA_DIR if USER_DATA_DIR else '(tự động tạo trong thư mục mặc định)'}")
    print()

    # Xử lý theo chế độ đã cấu hình
    connect_url = None
    user_data_dir = None

    if BROWSER_MODE == "cdp":
        connect_url = f"http://localhost:{CDP_PORT}"
        print("⚠️ Yêu cầu: Chrome phải được khởi động với cờ:")
        print(f"   google-chrome-stable --remote-debugging-port={CDP_PORT} --user-data-dir=/tmp/chrome-scraping")
        print("   (Đóng tất cả Chrome trước, sau đó chạy lệnh trên rồi quay lại đây)")
        print("   Sau khi Chrome mở, hãy đăng nhập vào novel543.com (nếu cần).")
        input("Nhấn Enter khi đã sẵn sàng...")
    elif BROWSER_MODE == "persistent":
        if not USER_DATA_DIR:
            USER_DATA_DIR = os.path.expanduser("~/chrome-crawl-profile")
        user_data_dir = USER_DATA_DIR
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"✅ Sẽ dùng profile tại: {user_data_dir}")
        print("   Lần đầu chạy sẽ tạo profile mới, bạn cần đăng nhập thủ công vào novel543.com.")
        input("Nhấn Enter khi đã sẵn sàng...")
    else:  # headless
        print("🌐 Chạy headless, có thể bị chặn.")

    downloader = NovelDownloader(NOVEL_URL, OUTPUT_FORMAT, CONCURRENCY,
                                 browser_mode=BROWSER_MODE, connect_url=connect_url,
                                 user_data_dir=user_data_dir)
    await downloader.run()

if __name__ == "__main__":
    if ENABLE_TRANSLATION:
        try:
            import requests
            requests.get("http://localhost:1234/v1/models", timeout=5)
        except:
            print("❌ LỖI: Không kết nối được LM Studio. Vui lòng khởi động LM Studio và bật server cổng 1234.")
            sys.exit(1)
    else:
        print("ℹ️ Chế độ không dịch được bật – bỏ qua kiểm tra LM Studio.")

    asyncio.run(main())