"""Application errors. All user-facing messages are Arabic."""


class AppError(Exception):
    """Business-rule error whose message is safe to show to the user (Arabic)."""

    def __init__(self, message_ar: str):
        super().__init__(message_ar)
        self.message_ar = message_ar


class PermissionDenied(AppError):
    def __init__(self, message_ar: str = "ليست لديك صلاحية لتنفيذ هذه العملية."):
        super().__init__(message_ar)


class InsufficientStock(AppError):
    pass
