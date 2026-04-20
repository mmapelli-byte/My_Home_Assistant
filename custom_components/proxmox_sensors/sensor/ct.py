"""Container (LXC) sensors for Proxmox."""

from .base import ProxmoxBaseSensor
from ..const import DOMAIN


class ProxmoxContainerSensor(ProxmoxBaseSensor):
    """Main CT status sensor."""

    def __init__(self, coordinator, ct_id, node, label):
        self._label = label
        uid = f"proxmox_ct_{node}_{ct_id}_status_v1"

        super().__init__(
            coordinator,
            ct_id,
            None,
            None,
            uid,
            node,
        )

        self._attr_translation_key = "ct_status"
        self._attr_icon = "mdi:label-outline"

    @property
    def device_info(self):
        node_id = self._node.lower()

        return {
            "identifiers": {(DOMAIN, f"proxmox_ct_{self._sensor_id}_v1")},
            "name": f"3. CT: {self._label}-({self._sensor_id})",
            "via_device": (DOMAIN, f"proxmox_node_{node_id}"),
            "manufacturer": "Proxmox",
            "model": "LXC Container",
        }

    def _get_value(self):
        ct_data = self.coordinator.data.get("cts", {}).get(self._sensor_id, {})
        return str(ct_data.get("status", "unknown")).capitalize()


class ProxmoxContainerAttributeSensor(ProxmoxBaseSensor):
    """Attribute sensors for CTs (CPU, memory, disk, network, uptime)."""

    def __init__(self, coordinator, ct_id, node, label, attr_name, unit, icon):
        self._label = label
        self._attr_key = attr_name

        uid = f"proxmox_ct_{node}_{ct_id}_{attr_name}_v1"

        names = {
            "cpu_usage": "CPU Usage",
            "memory_used": "RAM Used",
            "memory_total": "RAM Total",
            "disk_used": "Disk Used",
            "disk_total": "Disk Total",
            "network_rx": "Network RX",
            "network_tx": "Network TX",
            "uptime": "Uptime",
        }

        pretty = names.get(attr_name, attr_name.replace("_", " ").title())
        name = f"{ct_id} - {pretty}"

        super().__init__(
            coordinator,
            ct_id,
            name,
            unit,
            uid,
            node,
        )

        self._attr_translation_key = f"ct_{attr_name}"
        self._attr_icon = icon

    @property
    def device_info(self):
        node_id = self._node.lower()

        return {
            "identifiers": {(DOMAIN, f"proxmox_ct_{self._sensor_id}_v1")},
            "name": f"3. CT: {self._label}-({self._sensor_id})",
            "via_device": (DOMAIN, f"proxmox_node_{node_id}"),
            "manufacturer": "Proxmox",
            "model": "LXC Container",
        }

    def _get_value(self):
        ct_data = self.coordinator.data.get("cts", {}).get(self._sensor_id, {})
        if not ct_data:
            return None

        try:
            # CPU %
            if self._attr_key == "cpu_usage":
                cpu = ct_data.get("cpu")
                return round(float(cpu) * 100, 2) if cpu is not None else None

            # Network MB
            if self._attr_key == "network_rx":
                val = ct_data.get("netin")
                return round(float(val) / (1024**2), 2) if val is not None else None

            if self._attr_key == "network_tx":
                val = ct_data.get("netout")
                return round(float(val) / (1024**2), 2) if val is not None else None

            keys = {
                "memory_used": "mem",
                "memory_total": "maxmem",
                "disk_used": "disk",
                "disk_total": "maxdisk",
                "uptime": "uptime",
            }

            api_key = keys.get(self._attr_key)
            val = ct_data.get(api_key)

            if val is None:
                return None

            if self._attr_key == "uptime":
                return round(float(val) / 3600, 1)

            return round(float(val) / (1024**3), 2)

        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        """Extra attributes for additional CT info."""
        ct_data = self.coordinator.data.get("cts", {}).get(self._sensor_id, {})

        if not ct_data:
            return {}

        attrs = {}

        # CPU extra info
        if self._attr_key == "cpu_usage":
            cpu = ct_data.get("cpu")
            cores = ct_data.get("cpus")

            if cores:
                attrs["cores"] = cores

                if cpu is not None:
                    try:
                        attrs["cpu_per_core"] = round(float(cpu) * 100 / cores, 2)
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass

        return attrs
