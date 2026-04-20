from .base import ProxmoxBaseSensor
from ..const import DOMAIN


class ProxmoxHardwareSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, sensor_key, node):

        self._key = sensor_key.lower()

        self._is_chipset = "pch" in self._key

        # CPU grouping
        self._is_cpu = any(
            x in self._key for x in ["coretemp", "k10temp", "tctl", "tdie"]
        )

        if self._is_cpu:
            name = f"CPU Temperature ({node})"
            unique_id = f"proxmox_cpu_temp_{node}"
            unit = "°C"
            sensor_id = "cpu_temperature"
        else:
            name = f"{sensor_key} ({node})"
            clean_id = self._key.replace(" ", "_").replace("-", "_")
            unique_id = f"proxmox_hw_{node}_{clean_id}"
            unit = "°C"
            sensor_id = sensor_key

        super().__init__(coordinator, sensor_id, name, unit, unique_id, node)

        self._attr_device_class = "temperature"
        self._attr_state_class = "measurement"
        self._attr_icon = "mdi:thermometer-lines"

    # ================= MAIN VALUE ==================

    def _get_value(self):
        hw = self.coordinator.data.get("hardware", {})

        if self._is_cpu:
            # Prefer package / tctl / tdie
            for key, val in hw.items():
                kl = key.lower()
                if any(x in kl for x in ["package", "tctl", "tdie"]):
                    v = self._parse(val)
                    if v is not None:
                        return v

            # Fallback: average cores
            cores = []
            for key, val in hw.items():
                if "core" in key.lower():
                    v = self._parse(val)
                    if v is not None:
                        cores.append(v)

            if cores:
                return round(sum(cores) / len(cores), 1)

            return None

        # Direct lookup for non-cpu
        return self._parse(hw.get(self._key))

    # ================= ATTRIBUTES ==================

    @property
    def extra_state_attributes(self):
        hw = self.coordinator.data.get("hardware", {})

        attrs = {}

        # ---------------- CPU ----------------
        if self._is_cpu:
            cpu_critical = None
            package_temp = None

            for key, val in hw.items():
                kl = key.lower()

                # -------- Core temps --------
                if "core" in kl:
                    v = self._parse(val)
                    if v is not None:
                        attrs[kl.replace(" ", "_")] = v

                # -------- Package --------
                if any(x in kl for x in ["package", "tctl", "tdie"]):
                    v = self._parse(val)
                    if v is not None:
                        attrs["package"] = v
                        package_temp = v

                # -------- Critical temp --------
                if isinstance(val, dict):
                    for k, v in val.items():
                        try:
                            if "crit" in k.lower() and cpu_critical is None:
                                f = float(v)
                                if 1 < f < 145:
                                    cpu_critical = round(f, 1)
                        except (ValueError, TypeError):
                            continue

            # -------- Final attributes --------
            if cpu_critical is not None:
                attrs["cpu_critical_temp"] = cpu_critical

            # 🔥 Thermal margin (lo bueno)
            if cpu_critical is not None and package_temp is not None:
                attrs["thermal_margin"] = round(cpu_critical - package_temp, 1)

        # ---------------- CHIPSET ----------------
        elif self._is_chipset:
            acpi_values = []

            for key, val in hw.items():
                kl = key.lower()

                if "acpitz" in kl:
                    v = self._parse(val)
                    if v is not None:
                        acpi_values.append(v)

            if acpi_values:
                attrs["acpi_temp"] = round(sum(acpi_values) / len(acpi_values), 1)

        return attrs

    # ================= HELPERS ==================

    def _parse(self, val):
        try:
            # If dict (lm-sensors style)
            if isinstance(val, dict):
                for k, v in val.items():
                    if "input" in k.lower():
                        val = v
                        break

            f = float(val)
            if 1 < f < 145:
                return round(f, 1)
        except Exception:
            pass

        return None


class ProxmoxHardwareNVMeSensor(ProxmoxBaseSensor):
    def __init__(self, coordinator, device_prefix, node):
        self._device_prefix = device_prefix

        display_name = device_prefix.replace("nvme-pci-", "NVMe ").replace("_", " ")
        name = f"{display_name} ({node})"
        unique_id = f"proxmox_nvme_{device_prefix}_{node}"

        super().__init__(coordinator, "nvme_temperature", name, "°C", unique_id, node)

        self._attr_device_class = "temperature"
        self._attr_state_class = "measurement"
        self._attr_icon = "mdi:thermometer-lines"

    # ================= MAIN VALUE ==================

    def _get_value(self):
        hw = self.coordinator.data.get("hardware", {})

        # Priority: composite
        for key, val in hw.items():
            if key.startswith(self._device_prefix) and "composite" in key.lower():
                return self._extract_current(val)

        # Fallback
        for key, val in hw.items():
            if key.startswith(self._device_prefix):
                v = self._extract_current(val)
                if v is not None:
                    return v

        return None

    # ================= ATTRIBUTES ==================

    @property
    def extra_state_attributes(self):
        hw = self.coordinator.data.get("hardware", {})
        attrs = {}
        temps = []

        for key, val in hw.items():
            if not key.startswith(self._device_prefix):
                continue

            raw_name = key.replace(self._device_prefix, "").strip("_")
            kl = raw_name.lower()

            # -------- Naming --------

            if not raw_name or kl == "composite":
                display_name = "Composite Temp"

            elif "sensor" in kl or "temp" in kl:
                import re

                match = re.search(r"(\d+)", kl)

                if match:
                    num = int(match.group(1))
                    if num == 1:
                        display_name = "NAND Temp"
                    elif num == 2:
                        display_name = "Controller Temp"
                    else:
                        display_name = f"Sensor {num}"
                else:
                    display_name = raw_name.replace("_", " ").title()
            else:
                display_name = raw_name.replace("_", " ").title()

            # -------- Parse FULL data --------

            if isinstance(val, dict):
                parsed = {}

                for k, v in val.items():
                    try:
                        f = float(v)

                        kl = k.lower()

                        if "input" in kl:
                            parsed["current"] = round(f, 1)
                        elif "max" in kl or "high" in kl:
                            parsed["max"] = round(f, 1)
                        elif "crit" in kl:
                            parsed["critical"] = round(f, 1)
                        elif "min" in kl or "low" in kl:
                            parsed["min"] = round(f, 1)

                    except (ValueError, TypeError):
                        continue

                if parsed:
                    for sub_key, sub_val in parsed.items():
                        attrs[f"{display_name}_{sub_key}"] = sub_val

                    if "current" in parsed:
                        temps.append(parsed["current"])

            else:
                v = self._extract_current(val)
                if v is not None:
                    attrs[display_name] = v
                    temps.append(v)

        # -------- Max temp global --------

        if temps:
            attrs["max_temp"] = round(max(temps), 1)

        return attrs

    # ================= HELPERS ==================

    def _extract_current(self, val):
        try:
            if isinstance(val, dict):
                for k, v in val.items():
                    if "input" in k.lower():
                        val = v
                        break

            f = float(val)
            if 1 < f < 145:
                return round(f, 1)

        except (ValueError, TypeError):
            pass

        return None
