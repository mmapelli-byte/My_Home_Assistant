"""Node sensors for Proxmox (CPU, Memory, Tasks, and System)."""

from .base import ProxmoxBaseSensor
from ..const import DOMAIN

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity, SensorStateClass
import logging

_LOGGER = logging.getLogger(__name__)


class ProxmoxNodeSensor(ProxmoxBaseSensor):
    """General node sensors."""

    def __init__(self, coordinator, sensor_id, node):
        unit = None
        icon = "mdi:information-outline"
        state_class = None
        name = sensor_id.replace("_", " ").title()

        if sensor_id == "cpu":
            name = "CPU Usage"
            unit = "%"
            icon = "mdi:cpu-64-bit"
            state_class = "measurement"

        elif sensor_id == "wait":
            name = "CPU Wait"
            unit = "%"
            icon = "mdi:timer-sand"
            state_class = "measurement"

        elif sensor_id == "uptime":
            name = "Uptime"
            icon = "mdi:clock-outline"

        elif sensor_id == "kversion":
            name = "Kernel Version"
            icon = "mdi:linux"

        elif sensor_id == "pveversion":
            name = "PVE Version"
            icon = "mdi:numeric"

        elif sensor_id == "loadavg":
            name = "Load Average"
            icon = "mdi:chart-line"

        elif sensor_id == "network_rx":
            name = "Network RX"
            unit = "bytes"
            icon = "mdi:download-network"
            state_class = "measurement"

        elif sensor_id == "network_tx":
            name = "Network TX"
            unit = "bytes"
            icon = "mdi:upload-network"
            state_class = "measurement"

        name = f"{name} ({node})"

        unique_id = f"proxmox_node_{node}_{sensor_id}"
        super().__init__(coordinator, sensor_id, name, unit, unique_id, node)

        self._attr_icon = icon
        self._attr_state_class = state_class

    def _get_value(self):
        value = self.coordinator.data.get("node", {}).get(self._sensor_id)

        if self._sensor_id == "pveversion" and isinstance(value, str):
            parts = value.split("/")
            if len(parts) >= 2:
                return parts[1]

        if self._sensor_id in ["cpu", "wait"] and isinstance(value, (int, float)):
            return round(value * 100, 2)

        if self._sensor_id == "uptime" and isinstance(value, (int, float)):
            days = int(value // 86400)
            hours = int((value % 86400) // 3600)
            minutes = int((value % 3600) // 60)
            return f"{days}d {hours}h {minutes}m"

        if isinstance(value, dict):
            return (
                value.get("release") or value.get("version", "").split("\n")[0] or None
            )

        if isinstance(value, str):
            return value.split("\n")[0]

        return value

    @property
    def extra_state_attributes(self):
        # Apply only to CPU sensor
        if self._sensor_id != "cpu":
            return {}

        node_data = self.coordinator.data.get("node", {})

        cpu = node_data.get("cpu")
        cpuinfo = node_data.get("cpuinfo", {})
        cores = cpuinfo.get("cores")

        attrs = {}

        if cores:
            attrs["cpu_cores"] = cores

            if cpu is not None:
                try:
                    attrs["cpu_average_per_core"] = round((cpu * 100) / cores, 2)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        return attrs


class ProxmoxClusterTasksSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        uid = f"proxmox_{node}_cluster_tasks"
        super().__init__(coordinator, "last_task", "Last Task", None, uid, node)

    def _get_value(self):
        task = self.coordinator.data.get("node", {}).get("last_task")
        if not task:
            return "No Tasks"
        return f"{task.get('type', 'unknown')}: {task.get('status', 'unknown')}"

    @property
    def extra_state_attributes(self):
        task = self.coordinator.data.get("node", {}).get("last_task", {})
        tasks_list = self.coordinator.data.get("tasks", [])

        errors = [
            f"{t.get('type')}: {t.get('status')}"
            for t in tasks_list
            if t.get("status") and "OK" not in t.get("status")
        ]

        return {
            "user": task.get("user"),
            "status_raw": task.get("status"),
            "recent_errors": errors[:5] if errors else 0,
        }


class ProxmoxCPUInfoSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        super().__init__(
            coordinator, "cpuinfo", "CPU Info", None, f"p_node_cpu_{node}", node
        )
        self._attr_icon = "mdi:cpu-64-bit"

    def _get_value(self):
        info = self.coordinator.data.get("node", {}).get("cpuinfo", {})
        return info.get("model") or f"{info.get('cores', '?')} cores"


class ProxmoxKSMSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        super().__init__(
            coordinator, "ksm", "KSM Shared", "GB", f"p_node_ksm_{node}", node
        )
        self._attr_icon = "mdi:memory-arrow-down"

    def _get_value(self):
        val = self.coordinator.data.get("node", {}).get("ksm", {}).get("shared", 0)
        return round(val / (1024**3), 2)


class ProxmoxMemorySensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        super().__init__(
            coordinator, "memory", "Memory Usage", "%", f"p_node_mem_{node}", node
        )
        self._attr_icon = "mdi:memory"

    def _get_value(self):
        data = self.coordinator.data.get("node", {}).get("memory", {})
        used = data.get("used", 0)
        total = data.get("total", 1)
        return round((used / total) * 100, 2)


class ProxmoxSwapSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        super().__init__(
            coordinator, "swap", "Swap Usage", "%", f"p_node_swap_{node}", node
        )
        self._attr_icon = "mdi:swap-horizontal"

    def _get_value(self):
        data = self.coordinator.data.get("node", {}).get("swap", {})
        total = data.get("total", 0)
        if total == 0:
            return 0
        return round((data.get("used", 0) / total) * 100, 2)


class ProxmoxRootFSSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, node):
        super().__init__(
            coordinator,
            "rootfs",
            "Root FS Usage",
            "%",
            f"p_node_rootfs_{node}",
            node,
        )
        self._attr_icon = "mdi:folder"

    def _get_value(self):
        data = self.coordinator.data.get("node", {}).get("rootfs", {})
        total = data.get("total", 1)
        return round((data.get("used", 0) / total) * 100, 2)


class ProxmoxNodeUpdatesSensor(ProxmoxBaseSensor):
    """Sensor for node updates."""

    def __init__(self, coordinator, node):
        super().__init__(
            coordinator,
            "node_updates",
            "Node Updates",
            None,
            f"p_node_updates_{node}",
            node,
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _get_value(self):
        data = self.coordinator.data.get("node_updates", {})

        if data.get("error"):
            return None

        return data.get("count", 0)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data.get("node_updates", {})

        if data.get("error"):
            return {
                "error": True,
                "message": "Failed to fetch updates",
            }

        packages = data.get("packages", [])

        return {
            "available": data.get("available", False),
            "count": data.get("count", 0),
            "packages": [
                f"{p.get('Package')} ({p.get('OldVersion')} → {p.get('Version')})"
                for p in packages
                if isinstance(p, dict) and p.get("Package")
            ],
        }

    @property
    def icon(self):
        data = self.coordinator.data.get("node_updates", {})

        if data.get("error"):
            return "mdi:alert-circle"

        if data.get("count", 0) > 0:
            return "mdi:package-up"

        return "mdi:package-check"


class ProxmoxNodesSensor(CoordinatorEntity, SensorEntity):
    """Sensor that shows configured node and its statistics."""

    def __init__(self, coordinator, entry_id, node):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._node = node
        self._attr_name = f"Proxmox Node: {node}"
        self._attr_unique_id = f"{entry_id}_node_info"
        self._attr_icon = "mdi:server"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"proxmox_node_{self._node}")},
            "manufacturer": "Proxmox",
            "model": "Proxmox Node",
            "name": f"1. Node: {self._node}",
        }

    @property
    def native_value(self):
        data = self.coordinator.data

        node_status = data.get("node_status_map", {}).get(self._node, "unknown")

        if node_status != "online":
            return "offline"

        node_data = data.get("node", {})

        cpu = node_data.get("cpu", 0)
        memory = node_data.get("memory", {})
        wait = node_data.get("wait", 0)
        load = node_data.get("loadavg", [])
        cores = node_data.get("cpuinfo", {}).get("cores", 1)

        cpu_p = cpu * 100 if isinstance(cpu, (int, float)) else 0
        ram_p = (
            (memory.get("used", 0) / memory.get("total", 1)) * 100
            if memory.get("total")
            else 0
        )
        io = wait * 100 if isinstance(wait, (int, float)) else 0

        try:
            load1 = float(load[0]) if len(load) > 0 else 0
        except (ValueError, TypeError):
            load1 = 0

        load_ratio = load1 / cores if cores else 0

        score = cpu_p * 0.4 + ram_p * 0.3 + (load_ratio * 100) * 0.2 + io * 0.1

        if score < 20:
            return "Excellent"
        elif score < 40:
            return "Good"
        elif score < 60:
            return "Moderate"
        elif score < 80:
            return "High"
        else:
            return "Critical"

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        node_data = data.get("node", {})

        vm_count = 0
        ct_count = 0

        if "vms" in data:
            for vm_id, vm_info in data["vms"].items():
                if isinstance(vm_info, dict) and vm_info.get("node") == self._node:
                    vm_count += 1

        if "cts" in data:
            for ct_id, ct_info in data["cts"].items():
                if isinstance(ct_info, dict) and ct_info.get("node") == self._node:
                    ct_count += 1

        storage_count = 0
        storage_details = []

        if "storage" in data:
            for storage_name, storage_info in data["storage"].items():
                if not isinstance(storage_info, dict):
                    continue

                total_bytes = storage_info.get("total", 0) or 0
                used_bytes = storage_info.get("used", 0) or 0

                if total_bytes == 0 and used_bytes == 0:
                    continue

                free_bytes = max(total_bytes - used_bytes, 0)

                total_gb = round(total_bytes / (1024**3), 2)
                used_gb = round(used_bytes / (1024**3), 2)
                free_gb = round(free_bytes / (1024**3), 2)

                percentage = (
                    round(min((used_bytes / total_bytes) * 100, 100), 1)
                    if total_bytes > 0
                    else 0
                )

                storage_details.append(
                    {
                        "name": storage_name,
                        "type": storage_info.get("type", "unknown"),
                        "total_gb": total_gb,
                        "used_gb": used_gb,
                        "free_gb": free_gb,
                        "percentage": percentage,
                    }
                )

            storage_count = len(storage_details)

        node_status = data.get("node_status_map", {}).get(self._node, "unknown")
        cpu_usage = node_data.get("cpu", 0)
        if isinstance(cpu_usage, (int, float)):
            cpu_usage = round(cpu_usage * 100, 2)

        memory_data = node_data.get("memory", {})
        memory_used = memory_data.get("used", 0)
        memory_total = memory_data.get("total", 1)
        memory_percentage = (
            round((memory_used / memory_total) * 100, 2) if memory_total > 0 else 0
        )

        active_tasks = 0
        if "tasks" in data:
            for task in data["tasks"]:
                if isinstance(task, dict) and task.get("node") == self._node:
                    if task.get("status") not in ["OK", "stopped"]:
                        active_tasks += 1

        # Calculate CPU per core
        cpu_per_core = None
        if cpu_usage and node_data.get("cpuinfo", {}).get("cores"):
            cores = node_data.get("cpuinfo", {}).get("cores")
            cpu_per_core = round(cpu_usage / cores, 2)

        return {
            "node_name": self._node,
            "status": node_status,
            "cpu_average_per_core": cpu_per_core,
            "memory_usage_percent": memory_percentage,
            "vm_count": vm_count,
            "ct_count": ct_count,
            "storage_count": storage_count,
            "active_tasks": active_tasks,
            "storage_details": storage_details,
            "last_update": data.get("last_update", "unknown"),
            "pve_version": node_data.get("pveversion", "unknown"),
            "kernel_version": node_data.get("kversion", "unknown"),
            "uptime_seconds": node_data.get("uptime", 0),
        }


class ProxmoxStoragesSensor(CoordinatorEntity, SensorEntity):
    """Sensor listing all available storages in configured node."""

    def __init__(self, coordinator, entry_id, node):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._node = node
        self._attr_name = f"Proxmox Storages ({node})"
        self._attr_unique_id = f"{entry_id}_storages_{node}"
        self._attr_icon = "mdi:database"

    def _get_storage_data(self):
        """Get storage data from coordinator, checking multiple possible structures."""
        data = self.coordinator.data

        if "storages_by_node" in data:
            node_storages = data["storages_by_node"].get(self._node, {})
            if node_storages:
                return node_storages

        if "storage" in data and data["storage"]:
            return data["storage"]

        if "all_storages" in data and self._node in data["all_storages"]:
            if "storage" in data:
                return data["storage"]

        return {}

    def _format_size(self, bytes_size):
        if bytes_size == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(bytes_size)

        while size >= 1024 and i < len(size_names) - 1:
            size /= 1024
            i += 1

        if i >= 3:
            return f"{size:.2f} {size_names[i]}"
        elif i >= 1:
            return f"{size:.1f} {size_names[i]}"
        else:
            return f"{size:.0f} {size_names[i]}"

    def _bytes_to_gb(self, bytes_size):
        if not bytes_size:
            return 0
        return round(bytes_size / (1024**3), 2)

    @property
    def native_value(self):
        storage_data = self._get_storage_data()
        return len(storage_data)

    @property
    def extra_state_attributes(self):
        storage_data = self._get_storage_data()

        if not storage_data:
            return {
                "node": self._node,
                "storages": [],
                "count": 0,
                "message": "No storage data available",
            }

        storages_list = []
        total_capacity_bytes = 0
        total_used_bytes = 0
        type_accumulators = {}

        for storage_name, storage_info in storage_data.items():
            if isinstance(storage_info, dict):
                total_bytes = storage_info.get("total", 0) or 0
                used_bytes = storage_info.get("used", 0) or 0
                avail_bytes = storage_info.get("avail", 0) or 0

                if avail_bytes == 0 and total_bytes > 0:
                    avail_bytes = max(total_bytes - used_bytes, 0)

                percentage = (
                    round((used_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0
                )
                storage_type = storage_info.get("type", "unknown")

                if storage_type not in type_accumulators:
                    type_accumulators[storage_type] = {"count": 0, "total_bytes": 0}
                type_accumulators[storage_type]["count"] += 1
                type_accumulators[storage_type]["total_bytes"] += total_bytes

                total_gb = self._bytes_to_gb(total_bytes)
                used_gb = self._bytes_to_gb(used_bytes)
                free_gb = self._bytes_to_gb(avail_bytes)

                storages_list.append(
                    {
                        "name": storage_name,
                        "type": storage_type,
                        "path": storage_info.get("path", ""),
                        "content": storage_info.get("content", ""),
                        "total": self._format_size(total_bytes),
                        "used": self._format_size(used_bytes),
                        "free": self._format_size(avail_bytes),
                        "total_gb": total_gb,
                        "used_gb": used_gb,
                        "free_gb": free_gb,
                        "percentage": percentage,
                        "active": storage_info.get("active", 1) == 1,
                        "enabled": storage_info.get("enabled", 1) == 1,
                    }
                )

                total_capacity_bytes += total_bytes
                total_used_bytes += used_bytes

        total_free_bytes = max(total_capacity_bytes - total_used_bytes, 0)
        total_capacity_gb = self._bytes_to_gb(total_capacity_bytes)
        total_used_gb = self._bytes_to_gb(total_used_bytes)
        total_free_gb = self._bytes_to_gb(total_free_bytes)

        total_percentage = (
            round((total_used_bytes / total_capacity_bytes * 100), 1)
            if total_capacity_bytes > 0
            else 0
        )

        by_type = {}
        for storage_type, accumulator in type_accumulators.items():
            total_bytes_for_type = accumulator["total_bytes"]
            by_type[storage_type] = {
                "count": accumulator["count"],
                "total_capacity": self._format_size(total_bytes_for_type),
                "total_capacity_gb": self._bytes_to_gb(total_bytes_for_type),
            }

        return {
            "node": self._node,
            "storages": [s["name"] for s in storages_list],
            "count": len(storages_list),
            "storage_details": storages_list,
            "total_capacity": self._format_size(total_capacity_bytes),
            "total_used": self._format_size(total_used_bytes),
            "total_free": self._format_size(total_free_bytes),
            "total_capacity_gb": total_capacity_gb,
            "total_used_gb": total_used_gb,
            "total_free_gb": total_free_gb,
            "total_percentage": total_percentage,
            "by_type": by_type,
            "last_update": self.coordinator.data.get("last_update", "unknown"),
            "summary": f"{len(storages_list)} storages, {self._format_size(total_capacity_bytes)} total, {total_percentage}% used",
        }

    @property
    def device_info(self):
        node_id = self._node.lower()
        display_node = self._node.capitalize()

        return {
            "identifiers": {(DOMAIN, f"proxmox_node_{node_id}")},
            "name": f"1. Node: {display_node}",
            "manufacturer": "Proxmox",
            "model": "Proxmox Node",
        }


class ProxmoxNodeIOWaitSensor(ProxmoxBaseSensor):
    """Sensor for node IO wait (disk pressure)."""

    def __init__(self, coordinator, node):
        super().__init__(
            coordinator,
            "wait",
            "IO Wait",
            "%",
            f"p_node_iowait_{node}",
            node,
        )
        self._attr_icon = "mdi:harddisk"
        self._attr_state_class = "measurement"

    def _get_value(self):
        value = self.coordinator.data.get("node", {}).get("wait", 0)

        if isinstance(value, (int, float)):
            return round(value * 100, 2)

        return 0

    @property
    def extra_state_attributes(self):
        value = self.coordinator.data.get("node", {}).get("wait", 0)

        percent = round(value * 100, 2) if isinstance(value, (int, float)) else 0

        if percent < 2:
            level = "Low"
        elif percent < 5:
            level = "Moderate"
        elif percent < 10:
            level = "High"
        else:
            level = "Critical"

        return {
            "raw": value,
            "level": level,
        }


class ProxmoxNodeLoadAverageSensor(ProxmoxBaseSensor):
    """Sensor for node load average (1 min)."""

    def __init__(self, coordinator, node):
        super().__init__(
            coordinator,
            "loadavg_1m",
            "Load Average (1m)",
            None,
            f"p_node_load1_{node}",
            node,
        )
        self._attr_icon = "mdi:chart-line"

    def _get_value(self):
        load = self.coordinator.data.get("node", {}).get("loadavg", [])

        if isinstance(load, list) and len(load) >= 1:
            try:
                return round(float(load[0]), 2)
            except (ValueError, TypeError):
                return None

        return None

    @property
    def extra_state_attributes(self):
        node_data = self.coordinator.data.get("node", {})
        load = node_data.get("loadavg", [])
        cpuinfo = node_data.get("cpuinfo", {})

        cores = cpuinfo.get("cores")

        load1 = float(load[0]) if len(load) > 0 else 0
        load5 = float(load[1]) if len(load) > 1 else 0
        load15 = float(load[2]) if len(load) > 2 else 0

        status = "OK"
        if cores:
            if load1 > cores:
                status = "Overloaded"
            elif load1 > cores * 0.7:
                status = "High"

        return {
            "load_1m": load1,
            "load_5m": load5,
            "load_15m": load15,
            "cores": cores,
            "status": status,
        }


class ProxmoxNodeScoreSensor(ProxmoxBaseSensor):
    """Overall node performance score (lower is better)."""

    def __init__(self, coordinator, node):
        super().__init__(
            coordinator,
            "node_score",
            "Node Score",
            None,
            f"p_node_score_{node}",
            node,
        )
        self._attr_icon = "mdi:speedometer"

    def _get_value(self):
        data = self.coordinator.data.get("node", {})

        cpu = data.get("cpu", 0)
        memory = data.get("memory", {})
        wait = data.get("wait", 0)
        load = data.get("loadavg", [])
        cores = data.get("cpuinfo", {}).get("cores", 1)

        cpu_p = cpu * 100 if isinstance(cpu, (int, float)) else 0
        ram_p = (
            (memory.get("used", 0) / memory.get("total", 1)) * 100
            if memory.get("total")
            else 0
        )
        io = wait * 100 if isinstance(wait, (int, float)) else 0

        try:
            load1 = float(load[0]) if len(load) > 0 else 0
        except (ValueError, TypeError):
            load1 = 0

        load_ratio = load1 / cores if cores else 0

        score = cpu_p * 0.4 + ram_p * 0.3 + (load_ratio * 100) * 0.2 + io * 0.1

        return round(score, 2)

    @property
    def extra_state_attributes(self):
        score = self.native_value or 0

        if score < 20:
            state = "Excellent"
        elif score < 40:
            state = "Good"
        elif score < 60:
            state = "Moderate"
        elif score < 80:
            state = "High"
        else:
            state = "Critical"

        return {
            "interpretation": "Lower is better",
            "state": state,
        }


class PVEBackupProgressSensor(ProxmoxBaseSensor):
    """Sensor for backup progress in PVE using available tasks data."""

    def __init__(self, coordinator, node, entry_id):
        name = "Backup Progress"
        uid = f"proxmox_backup_progress_{node}"

        super().__init__(
            coordinator,
            node,
            name,
            None,
            uid,
            node,
        )

        self._attr_icon = "mdi:backup-restore"

    def _get_backup_tasks(self):
        data = self.coordinator.data
        backup_tasks = []

        if "tasks" in data:
            for task in data["tasks"]:
                if (
                    "vzdump" in str(task.get("type", "")).lower()
                    or "backup" in str(task.get("id", "")).lower()
                    or "vzdump" in str(task.get("upid", "")).lower()
                ) and task.get("node") == self._node:
                    backup_tasks.append(
                        {
                            "id": task.get("id", task.get("upid", "unknown")),
                            "vmid": self._extract_vmid(task),
                            "type": task.get("type", "unknown"),
                            "status": task.get("status", "unknown"),
                            "upid": task.get("upid", ""),
                            "starttime": task.get("starttime", 0),
                            "endtime": task.get("endtime", 0),
                            "user": task.get("user", "unknown"),
                            "storage": "unknown",
                            "node": task.get("node", "unknown"),
                        }
                    )
        return backup_tasks

    def _extract_vmid(self, task):
        upid = str(task.get("upid", ""))

        try:
            if "vm/" in upid:
                return upid.split("vm/")[1].split(":")[0]
            if "ct/" in upid:
                return upid.split("ct/")[1].split(":")[0]
        except Exception:
            pass

        return "unknown"

    @property
    def native_value(self):
        backup_tasks = self._get_backup_tasks()

        if not backup_tasks:
            return "idle"

        from time import time

        current_time = time()
        recent_tasks = [
            t for t in backup_tasks if t.get("starttime", 0) > (current_time - 86400)
        ]

        if not recent_tasks:
            return "idle"

        running = [t for t in recent_tasks if t.get("status") == "running"]
        failed = [t for t in recent_tasks if t.get("status") in ["error", "failed"]]
        completed = [t for t in recent_tasks if t.get("status") == "OK"]

        if running:
            return "running"
        elif failed:
            return "error"
        elif completed:
            return "ok"
        else:
            return "idle"

    @property
    def extra_state_attributes(self):
        backup_tasks = self._get_backup_tasks()

        if not backup_tasks:
            return {
                "status": "no_backups",
                "node": self._node,
                "message": "No backup tasks found in last 24 hours",
            }

        from time import time

        current_time = time()
        recent_tasks = [
            t for t in backup_tasks if t.get("starttime", 0) > (current_time - 86400)
        ]

        if not recent_tasks:
            return {
                "status": "no_recent_backups",
                "node": self._node,
                "message": "No backup tasks in last 24 hours",
            }

        running_tasks = [t for t in recent_tasks if t.get("status") == "running"]
        completed_tasks = [t for t in recent_tasks if t.get("status") == "OK"]
        failed_tasks = [
            t for t in recent_tasks if t.get("status") in ["error", "failed"]
        ]
        other_tasks = [
            t
            for t in recent_tasks
            if t.get("status") not in ["running", "OK", "error", "failed"]
        ]

        recent_backups_list = []
        for task in sorted(
            recent_tasks, key=lambda x: x.get("starttime", 0), reverse=True
        )[:10]:
            duration = None
            if task.get("starttime") and task.get("endtime"):
                duration = task.get("endtime") - task.get("starttime")

            recent_backups_list.append(
                {
                    "vmid": task.get("vmid"),
                    "status": task.get("status"),
                    "user": task.get("user"),
                    "starttime": task.get("starttime"),
                    "endtime": task.get("endtime"),
                    "duration": duration,
                }
            )

        current_task = running_tasks[0] if running_tasks else None

        total = len(recent_tasks)
        completed = len([t for t in recent_tasks if t.get("status") == "OK"])

        percentage = round((completed / total) * 100, 1) if total > 0 else 0

        return {
            "node": self._node,
            "total_backups_last_24h": len(recent_tasks),
            "running": len(running_tasks),
            "completed": len(completed_tasks),
            "percentage": percentage,
            "failed": len(failed_tasks),
            "other": len(other_tasks),
            "last_update": self.coordinator.data.get("last_update", "unknown"),
            "current_task": (
                {
                    "vmid": self._extract_vmid(current_task),
                    "user": current_task.get("user"),
                    "starttime": current_task.get("starttime"),
                    "upid": current_task.get("upid"),
                }
                if current_task
                else "idle"
            ),
            "recent_backups": recent_backups_list,
            "all_backups_count": len(backup_tasks),
        }

    @property
    def icon(self):
        state = self.native_value

        if state == "running":
            return "mdi:backup-restore"
        elif state == "error":
            return "mdi:alert"
        elif state == "ok":
            return "mdi:check-circle"
        else:
            return "mdi:sleep"
