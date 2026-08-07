import subprocess
from dataclasses import dataclass, field

import psutil

from rescuer.exceptions import DeviceError


@dataclass
class VolumeInfo:
    mount_point: str
    label: str = ""
    file_system: str = ""
    capacity: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    is_removable: bool = False
    is_ssd: bool | None = None
    bus_type: str = ""
    interface: str = ""
    model: str = ""
    serial: str = ""
    health: str = ""
    device_id: str = ""

    @property
    def used_percent(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return self.used_bytes / self.capacity

    @property
    def free_percent(self) -> float:
        return 1.0 - self.used_percent


@dataclass
class PhysicalDiskInfo:
    device_id: int
    model: str = ""
    media_type: str = ""
    bus_type: str = ""
    size: int = 0
    health: str = ""
    friendly_name: str = ""


class DeviceDetector:
    def __init__(self) -> None:
        self._ps_disks: dict[int, PhysicalDiskInfo] = {}
        self._ps_loaded = False

    def list_volumes(self) -> list[VolumeInfo]:
        volumes: list[VolumeInfo] = []
        try:
            partitions = psutil.disk_partitions(all=True)
        except Exception:
            partitions = []

        for part in partitions:
            if part.device and not part.mountpoint:
                continue
            fs = (part.fstype or "").upper()
            info = VolumeInfo(mount_point=part.mountpoint, file_system=fs)
            info.is_removable = bool(part.opts and "removable" in part.opts)
            info.device_id = part.device
            try:
                usage = psutil.disk_usage(part.mountpoint)
                info.capacity = usage.total
                info.used_bytes = usage.used
                info.free_bytes = usage.free
            except Exception:
                pass
            volumes.append(info)
        return volumes

    def load_physical_disks(self) -> None:
        if self._ps_loaded:
            return
        script = (
            "Get-PhysicalDisk | ForEach-Object { "
            "[PSCustomObject]@{ "
            "DeviceId=$_.DeviceId; FriendlyName=$_.FriendlyName; "
            "MediaType=[string]$_.MediaType; BusType=[string]$_.BusType; "
            "Size=$_.Size; HealthStatus=[string]$_.HealthStatus "
            "} } | ConvertTo-Json"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return
            import json

            data = json.loads(result.stdout or "[]")
            if isinstance(data, dict):
                data = [data]
            for item in data:
                self._ps_disks[int(item.get("DeviceId", -1))] = PhysicalDiskInfo(
                    device_id=int(item.get("DeviceId", -1)),
                    model=item.get("FriendlyName", ""),
                    media_type=item.get("MediaType", ""),
                    bus_type=item.get("BusType", ""),
                    size=int(item.get("Size", 0) or 0),
                    health=item.get("HealthStatus", ""),
                    friendly_name=item.get("FriendlyName", ""),
                )
        except Exception:
            pass
        finally:
            self._ps_loaded = True

    def list_physical_disks(self) -> list[PhysicalDiskInfo]:
        if not self._ps_loaded:
            self.load_physical_disks()
        return list(self._ps_disks.values())

    def enrich_volume(self, volume: VolumeInfo) -> VolumeInfo:
        if not self._ps_loaded:
            self.load_physical_disks()
        match = self._match_physical_disk(volume)
        if match:
            volume.model = match.friendly_name or match.model
            volume.media_type = match.media_type
            volume.bus_type = match.bus_type
            volume.health = match.health
            volume.is_ssd = match.media_type.lower() == "ssd"
            volume.interface = match.bus_type
            volume.device_id = f"PHYSICAL{match.device_id}"
        return volume

    def _match_physical_disk(self, volume: VolumeInfo) -> PhysicalDiskInfo | None:
        if not self._ps_disks:
            return None
        return next(iter(self._ps_disks.values()), None)
