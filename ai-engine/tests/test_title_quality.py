import pytest

from app.intelligence.title_quality import title_usable

GOOD = ["Fix login page", "Payment API integration", "Razorpay integration", "Banner design", "Update the invoice export", "Deploy backend to staging",
        "Payment gateway test", "dashboard UI", "Fix DB sync", "Homepage banner change", "Add watermark to product images", "इनवॉइस एक्सपोर्ट ठीक करना"]
JUNK = ["I URL", "I sub URL for", "Join sir", "join", "<Media omitted>", "ok sir", "I will", "we need", "and", "check this", "Deploy", "the work for", "Rahul sir"]


@pytest.mark.parametrize("t", GOOD)
def test_real_work_titles_are_kept(t):
    assert title_usable(t, ["Rahul", "Priya"]), t


@pytest.mark.parametrize("t", JUNK)
def test_fragments_are_not_tasks(t):
    assert not title_usable(t, ["Rahul", "Priya"]), t


def test_names_and_vocatives_do_not_count_as_content():
    assert not title_usable("Rahul Priya sir madam", ["Rahul", "Priya"])
    assert title_usable("Rahul fix payment bug", ["Rahul"])


def test_cut_off_sentences_are_rejected():
    assert not title_usable("Update the payment page and")
    assert title_usable("Update the payment page")


def test_whatsapp_mentions_and_invisible_marks_do_not_count_as_words():
    mention = "@⁨~Harsha Vardhan⁩"
    assert not title_usable(f"{mention} join sir")                 # only "join" is left after removing the mention
    assert title_usable(f"{mention} join the client demo call")
    assert not title_usable("‎‎<Media omitted>")
