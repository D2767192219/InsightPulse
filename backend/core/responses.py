from typing import Optional
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    code: int = Field(default=200, description="Status code")
    message: str = Field(default="success", description="Response message")
    data: Optional[dict | list | None] = Field(default=None, description="Response data")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 200,
                "message": "success",
                "data": {}
            }
        }


def success_response(data: dict | list | None = None, message: str = "success", code: int = 200) -> dict:
    return {"code": code, "message": message, "data": data}


def error_response(message: str, code: int = 400) -> dict:
    return {"code": code, "message": message, "data": None}
