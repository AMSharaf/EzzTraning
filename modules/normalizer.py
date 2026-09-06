import re

class Normalizer:
    @staticmethod
    def normalize_text(text: str) -> str:
        if text is None:
            return ""
        text = str(text).strip().lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
