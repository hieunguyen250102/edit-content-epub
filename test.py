import time
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List
import requests

# ==================== CẤU HÌNH ====================
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "wn-vn-14b-v0.1"
API_TIMEOUT = 300                         # 5 phút
MAX_RETRIES = 2
RETRY_DELAY = 2
MAX_CONCURRENT_API_CALLS = 4              # LM Studio hỗ trợ 4 parallel
MAX_WORKERS_FILE = 8                      # Có thể nhiều hơn, semaphore sẽ giới hạn tổng số API call
TRANSLATED_SUBDIR = "translated"
MAX_CHUNK_LENGTH = 100                    # Chunk nhỏ, có thể điều chỉnh
CHUNK_OVERLAP = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# Semaphore toàn cục để giới hạn số request đồng thời
api_semaphore = threading.Semaphore(MAX_CONCURRENT_API_CALLS)

def call_lm_studio(prompt: str) -> Optional[str]:
    """Gọi LM Studio với cơ chế retry, có kiểm soát số lượng concurrent bằng semaphore"""
    messages = [
        {
        "role": "system",
        "content": "You are a professional Chinese-to-Vietnamese webnovel translator.\n\nRules:\n- Return Vietnamese translation only.\n- Do NOT summarize.\n- Do NOT explain.\n- Do NOT add comments.\n- Do NOT add or remove story content.\n- Do NOT rewrite scenes.\n- Preserve original paragraph structure.\n- Preserve original meaning and tone.\n- Keep fast-paced webnovel narration style.\n- Use natural Vietnamese, not machine-translated wording.\n- Keep character names, locations, organizations, and terms consistent throughout the chapter.\n- Do NOT invent new names.\n- Do NOT duplicate sentences or paragraphs.\n- Translate idioms/context naturally when appropriate.\n- Keep dialogue casual and readable.\n- Avoid overly literary Vietnamese.\n- Keep humorous contrasts and comedic timing.\n- For Chinese internet/slang/webnovel terms, localize naturally into fluent Vietnamese.\n- If a term is unclear, prefer literal consistency instead of hallucinating.\n- Maintain consistent pronouns based on context.\n- Output clean Vietnamese prose only."
        },
        {"role": "user", "content": prompt}
    ]
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 512,
    }
    headers = {"Content-Type": "application/json"}

    # Acquire semaphore trước khi gọi API
    with api_semaphore:
        for attempt in range(MAX_RETRIES):
            start = time.time()
            try:
                resp = requests.post(LM_STUDIO_URL, json=payload, headers=headers, timeout=API_TIMEOUT)
                elapsed = time.time() - start
                logger.debug(f"API response in {elapsed:.1f}s")
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"].get("content", "")
                    if content:
                        content = content.strip()
                    return content if content else None
                else:
                    logger.error(f"HTTP {resp.status_code} for prompt: {prompt[:50]}")
            except requests.exceptions.Timeout:
                logger.error(f"Timeout after {API_TIMEOUT}s (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Error: {e}")
            time.sleep(RETRY_DELAY)
    return None

def translate_text_parallel(text: str, max_workers: int = MAX_CONCURRENT_API_CALLS) -> str:
    """Dịch văn bản dài bằng cách chia chunk và dịch song song"""
    if not text or not text.strip():
        return ""

    # Chia chunk
    chunks = []
    for i in range(0, len(text), MAX_CHUNK_LENGTH - CHUNK_OVERLAP):
        chunk = text[i:i+MAX_CHUNK_LENGTH]
        if chunk.strip():
            chunks.append(chunk)

    if not chunks:
        return ""
    
    logger.info(f"Split into {len(chunks)} chunks (max {MAX_CHUNK_LENGTH} chars)")
    translated_parts = [None] * len(chunks)

    # Sử dụng ThreadPoolExecutor để dịch các chunk song song
    # Số lượng worker tối đa cho chunk cũng được giới hạn bởi semaphore toàn cục
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {}
        for idx, chunk in enumerate(chunks):
            prompt = f"翻译成越南语：\n{chunk}"
            future = executor.submit(call_lm_studio, prompt)
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            result = future.result()
            translated_parts[idx] = result if result else ""
            if not result:
                logger.warning(f"Chunk {idx+1} failed -> skip")

    return "".join(translated_parts)

def translate_filename(filename: str) -> str:
    """Dịch tên file (vẫn gọi API tuần tự, không cần song song)"""
    stem = Path(filename).stem
    ext = Path(filename).suffix
    if not stem.strip():
        return filename
    prompt = f"Dịch sang tiếng Việt (chỉ tên file): {stem}"
    translated = call_lm_studio(prompt)
    if translated:
        cleaned = "".join(c for c in translated if c.isalnum() or c in " ._-")
        return cleaned + ext if cleaned else filename
    return filename

def process_one_file(src_file: Path, dst_file: Path) -> bool:
    """Xử lý một file: đọc, dịch song song các chunk, ghi kết quả"""
    try:
        with open(src_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Read error {src_file.name}: {e}")
        return False

    if not content or not content.strip():
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text("", encoding="utf-8")
        return True

    logger.info(f"📖 Translating: {src_file.name} ({len(content)} chars)")
    translated = translate_text_parallel(content)
    if not translated or not translated.strip():
        logger.error(f"❌ Translation failed: {src_file.name}")
        return False

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(translated, encoding="utf-8")
    logger.info(f"✅ Saved: {dst_file.name} ({len(translated)} chars)")
    return True

def translate_story_folder(root_folder: str):
    """Duyệt thư mục, tìm tất cả file .txt và dịch chúng sang thư mục con 'translated'"""
    root = Path(root_folder).resolve()
    dest_root = root / TRANSLATED_SUBDIR
    dest_root.mkdir(parents=True, exist_ok=True)

    all_files = [f for f in root.rglob("*.txt") if TRANSLATED_SUBDIR not in f.parts]
    logger.info(f"📁 Found {len(all_files)} .txt files")

    # Chuẩn bị danh sách (src, dst)
    tasks = []
    for src in all_files:
        rel_path = src.relative_to(root)
        new_name = translate_filename(rel_path.name)
        if rel_path.parent == Path("."):
            dst = dest_root / new_name
        else:
            dst = dest_root / rel_path.parent / new_name
        tasks.append((src, dst))

    success = 0
    # Dùng ThreadPoolExecutor cho các file, semaphore sẽ kiểm soát tổng số API call
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_FILE) as executor:
        future_to_src = {executor.submit(process_one_file, src, dst): src for src, dst in tasks}
        for future in as_completed(future_to_src):
            src = future_to_src[future]
            try:
                if future.result():
                    success += 1
                else:
                    logger.warning(f"Failed: {src.name}")
            except Exception as e:
                logger.error(f"Exception when processing {src.name}: {e}")

    logger.info(f"🎉 Done: {success}/{len(tasks)} files. Output: {dest_root}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dịch file .txt sang tiếng Việt bằng LM Studio, hỗ trợ song song 4 luồng API")
    parser.add_argument("folder", help="Đường dẫn thư mục chứa các file .txt cần dịch")
    args = parser.parse_args()
    translate_story_folder(args.folder)