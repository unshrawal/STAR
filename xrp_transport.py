import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Optional

import requests
import websockets
from bleak import BleakClient


class XrpTransport(ABC):
    """Transport abstraction for sending XRP command frames."""

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def send_command(self, command: bytes) -> None:
        pass

    async def wait_feedback(self) -> None:
        """Wait for ACK/feedback from the firmware if available."""
        return


class BleXrpTransport(XrpTransport):
    def __init__(self, address: str, rx_characteristic: str, tx_characteristic: str):
        self.address = address
        self.rx_characteristic = rx_characteristic
        self.tx_characteristic = tx_characteristic
        self.feedback_event = asyncio.Event()
        self.client: Optional[BleakClient] = None

    def _unlock_command_mutex(self, _sender, data):
        print(f"received {data}")
        self.feedback_event.set()

    async def connect(self) -> None:
        self.client = BleakClient(self.address)
        await self.client.connect()
        await self.client.start_notify(self.tx_characteristic, callback=self._unlock_command_mutex)

    async def disconnect(self) -> None:
        if self.client is not None:
            if self.client.is_connected:
                await self.client.disconnect()
            self.client = None

    async def send_command(self, command: bytes) -> None:
        if self.client is None:
            raise RuntimeError("BLE XRP transport is not connected")
        await self.client.write_gatt_char(self.rx_characteristic, command, response=True)

    async def wait_feedback(self) -> None:
        await self.feedback_event.wait()
        self.feedback_event.clear()


class WifiXrpTransport(XrpTransport):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip("/")
        self.protocol = "ws" if self.endpoint.startswith(("ws://", "wss://")) else "http"
        self.websocket = None

    async def connect(self) -> None:
        if self.protocol == "ws":
            self.websocket = await websockets.connect(self.endpoint)

    async def disconnect(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
            self.websocket = None

    async def send_command(self, command: bytes) -> None:
        frame = command.decode("utf-8")
        if self.protocol == "http":
            command_endpoint = os.getenv("XRP_WIFI_COMMAND_PATH", "/command")
            url = f"{self.endpoint}{command_endpoint}"

            def _post():
                response = requests.post(url, json={"frame": frame}, timeout=(3.05, 5))
                response.raise_for_status()

            await asyncio.to_thread(_post)
            return

        if self.websocket is None:
            raise RuntimeError("WiFi XRP transport websocket is not connected")

        await self.websocket.send(json.dumps({"type": "command", "frame": frame}))

    async def wait_feedback(self) -> None:
        if self.protocol != "ws" or self.websocket is None:
            return

        ack = await self.websocket.recv()
        try:
            payload = json.loads(ack)
        except json.JSONDecodeError:
            return

        if payload.get("type") == "ack":
            return
