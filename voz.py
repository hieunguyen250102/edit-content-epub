import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def clean_chapter_content(html_content):
    """
    Làm sạch nội dung một chương - Phiên bản cho cấu trúc VOZ
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. XÓA HEADER & NAVIGATION
    header_selectors = [
        'div.bg-black',  # Header chính
        'div.bg-gray-200',  # Breadcrumb
        'button#theme-toggle',  # Nút theme
        'div.float-left', 'div.float-right',  # Logo và controls
    ]
    
    for selector in header_selectors:
        for element in soup.select(selector):
            element.decompose()
    
    # 2. XÓA CONTROLS & INTERACTIVE
    interactive_elements = [
        'a#readButton',  # Nút "Đọc to"
        '#binh-luan',  # Phần bình luận
        '#comment-form', '#comments-wrapper',  # Form và list comments
        'form',  # Tất cả form
    ]
    
    for element in interactive_elements:
        for tag in soup.select(element):
            tag.decompose()
    
    # 3. XÓA RELATED CONTENT & FOOTER
    related_content = [
        'div.bg-green-001',  # "Quay lại truyện"
        'a[href*="post/create"]',  # Nút "Đăng Truyện"
        'div.bg-white.shadow',  # Danh sách truyện đề xuất
        'div.bg-siver-001',  # Footer
        'div.flex-1',  # Copyright
        'div.m-2',  # 🆕 CODE MỚI THÊM VÀO ĐÂY
    ]
    
    for selector in related_content:
        for element in soup.select(selector):
            element.decompose()
    
    # 4. XÓA STYLING & SCRIPTS
    for tag in soup.find_all(['style', 'script']):
        tag.decompose()
    
    # 5. XÓA COMMENTS
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # 6. XÓA CÁC THẺ ẨN
    for tag in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
        tag.decompose()
    
    # GIỮ LẠI NỘI DUNG QUAN TRỌNG
    kept_content = []
    
    # Tìm và giữ tiêu đề chương
    chapter_title = soup.find('h1', class_=re.compile(r'text-lg.*font-bold.*text-center', re.I))
    if chapter_title:
        title_text = chapter_title.get_text(strip=True)
        kept_content.append(f'<h1>{title_text}</h1>')
    else:
        # Fallback: lấy từ thẻ title
        title_tag = soup.find('title')
        if title_tag:
            kept_content.append(f'<h1>{title_tag.get_text(strip=True)}</h1>')
    
    # Tìm và giữ nội dung chính
    content_div = soup.find('div', id='content')
    if not content_div:
        # Fallback: tìm div chứa chapter
        content_div = soup.find('div', id=re.compile(r'chapter', re.I))
    
    if content_div:
        # Tìm các phần tử chứa text note (thường là thẻ p, div, hoặc span)
        note_elements = content_div.find_all(['p', 'div', 'span'], string=re.compile(r'Note:.*Sắp tới', re.I))
        for element in note_elements:
            element.decompose()

        # Hoặc tìm theo class nếu có
        note_by_class = content_div.find_all(class_=re.compile(r'note|thong-bao|notify', re.I))
        for element in note_by_class:
            element.decompose()
        # Làm sạch nội dung cuối cùng
        # Xóa link đề xuất cuối nội dung
        for promo_link in content_div.find_all('a', class_=re.compile(r'font-bold.*text-green-001', re.I)):
            promo_link.decompose()
        
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
            kept_content.append(str(body_content))
    
    # Tạo HTML sạch
    title_text = chapter_title.get_text(strip=True) if chapter_title else 'Chapter'
    clean_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8" />
    <title>{title_text}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 20px; }}
        h1 {{ text-align: center; color: #333; margin-bottom: 20px; }}
        p {{ margin-bottom: 15px; text-align: justify; }}
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
    """
    clean_spine = []
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Chỉ thêm vào spine nếu là chương truyện
            if any(keyword in item.get_name().lower() for keyword in ['chapter', 'text', 'chuong']):
                clean_spine.append(item)
    
    return clean_spine

def clean_complete_epub(input_path, output_path):
    """
    Xử lý toàn bộ file EPUB với cấu trúc VOZ mới
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
                
                if processed_chapters % 100 == 0:
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
    input_file = "input.epub"  # File EPUB mới của bạn
    output_file = "out_cleaned.epub"
    
    clean_complete_epub(input_file, output_file)
