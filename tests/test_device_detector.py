from rescuer.engine.device.detector import DeviceDetector


def test_list_volumes_returns_list():
    detector = DeviceDetector()
    volumes = detector.list_volumes()
    assert isinstance(volumes, list)
    for v in volumes:
        assert v.mount_point
        assert v.capacity >= 0
        assert v.free_bytes >= 0


def test_physical_disks_safe():
    detector = DeviceDetector()
    disks = detector.list_physical_disks()
    assert isinstance(disks, list)


def test_volume_used_percent():
    from rescuer.engine.device.detector import VolumeInfo

    v = VolumeInfo(mount_point="C:\\", capacity=100, used_bytes=25, free_bytes=75)
    assert v.used_percent == 0.25
    assert v.free_percent == 0.75
