import re
import unicodedata


QUESTION_ANSWER_WRAPPER_RE = re.compile(
    r"(?is)(^|\n|\*\*|\b)q(?:uestion)?\s*:\s*.+?(^|\n|\*\*|\b)a(?:nswer)?\s*:"
)


def has_question_answer_wrapper(text: str) -> bool:
    """Detect model-generated Q/A wrappers that violate the final answer contract."""
    if not text:
        return False
    return bool(QUESTION_ANSWER_WRAPPER_RE.search(str(text).strip()))


def _comparison_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def strip_leading_question_echo(answer: str, question: str) -> str:
    """Remove a candidate answer prefix that simply repeats the user question."""
    answer_text = str(answer or "").strip()
    question_text = str(question or "").strip()
    if not answer_text or not question_text:
        return answer_text

    normalized_answer = _comparison_text(answer_text)
    normalized_question = _comparison_text(question_text)
    if not normalized_answer.startswith(normalized_question):
        return answer_text

    stripped = answer_text[len(question_text) :].lstrip(" \t\r\n:：-–—,.!?")
    return stripped.strip()
