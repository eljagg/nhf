"""v0.2.4: friendly error pages, quiet logs, encoded-login redirect."""

import logging

import pytest

from apps.core.logfilters import BelowWarning, Quiet403

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_403_page_is_friendly_and_inside_the_app(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.get("/doctors/register-import/")
    assert resp.status_code == 403
    body = resp.content.decode()
    assert "not part of your role" in body and "Go to Home" in body


def test_404_page_is_friendly(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404 and "Page not found" in resp.content.decode()


def test_encoded_login_link_from_scanners_redirects(client):
    resp = client.get("/accounts/login/%3Fnext=/")
    assert resp.status_code == 302 and resp["Location"] == "/accounts/login/"


def test_403_and_404_do_not_reach_stderr_but_real_errors_do():
    f = Quiet403()
    rec = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "Forbidden", None, None)
    rec.status_code = 403
    assert not f.filter(rec)
    rec.status_code = 404
    assert not f.filter(rec)
    err = logging.LogRecord("django.request", logging.ERROR, __file__, 1, "Internal Server Error", None, None)
    err.status_code = 500
    assert f.filter(err)


def test_info_goes_to_stdout_only():
    f = BelowWarning()
    assert f.filter(logging.LogRecord("x", logging.INFO, __file__, 1, "ok", None, None))
    assert not f.filter(logging.LogRecord("x", logging.ERROR, __file__, 1, "bad", None, None))
