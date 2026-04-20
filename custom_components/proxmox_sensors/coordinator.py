# ====== COORDINATOR — PROXMOX EXTENDED SENSORS ======

import logging
import asyncio
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_NODE, CONF_PLATFORM_TYPE

_LOGGER = logging.getLogger(__name__)


async def create_proxmox_coordinator(hass, entry, client):

    data = entry.data
    node = data.get(CONF_NODE, "Proxmox")
    server_type = data.get(CONF_PLATFORM_TYPE, "PVE")

    selected_vms = data.get("selected_vms", [])
    selected_cts = data.get("selected_cts", [])
    selected_storage = data.get("selected_storage", [])

    enable_physical_disks = data.get("enable_physical_disks", True)
    enable_lm_sensors = data.get("enable_lm_sensors", True)
    enable_pbs_tasks = data.get("enable_pbs_tasks", True)
    enable_smart_monitoring = data.get("enable_smart_monitoring", True)

    enable_memory_monitoring = entry.options.get(
        "enable_memory_monitoring",
        entry.data.get("enable_memory_monitoring", True),
    )

    async def async_update_data():

        result = {"server_type": server_type}

        try:

            async with asyncio.timeout(30):

                # ========PBS==========

                if server_type == "PBS":

                    result["pbs_datastores"] = {}
                    result["pbs_snapshots"] = {}
                    result["pbs_gc"] = {}

                    selected = data.get("selected_storage")

                    if not selected:
                        actual_stores = await client.get_pbs_datastores(hass)
                    else:
                        actual_stores = selected

                    for store in actual_stores or []:

                        status = (
                            await client.get_pbs_datastore_status(hass, store) or {}
                        )
                        usage = await client.get_pbs_datastore_usage(hass, store) or {}
                        backups = await client.get_pbs_backup_list(hass, store) or []

                        backups_sorted = sorted(
                            backups, key=lambda x: x.get("backup-time", 0), reverse=True
                        )

                        last_backup = backups_sorted[0] if backups_sorted else None

                        backup_errors = [
                            b
                            for b in backups_sorted
                            if b.get("verification", {}).get("state") == "failed"
                        ]

                        try:
                            result["pbs_gc"][store] = (
                                await client.get_pbs_gc(hass, store) or {}
                            )
                        except Exception:
                            result["pbs_gc"][store] = {}

                        try:
                            result["pbs_snapshots"][store] = (
                                await client.get_pbs_snapshots(hass, store) or []
                            )
                        except Exception:
                            result["pbs_snapshots"][store] = []

                        result["pbs_datastores"][store] = {
                            **status,
                            **usage,
                            "backup_count": len(backups_sorted),
                            "backups": backups_sorted,
                            "last_backup": last_backup,
                            "backup_errors": backup_errors,
                        }

                    node_status = await client.get_pbs_node_status(hass)
                    result["pbs_node_status"] = (
                        node_status if isinstance(node_status, dict) else {}
                    )

                    version_info = await client.get_pbs_version(hass) or {}
                    result["pbs_version"] = version_info.get("version")
                    result["pbs_release"] = version_info.get("release")
                    result["pbs_auth_status"] = "OK" if version_info else "ERROR"

                    if enable_pbs_tasks:
                        tasks = await client.get_pbs_tasks(hass) or []
                        result["pbs_tasks"] = tasks if isinstance(tasks, list) else []
                    else:
                        result["pbs_tasks"] = []

                    from datetime import datetime

                    result["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    return result

                # ==========PVE================

                if server_type == "PVE":

                    # -------- Cluster nodes --------
                    try:
                        cluster_resources = await client.get_cluster_resources(hass)

                        nodes = set()
                        node_status_map = {}

                        for r in cluster_resources or []:
                            if not isinstance(r, dict):
                                continue

                            if r.get("type") == "node":
                                node_name = r.get("node")
                                status = r.get("status", "unknown")

                                if node_name:
                                    nodes.add(node_name)
                                    node_status_map[node_name] = status

                        result["cluster_nodes"] = sorted(nodes) if nodes else [node]
                        result["node_status_map"] = node_status_map

                    except Exception:
                        result["cluster_nodes"] = [node]
                        result["node_status_map"] = {node: "unknown"}

                    # -------- Parallel node calls --------

                    tasks = [
                        client.get_node_status(hass, node),
                        client.get_node_updates(hass, node),
                        client.get_node_network(hass, node),
                        client.get_cluster_tasks(hass),
                        client.get_vms(hass, node),
                        client.get_containers(hass, node),
                        client.get_storages(hass, node),
                        client.get_zfs_pools(hass, node),
                    ]

                    if enable_physical_disks:
                        tasks.append(client.get_disks(hass, node))

                    if enable_lm_sensors:
                        tasks.append(client.get_lm_sensors_http(hass, node))

                    if enable_smart_monitoring:
                        tasks.append(client.get_smart_data_http(hass, node))

                    if enable_memory_monitoring:
                        tasks.append(client.get_memory_http(hass, node))

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    idx = 0

                    # -------- Node status --------

                    node_status = results[idx]
                    idx += 1

                    normalized = {}

                    if isinstance(node_status, dict):

                        if "data" in node_status:
                            normalized = node_status["data"]

                        else:
                            normalized = node_status

                    result["node"] = normalized or {"status": "unknown"}

                    # -------- Node updates --------

                    updates = results[idx]
                    idx += 1

                    if isinstance(updates, Exception):
                        result["node_updates"] = {
                            "available": False,
                            "count": 0,
                            "packages": [],
                            "error": True,
                        }

                    elif not isinstance(updates, list):
                        result["node_updates"] = {
                            "available": False,
                            "count": 0,
                            "packages": [],
                            "error": True,
                        }

                    else:
                        result["node_updates"] = {
                            "available": len(updates) > 0,
                            "count": len(updates),
                            "packages": updates,
                            "error": False,
                        }

                    # -------- Network --------

                    interfaces = results[idx]
                    idx += 1

                    if isinstance(interfaces, list):

                        rx = sum(i.get("rx_bytes", 0) for i in interfaces)
                        tx = sum(i.get("tx_bytes", 0) for i in interfaces)

                        result["node"]["network_rx"] = rx
                        result["node"]["network_tx"] = tx

                    # -------- Tasks --------

                    cluster_tasks = results[idx]
                    idx += 1

                    result["tasks"] = (
                        cluster_tasks if isinstance(cluster_tasks, list) else []
                    )

                    if result["tasks"]:
                        last = result["tasks"][0]
                        result["node"]["last_task"] = {
                            "status": last.get("status", "running"),
                            "type": last.get("type", "unknown"),
                            "user": last.get("user", "unknown"),
                            "id": last.get("id", "node"),
                            "endtime": last.get("endtime"),
                        }

                    # -------- VMS --------

                    vms = results[idx]
                    idx += 1

                    vms_dict = {}

                    for vm in vms or []:

                        vmid = vm.get("vmid")

                        if vmid is None:
                            continue

                        if selected_vms and str(vmid) not in selected_vms:
                            continue

                        base = dict(vm)
                        base["node"] = node

                        for field in [
                            "cpu",
                            "mem",
                            "maxmem",
                            "disk",
                            "maxdisk",
                            "uptime",
                            "netin",
                            "netout",
                        ]:
                            base.setdefault(field, 0)

                        base.setdefault("status", "unknown")

                        vms_dict[vmid] = base

                    result["vms"] = vms_dict

                    # -------- Containers --------

                    cts = results[idx]
                    idx += 1

                    cts_dict = {}

                    for ct in cts or []:

                        vmid = ct.get("vmid")

                        if vmid is None:
                            continue

                        if selected_cts and str(vmid) not in selected_cts:
                            continue

                        base = dict(ct)
                        base["node"] = node

                        for field in [
                            "cpu",
                            "mem",
                            "maxmem",
                            "disk",
                            "maxdisk",
                            "uptime",
                            "netin",
                            "netout",
                        ]:
                            base.setdefault(field, 0)

                        base.setdefault("status", "unknown")

                        cts_dict[vmid] = base

                    result["cts"] = cts_dict

                    # -------- Storage --------

                    storages = results[idx]
                    idx += 1

                    storage_dict = {
                        st["storage"]: st
                        for st in storages or []
                        if isinstance(st, dict)
                        and "storage" in st
                        and (not selected_storage or st["storage"] in selected_storage)
                    }

                    result["storage"] = storage_dict

                    # -------- ZFS --------

                    zfs_data = results[idx]
                    idx += 1

                    if isinstance(zfs_data, list) and zfs_data:
                        result["zfs_pools"] = {
                            pool.get("name"): pool
                            for pool in zfs_data
                            if isinstance(pool, dict) and pool.get("name")
                        }
                    else:
                        result["zfs_pools"] = {}

                    # -------- Disks --------

                    if enable_physical_disks:

                        disks = results[idx]
                        idx += 1

                        result["disks"] = {
                            d.get("devpath", f"disk_{i}"): d
                            for i, d in enumerate(disks or [])
                        }

                    # -------- LM Sensors --------

                    result["hardware"] = {}

                    if enable_lm_sensors:

                        lm = results[idx]
                        idx += 1

                        if isinstance(lm, dict):

                            for chip, values in lm.items():

                                if isinstance(values, dict):

                                    for k, v in values.items():

                                        result["hardware"][f"{chip}_{k}".lower()] = v

                    # -------- SMART --------

                    result["smart"] = {}

                    if enable_smart_monitoring:

                        smart_data = results[idx]
                        idx += 1

                        if isinstance(smart_data, dict):

                            result["smart"][node] = smart_data

                        else:

                            result["smart"][node] = {}

                    # -------- Memory --------

                    result["memory"] = {}

                    if enable_memory_monitoring:

                        memory_data = results[idx]

                        if isinstance(memory_data, dict):

                            modules = memory_data.get("modules", [])

                            result["memory"][node] = {
                                "modules": modules,
                                "total_modules": memory_data.get(
                                    "total_modules", len(modules)
                                ),
                                "total_gb": memory_data.get("total_gb", 0),
                                "timestamp": memory_data.get("timestamp"),
                                "dimms": {
                                    module["locator"]: module
                                    for module in modules
                                    if "locator" in module
                                },
                            }

                        else:

                            result["memory"][node] = {
                                "modules": [],
                                "total_modules": 0,
                                "total_gb": 0,
                                "timestamp": None,
                                "dimms": {},
                            }

        except Exception as err:

            _LOGGER.exception("Coordinator update failure")

            raise UpdateFailed(f"Update error: {err}")

        from datetime import datetime

        result["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return result

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"proxmox_{server_type}_{node}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=60),
    )

    coordinator.client = client
    coordinator.api = client

    return coordinator
