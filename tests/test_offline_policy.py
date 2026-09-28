import socket

import pytest


def test_test_suite_denies_socket_connections() -> None:
    """Kills mutation: remove socket.socket.connect denial from offline_network_guard."""
    with (
        socket.socket() as connection,
        pytest.raises(AssertionError, match="tests must not make network connections"),
    ):
        connection.connect(("127.0.0.1", 9))


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="sendmsg unavailable")
def test_test_suite_denies_socket_sendmsg() -> None:
    """Kills mutation: remove socket.socket.sendmsg denial from offline_network_guard."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection,
        pytest.raises(AssertionError, match="tests must not make network connections"),
    ):
        connection.sendmsg([b"blocked"], (), 0, ("127.0.0.1", 9))
