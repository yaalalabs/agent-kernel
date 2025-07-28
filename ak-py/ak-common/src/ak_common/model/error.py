from pydantic import BaseModel


class Error(BaseModel):
    code: str
    message: str
