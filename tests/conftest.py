import socket

import pytest


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("tests must not make network connections")


@pytest.fixture(autouse=True)
def offline_network_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deny Python socket operations that can connect or transmit in tests."""
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket.socket, "sendto", _deny_network)
    monkeypatch.setattr(socket.socket, "sendmsg", _deny_network, raising=False)
