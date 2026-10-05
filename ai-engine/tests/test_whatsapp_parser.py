from datetime import datetime

import pytest

from app.parsers.whatsapp import UnsupportedFormatError, WhatsAppParser

IOS = """‎[01/10/2026, 10:30:15 AM] Rahul: Client has approved the login screen.
[01/10/2026, 10:45:02 AM] Amit: Frontend completed.
second line of Amit
[01/10/2026, 11:00:00 AM] Sales - Neha: Client has not responded regarding payment gateway.
‎[01/10/2026, 11:05:00 AM] Rahul: ‎image omitted
[01/10/2026, 11:30:00 PM] ~ Amit: This message was deleted
[13/10/2026, 12:10:00 AM] Rahul added Priya
"""

ANDROID = """01/10/2026, 10:30 - Rahul: Backend API is pending.
01/10/2026, 18:45 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.
01/10/2026, 18:50 - +91 98765 43210: kal tak kar dena https://example.com/x
IMG-2026.jpg (file attached)
01/10/2026, 18:51 - Amit: <Media omitted>
"""

US = """10/21/26, 9:05 PM - Rahul: ok
10/22/26, 12:00 AM - Amit: midnight
"""


def parse(t):
    p = WhatsAppParser()
    return p, p.parse_text(t)


def test_ios_basic_and_multiline():
    p, msgs = parse(IOS)
    assert len(msgs) == 6
    assert msgs[0].sender_name == "Rahul"
    assert msgs[0].timestamp == datetime(2026, 10, 1, 10, 30, 15)
    assert msgs[1].text == "Frontend completed.\nsecond line of Amit"
    assert msgs[2].sender_name == "Sales - Neha"
    assert p.report.header_style == "bracket"


def test_dmy_detected_from_day_gt_12():
    p, msgs = parse(IOS)
    assert p.report.date_order == "DMY" and not p.report.date_order_ambiguous
    assert msgs[-1].timestamp == datetime(2026, 10, 13, 0, 10)
    assert msgs[-1].is_system and msgs[-1].sender_name is None


def test_12h_am_pm_conversion():
    _, msgs = parse(IOS)
    assert msgs[4].timestamp.hour == 23
    _, msgs = parse(US)
    assert msgs[1].timestamp == datetime(2026, 10, 22, 0, 0)


def test_us_order_detected():
    p, msgs = parse(US)
    assert p.report.date_order == "MDY"
    assert msgs[0].timestamp == datetime(2026, 10, 21, 21, 5)


def test_media_deleted_flags():
    _, msgs = parse(IOS)
    assert msgs[3].is_media and msgs[3].media_kind == "image"
    assert msgs[4].is_deleted and msgs[4].message_type == "deleted"
    assert msgs[4].sender_name == "Amit"  # '~ ' prefix stripped


def test_android_system_phone_url_attachment():
    p, msgs = parse(ANDROID)
    assert p.report.clock == "24h"
    assert msgs[1].is_system and msgs[1].message_type == "system"
    assert msgs[2].sender_phone == "+919876543210"
    assert msgs[2].urls == ["https://example.com/x"]
    assert "IMG-2026.jpg (file attached)" in msgs[2].raw_text  # continuation preserved
    assert msgs[3].is_media


def test_ambiguous_date_flagged():
    p, msgs = parse("01/02/2026, 10:30 - A: hi\n03/04/2026, 10:31 - B: yo\n")
    assert p.report.date_order_ambiguous and p.report.warnings
    assert msgs[0].timestamp.month == 2  # DMY default


def test_ids_deterministic_and_unique_for_duplicates():
    t = "01/10/2026, 10:30 - A: ok\n01/10/2026, 10:30 - A: ok\n"
    _, m1 = parse(t)
    _, m2 = parse(t)
    assert [m.message_id for m in m1] == [m.message_id for m in m2]
    assert m1[0].message_id != m1[1].message_id


def test_raw_text_preserved():
    _, msgs = parse("01/10/2026, 10:30 - A: hello <This message was edited>\n")
    assert msgs[0].is_edited and msgs[0].text == "hello"
    assert msgs[0].raw_text.endswith("<This message was edited>")


def test_hinglish_devanagari_emoji_roundtrip():
    _, msgs = parse("01/10/2026, 10:30 - Amit: फ्रंटएंड complete ho gaya 👍\n")
    assert msgs[0].text == "फ्रंटएंड complete ho gaya 👍"


def test_system_message_with_colon_is_not_a_sender():
    _, msgs = parse('01/10/2026, 10:30 - Rahul changed the subject to "Proj: Alpha"\n')
    assert msgs[0].is_system


def test_unsupported_raises():
    with pytest.raises(UnsupportedFormatError):
        parse("just some random text\nnot a chat\n")


def test_empty_raises():
    with pytest.raises(UnsupportedFormatError):
        parse("")


def test_file_streaming_cp1252_and_utf16(tmp_path):
    f = tmp_path / "c.txt"
    f.write_bytes("01/10/2026, 10:30 - A: caf\xe9\n".encode("cp1252"))
    msgs = list(WhatsAppParser().parse_file(f))
    assert msgs[0].text == "café"
    g = tmp_path / "u.txt"
    g.write_text("01/10/2026, 10:30 - A: hi\n", encoding="utf-16")
    assert next(WhatsAppParser().parse_file(g)).text == "hi"
