import time
import logging
import json
import re
import threading
from pathlib import Path
from typing import Optional, Dict
import requests

# ==================== CẤU HÌNH ====================
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "wn-vn-14b-v0.1"
API_TIMEOUT = 600
MAX_RETRIES = 2
RETRY_DELAY = 2
MAX_CONCURRENT_API_CALLS = 1
MAX_WORKERS_FILE = 1
TRANSLATED_SUBDIR = "translated"
GLOSSARY_FILE = "glossary.json"
TEMPERATURE = 0.0
MAX_TOKENS = 3072
STOP_TOKENS = ["```", "\n\n\n\n"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

api_semaphore = threading.Semaphore(MAX_CONCURRENT_API_CALLS)

# ==================== GLOSSARY MANAGER ====================
class GlossaryManager:
    def __init__(self, glossary_path: Path):
        self.glossary_path = glossary_path
        self.glossary: Dict[str, str] = {}  # Chinese -> Vietnamese
        self._lock = threading.Lock()
        self._ensure_exists()

    def _ensure_exists(self):
        if not self.glossary_path.exists():
            self.glossary_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.glossary_path, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            logger.info(f"Created empty glossary at {self.glossary_path}")
        self.load()

    def load(self):
        try:
            with open(self.glossary_path, 'r', encoding='utf-8') as f:
                self.glossary = json.load(f)
            logger.info(f"Loaded {len(self.glossary)} terms from glossary")
        except Exception as e:
            logger.warning(f"Failed to load glossary: {e}")
            self.glossary = {}

    def save(self):
        with self._lock:
            try:
                with open(self.glossary_path, 'w', encoding='utf-8') as f:
                    json.dump(self.glossary, f, ensure_ascii=False, indent=2)
                logger.debug(f"Saved glossary with {len(self.glossary)} terms")
            except Exception as e:
                logger.error(f"Failed to save glossary: {e}")

    def update(self, new_terms: Dict[str, str]):
        if not new_terms:
            return
        with self._lock:
            self.glossary.update(new_terms)
        self.save()

    def build_prompt_glossary(self) -> str:
        if not self.glossary:
            return ""
        terms_list = "\n".join([f"- {ch} → {vi}" for ch, vi in self.glossary.items()])
        return f"""
IMPORTANT: Use these exact Vietnamese translations for the following Chinese terms. Never invent alternatives.
Glossary:
{terms_list}
"""


# ==================== API CALL ====================
def call_lm_studio(prompt: str) -> Optional[str]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional Chinese-to-Vietnamese webnovel translator.\n"
                "Rules:\n"
                "- Return ONLY the Vietnamese translation. No explanations, no comments.\n"
                "- DO NOT repeat any sentence or paragraph. Output each piece of content exactly once.\n"
                "- DO NOT include the original Chinese text.\n"
                "- Use the glossary provided in the user prompt exactly.\n"
                "- Keep character names and locations consistent.\n"
                "- Use natural, fluent Vietnamese. Preserve tone and style.\n"
                "- Translate the ENTIRE given text. Do not stop early.\n"
                "- Do NOT add any extra content after finishing."
            )
        },
        {"role": "user", "content": prompt}
    ]
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stop": STOP_TOKENS,
    }
    headers = {"Content-Type": "application/json"}

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
                        return content.strip()
                    else:
                        logger.warning("Empty response")
                else:
                    logger.error(f"HTTP {resp.status_code}")
                    logger.error(f"Response body: {resp.text}")   # <-- thêm dòng này
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
            time.sleep(RETRY_DELAY)
    return None

# ==================== DỊCH THUẬT ====================
def translate_full_text(text: str, glossary_mgr: GlossaryManager) -> str:
    if not text or not text.strip():
        return ""
    glossary_part = glossary_mgr.build_prompt_glossary()
    prompt = f"""{glossary_part}

Translate the following Chinese text to Vietnamese. Follow the glossary strictly. Do not repeat anything. Translate completely.

Chinese text:
{text}"""
    result = call_lm_studio(prompt)
    return result if result else ""

def translate_filename(filename: str, glossary_mgr: GlossaryManager) -> str:
    stem = Path(filename).stem
    ext = Path(filename).suffix
    if not stem.strip():
        return filename
    glossary_part = glossary_mgr.build_prompt_glossary()
    prompt = f"""{glossary_part}

Translate this Chinese filename to Vietnamese (output only the translated name, no extra text):
{stem}"""
    translated = call_lm_studio(prompt)
    if translated:
        cleaned = "".join(c for c in translated if c.isalnum() or c in " ._-")
        if cleaned:
            return cleaned + ext
    return filename

def post_process(text: str) -> str:
    # Sửa lỗi chính tả phổ biến
    text = re.sub(r'\bỜ lộc rồi\b', 'Ờ quen rồi', text)
    text = re.sub(r'không để ý ý đến', 'không để ý đến', text)
    text = re.sub(r'lên sà lan', 'lên pháp trường', text)  # tuỳ chỉnh
    # Cắt bỏ dòng quảng cáo
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if not line.strip().startswith(('Gợi ý:', 'Nhắc nhở', 'Đăng nhập')):
            cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)
    return text.strip()

def process_one_file(src_file: Path, dst_file: Path, glossary_mgr: GlossaryManager) -> bool:
    try:
        with open(src_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"Read error {src_file.name}: {e}")
        return False

    if not content.strip():
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text("", encoding="utf-8")
        return True

    logger.info(f"📖 Translating: {src_file.name} ({len(content)} chars)")
    translated = translate_full_text(content, glossary_mgr)
    if not translated:
        logger.error(f"❌ Translation failed: {src_file.name}")
        return False

    final = post_process(translated)
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(final, encoding="utf-8")
    logger.info(f"✅ Saved: {dst_file.name} ({len(final)} chars)")

    # ========== TRÍCH XUẤT THUẬT NGỮ VÀ CẬP NHẬT GLOSSARY ==========
    new_terms = glossary_mgr.extract_terms_from_chapter(content, final)
    if new_terms:
        logger.info(f"Extracted {len(new_terms)} new terms: {list(new_terms.keys())}")
        glossary_mgr.update(new_terms)
    else:
        logger.info("No new terms extracted from this chapter")
    return True

def translate_story_folder(root_folder: str):
    root = Path(root_folder).resolve()
    dest_root = root / TRANSLATED_SUBDIR
    dest_root.mkdir(parents=True, exist_ok=True)
    
    glossary_path = dest_root / GLOSSARY_FILE
    glossary_mgr = GlossaryManager(glossary_path)

    all_files = [f for f in root.rglob("*.txt") if TRANSLATED_SUBDIR not in f.parts]
    logger.info(f"📁 Found {len(all_files)} .txt files")

    tasks = []
    for src in all_files:
        rel_path = src.relative_to(root)
        new_name = translate_filename(rel_path.name, glossary_mgr)
        if rel_path.parent == Path("."):
            dst = dest_root / new_name
        else:
            dst = dest_root / rel_path.parent / new_name
        tasks.append((src, dst))

    success = 0
    for src, dst in tasks:
        try:
            if process_one_file(src, dst, glossary_mgr):
                success += 1
            else:
                logger.warning(f"Failed: {src.name}")
        except Exception as e:
            logger.error(f"Exception: {src.name} - {e}")

    logger.info(f"🎉 Done: {success}/{len(tasks)} files. Output: {dest_root}")
    logger.info(f"📖 Glossary file: {glossary_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dịch file .txt với glossary tự động cập nhật")
    parser.add_argument("folder", help="Đường dẫn thư mục chứa các file .txt cần dịch")
    args = parser.parse_args()
    translate_story_folder(args.folder)