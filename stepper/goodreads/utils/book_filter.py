import re


def extract_year(text: str) -> list[int]:
    m = re.search(r"(\d{4})", text or "")
    return [int(m.group(1))] if m else []


def is_under_year(years: list[int], max_year: int) -> bool:
    return bool(years) and min(years) <= max_year
