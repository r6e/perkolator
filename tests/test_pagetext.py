import pytest
from factories import benefits_page_html

from perkolator.pagetext import MAX_HTML_CHARS, MAX_TEXT_CHARS, PageError, html_to_text


def test_visible_text_is_kept_one_block_per_line() -> None:
    html = benefits_page_html("<h2>Up to $400 Resy Credit</h2><p>Up to $100\n   quarterly.</p>")
    assert "Up to $400 Resy Credit\nUp to $100 quarterly." in html_to_text(html)


@pytest.mark.parametrize("tag", ["script", "style", "noscript", "svg", "template"])
def test_non_visible_elements_are_dropped(tag: str) -> None:
    assert "HIDDEN" not in html_to_text(benefits_page_html(f"<{tag}>HIDDEN</{tag}><p>shown</p>"))


def test_line_repeated_under_different_benefits_is_kept_each_time() -> None:
    body = "<h2>Resy</h2><p>Enrollment required.</p><h2>Oura</h2><p>Enrollment required.</p>"
    assert html_to_text(benefits_page_html(body)).count("Enrollment required.") == 2


def test_line_repeated_back_to_back_is_kept_once() -> None:
    text = html_to_text(benefits_page_html("<p>Learn more</p>" * 3))
    assert text.count("Learn more") == 1


def test_entities_are_decoded() -> None:
    html = benefits_page_html("<p>Fine Hotels + Resorts&reg; &amp; more</p>")
    assert "Fine Hotels + Resorts® & more" in html_to_text(html)


def test_control_and_direction_characters_are_removed() -> None:
    html = benefits_page_html("<p>safe" + chr(0x202E) + chr(0x1B) + "text</p>")
    assert "safetext" in html_to_text(html)


def test_parser_failure_is_reported_as_an_unusable_page(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> None:
        raise RuntimeError

    monkeypatch.setattr("html.parser.HTMLParser.feed", explode)
    with pytest.raises(PageError, match="cannot be parsed"):
        html_to_text(benefits_page_html())


@pytest.mark.parametrize(
    ("html", "reason"),
    [
        pytest.param("", "too short", id="empty"),
        pytest.param("<html><body><p>Access Denied</p></body></html>", "too short", id="blocked"),
        pytest.param(
            "".join(f"<p>Some other long page, paragraph {n}.</p>" for n in range(300)),
            "does not name",
            id="not-the-card-page",
        ),
        pytest.param(
            benefits_page_html(f"<p>{'x' * (MAX_TEXT_CHARS + 1)}</p>"),
            "too long",
            id="more-text-than-the-model-is-given",
        ),
        pytest.param("x" * (MAX_HTML_CHARS + 1), "too large", id="oversized"),
    ],
)
def test_unusable_page_is_rejected(html: str, reason: str) -> None:
    with pytest.raises(PageError, match=reason):
        html_to_text(html)
