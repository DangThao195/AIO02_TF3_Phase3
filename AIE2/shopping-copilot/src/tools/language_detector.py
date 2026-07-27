import re
import unicodedata


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_VIETNAMESE_STOPWORDS = {
    _strip_diacritics(w)
    for w in {
        "của", "và", "có", "không", "các", "những", "này", "đó", "ấy",
        "nhiều", "một", "vài", "muốn", "hãy", "lòng", "cần", "mua",
        "thích", "nên", "phải", "được", "giúp", "tôi", "mình", "xin",
        "xem", "người", "dùng", "bằng", "thế", "lại", "rồi", "đây",
        "nhất", "chào", "làm", "gì", "nào", "bạn", "bán", "loại",
        "điện", "thoại", "máy", "tính", "sách", "giá", "tiền", "đô",
        "cái", "chiếc", "con", "vui", "cho", "tìm", "kiếm",
        "hàng", "sản", "phẩm", "dụng", "cụ", "thiết", "bị", "đồ",
        "chơi", "thể", "thao", "nấu", "ăn", "uống", "thời", "trang",
        "túi", "xách", "balo", "giày", "dép", "áo", "quần", "mũ",
        "đồng", "nghìn", "triệu", "tỷ", "trăm", "dưới", "trên",
        "giữa", "trong", "ngoài", "đầu", "cuối", "thứ",
        "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười",
    }
}

_VIETNAMESE_SPECIFIC = {
    _strip_diacritics(w)
    for w in {"nhé", "nha", "vậy", "thôi", "vâng",
              "bị", "đã", "sẽ", "đang", "rất", "lắm", "quá"}
}

def _is_vi_exclusive_word(word: str) -> bool:
    return word in _VIETNAMESE_SPECIFIC or (
        word in _VIETNAMESE_STOPWORDS and word not in {
            "a", "i", "an", "in", "on", "at", "to", "by", "so", "or",
            "be", "is", "am", "it", "we", "he", "she", "they",
        }
    )


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "vi"

    lowered = text.lower()

    vn_chars = len(re.findall(
        r'[àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắặẳẵ]', lowered
    ))
    total_alpha = len(re.findall(r'[a-zA-Z]', text))
    if total_alpha == 0:
        return "vi"
    vn_ratio = vn_chars / max(total_alpha, 1)
    if vn_ratio > 0.1:
        return "vi"

    words = set(re.findall(r'[a-zA-Z]+', lowered))

    vi_exclusive = {w for w in words if _is_vi_exclusive_word(w)}
    en_indicators = {"the", "is", "are", "was", "were", "do", "does",
                     "did", "has", "have", "had", "can", "could",
                     "will", "would", "shall", "should", "may", "might",
                     "this", "that", "these", "those", "what", "which"}
    en_hits = len(words & en_indicators)

    if vi_exclusive and en_hits == 0:
        return "vi"
    if len(vi_exclusive) >= 2:
        return "vi"
    if en_hits >= 2 and not vi_exclusive:
        return "en"

    return "en"


def build_system_prompt_with_lang(base_prompt: str, user_lang: str) -> str:
    lang_instruction = {
        "vi": "Trả về JSON danh sách tool — không kèm giải thích.",
        "en": "Return JSON tool list only — no explanation.",
    }.get(user_lang, "Match the language of the user's input.")
    return base_prompt + f"\n## Language rule: {lang_instruction}"
