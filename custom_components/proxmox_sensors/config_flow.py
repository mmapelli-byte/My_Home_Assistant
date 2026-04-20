# ============================================================
#  CONFIG FLOW — PROXMOX SENSORS EXTENDED
# ============================================================

from __future__ import annotations
import logging
import asyncio
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .api import ProxmoxClient
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

_LOGGER = logging.getLogger(__name__)

SERVER_TYPES = {"PVE": "Proxmox VE", "PBS": "Proxmox Backup Server"}


class ProxmoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    def __init__(self):
        self._config = {}
        self._use_token = False

    # ===== STEP 1 — SERVER TYPE + HOST ======================

    async def async_step_user(self, user_input=None) -> FlowResult:

        if user_input is not None:
            self._config.update(user_input)
            return await self.async_step_auth_method()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PLATFORM_TYPE, default="PVE"): vol.In(
                        SERVER_TYPES
                    ),
                }
            ),
        )

    # ===== STEP 2 — AUTH METHOD ==============================

    async def async_step_auth_method(self, user_input=None) -> FlowResult:

        if user_input is not None:
            self._use_token = user_input.get("use_token", False)
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="auth_method",
            data_schema=vol.Schema({vol.Required("use_token", default=False): bool}),
        )

    # ===== STEP 3 — CREDENTIALS ==============================

    async def async_step_credentials(self, user_input=None) -> FlowResult:

        if user_input is not None:
            self._config.update(user_input)

            if self._config[CONF_PLATFORM_TYPE] == "PVE":
                return await self.async_step_select_node()

            return await self._finish()

        schema_dict = {vol.Required(CONF_USER): str}

        if self._use_token:
            schema_dict[vol.Required(CONF_TOKEN_ID)] = str
            schema_dict[vol.Required(CONF_TOKEN_SECRET)] = str
        else:
            schema_dict[vol.Required(CONF_PASSWORD)] = str

        schema_dict[vol.Optional("auto_detect_node", default=True)] = bool
        schema_dict[vol.Optional("enable_lm_sensors", default=True)] = bool
        schema_dict[vol.Optional(CONF_VERIFY_SSL, default=False)] = bool

        return self.async_show_form(
            step_id="credentials", data_schema=vol.Schema(schema_dict)
        )

    # ===== STEP 4 — SELECT NODE ==============================

    async def async_step_select_node(self, user_input=None) -> FlowResult:

        client = ProxmoxClient(
            host=self._config[CONF_HOST],
            user=self._config[CONF_USER],
            password=self._config.get(CONF_PASSWORD),
            token_id=self._config.get(CONF_TOKEN_ID),
            token_secret=self._config.get(CONF_TOKEN_SECRET),
            server_type=self._config[CONF_PLATFORM_TYPE],
            verify_ssl=self._config.get(CONF_VERIFY_SSL, True),
        )

        try:

            resources = await client.get_cluster_resources(self.hass)

            nodes = [
                r for r in resources if isinstance(r, dict) and r.get("type") == "node"
            ]

            auto = self._config.get("auto_detect_node", True)

            # Auto mode with IP matching
            if auto and nodes:

                host_ip = self._config.get(CONF_HOST)

                for n in nodes:
                    node_name = n.get("node")

                    try:
                        ip = await client.get_node_ip(self.hass, node_name)

                        if ip == host_ip:
                            self._config[CONF_NODE] = node_name
                            return await self.async_step_select_resources()

                    except Exception:
                        continue

                # Fallback if no IP match
                detected = nodes[0]["node"]
                self._config[CONF_NODE] = detected

                return await self.async_step_select_resources()

            # Manual mode
            node_options = {}

            for n in nodes:

                node_name = n.get("node")
                ip = None

                try:
                    async with asyncio.timeout(5):
                        net = await client.get_node_network(self.hass, node_name)

                    for iface in net or []:

                        if iface.get("type") != "bridge":
                            continue

                        addr = iface.get("address")

                        if addr and not addr.startswith("127.") and ":" not in addr:
                            ip = addr
                            break

                    if not ip:
                        for iface in net or []:

                            addr = iface.get("address")

                            if addr and not addr.startswith("127.") and ":" not in addr:
                                ip = addr
                                break

                except Exception:
                    pass

                if ip:
                    node_options[node_name] = f"{node_name} ({ip})"
                else:
                    node_options[node_name] = node_name

            # Auto-select if only one node
            if len(node_options) == 1:
                self._config[CONF_NODE] = list(node_options.keys())[0]
                return await self.async_step_select_resources()

            if user_input is not None:
                self._config[CONF_NODE] = user_input[CONF_NODE]
                return await self.async_step_select_resources()

            return self.async_show_form(
                step_id="select_node",
                data_schema=vol.Schema({vol.Required(CONF_NODE): vol.In(node_options)}),
            )

        except Exception as e:
            _LOGGER.error("Error fetching nodes: %s", e)
            return await self.async_step_select_resources()

    # ===== STEP 5 — SELECT RESOURCES =========================

    async def async_step_select_resources(self, user_input=None) -> FlowResult:

        if user_input is not None:
            self._config["selected_vms"] = user_input.get("vms", [])
            self._config["selected_cts"] = user_input.get("cts", [])
            self._config["selected_storage"] = user_input.get("storage", [])
            self._config["enable_physical_disks"] = user_input.get(
                "enable_physical_disks", True
            )
            self._config["enable_node_controls"] = user_input.get(
                "enable_node_controls", False
            )
            return await self._finish()

        client = ProxmoxClient(
            host=self._config[CONF_HOST],
            user=self._config[CONF_USER],
            password=self._config.get(CONF_PASSWORD),
            token_id=self._config.get(CONF_TOKEN_ID),
            token_secret=self._config.get(CONF_TOKEN_SECRET),
            server_type=self._config[CONF_PLATFORM_TYPE],
            verify_ssl=self._config.get(CONF_VERIFY_SSL, True),
        )

        node = self._config[CONF_NODE]

        try:

            vms_data = await client.get_vms(self.hass, node) or []
            cts_data = await client.get_containers(self.hass, node) or []
            storage_data = await client.get_storages(self.hass, node) or []

            vm_options = {
                str(v["vmid"]): f"{v['vmid']} ({v.get('name', 'VM')})"
                for v in vms_data
                if "vmid" in v
            }

            ct_options = {
                str(c["vmid"]): f"{c['vmid']} ({c.get('name', 'CT')})"
                for c in cts_data
                if "vmid" in c
            }

            st_options = {}

            for s in storage_data or []:

                st_name = s.get("storage")
                if not st_name:
                    continue

                is_shared = s.get("shared", 0) == 1
                storage_node = s.get("node")
                storage_path = s.get("path", "")
                total = s.get("total", 0) or 0
                used = s.get("used", 0) or 0

                # Shared storage (PBS, NFS, etc.)
                if is_shared:
                    st_options[st_name] = st_name
                    continue

                # Local storage
                # Respect node
                if storage_node and storage_node != self._config[CONF_NODE]:
                    continue

                # Mounted disks (USB)
                if storage_path.startswith("/mnt") or storage_path.startswith("/media"):
                    if total == 0 and used == 0:
                        continue

                st_options[st_name] = st_name

            return self.async_show_form(
                step_id="select_resources",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "vms",
                            default=list(vm_options.keys()),
                        ): cv.multi_select(vm_options),
                        vol.Optional(
                            "cts",
                            default=list(ct_options.keys()),
                        ): cv.multi_select(ct_options),
                        vol.Optional(
                            "storage",
                            default=list(st_options.keys()),
                        ): cv.multi_select(st_options),
                        vol.Optional("enable_physical_disks", default=True): bool,
                        vol.Optional("enable_node_controls", default=False): bool,
                    }
                ),
            )

        except Exception as e:
            _LOGGER.error("Error fetching resources: %s", e)
            return await self._finish()

    # ===== FINAL STEP =======================================

    async def _finish(self):

        if CONF_NODE not in self._config:
            self._config[CONF_NODE] = "Proxmox"

        if self._config.get(CONF_PLATFORM_TYPE) == "PBS":

            entries = self.hass.config_entries.async_entries(DOMAIN)
            pbs_entries = [
                e for e in entries if e.data.get(CONF_PLATFORM_TYPE) == "PBS"
            ]

            self._config["server_id"] = f"pbs_{len(pbs_entries) + 1}"

        else:
            self._config["server_id"] = self._config[CONF_NODE]

        title_name = self._config.get(CONF_NODE)
        server_type = self._config.get(CONF_PLATFORM_TYPE, "Server")

        return self.async_create_entry(
            title=f"{server_type}: {title_name}",
            data=self._config,
        )

    # ===== OPTIONS FLOW =====================================

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        from .options_flow import ProxmoxOptionsFlow

        return ProxmoxOptionsFlow()
