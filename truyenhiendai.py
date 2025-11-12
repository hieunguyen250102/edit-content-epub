import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def extract_chapter_title(soup):
    """
    Tìm tiêu đề chương trong soup, ưu tiên span.chapter-text
    """
    # Cách 1: Tìm trực tiếp span.chapter-text (quan trọng nhất)
    chapter_span = soup.find('span', class_='chapter-text')
    if chapter_span:
        title_text = chapter_span.get_text(strip=True)
        print(f"[DEBUG] Tìm thấy span.chapter-text: {title_text}")
        if title_text:
            return title_text
    
    # Cách 2: Tìm a.chapter-title
    chapter_link = soup.find('a', class_='chapter-title')
    if chapter_link:
        title_text = chapter_link.get('title', '') or chapter_link.get_text(strip=True)
        print(f"[DEBUG] Tìm thấy a.chapter-title: {title_text}")
        if title_text:
            return title_text
    
    # Cách 3: Tìm trong breadcrumb
    breadcrumb = soup.find('ol', class_='breadcrumb')
    if breadcrumb:
        active_li = breadcrumb.find('li', class_='active')
        if active_li:
            h1 = active_li.find('h1')
            if h1:
                a = h1.find('a')
                if a:
                    title_text = a.get('title', '') or a.get_text(strip=True)
                    if title_text:
                        print(f"[DEBUG] Tìm thấy trong breadcrumb: {title_text}")
                        return title_text
    
    # Cách 4: Tìm thẻ h2 bất kỳ
    h2_tag = soup.find('h2')
    if h2_tag:
        text = h2_tag.get_text(strip=True)
        # Làm sạch text: loại bỏ "Hầu Môn -" nếu có
        if ' - ' in text:
            text = text.split(' - ')[-1]
        print(f"[DEBUG] Tìm thấy trong h2: {text}")
        if text:
            return text
    
    # Fallback: tìm bất kỳ text nào chứa 'Chương'
    body = soup.find('body')
    if body:
        for text in body.strings:
            if text and re.search(r'Chương\s+\d+', text, re.IGNORECASE):
                match = re.search(r'Chương\s+(\d+)(?:\s*:\s*(.+?))?(?:\n|$)', text, re.IGNORECASE)
                if match:
                    if match.group(2):
                        return f"Chương {match.group(1)}: {match.group(2).strip()}"
                    else:
                        return f"Chương {match.group(1)}"
                return text.strip()[:100]
    
    return "Không xác định được chương"

def clean_chapter_content(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. LƯU LẠI NỘI DUNG CHÍNH (div#chapter-c)
    content_div = soup.find('div', id='chapter-c')
    if not content_div:
        content_div = soup.find('div', class_=re.compile(r'chapter-c', re.I))
    
    # Lưu nội dung thô
    raw_content = None
    if content_div:
        import copy
        raw_content = copy.copy(content_div)
        print(f"[DEBUG] Đã tìm thấy content_div")
    
    # Fallback: tìm tất cả thẻ p
    if not raw_content:
        paragraphs = soup.find_all('p')
        content_paragraphs = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Lấy các đoạn có nội dung dài (trên 30 ký tự) và không chứa từ khóa quảng cáo
            if len(text) > 30 and not any(kw in text.lower() for kw in ['quảng cáo', 'advertisements', 'copyright']):
                content_paragraphs.append(p)
        
        if content_paragraphs:
            raw_content = BeautifulSoup('<div></div>', 'html.parser')
            for p in content_paragraphs:
                raw_content.append(p)
            print(f"[DEBUG] Fallback: tìm thấy {len(content_paragraphs)} đoạn văn")
    
    # 2. XÓA CÁC PHẦN KHÔNG CẦN
    # Header
    for selector in ['#nav', '.navbar', '.navbar-header', '.navbar-collapse', '.navbar-breadcrumb']:
        for element in soup.select(selector):
            element.decompose()
    
    # Navigation
    for selector in ['.chapter-nav', '#chapter-nav-top', '#chapter-nav-bot', '.btn-chapter-nav', 
                     '#chapter_error', '#chapter_comment', '.btn-group', '.btn']:
        for element in soup.select(selector):
            element.decompose()
    
    # Quảng cáo và đề xuất
    for selector in ['.related-all-content', '.related-box', '.realted-body', '.col-md-3', '.col-xs-3', 
                     '.background-FFF', '.box-notice', '.text-link-bottom', '.show_ads_google',
                     '.your-menu-class', 'nav']:
        for element in soup.select(selector):
            element.decompose()
    
    # Footer
    for selector in ['#footer', '.footer', '.tag-list']:
        for element in soup.select(selector):
            element.decompose()
    
    # Thẻ script, style
    for tag in soup.find_all(['style', 'script', 'link', 'noscript', 'form', 'input', 'button', 'hr']):
        tag.decompose()
    
    # Comment
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # 3. LẤY TIÊU ĐỀ CHƯƠNG
    chapter_title = extract_chapter_title(soup)
    print(f"[DEBUG] Tiêu đề cuối cùng: {chapter_title}")
    
    # 4. LẤY NỘI DUNG TỪ raw_content
    inner_html = ""
    if raw_content:
        for child in raw_content.children:
            if child.name == 'p':
                # Xóa các thẻ không mong muốn bên trong p
                for unwanted in child.find_all(['a', 'button', 'input', 'span', 'div']):
                    # Nếu là link chapter-title thì unwrap để giữ text
                    if unwanted.name == 'a' and unwanted.get('class') and 'chapter-title' in ' '.join(unwanted.get('class', [])):
                        unwanted.unwrap()
                    else:
                        unwanted.decompose()
                # Chỉ thêm nếu p còn nội dung
                if child.get_text(strip=True):
                    inner_html += str(child)
            elif child.name == 'div':
                for p in child.find_all('p'):
                    if p.get_text(strip=True):
                        inner_html += str(p)
            elif child.string and child.string.strip():
                # Text thường thì bọc vào p
                text = child.string.strip()
                if len(text) > 20:  # Chỉ lấy text có độ dài hợp lý
                    inner_html += f'<p>{text}</p>'
    
    # Kiểm tra nếu inner_html quá ngắn
    if not inner_html or len(inner_html.strip()) < 100:
        print(f"[WARNING] Nội dung ngắn, thử lấy text từ body")
        body = soup.find('body')
        if body:
            # Lấy text từ body, loại bỏ khoảng trắng thừa
            text = body.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 50]
            if lines:
                inner_html = ''.join([f'<p>{line}</p>' for line in lines])
            elif text:
                inner_html = f'<p>{text[:1000]}</p>'
    
    if not inner_html:
        inner_html = "<p>Không thể tải nội dung chương này</p>"
    
    # 5. TẠO HTML SẠCH
    clean_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8" />
    <title>{chapter_title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 20px; font-size: 1.5em; }}
        .chapter-content p {{ margin: 0 0 1em 0; text-align: justify; text-indent: 2em; }}
        .chapter-content p:first-of-type {{ text-indent: 0; }}
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
                if processed_chapters % 10 == 0:
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