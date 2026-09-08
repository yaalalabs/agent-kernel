import pytest

from scopewise.security import Auth
from scopewise.store import Store


def test_session_logout_and_wrong_password(tmp_path):
    auth = Auth(Store(tmp_path / "db.sqlite"), "classroom-invitation")
    auth.register("student", "a-long-test-password", "classroom-invitation")
    with pytest.raises(ValueError):
        auth.login("student", "wrong")
    token, csrf, user = auth.login("student", "a-long-test-password")
    assert auth.resolve(token)["id"] == user["id"]
    assert auth.check_csrf(token, csrf)
    assert not auth.check_csrf(token, "forged")
    auth.logout(token)
    assert auth.resolve(token) is None


def test_invitation_required(tmp_path):
    auth = Auth(Store(tmp_path / "db.sqlite"), "secret-invitation")
    with pytest.raises(ValueError):
        auth.register("student", "a-long-test-password", "wrong")
