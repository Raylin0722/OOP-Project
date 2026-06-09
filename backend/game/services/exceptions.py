class ServiceError(Exception):
    """Base error raised by service-layer objects and converted to JSON in views."""

    def __init__(self, message, status=400, code='bad_request'):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
