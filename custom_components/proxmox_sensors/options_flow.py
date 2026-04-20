# =========OPTIONS FLOW — PROXMOX EXTENDED SENSORS===========

from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

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


class ProxmoxOptionsFlow(config_entries.OptionsFlow):

    async def async_step_init(self, user_input=None) -> FlowResult:

        conf = self.config_entry.data
        server_type = conf.get(CONF_PLATFORM_TYPE, "PVE")

        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
        cluster_nodes = coordinator.data.get("cluster_nodes", [conf.get(CONF_NODE)])

        options = self.config_entry.options or {}
        wol_mac_map = options.get("wol_macs", {})

        # ======== SAVE OPTIONS ====================

        if user_input is not None:

            new_data = dict(self.config_entry.data)
            new_data[CONF_VERIFY_SSL] = user_input.get(CONF_VERIFY_SSL, True)

            # Save WOL MACs
            wol_macs = {
                node: user_input.get(f"wol_mac_{node}")
                for node in cluster_nodes
                if user_input.get(f"wol_mac_{node}")
            }

            if server_type == "PVE":
                new_data.update(
                    {
                        "enable_lm_sensors": user_input.get("enable_lm_sensors", True),
                        "enable_physical_disks": user_input.get(
                            "enable_physical_disks", True
                        ),
                        "enable_smart_monitoring": user_input.get(
                            "enable_smart_monitoring", True
                        ),
                        "enable_node_controls": user_input.get(
                            "enable_node_controls", False
                        ),
                        "enable_backup_progress": user_input.get(
                            "enable_backup_progress", True
                        ),
                        "enable_storage_list": user_input.get(
                            "enable_storage_list", True
                        ),
                        "enable_nodes_list": user_input.get("enable_nodes_list", True),
                        "selected_vms": user_input.get("vms", []),
                        "selected_cts": user_input.get("cts", []),
                        "selected_storage": user_input.get("storage", []),
                    }
                )

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
                options={"wol_macs": wol_macs},
            )

            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        # ======= PBS — OPTIONS ====================

        if server_type == "PBS":
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            CONF_VERIFY_SSL,
                            default=conf.get(CONF_VERIFY_SSL, False),
                        ): bool,
                        vol.Optional(
                            "enable_pbs_node_controls",
                            default=conf.get("enable_pbs_node_controls", True),
                        ): bool,
                        # WOL MAC
                        vol.Optional(
                            "wol_mac",
                            default=conf.get("wol_mac", ""),
                        ): str,
                    }
                ),
            )

        # ====== PVE — LOAD RESOURCES ==============

        client = ProxmoxClient(
            host=conf[CONF_HOST],
            user=conf[CONF_USER],
            password=conf.get(CONF_PASSWORD),
            token_id=conf.get(CONF_TOKEN_ID),
            token_secret=conf.get(CONF_TOKEN_SECRET),
            server_type=conf[CONF_PLATFORM_TYPE],
            verify_ssl=conf.get(CONF_VERIFY_SSL, False),
        )

        try:

            vms_data = await client.get_vms(self.hass, conf[CONF_NODE]) or []
            cts_data = await client.get_containers(self.hass, conf[CONF_NODE]) or []
            storage_data = await client.get_storages(self.hass, conf[CONF_NODE]) or []

            # Auto MAC discovery
            detected_macs = {}

            for node in cluster_nodes:
                try:
                    net_data = await client.get_node_network(self.hass, node) or []
                    for iface in net_data:
                        if iface.get("active") and iface.get("mac-address"):
                            detected_macs[node] = iface.get("mac-address")
                            break
                except Exception:
                    continue

            vm_options = {
                str(v["vmid"]): f"{v['vmid']} ({v.get('name', 'VM')})" for v in vms_data
            }

            ct_options = {
                str(c["vmid"]): f"{c['vmid']} ({c.get('name', 'CT')})" for c in cts_data
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

                if is_shared:
                    st_options[st_name] = st_name
                    continue

                if storage_node and storage_node != conf[CONF_NODE]:
                    continue

                if storage_path.startswith("/mnt") or storage_path.startswith("/media"):
                    if total == 0 and used == 0:
                        continue

                st_options[st_name] = st_name

            # Clean old selections
            selected_vms = conf.get("selected_vms") or list(vm_options.keys())
            selected_vms = [v for v in selected_vms if v in vm_options]

            selected_cts = conf.get("selected_cts") or list(ct_options.keys())
            selected_cts = [c for c in selected_cts if c in ct_options]

            selected_storage = conf.get("selected_storage") or list(st_options.keys())
            selected_storage = [s for s in selected_storage if s in st_options]

            # Build WOL fields
            wol_fields = {
                vol.Optional(
                    f"wol_mac_{node}",
                    default=wol_mac_map.get(node) or detected_macs.get(node, ""),
                ): str
                for node in cluster_nodes
            }

            # Show form
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional("vms", default=selected_vms): cv.multi_select(
                            vm_options
                        ),
                        vol.Optional("cts", default=selected_cts): cv.multi_select(
                            ct_options
                        ),
                        vol.Optional(
                            "storage", default=selected_storage
                        ): cv.multi_select(st_options),
                        vol.Optional(
                            "enable_physical_disks",
                            default=conf.get("enable_physical_disks", True),
                        ): bool,
                        vol.Optional(
                            "enable_lm_sensors",
                            default=conf.get("enable_lm_sensors", True),
                        ): bool,
                        vol.Optional(
                            "enable_smart_monitoring",
                            default=conf.get("enable_smart_monitoring", True),
                        ): bool,
                        vol.Optional(
                            "enable_node_controls",
                            default=conf.get("enable_node_controls", False),
                        ): bool,
                        vol.Optional(
                            "enable_backup_progress",
                            default=conf.get("enable_backup_progress", True),
                        ): bool,
                        vol.Optional(
                            "enable_storage_list",
                            default=conf.get("enable_storage_list", True),
                        ): bool,
                        vol.Optional(
                            "enable_nodes_list",
                            default=conf.get("enable_nodes_list", True),
                        ): bool,
                        vol.Optional(
                            CONF_VERIFY_SSL,
                            default=conf.get(CONF_VERIFY_SSL, False),
                        ): bool,
                        **wol_fields,
                    }
                ),
            )

        except Exception:

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            "enable_physical_disks",
                            default=conf.get("enable_physical_disks", True),
                        ): bool,
                        vol.Optional(
                            "enable_lm_sensors",
                            default=conf.get("enable_lm_sensors", True),
                        ): bool,
                        vol.Optional(
                            "enable_smart_monitoring",
                            default=conf.get("enable_smart_monitoring", True),
                        ): bool,
                        vol.Optional(
                            "enable_node_controls",
                            default=conf.get("enable_node_controls", False),
                        ): bool,
                        vol.Optional(
                            "enable_backup_progress",
                            default=conf.get("enable_backup_progress", True),
                        ): bool,
                        vol.Optional(
                            "enable_storage_list",
                            default=conf.get("enable_storage_list", True),
                        ): bool,
                        vol.Optional(
                            "enable_nodes_list",
                            default=conf.get("enable_nodes_list", True),
                        ): bool,
                        vol.Optional(
                            CONF_VERIFY_SSL,
                            default=conf.get(CONF_VERIFY_SSL, False),
                        ): bool,
                    }
                ),
            )
