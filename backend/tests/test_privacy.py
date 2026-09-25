from app.core.privacy import find_blocked_terms, redact


def test_redacts_contact_details():
    text = "Call +91 98765 43210 or mail amir@example.com, Aadhaar 1234 5678 9012, PAN ABCDE1234F"
    out = redact(text)
    assert "98765" not in out and "example.com" not in out and "9012" not in out and "ABCDE1234F" not in out


def test_keeps_years_and_short_numbers():
    text = "Worked 2019 - 2023 at WASP3D, 3 projects, class of 2021"
    assert redact(text) == text


def test_blocks_sensitive_requests():
    assert find_blocked_terms("Amir home address") == ["home address"]
    assert find_blocked_terms("Amir Choudhary WASP3D") == []


def test_where_questions_only_blocked_for_home_location():
    assert find_blocked_terms("Where does C001 work?") == []
    assert find_blocked_terms("where does he live") == ["where does he live"]
    assert find_blocked_terms("iska ghar ka pata kya hai") == ["ghar ka pata"]
