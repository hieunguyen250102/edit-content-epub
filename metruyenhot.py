import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def clean_chapter_content(html_content):
    """
    Làm sạch nội dung một chương - Phiên bản tối ưu cho metruyenhot.me
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # XÓA TOÀN BỘ PHẦN KHÔNG CẦN THIẾT
    elements_to_remove = [
        'div.section-header',  # Header trang
        'div.section-breadcrumb',  # Breadcrumb
        'div.notice', 'div.box-notice',  # Thông báo quảng cáo
        'div#fbcomment', 'div.comment-facebook',  # Phần bình luận
        'div.section-footer',  # Footer
        'ul.menu.breadcrumb',  # Menu breadcrumb
        'input', 'form',  # Các trường input và form
        'style', 'script',  # CSS và JS
    ]
    
    for selector in elements_to_remove:
        for element in soup.select(selector):
            element.decompose()
    
    # XÓA CÁC COMMENT
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # GIỮ LẠI NỘI DUNG QUAN TRỌNG
    kept_content = []
    
    # 1. TÌM VÀ GIỮ TIÊU ĐỀ CHƯƠNG
    chapter_title = None
    
    # Ưu tiên 1: Tìm theo class rv-chapt-title
    title_div = soup.find('div', class_='rv-chapt-title')
    if title_div:
        chapter_title = title_div.get_text(strip=True)
    else:
        # Ưu tiên 2: Tìm thẻ h2
        h2_tags = soup.find_all('h2')
        for h2 in h2_tags:
            if 'chương' in h2.get_text().lower():
                chapter_title = h2.get_text(strip=True)
                break
    
    if chapter_title:
        kept_content.append(f'<h1>{chapter_title}</h1>')
    
    # 2. TÌM VÀ GIỮ NỘI DUNG CHÍNH
    content_found = False
    
    # Ưu tiên 1: Tìm div có class chapter-c
    content_div = soup.find('div', class_='chapter-c')
    if content_div:
        # Làm sạch nội dung trong div
        clean_content_div(content_div)
        kept_content.append(str(content_div))
        content_found = True
    
    # Ưu tiên 2: Tìm div có chứa các đoạn văn
    if not content_found:
        content_divs = soup.find_all('div')
        for div in content_divs:
            # Tìm div chứa nhiều thẻ p (đoạn văn)
            paragraphs = div.find_all('p')
            if len(paragraphs) > 3:  # Nếu có ít nhất 4 đoạn văn
                clean_content_div(div)
                kept_content.append(str(div))
                content_found = True
                break
    
    # Ưu tiên 3: Tìm trực tiếp các đoạn văn
    if not content_found:
        paragraphs = soup.find_all('p')
        if len(paragraphs) > 3:
            content_wrapper = soup.new_tag('div')
            for p in paragraphs:
                if len(p.get_text(strip=True)) > 10:  # Chỉ lấy đoạn văn có nội dung
                    content_wrapper.append(p)
            if len(content_wrapper.find_all('p')) > 0:
                kept_content.append(str(content_wrapper))
                content_found = True
    
    # Tạo HTML sạch
    title_text = chapter_title if chapter_title else "Chapter"
    
    clean_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8" />
    <title>{title_text}</title>
    <style>
        body {{ 
            font-family: Arial, sans-serif; 
            line-height: 1.8; 
            margin: 20px; 
            text-align: justify;
        }}
        h1 {{ 
            text-align: center; 
            color: #333; 
            margin-bottom: 30px; 
            font-size: 1.5em;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
        }}
        p {{ 
            margin-bottom: 20px; 
            text-indent: 2em;
        }}
        div {{ margin: 0; padding: 0; }}
    </style>
</head>
<body>
    {''.join(kept_content)}
</body>
</html>"""
    
    return clean_html

def clean_content_div(div):
    """Làm sạch nội dung trong div"""
    # Xóa các thẻ không cần thiết bên trong
    unwanted_tags = ['script', 'style', 'div', 'span']
    for tag in unwanted_tags:
        for element in div.find_all(tag):
            # Giữ lại div nếu nó chứa nội dung quan trọng
            if tag == 'div':
                if not element.get_text(strip=True):
                    element.decompose()
                else:
                    # Thay thẻ div bằng nội dung bên trong
                    element.unwrap()
            else:
                element.decompose()
    
    # Xóa các thuộc tính style
    for tag in div.find_all(True):
        if tag.attrs:
            tag.attrs = {}
    
    # Xóa các thẻ rỗng
    for tag in div.find_all():
        if not tag.get_text(strip=True) and not tag.find_all(['img', 'br']):
            tag.decompose()

def optimize_epub_structure(book):
    """
    Tối ưu cấu trúc EPUB sau khi làm sạch
    """
    clean_spine = []
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Chỉ thêm vào spine nếu là chương truyện
            name = item.get_name().lower()
            if any(keyword in name for keyword in ['chapter', 'text', 'chuong', 'part']):
                clean_spine.append(item)
            elif 'index' not in name and 'nav' not in name:
                clean_spine.append(item)
    
    return clean_spine

def clean_complete_epub(input_path, output_path):
    """
    Xử lý toàn bộ file EPUB với cấu trúc metruyenhot.me
    """
    print("Đang đọc file EPUB...")
    book = epub.read_epub(input_path)
    
    total_items = 0
    processed_items = 0
    
    # Đếm tổng số items
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            total_items += 1
    
    print(f"Tổng số items cần xử lý: {total_items}")
    
    # Xử lý từng item
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            try:
                content = item.get_content().decode('utf-8')
                
                # Chỉ xử lý nếu có nội dung đáng kể
                if len(content.strip()) > 100:
                    cleaned_content = clean_chapter_content(content)
                    item.set_content(cleaned_content.encode('utf-8'))
                
                processed_items += 1
                
                if processed_items % 10 == 0:
                    print(f"Đã xử lý {processed_items}/{total_items} items")
                    
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
    print(f"📊 Đã xử lý: {processed_items}/{total_items} items")

# SỬ DỤNG
if __name__ == "__main__":
    input_file = "input.epub"  # File EPUB của bạn
    output_file = "out_cleaned.epub"
    
    clean_complete_epub(input_file, output_file)
