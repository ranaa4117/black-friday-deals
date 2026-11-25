#!/usr/bin/env python3
"""Shared rules for the Makeup section: product category, gift-set detection, item count in a set,
size reading, and the add-on class (30 / 40 / 60 SAR, or 20 SAR per item for sets).
Nothing here invents data: when a rule can't decide from the official text, it says so (None)."""
import html, re

BRANDS = {   # official spelling
    "mario": "MAKEUP BY MARIO", "westman": "Westman Atelier", "saie": "Saie", "tarte": "tarte", "huda": "HUDA BEAUTY",
    "ct": "Charlotte Tilbury", "nars": "NARS", "kosas": "Kosas", "refy": "REFY", "mac": "MAC Cosmetics",
    "toofaced": "Too Faced", "fenty": "Fenty Beauty", "rare": "Rare Beauty",
}
# how each brand is written on Sephora USA (lower-case) → our key
SEPHORA_NAMES = {
    "makeup by mario": "mario", "westman atelier": "westman", "saie": "saie", "tarte": "tarte", "huda beauty": "huda",
    "charlotte tilbury": "ct", "nars": "nars", "kosas": "kosas", "refy": "refy", "mac cosmetics": "mac",
    "too faced": "toofaced", "fenty beauty by rihanna": "fenty", "fenty beauty": "fenty", "rare beauty by selena gomez": "rare", "rare beauty": "rare",
}

ADD = {"light": 30, "standard": 40, "large": 60, "per_item": 20}

# Makeup Sale categories (key, English, Arabic, group)
CATS = [
    ("foundation", "Foundation", "كريم الأساس", "face"), ("concealer", "Concealer", "الكونسيلر", "face"), ("powder", "Powder", "البودرة", "face"),
    ("blush", "Blush", "البلاشر", "face"), ("bronzer", "Bronzer", "البرونزر", "face"), ("highlighter", "Highlighter", "الهايلايتر", "face"),
    ("face", "Face", "الوجه", "face"),
    ("lipgloss", "Lip Gloss", "ملمع الشفاه", "lips"), ("lipbalm", "Lip Balm", "مرطب الشفاه", "lips"), ("lipstick", "Lipstick", "أحمر الشفاه", "lips"),
    ("lips", "Lips", "الشفاه", "lips"),
    ("mascara", "Mascara", "الماسكارا", "eyes"), ("eyeliner", "Eyeliner", "الآيلاينر", "eyes"), ("eyeshadow", "Eyeshadow", "ظلال العيون", "eyes"),
    ("brows", "Brows", "الحواجب", "eyes"), ("eyes", "Eyes", "العيون", "eyes"),
    ("other", "Other Makeup", "منتجات مكياج أخرى", "other"),
]
CAT_RULES = [   # first match wins; checked against "type + name"
    ("brows", r"\bbrow"), ("mascara", r"mascara"), ("eyeliner", r"eye ?liner|kohl|\bliner\b(?!.*lip)"),
    ("eyeshadow", r"eye ?shadow|shadow (palette|stick)|eye palette|shadow"),
    ("concealer", r"conceal|corrector|color correct"), ("foundation", r"foundation|skin tint|tinted moisturi|\bbb cream|\bcc cream|serum foundation"),
    ("blush", r"blush|\bcheek"), ("bronzer", r"bronz|contour|sculpt"), ("highlighter", r"highlight|illuminat|luminiz|glow (drops|stick)|strobe"),
    ("powder", r"powder"), ("lipgloss", r"gloss|lip oil|plump"), ("lipbalm", r"lip (balm|mask|treatment|butter)|balm"),
    ("lipstick", r"lipstick|lip stick|lip colou?r|matte lip|liquid lip|lip (cream|crayon|stain)"), ("lips", r"\blip"),
    ("eyes", r"\blash|eye primer|\beye"), ("face", r"primer|setting spray|setting mist|fixing|face|cushion|complexion|flawless filter|palette"),
]

SET_WORDS = r"\b(gift set|value set|set|kit|duo|trio|quad|bundle|vault|collection set|minis? set|\d+[- ]piece)\b"


def text_of(body):
    raw = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d)>", "\n", body or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.split("\n")).strip()


def category(name, ptype=""):
    s = f"{ptype} {name}".lower()
    for key, rx in CAT_RULES:
        if re.search(rx, s):
            return key
    return "other"


def is_set(name, ptype="", tags=(), value_price=None):
    s = f"{ptype} {name} {' '.join(tags or [])}".lower()
    if value_price:      # Sephora shows "(… value)" only for sets
        return True
    if re.search(r"\b(set|kit|bundle|vault)\b", (ptype or "").lower()):
        return True
    return bool(re.search(SET_WORDS, s)) and not re.search(r"setting (spray|powder|mist)|\bsetting\b", s.replace("gift set", ""))


WORD_N = {"duo": 2, "trio": 3, "quad": 4, "quartet": 4}


def set_items(name, desc=""):
    """How many individual products are inside a set, from the official name and description.
    Returns (count, how) or (None, reason)."""
    d = text_of(desc)
    # "Set includes:" / "This kit contains:" followed by a list
    m = re.search(r"(?is)(?:set|kit|bundle|collection|vault|duo|trio)?\s*(?:includes?|contains?|what'?s inside|in the (?:set|kit|box))\s*:?\s*\n(.+)", d)
    if m:
        lines = []
        for ln in m.group(1).split("\n"):
            ln = ln.strip(" •-–*·\t")
            if not ln:
                if lines:
                    break
                continue
            if re.match(r"(?i)^(how to|what it is|why|benefits|ingredients|key|highlighted|formulation|what else|suggested|skin ?type)", ln):
                break
            lines.append(ln)
        items = [l for l in lines if re.search(r"(?i)\b(oz|ml|g|fl|mini|full[- ]size|travel|deluxe)\b|\d", l) or len(l) < 90]
        if 2 <= len(items) <= 30:
            qty = 0
            for l in items:
                q = re.match(r"^(\d+)\s*x\s", l, re.I)
                qty += int(q.group(1)) if q else 1
            return qty, "description list"
    n = re.search(r"(?i)\b(\d{1,2})[- ]?(piece|pc|pcs)\b", name + " " + d[:300])
    if n:
        return int(n.group(1)), "name"
    for w, k in WORD_N.items():
        if re.search(rf"(?i)\b{w}\b", name):
            return k, "name"
    return None, "contents not published in a readable list"


SIZE_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz|oz|ml|mL|g|gm|kg|l)\b", re.I)


def size_of(text):
    """Largest stated size in ml or g (oz converted). None if the official text doesn't state one."""
    best = None
    for num, unit in SIZE_RX.findall(text or ""):
        v, u = float(num), unit.lower().replace(" ", "").replace(".", "")
        val = v * 29.57 if u in ("floz", "oz") else v * 1000 if u in ("kg", "l") else v
        best = max(best or 0, val)
    return best


def add_class(name, cat, size_ml=None, mini=False, top=""):
    """Which add-on applies to one individual product: 'light' 30, 'standard' 40 or 'large' 60."""
    s = (name or "").lower()
    if mini or re.search(r"\bmini\b|travel[- ]size|deluxe sample", s):
        return "light", "mini / travel size"
    if size_ml and size_ml >= 100:
        return "large", f"stated size {round(size_ml)} ml/g (100 or more)"
    if top == "hair" and re.search(r"dryer|straightener|curling|flat iron|hot brush|styler|airwrap|wand", s):
        return "large", "hair tool (heavy)"
    if cat in ("eyeshadow",) and re.search(r"palette", s) or re.search(r"\bpalette\b", s):
        return "standard", "palette"
    if cat in ("foundation", "powder") or (cat == "face" and re.search(r"primer|setting spray|setting mist", s)):
        return "standard", "foundation / powder / primer"
    if top in ("skincare", "fragrance", "hair", "bath") and cat == "other":
        return "standard", "standard-size " + top + " product"
    return "light", "small lightweight item"
