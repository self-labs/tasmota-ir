"""Version 1 entries, with appliances in the options, move to subentries."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .conftest import NEC_POWER, board_entry


async def test_appliances_and_codes_move_without_renaming_anything(
    hass: HomeAssistant,
    mqtt_mock,
    hass_storage,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entity ids, emitters and codes survive; every appliance gets a device."""
    entry = board_entry(
        version=1,
        options={
            "appliances": {
                "TV Quarto": {"channel": 3, "kind": "generic"},
                "Ar Escritorio": {
                    "channel": 5,
                    "kind": "climate",
                    "vendor": "LG2",
                    "model": "AKB75215403",
                    "min_temp": 18,
                    "max_temp": 30,
                },
            }
        },
    )
    entry.add_to_hass(hass)
    hass_storage[f"tasmota_ir_{entry.entry_id}_codes"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"tasmota_ir_{entry.entry_id}_codes",
        "data": {
            "TV Quarto": {"power": NEC_POWER},
            # Learned by action under a name nobody registered.
            "Bancada": {"teste1": NEC_POWER},
        },
    }
    entity_registry.async_get_or_create(
        "button",
        "tasmota_ir",
        f"{entry.entry_id}_TV Quarto_power",
        config_entry=entry,
        suggested_object_id="hubb_ir1_tv_quarto_power",
    )
    entity_registry.async_get_or_create(
        "climate",
        "tasmota_ir",
        f"{entry.entry_id}_climate_Ar Escritorio",
        config_entry=entry,
        suggested_object_id="hubb_ir1_ar_escritorio",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.options == {}
    by_title = {sub.title: sub for sub in entry.subentries.values()}
    assert set(by_title) == {"TV Quarto", "Ar Escritorio", "Bancada"}
    assert by_title["TV Quarto"].data["channel"] == 3
    assert by_title["Ar Escritorio"].subentry_type == "climate"
    assert by_title["Ar Escritorio"].data["vendor"] == "LG2"
    assert by_title["Bancada"].data["channel"] == 1

    tv = by_title["TV Quarto"]
    button = entity_registry.async_get("button.hubb_ir1_tv_quarto_power")
    assert button.unique_id == f"{tv.unique_id}_power"
    assert button.config_subentry_id == tv.subentry_id
    assert hass.states.get("button.hubb_ir1_tv_quarto_power") is not None

    device = device_registry.async_get(button.device_id)
    assert device.name == "TV Quarto"
    assert device_registry.async_get(device.via_device_id).name == "Hubb IR1"

    ac = by_title["Ar Escritorio"]
    climate = entity_registry.async_get("climate.hubb_ir1_ar_escritorio")
    assert climate.unique_id == f"{ac.unique_id}_climate"
    assert hass.states.get("climate.hubb_ir1_ar_escritorio") is not None

    coordinator = entry.runtime_data
    assert coordinator.get_code(tv.unique_id, "power") == NEC_POWER
    assert coordinator.get_code(by_title["Bancada"].unique_id, "teste1") == NEC_POWER


async def test_removing_an_appliance_drops_its_codes(
    hass: HomeAssistant, mqtt_mock, hass_storage
) -> None:
    """Codes nobody can reach any more are not kept."""
    entry = board_entry(
        subentries_data=(
            {
                "data": {"channel": 1},
                "subentry_type": "appliance",
                "title": "TV Quarto",
                "unique_id": "tvkey",
            },
        )
    )
    entry.add_to_hass(hass)
    hass_storage[f"tasmota_ir_{entry.entry_id}_codes"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"tasmota_ir_{entry.entry_id}_codes",
        "data": {"tvkey": {"power": NEC_POWER}},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("button.tv_quarto_power") is not None

    (subentry,) = entry.subentries.values()
    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.codes == {}
    assert hass.states.get("button.tv_quarto_power") is None
