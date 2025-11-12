import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def extract_chapter_title(soup):
    """
    Tìm tiêu đề chương dựa trên cấu trúc mới của doctruyenfull.vn
    Ưu tiên: h2 a.chapter-title > span.chapter-text, h1 trong breadcrumb, hoặc thẻ title
    """
    # 1. Tìm trong thẻ h2 với class chapter-title
    title_tag = soup.find('h2')
    if title_tag:
        link = title_tag.find('a', class_='chapter-title')
        if link:
            span = link.find('span', class_='chapter-text')
            if span:
                text = span.get_text(strip=True)
                if text:
                    return text
    # 2. Tìm trong breadcrumb (ol.breadcrumb) - thẻ h1 chứa link chương
    breadcrumb_h1 = soup.select_one('ol.breadcrumb h1 a')
    if breadcrumb_h1:
        text = breadcrumb_h1.get_text(strip=True)
        if text:
            return text
    # 3. Fallback: dùng regex như cũ
    patterns = [
        r'Chương\s+(\d+)\s*:\s*([^<>\n]+)',
        r'Chương\s+(\d+)',
        r'Chapter\s+(\d+)\s*:\s*([^<>\n]+)',
    ]
    candidates = []
    for tag in soup.find_all(['a', 'h2', 'h1', 'h3', 'h4', 'title']):
        text = tag.get_text(strip=True)
        if text and ('chương' in text.lower() or 'chapter' in text.lower()):
            candidates.append(text)
    for text in candidates:
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    return f"Chương {match.group(1)}: {match.group(2).strip()}"
                else:
                    return f"Chương {match.group(1)}"
    title_tag = soup.find('title')
    if title_tag:
        return title_tag.get_text(strip=True)
    return "Chương"

def clean_chapter_content(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # ------------------------------------------------------------
    # 1. XÓA CÁC PHẦN KHÔNG CẦN (điều hướng, quảng cáo, chân trang)
    # ------------------------------------------------------------
    # Header / navbar
    header_selectors = [
        '#nav', '.navbar', '.navbar-breadcrumb', '#header-ads', '#header-ads-full',
        '.header-ads', '.header-ads-full', '#ads-head', '#ads-install-app'
    ]
    for selector in header_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Nút điều hướng chương
    nav_selectors = [
        '.chapter-nav', '#chapter-nav-top', '#chapter-nav-bot', '.btn-chapter-nav',
        '#prev_chap', '#next_chap', '.chapter_jump', '#chapter_error', '#chapter_comment'
    ]
    for selector in nav_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Quảng cáo cũ (dựa trên class/id)
    ad_selectors = [
        '[id*="ads"]', '[class*="ads"]', '.adfill', '.ads-responsive', '#ads-chapter-pc-top',
        '#ads-adsVtri1', '#ads-chapter-bottom', '#ads-chapter-bottom-lien-quan',
        '#ads-flyicon', '#ads-xuyentrang-bottom', '#catfish-bottom-sp', '#ads_xuyen_trang_bottom',
        '.show_ads_google', '.box-notice', '.text-link-bottom', '.ln-aff-slot'
    ]
    for selector in ad_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Quảng cáo dạng box Shopee/Camera (có style đỏ cam hoặc chứa auto-ads-link)
    for div in soup.find_all('div', style=True):
        style = div.get('style', '').lower()
        if 'border:2px solid #ff4d4d' in style or '#ff4d4d' in style:
            div.decompose()
    for ad_link in soup.find_all('a', class_='auto-ads-link'):
        ad_link.decompose()
    
    # Xóa các popup / floating quảng cáo mới
    popup_selectors = ['#cam-popup', '#cam-floating', '#qc-floating', '#shopee-overlay', '#shopee-mini-icon']
    for selector in popup_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Bình luận Facebook
    comment_selectors = ['#fb-comment-chapter', '#fb-root', '.fb_reset', '#demo', '.collapse', '[class*="comment"]']
    for selector in comment_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Chân trang
    footer_selectors = ['#footer', '.footer', '.text-link-bottom']
    for selector in footer_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # Thẻ style, script, link, noscript
    for tag in soup.find_all(['style', 'script', 'link', 'noscript']):
        tag.decompose()
    # Comment HTML
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # Ẩn các phần tử display:none
    for tag in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
        tag.decompose()
    
    # ------------------------------------------------------------
    # 2. LẤY TIÊU ĐỀ CHƯƠNG (sau khi đã xóa rác)
    # ------------------------------------------------------------
    chapter_title = extract_chapter_title(soup)
    print(f"[DEBUG] Tiêu đề chương: {chapter_title}")
    
    # ------------------------------------------------------------
    # 3. LẤY NỘI DUNG CHÍNH (trong div#chapter-c)
    # ------------------------------------------------------------
    # Tìm div chứa nội dung chương (ưu tiên id="chapter-c")
    content_div = soup.find('div', id='chapter-c')
    if not content_div:
        content_div = soup.find('div', class_=re.compile(r'chapter-c', re.I))
    if not content_div:
        content_div = soup.find('body')
    
    # Xóa các thẻ h2 (vì tiêu đề đã được thêm lại sau)
    if content_div:
        for unwanted in content_div.find_all(['h1', 'h2']):
            unwanted.decompose()
        # Xóa các đường kẻ <hr> bên trong nội dung
        for hr in content_div.find_all('hr'):
            hr.decompose()
    
    # Lấy nội dung dạng string từ content_div
    if content_div:
        inner_html = ''.join(str(child) for child in content_div.children)
    else:
        inner_html = "<p>Không có nội dung</p>"
    
    # ------------------------------------------------------------
    # 4. TẠO HTML SẠCH CHO EPUB
    # ------------------------------------------------------------
    clean_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8" />
    <title>{chapter_title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 20px; }}
        .chapter-content p {{ margin: 0 0 1em 0; text-align: justify; }}
        br {{ display: block; margin: 0.5em 0; }}
    </style>
</head>
<body>
    <h1>{chapter_title}</h1>
    <div class="chapter-content">
        {inner_html}
    </div>
</body>
</html>"""
    return clean_html

def optimize_epub_structure(book):
    clean_spine = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            clean_spine.append(item)
    return clean_spine

def clean_complete_epub(input_path, output_path):
    print("Đang đọc file EPUB...")
    book = epub.read_epub(input_path)
    
    total_chapters = 0
    processed_chapters = 0
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            total_chapters += 1
    
    print(f"Tổng số chương cần xử lý: {total_chapters}")
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            try:
                content = item.get_content().decode('utf-8')
                cleaned_content = clean_chapter_content(content)
                item.set_content(cleaned_content.encode('utf-8'))
                processed_chapters += 1
                if processed_chapters % 50 == 0:
                    print(f"Đã xử lý {processed_chapters}/{total_chapters} chương")
            except Exception as e:
                print(f"Lỗi khi xử lý {item.get_name()}: {str(e)}")
                continue
    
    print("Đang tối ưu cấu trúc EPUB...")
    book.spine = optimize_epub_structure(book)
    
    print("Đang ghi file EPUB mới...")
    epub.write_epub(output_path, book, {})
    
    print(f"✅ HOÀN THÀNH!")
    print(f"📁 Input: {input_path}")
    print(f"📁 Output: {output_path}")
    print(f"📊 Đã xử lý: {processed_chapters}/{total_chapters} chương")

if __name__ == "__main__":
    input_file = "input.epub"
    output_file = "out_cleaned.epub"
    clean_complete_epub(input_file, output_file)
