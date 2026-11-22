"""Smoke test of the Streamlit screen itself (no model, no photos)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def click(at: AppTest, text: str) -> AppTest:
    button = next(b for b in at.button if text in b.label)
    return button.click().run()


def test_sample_batch_flows_from_input_to_result():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception

    at = click(at, "تجربة ببيانات نموذجية")
    assert not at.exception
    assert at.session_state["nav"].startswith("٢")

    at = click(at, "إعادة الحساب")
    assert not at.exception
    result = at.session_state["result"]
    assert result.ok and str(result.computed_total) == "1900000"
    assert result.previous_last_serial == 1200          # smallest serial 1201 minus 1
    assert any("كل شيء مطابق" in s.value for s in at.success)


def test_merged_rounding_shows_note_and_three_numbers():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at = click(at, "تجربة ببيانات نموذجية")
    tax = next(t for t in at.text_input if "الرقم 2" in t.label)
    rounding = next(t for t in at.text_input if "الرقم 3" in t.label)
    tax.set_value("١٠٠٬٠٠٠")
    rounding.set_value("")
    at = click(at, "إعادة الحساب")
    assert not at.exception
    result = at.session_state["result"]
    assert len(result.numbers) == 3
    assert any("كان يجب دفع كل مبلغ على حدة" in i.value for i in at.info)


def test_phone_page_renders_without_the_main_screen():
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["phone"] = "1"
    at.run()
    assert not at.exception
    assert any("تصوير الكشوف" in t.value for t in at.title)
    assert any("إرسال إلى الحاسوب" in b.label for b in at.button)
    assert not at.radio                      # the step navigation is not shown on the phone


def test_photos_sent_from_the_phone_show_up_on_the_computer(tmp_path, monkeypatch):
    import io

    from PIL import Image

    from sheetcheck import inbox

    monkeypatch.setattr("sheetcheck.config.DATA_DIR", tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="JPEG")
    inbox.save(tmp_path / "inbox", inbox.SUMMARY, buf.getvalue())
    inbox.save(tmp_path / "inbox", inbox.SHEETS, buf.getvalue())
    inbox.save(tmp_path / "inbox", inbox.SHEETS, buf.getvalue())

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("وصلت من الهاتف" in s.value and "كشوف 2" in s.value for s in at.success)


def test_qr_code_is_offered_only_when_the_app_listens_on_the_network(monkeypatch):
    import pytest
    from streamlit import config

    from sheetcheck import inbox

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert any("run_phone.bat" in i.value for i in at.info)       # localhost only: explain how

    if inbox.lan_ip() is None:
        pytest.skip("no local network on this machine")
    monkeypatch.setattr("sheetcheck.inbox.lan_ip", lambda: "192.168.1.5")
    previous = config.get_option("server.address")
    config.set_option("server.address", "0.0.0.0")
    try:
        at = AppTest.from_file(APP, default_timeout=30).run()
    finally:
        config.set_option("server.address", previous)
    assert not at.exception
    assert any("http://192.168.1.5:" in c.value and "?phone=1" in c.value for c in at.code)


def test_photos_are_read_reviewed_and_verified(tmp_path, monkeypatch):
    """The whole photo flow with the model replaced by canned readings."""
    import io

    from PIL import Image

    from sheetcheck import extraction as ex
    from sheetcheck import inbox

    monkeypatch.setattr("sheetcheck.config.DATA_DIR", tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="JPEG")
    inbox.save(tmp_path / "inbox", inbox.SUMMARY, buf.getvalue())
    inbox.save(tmp_path / "inbox", inbox.SHEETS, buf.getvalue())

    def fake_sheet(image, cfg, double_read=False, on_progress=None, on_step=None):
        on_step(1, 2)
        on_progress(25)
        return ex.sheet_from_json({"sheet_number": "1", "sheet_date": "", "rows": [
            {"serial": "1201", "amount": "150000", "date": "1/7/2026", "unclear": []},
            {"serial": "1202", "amount": "50000", "date": "", "unclear": [
                {"field": "amount", "reason": "رقم مطموس", "alternatives": ["80000"]}]}]})

    def fake_summary(image, cfg, double_read=False, on_progress=None, on_step=None):
        return ex.summary_from_json(
            {"total": "200000", "tax": "10000", "rounding": "", "stamp": "2500", "unclear": []})

    monkeypatch.setattr(ex, "server_status", lambda model: (True, True, "ok"))
    monkeypatch.setattr(ex, "extract_sheet", fake_sheet)
    monkeypatch.setattr(ex, "extract_summary", fake_summary)

    at = AppTest.from_file(APP, default_timeout=30).run()
    at = click(at, "استخراج البيانات")
    assert not at.exception
    assert at.session_state["nav"].startswith("٢")
    table = at.session_state["sheets"][0]["df"]
    assert list(table["التسلسل"]) == [1201, 1202]
    assert list(table["غير واضح"]) == [False, True]
    assert inbox.counts(tmp_path / "inbox") == (0, 0)        # photos moved into the session

    at = click(at, "إعادة الحساب")
    assert not at.exception
    result = at.session_state["result"]
    assert str(result.computed_total) == "200000" and result.exact_tax == 10000
    assert result.quarter == (2026, 3)                      # from the date 1/7/2026
    assert not result.ok and any("رقم مطموس" in u for u in result.unclear)
