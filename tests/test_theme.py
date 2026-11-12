"""The colours stay readable: WCAG 2.2 contrast, checked on every surface they sit on.

Accessibility by default: a colour change that makes a text hard to read fails here.
"""

from __future__ import annotations

import re

import pytest

from microcompta.ui import theme

SURFACES = {
    "window": theme.SURFACE_0,
    "card": theme.SURFACE_1,
    "field": theme.SURFACE_2,
    "hover": theme.SURFACE_3,
}
TEXT_LEVEL = 4.5      # WCAG 1.4.3, normal text, level AA
UI_LEVEL = 3.0        # WCAG 1.4.11, the parts of a control you need to see


def _luminance(colour: str) -> float:
    channels = []
    for i in (0, 2, 4):
        c = int(colour.lstrip("#")[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_formula_matches_known_values():
    assert contrast("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("surface", list(SURFACES))
@pytest.mark.parametrize("name", ["TEXT", "TEXT_2", "TEXT_3", "ACCENT", "GOOD", "WARN", "BAD"])
def test_every_text_colour_is_readable_on_every_surface(name, surface):
    assert contrast(getattr(theme, name), SURFACES[surface]) >= TEXT_LEVEL


@pytest.mark.parametrize("fill", [theme.ACCENT_FILL, theme.ACCENT_FILL_HOVER])
def test_the_primary_button_text_is_readable(fill):
    assert contrast(theme.ON_ACCENT, fill) >= TEXT_LEVEL


@pytest.mark.parametrize("name", ["GOOD", "WARN", "BAD", "ACCENT"])
def test_a_chip_or_banner_is_readable_on_its_own_tint(name):
    colour = getattr(theme, name)
    for base in (theme.SURFACE_0, theme.SURFACE_1):
        assert contrast(colour, theme.soft(colour, base)) >= TEXT_LEVEL
        assert contrast(theme.TEXT, theme.soft(colour, base)) >= TEXT_LEVEL


@pytest.mark.parametrize("name", ["GOOD", "WARN", "BAD", "ACCENT"])
def test_a_badge_number_is_readable_on_its_colour(name):
    assert contrast(theme.ON_STATUS, getattr(theme, name)) >= TEXT_LEVEL


def test_a_selected_row_stays_readable():
    assert contrast(theme.TEXT, theme.SELECTION) >= TEXT_LEVEL


@pytest.mark.parametrize("surface", list(SURFACES))
def test_the_focus_ring_can_be_seen(surface):
    assert contrast(theme.ACCENT, SURFACES[surface]) >= UI_LEVEL


@pytest.mark.parametrize("status, colour", list(theme.STATUS_COLOURS.items()))
def test_every_status_colour_reads_in_a_table(status, colour):
    assert contrast(colour, theme.SURFACE_1) >= TEXT_LEVEL, status


def test_the_stylesheet_uses_only_tokens():
    """Colours are named by their role. A stray hex code would escape every check above."""
    tokens = {value.lower() for name, value in vars(theme).items()
              if name.isupper() and isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value)}
    tints = {theme.soft(colour, base).lower()
             for colour in (theme.ACCENT, theme.GOOD, theme.WARN, theme.BAD)
             for base in SURFACES.values()}
    used = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", theme.STYLESHEET)}
    assert used - tokens - tints == set()
