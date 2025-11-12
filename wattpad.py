import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def clean_chapter_content(html_content):
    """
    Làm sạch nội dung một chương - Phiên bản cho cấu trúc wattpad.com.vn
    Giữ lại đầy đủ thông tin cho mục lục
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. XÓA HEADER & NAVIGATION
    header_selectors = [
        'header.header',  # Header chính
        '.breadcrumb',  # Breadcrumb
        '.chapter_control',  # Nút chuyển chương trên và dưới
        '#gotochap',  # Đi đến chương
        '.control-last',  # Điều khiển cuối
        '.line-control',  # Dòng điều khiển với phím tắt
        '#download-book',  # Nút tải ebook
        'button#download-book',
    ]
    
    for selector in header_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # 2. XÓA CÁC THÀNH PHẦN TƯƠNG TÁC
    interactive_elements = [
        '#binh-luan',  # Phần bình luận
        '#comment',  # Comment section
        '#comment-form', 
        '#comments-wrapper',
        '.btn-error',  # Nút báo lỗi
        '.btn-comment',  # Nút bình luận
        '.btn-dschuong',  # Nút danh sách chương
        '#browse-chapter',  # Popup danh sách chương
        '#site-setting',  # Cài đặt giao diện
        '.getcode',  # Popup loading
        '#popup', '#popup-overlay',  # Popup
        '.close-btn',  # Nút đóng
        'form',  # Form tìm kiếm
        'form[name="frmsearch"]',
        '.header-search',
    ]
    
    for element in interactive_elements:
        for tag in soup.select(element):
            tag.decompose()
    
    # 3. XÓA QUẢNG CÁO VÀ NỘI DUNG LIÊN QUAN
    ads_content = [
        'div[style*="margin-top:15px"]',  # Quảng cáo
        'script[src*="unfretarara.com"]',  # Script quảng cáo
        '#flyer',  # Banner quảng cáo flyer
        '.sp-animate',  # Quảng cáo shopee
        '.book-relate',  # Truyện liên quan
        '.chapter-container.book-relate',  # Container truyện hot
        '.full-book',  # Danh sách truyện đề xuất
        '.tag-list',  # Danh sách tag
        'footer',  # Footer
        '.contact',  # Contact info
        '.backtop',  # Nút back to top
    ]
    
    for selector in ads_content:
        for element in soup.select(selector):
            element.decompose()
    
    # 4. XÓA STYLING & SCRIPTS
    for tag in soup.find_all(['style', 'script', 'link', 'meta', 'noscript']):
        tag.decompose()
    
    # 5. XÓA COMMENTS HTML
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # 6. XÓA CÁC THẺ ẨN
    for tag in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
        tag.decompose()
    
    # 7. GIỮ LẠI NỘI DUNG CHÍNH
    kept_content = []
    
    # Tìm và giữ tiêu đề truyện và tiêu đề chương
    book_title = ""
    chapter_title = ""
    
    # Lấy tiêu đề truyện từ breadcrumb hoặc từ link trong chapter-title
    book_link = soup.find('a', href=re.compile(r'/mon-qua-kham-diem-phe-sai$'))
    if book_link:
        book_title = book_link.get_text(strip=True)
    else:
        # Fallback: lấy từ breadcrumb
        breadcrumb_items = soup.find_all('li', itemprop='itemListElement')
        if len(breadcrumb_items) >= 2:
            book_title_elem = breadcrumb_items[1].find('span', itemprop='name')
            if book_title_elem:
                book_title = book_title_elem.get_text(strip=True)
    
    # Lấy tiêu đề chương
    # Cách 1: Từ thẻ title
    title_tag = soup.find('title')
    if title_tag:
        chapter_title = title_tag.get_text(strip=True)
    
    # Cách 2: Từ h2.current-chapter
    if not chapter_title:
        chapter_h2 = soup.find('h2', class_='current-chapter')
        if chapter_h2:
            chapter_link = chapter_h2.find('a')
            if chapter_link:
                chapter_title = chapter_link.get_text(strip=True)
            else:
                chapter_title = chapter_h2.get_text(strip=True)
    
    # Cách 3: Từ breadcrumb
    if not chapter_title:
        breadcrumb_items = soup.find_all('li', itemprop='itemListElement')
        if len(breadcrumb_items) >= 3:
            chapter_elem = breadcrumb_items[2].find('span', itemprop='name')
            if chapter_elem:
                chapter_title = chapter_elem.get_text(strip=True)
    
    # Thêm tiêu đề truyện và tiêu đề chương vào kept_content
    if book_title:
        kept_content.append(f'<h2 class="book-title">{book_title}</h2>')
    
    if chapter_title:
        kept_content.append(f'<h1 class="chapter-title">{chapter_title}</h1>')
    else:
        # Fallback nếu không tìm thấy tiêu đề
        kept_content.append('<h1 class="chapter-title">Chapter</h1>')
    
    # Tìm nội dung chính - ưu tiên div có class "truyen"
    content_div = soup.find('div', class_='truyen')
    if not content_div:
        # Fallback: tìm div chứa chapter
        content_div = soup.find('div', class_='vung-doc')
    
    if content_div:
        # Xóa các phần tử không mong muốn trong content
        unwanted_in_content = [
            '.chapter_wrap',  # Wrap của chapter
            '.chapter-title',  # Tiêu đề chapter (đã thêm riêng)
            '.current-book', 
            '.current-chapter',
            '.clearfix',
        ]
        
        for selector in unwanted_in_content:
            for element in content_div.select(selector):
                element.decompose()
        
        # Giữ lại lời tác giả (nếu muốn loại bỏ thì bỏ comment dòng dưới)
        # Nếu muốn giữ lại thì comment đoạn code này
        author_note = content_div.find(string=re.compile(r'Lời tác giả|Cảnh báo', re.I))
        if author_note:
            # Giữ lại nhưng có thể thêm class để styling
            parent = author_note.find_parent()
            if parent:
                parent['class'] = parent.get('class', []) + ['author-note']
        
        # Làm sạch nội dung
        # Xóa các thẻ rỗng
        for tag in content_div.find_all():
            if (len(tag.get_text(strip=True)) == 0 and 
                not tag.find_all(['img', 'br', 'hr']) and
                tag.name not in ['br', 'hr', 'img']):
                tag.decompose()
        
        kept_content.append(str(content_div))
    else:
        # Fallback cuối: giữ body
        body_content = soup.find('body')
        if body_content:
            # Xóa tất cả các thẻ không phải nội dung chính
            for tag in body_content.find_all(['header', 'footer', 'nav', 'aside']):
                tag.decompose()
            kept_content.append(str(body_content))
    
    # Tạo HTML sạch với cấu trúc rõ ràng cho mục lục
    clean_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <meta charset="utf-8" />
    <title>{chapter_title if chapter_title else 'Chapter'}</title>
    <style>
        body {{ 
            font-family: 'Open Sans', Arial, sans-serif; 
            line-height: 1.8; 
            margin: 30px auto; 
            max-width: 800px;
            padding: 20px;
            background-color: #fafaf3;
            color: #000000;
        }}
        h1 {{ 
            text-align: center; 
            color: #c0392b; 
            margin-bottom: 10px; 
            font-size: 24px;
            font-weight: 700;
        }}
        h2.book-title {{
            text-align: center;
            color: #666;
            margin-bottom: 5px;
            font-size: 18px;
            font-weight: 500;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
        }}
        p {{ 
            margin-bottom: 20px; 
            text-align: justify;
            font-size: 20px;
        }}
        .author-note {{
            margin-top: 30px;
            padding: 15px;
            background-color: #f5f5f5;
            border-left: 4px solid #c0392b;
            font-style: italic;
        }}
    </style>
</head>
<body>
    {''.join(kept_content)}
</body>
</html>"""
    
    return clean_html

def optimize_epub_structure(book):
    """
    Tối ưu cấu trúc EPUB sau khi làm sạch
    Giữ nguyên thứ tự các chương
    """
    clean_spine = []
    
    # Lấy tất cả các item và sắp xếp theo thứ tự
    items_with_ref = []
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Kiểm tra tên file để xác định thứ tự
            name = item.get_name().lower()
            if any(keyword in name for keyword in ['chapter', 'text', 'chuong', 'doc']):
                # Thử lấy số chương từ tên file
                chapter_num = None
                match = re.search(r'chuong[.-]?(\d+)', name)
                if match:
                    chapter_num = int(match.group(1))
                items_with_ref.append((chapter_num, item))
            else:
                # Nếu không phải chương, vẫn thêm vào nhưng không cần số thứ tự
                items_with_ref.append((float('inf'), item))
    
    # Sắp xếp theo số chương (nếu có), giữ nguyên thứ tự nếu không có số
    items_with_ref.sort(key=lambda x: (x[0] if x[0] is not None else float('inf'), x[1].get_name()))
    
    clean_spine = [item for _, item in items_with_ref]
    
    return clean_spine

def clean_complete_epub(input_path, output_path):
    """
    Xử lý toàn bộ file EPUB với cấu trúc wattpad mới
    """
    print("Đang đọc file EPUB...")
    book = epub.read_epub(input_path)
    
    total_chapters = 0
    processed_chapters = 0
    
    # Đếm tổng số chương
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            total_chapters += 1
    
    print(f"Tổng số chương cần xử lý: {total_chapters}")
    
    # Xử lý từng chương
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
    
    # Tối ưu cấu trúc
    print("Đang tối ưu cấu trúc EPUB...")
    book.spine = optimize_epub_structure(book)
    
    # Ghi file output
    print("Đang ghi file EPUB mới...")
    epub.write_epub(output_path, book, {})
    
    print(f"✅ HOÀN THÀNH!")
    print(f"📁 Input: {input_path}")
    print(f"📁 Output: {output_path}")
    print(f"📊 Đã xử lý: {processed_chapters}/{total_chapters} chương")

# SỬ DỤNG
if __name__ == "__main__":
    input_file = "input.epub"  # File EPUB từ wattpad.com.vn
    output_file = "output_cleaned.epub"
    
    clean_complete_epub(input_file, output_file)
