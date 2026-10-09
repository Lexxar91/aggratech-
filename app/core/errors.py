from fastapi import HTTPException


class ApiError(HTTPException):
    """Безопасная прикладная ошибка без секретов и внутренних исключений."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(status_code=status, detail=detail)
        self.code = code
