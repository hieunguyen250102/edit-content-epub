import asyncio
import html
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from ebooklib import epub
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from lxml import etree, html as lxml_html

TRUYEN_URL = "https://mongtruyen.com/tinh-dau-kieu-ngao.html"
OUTPUT_EPUB = "tinh_dau_kieu_ngao_fixed.epub"
TIMEOUT = 60000

async def get_all_chapters(page):
    """
    Lấy danh sách tất cả chương truyện bằng cách duyệt qua các trang phân trang.
    """
    print("Đang phân tích cấu trúc phân trang...")
    # Đi tới trang đầu tiên của danh sách chương
    first_page_url = f"{TRUYEN_URL}?page=1"
    await page.goto(first_page_url, wait_until="domcontentloaded")
    await page.wait_for_selector(".mvd-san-pham-show-danh-sach-chuong-item a", timeout=TIMEOUT)

    # --- Bước 1: Tìm tổng số trang ---
    total_pages = 1
    try:
        # Tìm tất cả các nút số trang trong phân trang
        page_numbers = await page.query_selector_all('.pagination .page-item a')
        max_page_num = 0
        for page_link in page_numbers:
            page_text = await page_link.inner_text()
            # Lọc ra các số (bỏ qua nút "Trang tiếp" / "Trang cuối")
            if page_text.strip().isdigit():
                max_page_num = max(max_page_num, int(page_text.strip()))
        if max_page_num > 0:
            total_pages = max_page_num
            print(f"Phát hiện {total_pages} trang danh sách chương.")
        else:
            print("Không tìm thấy thông tin phân trang, chỉ lấy trang đầu tiên.")
    except Exception as e:
        print(f"Lỗi khi đọc phân trang: {e}. Chỉ lấy trang đầu tiên.")

    # --- Bước 2: Lặp qua từng trang để lấy danh sách chương ---
    all_links = []
    for current_page in range(1, total_pages + 1):
        paginated_url = f"{TRUYEN_URL}?page={current_page}"
        if current_page > 1:
            print(f"Đang truy cập trang danh sách: {paginated_url}")
            await page.goto(paginated_url, wait_until="domcontentloaded")
            await page.wait_for_selector(".mvd-san-pham-show-danh-sach-chuong-item a", timeout=TIMEOUT)

        # Lấy nội dung HTML của trang hiện tại
        page_html = await page.content()
        soup = BeautifulSoup(page_html, 'html.parser')

        # Tìm và trích xuất các link chương
        for a in soup.select(".mvd-san-pham-show-danh-sach-chuong-item a"):
            href = a.get("href")
            title = a.get_text(strip=True)
            if href and "chuong=" in href:
                # Sử dụng urljoin để đảm bảo URL đầy đủ
                full_url = urljoin(TRUYEN_URL, href)
                # Thêm vào danh sách tổng, tránh trùng lặp (dùng set nếu cần)
                if (title, full_url) not in all_links:
                    all_links.append((title, full_url))

        print(f"  Trang {current_page}/{total_pages}: Đã lấy {len(all_links)} chương.")

    print(f"\nTổng cộng lấy được {len(all_links)} chương từ {total_pages} trang.")
    return all_links

async def get_chapter_content(page, chapter_url, chap_num):
    print(f"  [Chương {chap_num}] Mở: {chapter_url}")
    await page.goto(chapter_url, wait_until="domcontentloaded")
    
    try:
        await page.wait_for_selector("#noi_dung_truyen", timeout=TIMEOUT)
        await page.wait_for_function("""
            () => {
                const div = document.querySelector('#noi_dung_truyen');
                if (!div) return false;
                const text = div.innerText;
                return text && text.length > 100 && !text.includes('Đang tải');
            }
        """, timeout=TIMEOUT)
        print(f"    [Chương {chap_num}] Đã có nội dung.")
    except PlaywrightTimeoutError:
        print(f"    [Chương {chap_num}] Timeout, tiếp tục...")
    
    page_html = await page.content()
    soup = BeautifulSoup(page_html, 'html.parser')
    
    title_span = soup.select_one(".mdv-san-pham-detail-chuong-title-text")
    if not title_span:
        title_span = soup.select_one(".breadcrumb-item.active a")
    chapter_title = title_span.get_text(strip=True) if title_span else f"Chương {chap_num}"
    
    content_div = soup.find("div", id="noi_dung_truyen")
    if not content_div:
        content_div = soup.find("div", class_="msv-khung-truyen-noi-dung")
    
    if content_div:
        for unwanted in content_div.select(".text-center, .mt-chapter-loading, .mt-protect-content, script, style, .mt-hidden-watermark, .copy-protection-overlay"):
            unwanted.decompose()
        inner_html = content_div.decode_contents()
        print(f"    [Chương {chap_num}] Độ dài nội dung thô: {len(inner_html)} ký tự")
    else:
        print(f"    [Chương {chap_num}] Không tìm thấy div #noi_dung_truyen")
        inner_html = "<p>Không thể tải nội dung</p>"
    
    if not inner_html.strip() or len(inner_html) < 50:
        print(f"    [Chương {chap_num}] Nội dung quá ngắn, bỏ qua.")
        with open(f"debug_chap_{chap_num}.html", "w", encoding="utf-8") as f:
            f.write(page_html)
        return None, None
    
    # Chuẩn hóa HTML thành XHTML hợp lệ
    try:
        fragment = lxml_html.fromstring(inner_html, parser=lxml_html.HTMLParser())
        inner_xhtml = etree.tostring(fragment, method='html', encoding='unicode', with_tail=False)
        if not inner_xhtml:
            inner_xhtml = inner_html
    except Exception as e:
        print(f"    [Chương {chap_num}] Lỗi chuẩn hóa: {e}, dùng gốc.")
        inner_xhtml = inner_html
    
    # Tạo HTML5 đơn giản (không DOCTYPE XHTML)
    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/><title>{html.escape(chapter_title)}</title>
<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; }}
    h1 {{ text-align: center; color: #333; }}
    .chapter-content p {{ margin: 0 0 1em 0; text-align: justify; }}
</style>
</head>
<body>
    <h1>{html.escape(chapter_title)}</h1>
    <div class="chapter-content">{inner_xhtml}</div>
</body>
</html>"""
    return chapter_title, full_html

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)
        
        chapters = await get_all_chapters(page)
        if not chapters:
            await browser.close()
            return
        
        # Metadata
        await page.goto(TRUYEN_URL, wait_until="networkidle")
        main_soup = BeautifulSoup(await page.content(), 'html.parser')
        book_title = main_soup.select_one("h1.hydrosite-mong-truyen-title")
        if not book_title:
            book_title = main_soup.select_one(".mdv-san-pham-detail-title")
        book_title = book_title.get_text(strip=True) if book_title else "Truyện từ Mộng Truyện"
        
        author_tag = main_soup.select_one(".truyen-tacgia-text")
        author = author_tag.get_text(strip=True) if author_tag else "Không rõ"
        
        book = epub.EpubBook()
        book.set_identifier(TRUYEN_URL.split('/')[-1].replace('.html', ''))
        book.set_title(book_title)
        book.set_language("vi")
        book.add_author(author)
        
        epub_chapters = []
        for idx, (chap_title, chap_url) in enumerate(chapters, start=1):
            print(f"\nXử lý chương {idx}/{len(chapters)}: {chap_title}")
            title, content = await get_chapter_content(page, chap_url, idx)
            if content is None or len(content) < 200:
                print(f"    [Chương {idx}] Bỏ qua do nội dung không hợp lệ.")
                continue
            
            print(f"    [Chương {idx}] Mẫu nội dung: {content[:200]}...")
            c = epub.EpubHtml(title=title, file_name=f"chap_{idx:04d}.xhtml", lang='vi')
            c.content = content
            book.add_item(c)
            epub_chapters.append(c)
        
        if not epub_chapters:
            print("Không có chương nào hợp lệ.")
            await browser.close()
            return
        
        book.toc = epub_chapters
        book.spine = ['nav'] + epub_chapters
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        try:
            epub.write_epub(OUTPUT_EPUB, book, {})
            print(f"\n✅ Thành công! File EPUB: {OUTPUT_EPUB}")
        except Exception as e:
            print(f"\n❌ Lỗi khi ghi EPUB: {e}")
            print("Các chương đã thêm:", [c.title for c in epub_chapters])
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())