from __future__ import annotations
import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er

from .services import register_services
from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_USER,
    CONF_PASSWORD,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_NODE,
    CONF_PLATFORM_TYPE,
    CONF_VERIFY_SSL,
)

from .api import ProxmoxClient
from .coordinator import create_proxmox_coordinator

_LOGGER = logging.getLogger(__name__)

ENTRY_VERSION = 2

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]


async def async_migrate_entry(hass, config_entry):
    """Migrate Proxmox entry to prefixed unique_id format."""

    if config_entry.version >= ENTRY_VERSION:
        return True

    _LOGGER.info(
        "Migrating Proxmox entry %s from version %s to %s",
        config_entry.entry_id,
        config_entry.version,
        ENTRY_VERSION,
    )

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)

    server_id = (config_entry.data.get("server_id") or "default").lower()
    server_type = (config_entry.data.get("server_type") or "").lower()

    _LOGGER.debug("Migration server_type raw value: %s", server_type)

    if server_type == "pbs":
        prefix = "pbs"
    elif server_type == "pve":
        prefix = "pve"
    else:
        if any("datastore" in (e.unique_id or "") for e in entries):
            prefix = "pbs"
            _LOGGER.info("Legacy entry detected as PBS")
        else:
            prefix = "pve"
            _LOGGER.info("Legacy entry detected as PVE")

    for entity in entries:
        old_unique_id = entity.unique_id

        if not old_unique_id:
            continue

        # Skip if already migrated
        if old_unique_id.startswith(f"{prefix}_{server_id}_"):
            continue

        new_unique_id = f"{prefix}_{server_id}_{old_unique_id}".lower()

        ent_reg.async_update_entity(
            entity.entity_id,
            new_unique_id=new_unique_id,
        )

        _LOGGER.debug(
            "Updated unique_id: %s -> %s",
            old_unique_id,
            new_unique_id,
        )

    hass.config_entries.async_update_entry(
        config_entry,
        version=ENTRY_VERSION,
    )

    _LOGGER.info("Migration completed for entry %s", config_entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:

    if entry.version < ENTRY_VERSION:
        migrated = await async_migrate_entry(hass, entry)
        if not migrated:
            return False

    data = entry.data

    client = ProxmoxClient(
        host=data[CONF_HOST],
        user=data[CONF_USER],
        password=data.get(CONF_PASSWORD),
        token_id=data.get(CONF_TOKEN_ID),
        token_secret=data.get(CONF_TOKEN_SECRET),
        server_type=data[CONF_PLATFORM_TYPE],
        verify_ssl=data.get(CONF_VERIFY_SSL, False),
    )

    coordinator = await create_proxmox_coordinator(hass, entry, client)

    try:
        async with asyncio.timeout(20):
            await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Unable to connect to Proxmox {data[CONF_HOST]}"
        ) from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "node": data[CONF_NODE],
        "server_type": client._server_type,
        "features": data.get("features", {}),
    }

    register_services(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
