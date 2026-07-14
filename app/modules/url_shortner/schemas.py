from typing import Optional
from pydantic import BaseModel, HttpUrl, Field, field_validator

# Custom aliases can't collide with real top-level app routes.
RESERVED_ALIASES = {
    "api",
    "static",
    "stats",
    "health",
    "docs",
    "redoc",
    "openapi.json",
    "favicon.ico",
}


class UrlShortnerBodySchemas(BaseModel):
    url: HttpUrl
    custom_alias: Optional[str] = Field(default=None, min_length=3, max_length=32)
    ttl: Optional[int] = Field(
        default=None, gt=0, description="Seconds until this link expires"
    )

    @field_validator("custom_alias")
    @classmethod
    def validate_alias_not_reserved(cls, value: Optional[str]) -> Optional[str]:
        if value and value.lower() in RESERVED_ALIASES:
            raise ValueError(f"'{value}' is reserved and can't be used as a custom alias")
        return value
