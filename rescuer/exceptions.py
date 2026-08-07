class RescuerError(Exception):
    pass


class ConfigurationError(RescuerError):
    pass


class DatabaseError(RescuerError):
    pass


class DeviceError(RescuerError):
    pass


class DeviceAccessError(DeviceError):
    pass


class ScanError(RescuerError):
    pass


class CarveError(RescuerError):
    pass


class PreviewError(RescuerError):
    pass


class RecoveryError(RescuerError):
    pass


class ImagingError(RescuerError):
    pass


class ReportError(RescuerError):
    pass


class PluginError(RescuerError):
    pass
