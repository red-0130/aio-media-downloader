"""Lightweight asyncio SOCKS5 proxy server for E2E testing with connection tracking."""

import asyncio
import socket
import struct
from typing import Any


class MockSocks5Proxy:
    """AsyncIO SOCKS5 proxy test stub tracking connections."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.server: asyncio.Server | None = None
        self.connections: list[dict[str, Any]] = []
        self._running = False

    @property
    def connection_count(self) -> int:
        return len(self.connections)

    def get_connections(self) -> list[dict[str, Any]]:
        return list(self.connections)

    def reset(self) -> None:
        self.connections.clear()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        client_addr = writer.get_extra_info("peername")
        target_host: str | None = None
        target_port: int | None = None

        try:
            # 1. Negotiation Handshake
            ver = await reader.read(1)
            if not ver or ver[0] != 5:
                writer.close()
                await writer.wait_closed()
                return

            nmethods_byte = await reader.read(1)
            if not nmethods_byte:
                writer.close()
                await writer.wait_closed()
                return

            nmethods = nmethods_byte[0]
            methods = await reader.read(nmethods)

            # Reply: VER 5, METHOD 0 (NO AUTHENTICATION REQUIRED)
            writer.write(b"\x05\x00")
            await writer.drain()

            # 2. Request Details
            req_header = await reader.read(4)
            if len(req_header) < 4:
                writer.close()
                await writer.wait_closed()
                return

            ver, cmd, rsv, atyp = req_header
            if ver != 5 or cmd != 1:  # 1 = CONNECT
                # Command not supported
                writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            # Address resolution
            if atyp == 1:  # IPv4
                addr_bytes = await reader.read(4)
                target_host = socket.inet_ntoa(addr_bytes)
            elif atyp == 3:  # Domain name
                domain_len = (await reader.read(1))[0]
                domain_bytes = await reader.read(domain_len)
                target_host = domain_bytes.decode("utf-8", errors="replace")
            elif atyp == 4:  # IPv6
                addr_bytes = await reader.read(16)
                target_host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            else:
                writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            port_bytes = await reader.read(2)
            target_port = struct.unpack("!H", port_bytes)[0]

            # Record connection event
            self.connections.append(
                {
                    "client": client_addr,
                    "target_host": target_host,
                    "target_port": target_port,
                    "cmd": cmd,
                    "atyp": atyp,
                }
            )

            # Try to forward traffic if target is reachable (e.g. localhost test server)
            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(target_host, target_port), timeout=1.0
                )
                # Reply: SUCCESS (REP 0)
                writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                await writer.drain()

                async def forward(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
                    try:
                        while not src.at_eof():
                            data = await src.read(4096)
                            if not data:
                                break
                            dst.write(data)
                            await dst.drain()
                    except Exception:
                        pass
                    finally:
                        try:
                            dst.close()
                            await dst.wait_closed()
                        except Exception:
                            pass

                await asyncio.gather(
                    forward(reader, remote_writer),
                    forward(remote_reader, writer),
                    return_exceptions=True,
                )
            except Exception:
                # Target not reachable or synthetic test endpoint: send success response
                # to satisfy client handshake for mock calls
                writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                await writer.drain()
                # Read remainder until EOF
                while not reader.at_eof():
                    chunk = await reader.read(1024)
                    if not chunk:
                        break

        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> int:
        """Start proxy server and return bound port."""
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        # Determine actual assigned port
        sockets = self.server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        self._running = True
        return self.port

    async def stop(self) -> None:
        """Stop proxy server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self._running = False
