import socket

import pytest

from app.serve import make_socket


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_listener_accepts_ipv4_and_ipv6_clients():
    port = _free_port()
    srv = make_socket(port)
    srv.listen(4)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            pass  # IPv4 client (Docker bridge, 127.0.0.1 health checks)
        if srv.family == socket.AF_INET6:
            with socket.create_connection(("::1", port), timeout=3):
                pass  # IPv6 client (Railway private network)
        else:
            pytest.skip("IPv6 not available on this host")
    finally:
        srv.close()
