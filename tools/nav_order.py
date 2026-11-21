"""MkDocs hook: put the menu in a player-friendly order instead of alphabetical."""

TOP_ORDER = ["Home", "Locations", "Crafting", "Activities", "Navigation", "Items"]
CRAFTING_ORDER = ["Crafting progression", "Crafting stations", "Materials", "Tools", "Weapons"]


def _rank(order, title):
    return order.index(title) if title in order else len(order)


def on_nav(nav, config, files):
    nav.items.sort(key=lambda item: _rank(TOP_ORDER, item.title or ""))
    for item in nav.items:
        if item.title == "Crafting" and getattr(item, "children", None):
            item.children.sort(key=lambda c: _rank(CRAFTING_ORDER, c.title or ""))
    return nav
