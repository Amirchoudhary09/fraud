"""Production launcher: one dual-stack socket (IPv6 + IPv4) handed to uvicorn.

uvicorn --host :: gives an IPv6 socket with IPV6_V6ONLY set by asyncio, which silently refuses
IPv4 clients (Docker's default network, health checks on 127.0.0.1, IPv4 peers on Railway).
Here the socket accepts both families; hosts without IPv6 fall back to IPv4 only.

    python -m app.serve            (PORT from the environment, default 8000)
"""
import logging
import os
import socket

import uvicorn


def make_socket(port: int) -> socket.socket:
    if socket.has_ipv6:
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # accept IPv4-mapped clients too
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("::", port))
            return s
        except OSError as e:  # IPv6 disabled in this container/kernel
            logging.getLogger(__name__).info("IPv6 unavailable (%s); listening on IPv4 only", e)
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    return s


def main():
    logging.basicConfig(level=logging.INFO)
    sock = make_socket(int(os.getenv("PORT", "8000")))
    sock.listen(2048)
    sock.set_inheritable(True)
    uvicorn.run("app.main:app", fd=sock.fileno(), proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
