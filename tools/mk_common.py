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

ADD = {"light": 30, "standard": 40, "large": 60, "palette_large": 80}
GIFT_ADD = {"large": 250, "small": 120, "xsmall": 60}

# Makeup Sale categories (key, English, Arabic, group)
CATS = [
    ("foundation", "Foundation", "كريم الأساس", "face"), ("concealer", "Concealer", "الكونسيلر", "face"), ("powder", "Powder", "البودرة", "face"),
    ("blush", "Blush", "البلاشر", "face"), ("bronzer", "Bronzer", "البرونزر", "face"), ("contour", "Contour", "الكونتور", "face"),
    ("highlighter", "Highlighter", "الهايلايتر", "face"), ("primer", "Primer", "البرايمر", "face"), ("settingspray", "Setting Spray", "مثبت المكياج", "face"),
    ("face", "Face", "الوجه", "face"),
    ("lipgloss", "Lip Gloss", "ملمع الشفاه", "lips"), ("lipbalm", "Lip Balm", "مرطب الشفاه", "lips"), ("lipstick", "Lipstick", "أحمر الشفاه", "lips"),
    ("lipliner", "Lip Liner", "محدد الشفاه", "lips"), ("lipoil", "Lip Oil", "زيت الشفاه", "lips"), ("lipsets", "Lip Sets", "مجموعات الشفاه", "lips"),
    ("lips", "Lips", "الشفاه", "lips"),
    ("eyeshadow", "Eyeshadow", "ظلال العيون", "eyes"), ("palette", "Eyeshadow Palettes", "باليتات ظلال العيون", "eyes"), ("mascara", "Mascara", "الماسكارا", "eyes"),
    ("eyeliner", "Eyeliner", "الآيلاينر", "eyes"), ("brows", "Brow Products", "منتجات الحواجب", "eyes"), ("eyes", "Eyes", "العيون", "eyes"),
    ("brushes", "Makeup Brushes", "فرش المكياج", "other"), ("tools", "Makeup Tools", "أدوات المكياج", "other"), ("other", "Other Makeup", "منتجات مكياج أخرى", "other"),
]
CAT_RULES = [   # first match wins
    ("brushes", r"\bbrush(es)?\b"), ("tools", r"sponge|applicator|sharpener|eyelash curler|lash curler|tweezer|puff\b|blender\b|makeup bag|cosmetic bag|pouch"),
    ("lipsets", r"\blip\b.*\b(set|kit|duo|trio|bundle)\b|\b(set|kit|duo|trio)\b.*\blip"),
    ("palette", r"(eye ?shadow|shadow|eye) palette|palette.*(eye|shadow)|\beye palette"),
    ("brows", r"\bbrow"), ("mascara", r"mascara"), ("lipliner", r"lip ?liner|lip pencil|lip contour"), ("eyeliner", r"eye ?liner|kohl|\bliner\b"),
    ("eyeshadow", r"eye ?shadow|shadow"), ("concealer", r"conceal|corrector|color correct"),
    ("foundation", r"foundation|skin tint|tinted moisturi|\bbb cream|\bcc cream"),
    ("settingspray", r"setting (spray|mist)|fixing (spray|mist)|makeup setting"), ("primer", r"primer"),
    ("contour", r"contour|sculpt"), ("blush", r"blush|\bcheek"), ("bronzer", r"bronz"), ("highlighter", r"highlight|illuminat|luminiz|glow (drops|stick)|strobe"),
    ("powder", r"powder"), ("lipoil", r"lip oil|lip glow oil"), ("lipgloss", r"gloss|plump"), ("lipbalm", r"lip (balm|mask|treatment|butter)|\bbalm\b"),
    ("lipstick", r"lipstick|lip stick|lip colou?r|matte lip|liquid lip|lip (cream|crayon|stain)"), ("lips", r"\blip"),
    ("eyes", r"\blash|eye primer|\beye"), ("face", r"fixing|face|cushion|complexion|flawless filter|palette"),
]

FRAGRANCE = r"parfum|perfume|eau de|cologne|fragrance|body mist|hair (& |and )?body mist|scent|rollerball|roll-on perfume|\bedp\b|\bedt\b|parfum|discovery set|olfactory"


def is_fragrance(*texts):
    return bool(re.search(FRAGRANCE, " ".join(t or "" for t in texts).lower()))


SET_WORDS = r"\b(gift set|value set|set|kit|duo|trio|quad|bundle|vault|collection set|minis? set|\d+[- ]piece)\b"


def text_of(body):
    raw = re.sub(r"(?i)<br\s*/?>|</(p|li|div|h\d)>", "\n", body or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.split("\n")).strip()


def category(name, ptype=""):
    """The product's own name decides first; the store's product type only when the name says nothing."""
    for s in ((name or "").lower(), (ptype or "").lower()):
        for key, rx in CAT_RULES:
            if re.search(rx, s):
                return key
    return "other"


NOT_BEAUTY = r"phone case|phone accessor|casetify|sunglasses|hoodie|sweatpant|sweatshirt|apparel|scrunchie|ponytail|mirror|alphabet charm|notebook|\bcharm\b|hair clip|claw clip|\bclip\b|\btote\b|hoodie|sweatshirt|t-shirt|\btee\b|\bhat\b|gift card|e-gift|keychain|sticker|\bsocks?\b|blanket|candle holder"


def not_beauty(name, ptype=""):
    return bool(re.search(NOT_BEAUTY, f"{name or ''} {ptype or ''}".lower()))


def is_set(name, ptype="", tags=(), value_price=None):
    s = f"{ptype} {name}".lower()        # store tags are not used: they mark gift-guide pages, not what the product is
    if value_price and re.search(r"\b(set|kit|duo|trio|quad|bundle|vault|collection|minis|sampler|discovery|\d+[- ]piece)\b", s):
        return True      # Sephora also shows "(… value)" on value-size single products, so the name must say it's a set
    if re.search(r"\b(set|kit|bundle|vault)\b", (ptype or "").lower()):
        return True
    if re.search(r"duo[- ]fib(re|er)|\bset(ting)? (spray|powder|mist)\b|\bsetting\b", s.replace("gift set", "")):
        return False
    return bool(re.search(SET_WORDS, s))


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
    m = re.search(r"(?i)(?:set|kit|bundle|collection|duo|trio)?\s*(?:includes?|contains?|what'?s included|featuring)\s*:?\s*([^\n.]{8,400})", d)
    if m and re.search(r",| and | \+ ", m.group(1)):
        parts = [x for x in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s\+\s", m.group(1)) if len(x.strip()) > 2]
        if 2 <= len(parts) <= 15:
            return len(parts), "description sentence"
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


def top_of(name):
    s = (name or "").lower()
    if re.search(r"parfum|perfume|eau de|cologne|fragrance|body mist|hair & body mist|rollerball", s): return "fragrance"
    if re.search(r"shampoo|conditioner|hair (mask|oil|serum|spray)|dry shampoo|dryer|straightener|curling|hair", s): return "hair"
    if re.search(r"body (lotion|wash|cream|butter|oil|scrub)|hand (cream|balm)|shower|bath", s): return "bath"
    if re.search(r"moistur|serum|cleanser|toner|sunscreen|spf|eye cream|face mask|sheet mask|exfoliat|retinol|essence|night cream|day cream|face cream|skincare", s) and not re.search(r"foundation|tint|primer|lip", s): return "skincare"
    return "makeup"


def palette_size(text):
    """Number of shades/pans and total weight (g) stated on the official page, when stated."""
    t = (text or "").lower()
    pans = tot = None
    m = re.search(r"(\d{1,2})\s*x\s*(\d+(?:\.\d+)?)\s*(g|oz)\b", t)
    if m:
        pans, tot = int(m.group(1)), int(m.group(1)) * float(m.group(2)) * (28.35 if m.group(3) == "oz" else 1)
    else:
        m = re.search(r"(\d{1,2})[- ]?(?:pans?|shades?|colou?rs?)\b", t)
        if m:
            pans = int(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(g|oz)\b", t)
        if m:
            tot = float(m.group(1)) * (28.35 if m.group(2) == "oz" else 1)
    return pans, tot


def add_class(name, cat, size_ml=None, mini=False, top="", detail=""):
    """Add-on for one individual product: light 30, standard 40, large 60, large eyeshadow palette 80."""
    s = (name or "").lower()
    if mini or re.search(r"\bmini\b|travel[- ]size|deluxe sample", s):
        return "light", "mini / travel size"
    if cat == "palette" or re.search(r"\bpalette\b", s):
        pans, grams = palette_size(f"{name} {detail}")
        if (pans and pans >= 12) or (grams and grams >= 12):
            return "palette_large", f"large palette ({pans or '?'} shades, {round(grams) if grams else '?'} g stated)"
        if pans or grams:
            return "standard", f"palette ({pans or '?'} shades, {round(grams) if grams else '?'} g stated)"
        return "standard", "palette — size not stated (check)"
    if size_ml and size_ml >= 100:
        return "large", f"stated size {round(size_ml)} ml/g (100 or more)"
    if cat in ("foundation", "powder", "primer", "settingspray"):
        return "standard", "foundation / powder / primer / setting spray"
    if top in ("skincare", "hair", "bath") and cat == "other":
        return "standard", "standard-size " + top + " product"
    return "light", "small lightweight item"


def gift_class(name, contents=(), desc=""):
    """Gift-set fee by the set's real size, from the official contents (stated sizes) and packaging words.
    Returns (class, why) or (None, reason) when it can't be decided reliably."""
    s = (name or "").lower()
    if re.search(r"advent calendar|vault|trunk|train case|vanity case|carry-?all|beauty box", s):
        return "large", "large packaging stated in the official name"
    items = [c for c in (contents or []) if c]
    known = [x for x in (size_of(c) for c in items) if x]
    if items and len(known) >= max(2, round(len(items) * 0.6)):
        total = sum(known)
        minis = all(re.search(r"(?i)mini|travel|deluxe|sample", c) or (size_of(c) or 0) <= 10 for c in items)
        if total <= 25 or (minis and total <= 40):
            return "xsmall", f"very small: {len(items)} items, about {round(total)} ml/g in total"
        if total <= 220:
            return "small", f"compact set: about {round(total)} ml/g in total"
        return "large", f"large set: about {round(total)} ml/g in total"
    if re.search(r"\bminis?\b|travel", s) and re.search(r"\b(duo|trio|set|kit)\b", s):
        return "xsmall", "mini set (official name)"
    return None, "size can't be determined from the official contents — manual review"
