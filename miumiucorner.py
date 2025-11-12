import os
import re
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

def clean_chapter_content(html_content):
    """
    Làm sạch nội dung một chương - Phiên bản tối ưu cho WordPress
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # XÓA TOÀN BỘ PHẦN KHÔNG CẦN THIẾT
    elements_to_remove = [
        # Header và navigation
        'header', 'nav', '.wp-block-template-part',
        
        # Comments và forms
        '.wp-block-comments', '#comments', '.comment-respond',
        '.wp-block-post-comments-form', '.comment-form',
        '.wp-block-comment-template', '.commentlist',
        
        # Sidebar và footer
        'footer', '.wp-block-template-part footer',
        
        # Scripts và styles
        'script', 'style', 'link', 'meta', 'noscript',
        
        # WordPress specific
        '#jp-post-flair', '.sharedaddy', '.sd-like-enabled',
        '.sd-sharing-enabled', '.jp-relatedposts',
        
        # Action bar và các thành phần WordPress
        '#actionbar', 
        'div[class*="actnbr-"]',  # Thay .actnbr-* bằng cách này
        '.comment-likes',
        '.jetpack-reblog-enabled', 
        
        # Các thành phần phụ khác
        '.wp-block-post-author-name', 
        '.wp-block-post-date',
        '.wp-block-post-terms', 
        '.wp-block-avatar',
        '.wp-block-post-navigation-link',
        '.wp-block-separator', 
        '.wp-block-spacer',
        '.wp-block-buttons', 
        '.wp-block-button',
        
        # Các div rác
        'div[style*="display:none"]',
        'div[style*="display: none"]',
        'div[class*="grofile-hash-map"]',  # Thay .grofile-hash-map-* bằng cách này
    ]
    
    for selector in elements_to_remove:
        try:
            for element in soup.select(selector):
                element.decompose()
        except Exception as e:
            # Nếu selector không hợp lệ, thử phương pháp khác
            if '*' in selector:
                # Xử lý selector có dấu * bằng find_all với attribute contains
                if selector.startswith('div[class*="'):
                    class_pattern = selector.split('"')[1]
                    for element in soup.find_all('div', class_=lambda x: x and class_pattern in x):
                        element.decompose()
                elif selector.startswith('div[id*="'):
                    id_pattern = selector.split('"')[1]
                    for element in soup.find_all('div', id=lambda x: x and id_pattern in x):
                        element.decompose()
    
    # XÓA CÁC COMMENT
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    # XÓA CÁC THUỘC TÍNH KHÔNG CẦN THIẾT
    for tag in soup.find_all(True):
        # Giữ lại các thuộc tính cần thiết
        allowed_attrs = ['class', 'id', 'src', 'href', 'alt', 'title', 'style']
        attrs_to_remove = []
        for attr in tag.attrs:
            if attr not in allowed_attrs:
                attrs_to_remove.append(attr)
        for attr in attrs_to_remove:
            del tag[attr]
    
    # GIỮ LẠI NỘI DUNG QUAN TRỌNG
    kept_content = []
    
    # 1. TÌM VÀ GIỮ TIÊU ĐỀ CHƯƠNG
    chapter_title = None
    
    # Đọc title từ file name hoặc nội dung
    title_from_file = None
    
    # Ưu tiên 1: Tìm thẻ title trong head
    title_tag = soup.find('title')
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        # Tách phần "Chương X:" từ title
        match = re.search(r'(Chương\s+\d+[:\s]+[^––]+)', title_text, re.IGNORECASE)
        if match:
            chapter_title = match.group(1).strip()
        else:
            # Nếu không tìm thấy theo pattern, lấy toàn bộ title
            chapter_title = title_text
    
    # Ưu tiên 2: Tìm thẻ h1 với class wp-block-post-title
    if not chapter_title:
        title_tag = soup.find('h1', class_='wp-block-post-title')
        if title_tag:
            chapter_title = title_tag.get_text(strip=True)
    
    # Ưu tiên 3: Tìm thẻ h1 bất kỳ
    if not chapter_title:
        h1_tags = soup.find_all('h1')
        for h1 in h1_tags:
            text = h1.get_text(strip=True)
            if 'chương' in text.lower() or 'chapter' in text.lower():
                chapter_title = text
                break
    
    if chapter_title:
        kept_content.append(f'<h1>{chapter_title}</h1>')
    else:
        kept_content.append('<h1>Chapter</h1>')
    
    # 2. TÌM VÀ GIỮ NỘI DUNG CHÍNH
    content_found = False
    
    # Ưu tiên 1: Tìm div có class entry-content hoặc wp-block-post-content
    content_div = soup.find('div', class_='entry-content')
    if not content_div:
        content_div = soup.find('div', class_='wp-block-post-content')
    
    if content_div:
        # Làm sạch nội dung trong div
        clean_content_div(content_div)
        kept_content.append(str(content_div))
        content_found = True
    
    # Ưu tiên 2: Tìm các đoạn văn trong main
    if not content_found:
        main_tag = soup.find('main')
        if main_tag:
            # Tìm tất cả các đoạn văn, không chỉ wp-block-paragraph
            paragraphs = main_tag.find_all('p')
            valid_paragraphs = []
            for p in paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 10 and not is_junk_text(text):
                    valid_paragraphs.append(p)
            
            if len(valid_paragraphs) > 2:
                content_wrapper = soup.new_tag('div')
                content_wrapper['class'] = 'chapter-content'
                for p in valid_paragraphs:
                    # Xử lý emoji
                    for img in p.find_all('img', class_='emoji'):
                        # Thay thế emoji bằng text tương ứng nếu có thể
                        alt_text = img.get('alt', '')
                        if alt_text:
                            img.replace_with(alt_text)
                        else:
                            img.decompose()
                    content_wrapper.append(p)
                if len(content_wrapper.find_all('p')) > 0:
                    kept_content.append(str(content_wrapper))
                    content_found = True
    
    # Ưu tiên 3: Tìm tất cả các đoạn văn trong body
    if not content_found:
        body = soup.find('body')
        if body:
            paragraphs = body.find_all('p')
            valid_paragraphs = []
            for p in paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 10 and not is_junk_text(text):
                    valid_paragraphs.append(p)
            
            if len(valid_paragraphs) > 2:
                content_wrapper = soup.new_tag('div')
                content_wrapper['class'] = 'chapter-content'
                for p in valid_paragraphs:
                    # Xử lý emoji
                    for img in p.find_all('img', class_='emoji'):
                        alt_text = img.get('alt', '')
                        if alt_text:
                            img.replace_with(alt_text)
                        else:
                            img.decompose()
                    content_wrapper.append(p)
                if len(content_wrapper.find_all('p')) > 0:
                    kept_content.append(str(content_wrapper))
                    content_found = True
    
    # Nếu vẫn không tìm thấy, giữ lại nội dung gốc đã được làm sạch
    if not content_found:
        body = soup.find('body')
        if body:
            clean_content_div(body)
            kept_content.append(str(body))
    
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
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            line-height: 1.8; 
            margin: 20px; 
            text-align: justify;
            color: #111;
            max-width: 800px;
            margin-left: auto;
            margin-right: auto;
        }}
        h1 {{ 
            text-align: center; 
            color: #333; 
            margin-bottom: 30px; 
            font-size: 1.8em;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
            font-weight: 600;
        }}
        .chapter-content {{
            width: 100%;
        }}
        p {{ 
            margin-bottom: 20px; 
            text-indent: 2em;
            font-size: 1.1em;
        }}
        p:first-of-type {{
            margin-top: 0;
        }}
        /* Không thụt đầu dòng cho các đoạn đặc biệt */
        p[style*="text-align:center"],
        p:has(> strong:only-child),
        p:has(> em:only-child) {{
            text-indent: 0;
        }}
        hr {{
            border: none;
            border-top: 2px solid #ddd;
            margin: 30px auto;
            width: 50px;
        }}
        /* Giữ lại định dạng cho các thẻ cơ bản */
        strong, b {{ font-weight: bold; }}
        em, i {{ font-style: italic; }}
    </style>
</head>
<body>
    {''.join(kept_content)}
</body>
</html>"""
    
    return clean_html

def is_junk_text(text):
    """Kiểm tra xem text có phải là rác không"""
    junk_patterns = [
        r'^Bình luận$',
        r'^Chia sẻ:$',
        r'^Đang tải\.\.\.$',
        r'^Thích$',
        r'^Trả lời$',
        r'^bình luận',
        r'^comment',
        r'^share',
        r'^facebook',
        r'^twitter',
        r'^wordpress\.com',
        r'^Đã có \d+ người theo dõi',
    ]
    
    for pattern in junk_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def clean_content_div(div):
    """Làm sạch nội dung trong div"""
    # Xóa các thẻ không cần thiết bên trong
    unwanted_tags = ['script', 'style', 'iframe', 'form', 'input', 'button', 'noscript']
    for tag in unwanted_tags:
        for element in div.find_all(tag):
            element.decompose()
    
    # Xử lý các thẻ div không cần thiết
    for div_tag in div.find_all('div'):
        # Nếu div không có class hoặc chỉ có class rác
        if not div_tag.get('class') or all(c in ['wp-block-group', 'has-global-padding'] for c in div_tag.get('class', [])):
            # Giữ lại nội dung bên trong
            div_tag.unwrap()
    
    # Xóa các thuộc tính không cần thiết nhưng giữ lại class có ích
    for tag in div.find_all(True):
        if tag.attrs:
            allowed_classes = ['wp-block-paragraph', 'has-text-align-center', 
                             'has-background', 'chapter-content']
            new_attrs = {}
            if 'class' in tag.attrs:
                # Giữ lại các class có ích
                useful_classes = []
                for c in tag['class']:
                    for ac in allowed_classes:
                        if ac in c:
                            useful_classes.append(c)
                            break
                if useful_classes:
                    new_attrs['class'] = useful_classes
            if 'style' in tag.attrs and tag.name == 'p':
                # Giữ lại style text-align cho paragraph
                style = tag['style']
                if 'text-align' in style:
                    new_attrs['style'] = style
            tag.attrs = new_attrs
    
    # Xóa các thẻ rỗng
    for tag in div.find_all():
        if not tag.get_text(strip=True) and not tag.find_all(['img', 'br', 'hr']):
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
            if any(keyword in name for keyword in ['chng', 'chuong', 'chapter', 'text', 'post']):
                clean_spine.append(item)
            elif 'index' not in name and 'nav' not in name and 'comment' not in name:
                # Kiểm tra nội dung có phải là chapter không
                try:
                    content = item.get_content().decode('utf-8')
                    if 'chương' in content.lower() or 'chapter' in content.lower():
                        clean_spine.append(item)
                except:
                    pass
    
    return clean_spine

def clean_complete_epub(input_path, output_path):
    """
    Xử lý toàn bộ file EPUB với cấu trúc WordPress
    """
    print("Đang đọc file EPUB...")
    book = epub.read_epub(input_path)
    
    total_items = 0
    processed_items = 0
    chapter_count = 0
    
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
                    # Kiểm tra nếu có dấu hiệu của chapter
                    if 'chương' in content.lower() or 'chapter' in content.lower() or 'post' in content.lower():
                        cleaned_content = clean_chapter_content(content)
                        item.set_content(cleaned_content.encode('utf-8'))
                        chapter_count += 1
                        print(f"  ✅ Đã xử lý chapter: {item.get_name()}")
                    else:
                        # Vẫn xử lý nhưng không đếm là chapter
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
    print(f"📚 Số chương đã xử lý: {chapter_count}")

# SỬ DỤNG
if __name__ == "__main__":
    input_file = "input.epub"  # File EPUB của bạn
    output_file = "out_cleaned.epub"
    
    clean_complete_epub(input_file, output_file)
