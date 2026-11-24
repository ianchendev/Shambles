"""Pulling the sign-in URL out of what the vendor prints."""

from shambles import login


def test_finds_a_url_in_a_noisy_line():
    line = ("Open this URL in your browser: "
            "https://claude.ai/oauth/authorize?code_challenge=abc&state=xyz")
    assert login.find_url(line) == (
        "https://claude.ai/oauth/authorize?code_challenge=abc&state=xyz")


def test_finds_a_url_on_its_own_line():
    url = "https://auth.openai.com/authorize?x=1"
    assert login.find_url(f"  {url}  ") == url


def test_ignores_a_line_with_no_url():
    assert login.find_url("Waiting for the browser...") is None
    assert login.find_url("") is None


def test_takes_the_first_url_when_a_line_has_two():
    first = "https://a.example/one"
    assert login.find_url(f"{first} or https://b.example/two") == first


def test_strips_trailing_punctuation_that_is_not_part_of_the_url():
    assert login.find_url("Visit https://claude.ai/oauth?a=1.") == \
        "https://claude.ai/oauth?a=1"
    assert login.find_url("(https://claude.ai/oauth)") == \
        "https://claude.ai/oauth"


def test_only_http_schemes():
    assert login.find_url("file:///etc/passwd") is None
    assert login.find_url("ftp://example.com/x") is None
