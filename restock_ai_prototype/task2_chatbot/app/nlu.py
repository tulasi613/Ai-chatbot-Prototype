"""
Rule-based natural language understanding for the chatbot.

Deterministic and dependency-free (no LLM call, no training data) so the demo
always behaves the same way. It answers three questions about a message:

    what does the customer want?      -> intent
    which product are they asking about? -> product resolution (fuzzy + vector search)
    did they hand over contact details?  -> email / phone extraction
"""
import re

from . import similarity, subscriptions

PATTERNS = [
    ("greeting", r"^\s*(hi|hey|hello|yo|hiya|good (morning|afternoon|evening))\b"),
    ("thanks", r"\b(thanks|thank you|thankyou|cheers|appreciate it)\b"),
    ("help", r"\b(help|what can you do|how does this work|who are you|commands)\b"),
    ("browse", r"\b((what|anything|something)( else)?( is| are|'?s)?( currently)?"
               r" out of stock|out of stock items|show me (products|everything)|"
               r"list products|browse|catalog|catalogue|what do you (have|sell)|"
               r"what'?s (popular|trending|in demand))\b"),
    ("subscribe", r"\b(notify me|alert me|let me know|email me|text me|inform me|"
                  r"subscribe|remind me|tell me when|ping me|keep me posted)\b"),
    ("alternatives", r"\b(alternative|alternatives|similar|substitute|instead|"
                     r"other options?|something else|anything else like|recommend|"
                     r"suggestion|suggest|comparable|closest)\b"),
    ("explain", r"\b(explain|why do you|how did you|how do you know|breakdown|"
                r"how accurate|what'?s the confidence|show your working)\b"),
    ("price", r"\b(price|how much|cost|cheaper)\b"),
    ("availability", r"\b(in stock|out of stock|available|availability|restock|"
                     r"back in stock|when will|when is|eta|arrive|arriving|ship|"
                     r"how long|do you have|stock level)\b"),
]

AFFIRMATIVE_RE = re.compile(
    r"^\s*(y|ya|yes|yeah|yep|yup|sure|ok|okay|please|go ahead|do it|sounds good|"
    r"why not|alright)\b", re.I
)
NEGATIVE_RE = re.compile(r"^\s*(n|no|nope|nah|not now|no thanks|later)\b", re.I)
PRODUCT_ID_RE = re.compile(r"(?:product\s*)?#\s*(\d+)\b", re.I)


def detect_intent(text):
    lowered = (text or "").lower()
    for intent, pattern in PATTERNS:
        if re.search(pattern, lowered):
            return intent
    return None


def resolve_product(text, min_score=0.35):
    """
    Map free text to a catalogue product.

    Returns (product, candidates). `product` is set when we're confident;
    otherwise `candidates` holds the options to offer as clarification chips.
    """
    id_match = PRODUCT_ID_RE.search(text or "")
    if id_match:
        matches = similarity.search_products(text, limit=5)
        target_id = int(id_match.group(1))
        for match in matches:
            if match["product_id"] == target_id:
                return match, []
        from . import db

        product = db.query(
            "SELECT * FROM products WHERE product_id = %s", (target_id,), fetchone=True
        )
        if product:
            return product, []

    matches = similarity.search_products(text, limit=5)
    if not matches:
        return None, []

    best = matches[0]
    if best["score"] < min_score:
        return None, matches[:3]

    runner_up = matches[1]["score"] if len(matches) > 1 else 0.0
    # Clearly ahead of the next candidate -> commit. Otherwise ask which one.
    if best["score"] >= runner_up * 1.35 or best["score"] >= 1.0:
        return best, matches[1:3]
    return None, matches[:3]


def understand(text, session=None):
    """Full parse of one customer message."""
    session = session or {}
    text = (text or "").strip()
    email, phone = subscriptions.extract_contact(text)
    intent = detect_intent(text)
    product, candidates = resolve_product(text)

    pending = session.get("pending")

    # Contact details always mean "subscribe me", whatever else was said.
    if (email or phone) and pending in ("awaiting_contact", None, "offer_alternatives"):
        intent = "subscribe"

    # Short yes/no answers only make sense against the question we just asked.
    if not intent and pending:
        if AFFIRMATIVE_RE.match(text):
            intent = {
                "offer_alternatives": "alternatives",
                "offer_subscribe": "subscribe",
                "awaiting_contact": "subscribe",
            }.get(pending, "availability")
        elif NEGATIVE_RE.match(text):
            intent = "decline"

    # A bare product name ("smart fitness watch") is an availability question.
    if not intent and product:
        intent = "availability"

    # Follow-ups like "any alternatives?" inherit the product from context.
    if not product and session.get("product_id") and intent in (
        "alternatives", "subscribe", "availability", "price", "decline", "explain"
    ):
        from . import db

        product = db.query(
            "SELECT * FROM products WHERE product_id = %s",
            (session["product_id"],),
            fetchone=True,
        )

    return {
        "text": text,
        "intent": intent or "unknown",
        "product": product,
        "candidates": candidates,
        "email": email,
        "phone": phone,
    }
