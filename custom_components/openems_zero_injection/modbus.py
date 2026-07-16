"""Minimal, deliberately restricted Modbus TCP client for the DTU Pro-S."""

from __future__ import annotations

import asyncio
import logging
import struct

from .const import DEFAULT_DEVICE_ID, MODBUS_TIMEOUT_SECONDS
from .registers import POWER_LIMIT_REGISTERS, TEMPORARY_POWER_LIMIT_REGISTERS

_LOGGER = logging.getLogger(__name__)

_FUNCTION_READ_HOLDING_REGISTERS = 0x03
_FUNCTION_READ_INPUT_REGISTERS = 0x04
_FUNCTION_WRITE_SINGLE_REGISTER = 0x06
_MBAP_SIZE = 7


class DtuConnectionError(Exception):
    """Raised for network, Modbus, or invalid Modbus TCP responses."""


class DtuProSModbusClient:
    """DTU client restricted to documented telemetry and temporary power limits.

    Function ``0x03`` is restricted to the six documented power-limit
    registers. Function ``0x06`` is restricted to the three temporary,
    per-port power-limit registers. No API can write a global or permanent
    register.
    """

    def __init__(
        self, host: str, port: int, device_id: int = DEFAULT_DEVICE_ID
    ) -> None:
        self.host = host
        self.port = port
        self.device_id = device_id
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction_id = 0
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return whether a usable TCP stream is currently open."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> bool:
        """Open the TCP connection if it is not already open."""
        if self.connected:
            return True
        await self.async_disconnect()
        try:
            async with asyncio.timeout(MODBUS_TIMEOUT_SECONDS):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
        except (OSError, TimeoutError) as err:
            raise DtuConnectionError(str(err) or "Connection failed") from err
        _LOGGER.debug("Connected to DTU Modbus TCP endpoint %s:%s", self.host, self.port)
        return True

    async def async_check_connectivity(self) -> bool:
        """Check that the DTU TCP endpoint is reachable."""
        return await self.async_connect()

    async def async_read_input_registers(self, address: int, count: int) -> list[int]:
        """Read documented input-register telemetry using function ``0x04``."""
        self._validate_range(address, count, "input register")
        return await self._async_read_registers(
            _FUNCTION_READ_INPUT_REGISTERS, address, count
        )

    async def async_read_power_limit_register(self, address: int) -> int:
        """Read one documented per-port or global power-limit register.

        This intentionally does not provide a generic holding-register API.
        """
        if address not in POWER_LIMIT_REGISTERS:
            raise DtuConnectionError("Undocumented power-limit register")
        registers = await self._async_read_registers(
            _FUNCTION_READ_HOLDING_REGISTERS, address, 1
        )
        return registers[0]

    async def async_write_temporary_power_limit(self, address: int, value: int) -> None:
        """Write a single documented temporary per-port power limit.

        The response must echo precisely the request address and value. Global
        and permanent registers are rejected before any Modbus frame is sent.
        """
        if address not in TEMPORARY_POWER_LIMIT_REGISTERS:
            raise DtuConnectionError("Only temporary per-port limits may be written")
        if not isinstance(value, int) or not 2 <= value <= 100:
            raise DtuConnectionError("Temporary power limit must be between 2 and 100")

        async with self._lock:
            _LOGGER.info(
                "Writing temporary DTU power limit: register 0x%04X, value %s%%",
                address,
                value,
            )
            response = await self._async_request_locked(
                _FUNCTION_WRITE_SINGLE_REGISTER,
                struct.pack(">HH", address, value),
            )
            self._validate_write_response(response, address, value)
            _LOGGER.info(
                "DTU acknowledged temporary power limit: register 0x%04X, value %s%%",
                address,
                value,
            )

    async def _async_read_registers(
        self, function_code: int, address: int, count: int
    ) -> list[int]:
        async with self._lock:
            response = await self._async_request_locked(
                function_code, struct.pack(">HH", address, count)
            )
            return self._decode_read_response(response, function_code, count)

    async def _async_request_locked(self, function_code: int, data: bytes) -> bytes:
        """Send exactly one PDU and return its response while holding the lock."""
        await self.async_connect()
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        transaction_id = self._transaction_id
        pdu = bytes([function_code]) + data
        request = (
            struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, self.device_id)
            + pdu
        )
        try:
            assert self._writer is not None and self._reader is not None
            self._writer.write(request)
            await self._writer.drain()
            async with asyncio.timeout(MODBUS_TIMEOUT_SECONDS):
                mbap = await self._reader.readexactly(_MBAP_SIZE)
                response_tid, protocol_id, length, device_id = struct.unpack(
                    ">HHHB", mbap
                )
                if response_tid != transaction_id:
                    raise DtuConnectionError("Unexpected Modbus transaction ID")
                if protocol_id != 0:
                    raise DtuConnectionError("Unexpected Modbus protocol ID")
                if device_id != self.device_id:
                    raise DtuConnectionError("Unexpected Modbus device ID")
                if length < 2:
                    raise DtuConnectionError("Invalid Modbus TCP response length")
                return await self._reader.readexactly(length - 1)
        except DtuConnectionError:
            await self.async_disconnect()
            raise
        except (OSError, asyncio.IncompleteReadError, TimeoutError) as err:
            await self.async_disconnect()
            raise DtuConnectionError(str(err) or "Modbus communication failed") from err

    def _decode_read_response(
        self, response: bytes, expected_function: int, count: int
    ) -> list[int]:
        if len(response) < 2:
            raise DtuConnectionError("Truncated Modbus register response")
        function_code, byte_count = response[0], response[1]
        if function_code == (expected_function | 0x80):
            raise DtuConnectionError(
                f"Modbus exception 0x{response[1]:02X}"
                if len(response) == 2
                else "Malformed Modbus exception response"
            )
        if function_code != expected_function:
            raise DtuConnectionError("Unexpected Modbus function code")
        payload = response[2:]
        if byte_count != len(payload) or byte_count != count * 2:
            raise DtuConnectionError("Invalid Modbus register byte count")
        return list(struct.unpack(f">{count}H", payload))

    @staticmethod
    def _validate_write_response(response: bytes, address: int, value: int) -> None:
        if len(response) < 2:
            raise DtuConnectionError("Truncated Modbus write response")
        function_code = response[0]
        if function_code == (_FUNCTION_WRITE_SINGLE_REGISTER | 0x80):
            raise DtuConnectionError(
                f"Modbus exception 0x{response[1]:02X}"
                if len(response) == 2
                else "Malformed Modbus exception response"
            )
        if function_code != _FUNCTION_WRITE_SINGLE_REGISTER or len(response) != 5:
            raise DtuConnectionError("Unexpected Modbus write response")
        echoed_address, echoed_value = struct.unpack(">HH", response[1:])
        if echoed_address != address:
            raise DtuConnectionError("Modbus write response address does not match")
        if echoed_value != value:
            raise DtuConnectionError("Modbus write response value does not match")

    @staticmethod
    def _validate_range(address: int, count: int, description: str) -> None:
        if not 0 <= address <= 0xFFFF or not 1 <= count <= 125:
            raise DtuConnectionError(f"Invalid {description} address or count")

    async def async_disconnect(self) -> None:
        """Close the TCP stream and release its reader and writer."""
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            _LOGGER.debug("Disconnected from DTU Modbus TCP endpoint")
