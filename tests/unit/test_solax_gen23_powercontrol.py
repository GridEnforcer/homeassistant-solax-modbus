"""GEN2/GEN3 ModbusPowerControl block (regs 124-128).

The block layout and the signed encoding are ported from a field-proven
deployment, so these tests pin the exact register values that deployment
writes. Getting the word order or the sign wrong here is not a cosmetic bug:
a hand-rolled RemoteControl loop with an inverted sign took two inverters
offline for two hours in the field, which is why this is asserted rather
than assumed.
"""

import pytest

from custom_components.solax_modbus.const import (
    BUTTONREPEAT_FIRST,
    BUTTONREPEAT_LOOP,
    BUTTONREPEAT_POST,
    REGISTER_S32,
    REGISTER_U16,
    WRITE_MULTI_MODBUS,
)
from custom_components.solax_modbus.plugin_solax import (
    autorepeat_function_powercontrol_recompute,
    plugin_instance,
)


def _block(datadict, initval=BUTTONREPEAT_FIRST):
    # The hub always seeds data["_repeatUntil"]; autorepeat_stop() relies on it.
    datadict.setdefault("_repeatUntil", {})
    return autorepeat_function_powercontrol_recompute(initval, None, datadict)


def test_enabled_charge_block():
    out = _block({"powercontrol_enable": "Enabled", "powercontrol_active_power": 2500})
    assert out["action"] == WRITE_MULTI_MODBUS
    assert out["data"] == [(REGISTER_U16, 1), (REGISTER_S32, 2500), (REGISTER_S32, 0)]


def test_discharge_is_negative_not_inverted():
    """Positive = charge, negative = discharge, at the AC reference point."""
    out = _block({"powercontrol_enable": "Enabled", "powercontrol_active_power": -3000})
    assert out["data"][1] == (REGISTER_S32, -3000)


def test_disabled_writes_the_zero_release_block():
    """Release hands the battery back to the inverter's own work mode."""
    out = _block({"powercontrol_enable": "Disabled", "powercontrol_active_power": -3000})
    assert out["data"] == [(REGISTER_U16, 0), (REGISTER_S32, 0), (REGISTER_S32, 0)]


def test_autorepeat_expiry_releases():
    """The POST call after the autorepeat lapses must release, not hold the
    last setpoint - otherwise a stalled loop leaves the inverter throttled."""
    out = _block(
        {"powercontrol_enable": "Enabled", "powercontrol_active_power": -3000},
        initval=BUTTONREPEAT_POST,
    )
    assert out["data"] == [(REGISTER_U16, 0), (REGISTER_S32, 0), (REGISTER_S32, 0)]


def test_loop_keeps_asserting_the_setpoint():
    out = _block(
        {"powercontrol_enable": "Enabled", "powercontrol_active_power": -3000},
        initval=BUTTONREPEAT_LOOP,
    )
    assert out["data"][0] == (REGISTER_U16, 1)
    assert out["data"][1] == (REGISTER_S32, -3000)


def test_missing_or_junk_target_is_treated_as_zero():
    for value in (None, "", "abc"):
        out = _block({"powercontrol_enable": "Enabled", "powercontrol_active_power": value})
        assert out["data"][1] == (REGISTER_S32, 0)


@pytest.mark.parametrize(
    "target,expected",
    [
        (-1000, [64536, 65535]),  # legacy: [1, 65536 + s, 65535, 0, 0]
        (-3000, [62536, 65535]),
        (2500, [2500, 0]),
        (0, [0, 0]),
    ],
)
def test_s32_encodes_low_word_first_like_the_reference_implementation(target, expected):
    """The reference writes `[1, 65536 + s, 65535, 0, 0]` for a negative target,
    i.e. int32 LOW word first. That must be what this plugin's word order gives.
    """
    from pymodbus.client.mixin import ModbusClientMixin

    assert plugin_instance.order32 == "little"
    regs = ModbusClientMixin.convert_to_registers(target, ModbusClientMixin.DATATYPE.INT32, plugin_instance.order32)
    assert regs == expected
