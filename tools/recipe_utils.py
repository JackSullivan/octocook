"""Shared recipe utilities not tied to any storage backend."""

from scraper import RecipeData


_ICON_KEYWORDS: list[tuple[str, str]] = [
    # Order matters: more specific keywords first.
    ("pizza", "🍕"),
    ("spaghetti", "🍝"),
    ("pasta", "🍝"),
    ("ramen", "🍜"),
    ("noodle", "🍜"),
    ("burger", "🍔"),
    ("sandwich", "🥪"),
    ("taco", "🌮"),
    ("burrito", "🌯"),
    ("sushi", "🍣"),
    ("dumpling", "🥟"),
    ("paneer", "🍛"),
    ("curry", "🍛"),
    ("biryani", "🍛"),
    ("dal", "🍛"),
    ("indian", "🍛"),
    ("rice", "🍚"),
    ("risotto", "🍚"),
    ("soup", "🍲"),
    ("stew", "🍲"),
    ("chili", "🌶️"),
    ("salad", "🥗"),
    ("bread", "🍞"),
    ("toast", "🍞"),
    ("bagel", "🥯"),
    ("pancake", "🥞"),
    ("waffle", "🧇"),
    ("omelette", "🍳"),
    ("egg", "🥚"),
    ("breakfast", "🍳"),
    ("cake", "🍰"),
    ("cupcake", "🧁"),
    ("cookie", "🍪"),
    ("brownie", "🍫"),
    ("pie", "🥧"),
    ("ice cream", "🍦"),
    ("donut", "🍩"),
    ("doughnut", "🍩"),
    ("chocolate", "🍫"),
    ("chicken", "🍗"),
    ("turkey", "🦃"),
    ("steak", "🥩"),
    ("beef", "🥩"),
    ("bacon", "🥓"),
    ("pork", "🥓"),
    ("salmon", "🐟"),
    ("tuna", "🐟"),
    ("fish", "🐟"),
    ("shrimp", "🍤"),
    ("crab", "🦀"),
    ("lobster", "🦞"),
    ("seafood", "🦐"),
    ("mushroom", "🍄"),
    ("potato", "🥔"),
    ("tomato", "🍅"),
    ("avocado", "🥑"),
    ("vegan", "🥬"),
    ("vegetarian", "🥕"),
    ("vegetable", "🥦"),
    ("smoothie", "🥤"),
    ("cocktail", "🍹"),
    ("tea", "🍵"),
    ("coffee", "☕"),
    ("drink", "🍸"),
]


def pick_icon(recipe: RecipeData) -> str:
    """Best-guess emoji icon based on recipe title and tags."""
    haystack = " ".join([recipe.title or "", *(recipe.tags or [])]).lower()
    for keyword, emoji in _ICON_KEYWORDS:
        if keyword in haystack:
            return emoji
    return "🍽️"
