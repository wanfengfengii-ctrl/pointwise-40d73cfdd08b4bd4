class WarehouseError(Exception):
    """Public base error."""


class SchemaError(WarehouseError):
    pass


class ResolutionError(WarehouseError):
    pass


class Conflict(WarehouseError):
    pass


class NotFound(WarehouseError):
    pass
