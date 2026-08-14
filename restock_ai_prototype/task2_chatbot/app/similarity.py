"""
Feature 2 - Alternative recommendations via Python vector similarity.

Each product is turned into a sparse TF-IDF vector built from its name,
category and JSON attributes; alternatives are ranked by cosine similarity,
then blended with attribute overlap and price closeness:

    match = 0.50 * cosine(tfidf) + 0.25 * jaccard(attributes) + 0.25 * price_closeness
            + same-category bonus

No numpy/sklearn required — the maths is small and explicit so the score can be
explained back to the customer ("shares bluetooth, over-ear, noise cancelling").
"""
import math
import re
from datetime import datetime

from . import config, db

_STOPWORDS = {"the", "and", "for", "with", "a", "an", "of", "pc", "pcs", "set", "s"}
_CACHE = {"built_at": None, "vectors": {}, "products": {}}
_CACHE_TTL_SECONDS = 30


# ------------------------------------------------------------------ tokenising
def _words(text):
    return [
        w for w in re.split(r"[^a-z0-9]+", str(text).lower())
        if w and w not in _STOPWORDS and len(w) > 1
    ]


def product_tokens(product):
    """Weighted bag of words: name terms, category (x3), attribute key=value pairs."""
    tokens = []
    tokens += _words(product["name"])
    tokens += _words(product["category"]) * 3

    attrs = db.load_json(product.get("attributes"))
    for key, value in attrs.items():
        if isinstance(value, bool):
            if value:
                tokens += [f"attr:{key}"] * 2
            continue
        tokens += [f"attr:{key}={str(value).lower()}"] * 2
        tokens += _words(value)
    return tokens


def _tfidf_vectors(products):
    """Standard TF-IDF: term frequency in a product, damped by document frequency."""
    docs = {p["product_id"]: product_tokens(p) for p in products}
    n_docs = max(1, len(docs))

    doc_freq = {}
    for tokens in docs.values():
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    vectors = {}
    for pid, tokens in docs.items():
        counts = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        total = max(1, len(tokens))
        vec = {}
        for token, count in counts.items():
            tf = count / total
            idf = math.log((1 + n_docs) / (1 + doc_freq.get(token, 0))) + 1.0
            vec[token] = tf * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors[pid] = {t: v / norm for t, v in vec.items()}
    return vectors


def _catalogue():
    """Cached TF-IDF index; rebuilt every 30s (or when the catalogue changes)."""
    now = datetime.now()
    built = _CACHE["built_at"]
    if built and (now - built).total_seconds() < _CACHE_TTL_SECONDS:
        return _CACHE["vectors"], _CACHE["products"]

    products = db.query("SELECT * FROM products")
    _CACHE["vectors"] = _tfidf_vectors(products)
    _CACHE["products"] = {p["product_id"]: p for p in products}
    _CACHE["built_at"] = now
    return _CACHE["vectors"], _CACHE["products"]


def invalidate_cache():
    _CACHE["built_at"] = None


# ------------------------------------------------------------------ scoring parts
def cosine(vec_a, vec_b):
    if len(vec_b) < len(vec_a):
        vec_a, vec_b = vec_b, vec_a
    return sum(weight * vec_b.get(token, 0.0) for token, weight in vec_a.items())


def attribute_overlap(attrs_a, attrs_b):
    """Jaccard similarity over key=value pairs, plus the shared pairs themselves."""
    set_a = {f"{k}={str(v).lower()}" for k, v in attrs_a.items()}
    set_b = {f"{k}={str(v).lower()}" for k, v in attrs_b.items()}
    if not set_a or not set_b:
        return 0.0, []
    shared = set_a & set_b
    union = set_a | set_b
    readable = [
        pair.split("=", 1)[1] if pair.split("=", 1)[1] not in ("true", "false")
        else pair.split("=", 1)[0].replace("_", " ")
        for pair in sorted(shared)
    ]
    return len(shared) / len(union), readable


def price_closeness(price_a, price_b):
    price_a, price_b = float(price_a), float(price_b)
    high = max(price_a, price_b)
    if high == 0:
        return 1.0
    return max(0.0, 1 - abs(price_a - price_b) / high)


# ------------------------------------------------------------------ public API
def find_alternatives(product_id, limit=None, min_score=30.0):
    """Top in-stock alternatives with an explainable match score."""
    limit = limit or config.MAX_ALTERNATIVES
    vectors, products = _catalogue()
    target = products.get(product_id)
    if not target:
        return []

    target_attrs = db.load_json(target.get("attributes"))
    target_vec = vectors.get(product_id, {})
    results = []

    for pid, candidate in products.items():
        if pid == product_id or int(candidate["stock_level"]) <= 0:
            continue

        cos = cosine(target_vec, vectors.get(pid, {}))
        jac, shared = attribute_overlap(target_attrs, db.load_json(candidate.get("attributes")))
        price_sim = price_closeness(target["price"], candidate["price"])
        same_category = candidate["category"] == target["category"]

        score = 0.50 * cos + 0.25 * jac + 0.25 * price_sim
        if same_category:
            score = min(1.0, score + 0.12)
        match_score = round(score * 100, 1)
        if match_score < min_score:
            continue

        price_delta = float(candidate["price"]) - float(target["price"])
        reasons = []
        if same_category:
            reasons.append(f"Same category ({candidate['category']})")
        if shared:
            reasons.append("Shares " + ", ".join(shared[:3]))
        if abs(price_delta) < 0.01:
            reasons.append("Identical price")
        elif price_delta < 0:
            reasons.append(f"${abs(price_delta):.2f} cheaper")
        else:
            reasons.append(f"${price_delta:.2f} more expensive")

        results.append({
            "product_id": pid,
            "name": candidate["name"],
            "category": candidate["category"],
            "price": float(candidate["price"]),
            "stock_level": int(candidate["stock_level"]),
            "image_url": candidate["image_url"],
            "match_score": match_score,
            "price_delta": round(price_delta, 2),
            "reasons": reasons,
            "breakdown": {
                "vector_similarity": round(cos * 100, 1),
                "attribute_overlap": round(jac * 100, 1),
                "price_closeness": round(price_sim * 100, 1),
                "same_category_bonus": 12 if same_category else 0,
            },
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]


def search_products(text, limit=6):
    """Fuzzy catalogue search used by the chatbot when resolving a product name."""
    vectors, products = _catalogue()
    query_tokens = _words(text)
    if not query_tokens:
        return []

    # Score the free-text query against every product vector.
    counts = {}
    for token in query_tokens:
        counts[token] = counts.get(token, 0) + 1
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    query_vec = {t: v / norm for t, v in counts.items()}

    scored = []
    for pid, product in products.items():
        score = cosine(query_vec, vectors.get(pid, {}))
        name = product["name"].lower()
        lowered = text.lower().strip()
        if lowered and lowered in name:  # exact substring beats everything
            score += 1.0
        overlap = len(set(query_tokens) & set(_words(name)))
        score += overlap * 0.35
        if score > 0.12:
            scored.append((score, product))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [{"score": round(s, 3), **p} for s, p in scored[:limit]]
