import time
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, Comment
from ebooklib import epub
import ebooklib

# ================== CẤU HÌNH LM STUDIO ==================
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "wn-vn-14b-v0.1"
MAX_CHUNK_LENGTH = 1000
MAX_WORKERS = 4
TRANSLATION_TIMEOUT = 60
# ========================================================

def check_lm_studio():
    """Kiểm tra LM Studio có hoạt động không."""
    try:
        resp = requests.get("http://localhost:1234/v1/models", timeout=5)
        if resp.status_code == 200:
            print("✅ LM Studio đang chạy và sẵn sàng.")
            return True
        else:
            print("⚠️ LM Studio trả về status code:", resp.status_code)
            return False
    except Exception as e:
        print(f"❌ Không thể kết nối LM Studio: {e}")
        print("   Hãy đảm bảo LM Studio đã mở và server local đang chạy (cổng 1234).")
        return False

def translate_text_chunk(chunk: str, chunk_index: int) -> tuple:
    print(f"[DEBUG] Đang dịch chunk {chunk_index}, độ dài {len(chunk)} ký tự")
    system_prompt = (
        "You are a professional translator. Translate the following text "
        "to Vietnamese. Only output the translation, no extra explanation. "
        "The text may be in Chinese or English, translate to Vietnamese."
    )
    user_prompt = chunk
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    try:
        resp = requests.post(LM_STUDIO_URL, json=payload, timeout=TRANSLATION_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        translated = data["choices"][0]["message"]["content"].strip()
        return chunk_index, translated
    except Exception as e:
        print(f"[LỖI DỊCH] chunk {chunk_index}: {e}")
        return chunk_index, chunk

def split_long_text(text: str, max_len: int = MAX_CHUNK_LENGTH) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = []
    current = ""
    sentences = re.split(r'(?<=[.!?;:\n])\s+', text)
    for sent in sentences:
        if len(current) + len(sent) + 1 <= max_len:
            current += (sent + " ")
        else:
            if current:
                chunks.append(current.strip())
            if len(sent) > max_len:
                for i in range(0, len(sent), max_len):
                    chunks.append(sent[i:i+max_len])
                current = ""
            else:
                current = sent + " "
    if current:
        chunks.append(current.strip())
    return chunks

def translate_paragraph(para_text: str) -> str:
    if not para_text or len(para_text.strip()) == 0:
        return para_text
    chunks = split_long_text(para_text)
    if len(chunks) == 1:
        _, translated = translate_text_chunk(chunks[0], 0)
        return translated
    else:
        translated_chunks = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(chunks))) as executor:
            futures = {executor.submit(translate_text_chunk, chunk, i): i for i, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                idx, translated = future.result()
                translated_chunks[idx] = translated
        return " ".join(translated_chunks)

def translate_html_content(html_content: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    content_div = soup.find('div', class_='chapter-content')
    if not content_div:
        print("[WARN] Không tìm thấy div.chapter-content, giữ nguyên.")
        return html_content

    # Lấy tất cả các thẻ con trực tiếp có text đáng kể
    elements_to_translate = []
    for child in content_div.children:
        if child.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # Chỉ lấy nếu có text không rỗng
            if child.get_text(strip=True):
                elements_to_translate.append(child)
        elif child.string and child.string.strip():
            # Nếu là text node, bọc trong <p> tạm
            p = soup.new_tag('p')
            p.string = child.string
            child.replace_with(p)
            elements_to_translate.append(p)

    if not elements_to_translate:
        # Trường hợp toàn bộ là text trong div (không có thẻ con)
        all_text = content_div.get_text(separator="\n", strip=True)
        if all_text:
            print(f"[DEBUG] Dịch toàn bộ nội dung div, {len(all_text)} ký tự")
            translated = translate_paragraph(all_text)
            content_div.clear()
            new_p = soup.new_tag('p')
            new_p.string = translated
            content_div.append(new_p)
        return str(soup)

    print(f"[DEBUG] Tìm thấy {len(elements_to_translate)} phần tử cần dịch trong chương này")

    def process_element(el):
        original = el.get_text(separator=" ", strip=True)
        if original:
            print(f"[DEBUG] Dịch phần tử {el.name} dài {len(original)} ký tự")
            translated = translate_paragraph(original)
            el.clear()
            el.append(translated)
        return el

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_element, el): el for el in elements_to_translate}
        for future in as_completed(futures):
            future.result()
    return str(soup)

def extract_chapter_title(soup):
    patterns = [
        r'Chương\s+(\d+)\s*:\s*([^<>\n]+)',
        r'Chương\s+(\d+)',
        r'Chapter\s+(\d+)\s*:\s*([^<>\n]+)',
    ]
    candidates = []
    for tag in soup.find_all(['a', 'h2', 'h1', 'h3', 'h4', 'title']):
        text = tag.get_text(strip=True)
        if text:
            candidates.append(text)
    for tag in soup.find_all(class_=re.compile(r'title', re.I)):
        text = tag.get_text(strip=True)
        if text and len(text) < 200:
            candidates.append(text)
    if not candidates:
        body = soup.find('body')
        if body:
            for text in body.strings:
                if text and 'chương' in text.lower():
                    candidates.append(text.strip())
                    break
    for text in candidates:
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    return f"Chương {match.group(1)}: {match.group(2).strip()}"
                else:
                    return f"Chương {match.group(1)}"
    h1_tag = soup.find('h1')
    if h1_tag:
        return h1_tag.get_text(strip=True)
    title_tag = soup.find('title')
    if title_tag:
        return title_tag.get_text(strip=True)
    return "Chương"

def clean_chapter_content(html_content, translate=False):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Xóa rác (giữ nguyên như cũ)
    header_selectors = ['#nav', '.navbar', '.navbar-breadcrumb', '#header-ads', '#header-ads-full',
        '.header-ads', '.header-ads-full', '#ads-head', '#ads-install-app']
    for selector in header_selectors:
        for element in soup.select(selector):
            element.decompose()
    nav_selectors = ['.chapter-nav', '#chapter-nav-top', '#chapter-nav-bot', '.btn-chapter-nav',
        '#prev_chap', '#next_chap', '.chapter_jump', '#chapter_error', '#chapter_comment']
    for selector in nav_selectors:
        for element in soup.select(selector):
            element.decompose()
    ad_selectors = ['[id*="ads"]', '[class*="ads"]', '.adfill', '.ads-responsive', '#ads-chapter-pc-top',
        '#ads-adsVtri1', '#ads-chapter-bottom', '#ads-chapter-bottom-lien-quan',
        '#ads-flyicon', '#ads-xuyentrang-bottom', '#catfish-bottom-sp', '#ads_xuyen_trang_bottom',
        '.show_ads_google', '.box-notice', '.text-link-bottom']
    for selector in ad_selectors:
        for element in soup.select(selector):
            element.decompose()
    comment_selectors = ['#fb-comment-chapter', '#fb-root', '.fb_reset', '[class*="comment"]']
    for selector in comment_selectors:
        for element in soup.select(selector):
            element.decompose()
    footer_selectors = ['#footer', '.footer', '.text-link-bottom']
    for selector in footer_selectors:
        for element in soup.select(selector):
            element.decompose()
    for tag in soup.find_all(['style', 'script', 'link', 'noscript']):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
        tag.decompose()
    
    chapter_title = extract_chapter_title(soup)
    print(f"[DEBUG] Tiêu đề chương: {chapter_title}")
    
    # Lấy nội dung chính
    content_div = soup.find('div', id='chapter-c')
    if not content_div:
        content_div = soup.find('div', class_=re.compile(r'chapter-c', re.I))
    if not content_div:
        body = soup.find('body')
        if body:
            content_div = body.find('div')
    if not content_div:
        content_div = soup.find('body')
    
    if content_div:
        for unwanted in content_div.find_all(['h1', 'h2']):
            unwanted.decompose()
        inner_html = ''.join(str(child) for child in content_div.children)
    else:
        inner_html = "<p>Không có nội dung</p>"
    
    # Dịch nếu yêu cầu
    if translate:
        print(f"[DEBUG] Bắt đầu dịch chương: {chapter_title}")
        temp_html = f'<div class="chapter-content">{inner_html}</div>'
        translated_html = translate_html_content(temp_html)
        temp_soup = BeautifulSoup(translated_html, 'html.parser')
        new_content = temp_soup.find('div', class_='chapter-content')
        if new_content:
            inner_html = ''.join(str(child) for child in new_content.children)
        else:
            print("[WARN] Không lấy được nội dung đã dịch, giữ nguyên.")
    
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

def clean_complete_epub(input_path, output_path, translate=False):
    start_time = time.time()
    if translate and not check_lm_studio():
        print("❌ LM Studio không sẵn sàng. Hủy dịch.")
        return

    print("Đang đọc file EPUB...")
    book = epub.read_epub(input_path)
    
    total_chapters = 0
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            total_chapters += 1
    print(f"Tổng số chương: {total_chapters}")
    if translate:
        print(f"*** Chế độ DỊCH bật (LM Studio: {MODEL_NAME}, workers={MAX_WORKERS}, chunk={MAX_CHUNK_LENGTH}) ***")
    
    processed = 0
    # Biến để tính trung bình thời gian mỗi chương (dùng moving average)
    avg_time_per_chapter = None
    
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            try:
                chapter_start = time.time()
                content = item.get_content().decode('utf-8')
                cleaned = clean_chapter_content(content, translate=translate)
                item.set_content(cleaned.encode('utf-8'))
                processed += 1
                chapter_elapsed = time.time() - chapter_start
                
                # Cập nhật thời gian trung bình
                if avg_time_per_chapter is None:
                    avg_time_per_chapter = chapter_elapsed
                else:
                    # Moving average (càng về sau càng chính xác)
                    avg_time_per_chapter = 0.9 * avg_time_per_chapter + 0.1 * chapter_elapsed
                # Tính ETA
                remaining = total_chapters - processed
                eta_seconds = avg_time_per_chapter * remaining
                eta_minutes = eta_seconds / 60
                eta_hours = eta_minutes / 60
                
                if eta_hours >= 1:
                    eta_str = f"{eta_hours:.1f} giờ"
                elif eta_minutes >= 1:
                    eta_str = f"{eta_minutes:.1f} phút"
                else:
                    eta_str = f"{eta_seconds:.0f} giây"
                
                # In tiến độ + ETA (mỗi 5 chương hoặc chương đầu/cuối)
                if processed == 1 or processed % 5 == 0 or processed == total_chapters:
                    percent = processed / total_chapters * 100
                    print(f"📊 Tiến độ: {processed}/{total_chapters} ({percent:.1f}%) - ETA: {eta_str}")
            
            except Exception as e:
                print(f"❌ Lỗi xử lý {item.get_name()}: {e}")
    
    book.spine = optimize_epub_structure(book)
    epub.write_epub(output_path, book, {})
    
    elapsed = time.time() - start_time
    print(f"✅ Hoàn thành! {processed}/{total_chapters} chương trong {elapsed:.2f} giây ({elapsed/60:.2f} phút)")
if __name__ == "__main__":
    input_file = "input.epub"
    output_file = "out_cleaned.epub"
    clean_complete_epub(input_file, output_file, translate=True)