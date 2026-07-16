"""Minimal internal Modbus TCP client, read-only function 0x04 only."""
from __future__ import annotations
import asyncio
import struct
from .const import DEFAULT_DEVICE_ID, MODBUS_TIMEOUT_SECONDS

_FUNCTION_READ_INPUT_REGISTERS = 0x04
_MBAP_SIZE = 7

class DtuConnectionError(Exception):
    """Raised for network or invalid Modbus TCP responses."""

class DtuProSModbusClient:
    """DTU client with no Modbus write capability."""
    def __init__(self, host: str, port: int, device_id: int = DEFAULT_DEVICE_ID) -> None:
        self.host, self.port, self.device_id = host, port, device_id
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction_id = 0
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> bool:
        if self.connected:
            return True
        await self.async_disconnect()
        try:
            async with asyncio.timeout(MODBUS_TIMEOUT_SECONDS):
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except (OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err) or "Connection failed") from err
        return True

    async def async_check_connectivity(self) -> bool:
        return await self.async_connect()

    async def async_read_input_registers(self, address: int, count: int) -> list[int]:
        if not 0 <= address <= 0xFFFF or not 1 <= count <= 125:
            raise DtuConnectionError("Invalid input register address or count")
        async with self._lock:
            await self.async_connect()
            self._transaction_id = (self._transaction_id + 1) & 0xFFFF
            transaction_id = self._transaction_id
            pdu = struct.pack(">BHH", _FUNCTION_READ_INPUT_REGISTERS, address, count)
            request = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, self.device_id) + pdu
            try:
                assert self._writer is not None and self._reader is not None
                self._writer.write(request)
                await self._writer.drain()
                async with asyncio.timeout(MODBUS_TIMEOUT_SECONDS):
                    mbap = await self._reader.readexactly(_MBAP_SIZE)
                    response_tid, protocol_id, length, device_id = struct.unpack(">HHHB", mbap)
                    if response_tid != transaction_id or protocol_id != 0 or device_id != self.device_id:
                        raise DtuConnectionError("Invalid Modbus TCP response header")
                    if length < 2:
                        raise DtuConnectionError("Invalid Modbus TCP response length")
                    pdu_response = await self._reader.readexactly(length - 1)
            except (OSError, asyncio.IncompleteReadError, TimeoutError) as err:
                await self.async_disconnect()
                raise DtuConnectionError(str(err) or "Modbus communication failed") from err
            function_code = pdu_response[0]
            if function_code == (_FUNCTION_READ_INPUT_REGISTERS | 0x80):
                raise DtuConnectionError("Modbus exception response")
            if function_code != _FUNCTION_READ_INPUT_REGISTERS:
                raise DtuConnectionError("Unexpected Modbus function code")
            byte_count = pdu_response[1]
            payload = pdu_response[2:]
            if byte_count != len(payload) or byte_count != count * 2:
                raise DtuConnectionError("Invalid Modbus register byte count")
            return list(struct.unpack(f">{count}H", payload))

    async def async_disconnect(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
