from pathlib import Path

from bs4 import BeautifulSoup

from app.whop.extractor import _extract_image_url, extract_messages

FIXTURES = Path(__file__).parent / "fixtures"


def _msg_el(name: str):
    html = (FIXTURES / name).read_text()
    return BeautifulSoup(html, "html.parser").find(attrs={"data-message-id": True})


def test_extract_image_url_from_message_with_image():
    el = _msg_el("message_with_image.html")
    url = _extract_image_url(el)
    assert url == (
        "https://img-v2-prod.whop.com/unsafe/rs:fit:3840:0/plain/"
        "https%3A%2F%2Fexample.png"
    )


def test_extract_image_url_returns_none_for_text_only():
    el = _msg_el("message_text_only.html")
    assert _extract_image_url(el) is None


def test_extract_image_url_ignores_non_whop_images():
    html = """
    <div data-message-id="m" data-attachment-id="a">
      <img src="https://other.cdn.com/foo.png" />
    </div>
    """
    el = BeautifulSoup(html, "html.parser").find(attrs={"data-message-id": True})
    assert _extract_image_url(el) is None


def test_extract_messages_image_only_flows_through():
    """A message with only an image (no caption) should produce a Message
    with content="" and image_url set, not be silently dropped."""
    fixture = FIXTURES / "message_with_image.html"
    html = fixture.read_text()
    messages = extract_messages(html, source="chat")
    assert len(messages) == 1
    assert messages[0].image_url is not None
    assert messages[0].image_url.endswith("example.png")
