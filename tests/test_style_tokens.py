"""Colors come only from tokens: no hex or rgb() outside style.css's three token blocks, and every dark token defined.

docs/ui.md "Design system"; design-system/home-manager/MASTER.md "Color tokens".
"""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "src" / "home_manager" / "app" / "static"
CHARTS = Path(__file__).resolve().parents[1] / "src" / "home_manager" / "finance" / "charts.py"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
LIGHT = ":root {"
SYSTEM_DARK = ':root:not([data-theme="light"]) {'
CHOSEN_DARK = ':root[data-theme="dark"] {'
# Tokens that don't change with the theme: sizes, fonts, motion, and the paper behind document images.
THEME_INDEPENDENT = {"--paper", "--font", "--font-mono", "--content-max", "--sidebar-width", "--panel-width", "--motion-fast", "--motion-panel"}
THEME_INDEPENDENT_PREFIXES = ("--text-xs", "--text-sm", "--text-md", "--text-lg", "--text-xl", "--figure-", "--space-", "--radius-", "--control-")


def css():
    return (STATIC / "style.css").read_text(encoding="utf-8")


def block(text, opener):
    """The body of the first rule that starts with opener, up to its matching brace."""
    start = text.index(opener) + len(opener)
    depth, index = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        index += 1
    return text[start:index - 1]


def tokens(body):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))


def without_token_blocks(text):
    for opener in (LIGHT, SYSTEM_DARK, CHOSEN_DARK):
        text = text.replace(block(text, opener), "")
    return text


def test_no_colors_outside_the_token_blocks():
    rest = without_token_blocks(css())
    assert not HEX.findall(rest)
    assert "rgb(" not in rest and "rgba(" not in rest


def test_chart_code_has_no_hex_colors():
    for path in (STATIC / "home.js", CHARTS):
        assert not HEX.findall(path.read_text(encoding="utf-8")), path.name


def test_every_used_token_is_defined_in_light():
    text = css()
    defined = set(tokens(block(text, LIGHT)))
    used = set(re.findall(r"var\((--[\w-]+)", text))
    assert used - defined == set()


def test_the_dark_blocks_match_and_cover_every_light_color():
    text = css()
    light, system_dark, chosen_dark = (tokens(block(text, opener)) for opener in (LIGHT, SYSTEM_DARK, CHOSEN_DARK))
    assert system_dark == chosen_dark
    for name, value in light.items():
        if value.strip().startswith("var(") or name in THEME_INDEPENDENT or name.startswith(THEME_INDEPENDENT_PREFIXES):
            continue
        assert name in system_dark, name
    for body in (block(text, LIGHT), block(text, SYSTEM_DARK), block(text, CHOSEN_DARK)):
        assert "color-scheme:" in body
