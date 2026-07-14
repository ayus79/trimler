from traceback import format_exc
from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from app.utils.log_config import log_message
from app.modules.url_shortner.views import short_url, get_url_stats
from app.modules.url_shortner.schemas import UrlShortnerBodySchemas
from app.templating import templates


url_shortner_router = APIRouter(prefix="/api", tags=["URL Shortner"])

url_shortner_page_router = APIRouter(tags=["URL Shortner UI"])


@url_shortner_router.post("/url")
async def short_url_endpoint(
    request: Request, params: UrlShortnerBodySchemas = Body(...)
):
    try:
        data = await short_url(request, params)
    except Exception:
        log_message(f"Error: {format_exc()}", error=True)
        data = {
            "status": False,
            "message": "An unexpected error occurred. Please try again later.",
            "status_code": 500,
        }

    return JSONResponse(
        content={
            "status": data.get("status"),
            "message": data.get("message"),
            "data": data.get("data", None),
        },
        status_code=data.get("status_code", 200),
    )


@url_shortner_router.get("/url/{short_code}/stats")
async def url_stats_endpoint(short_code: str):
    try:
        data = await get_url_stats(short_code)
    except Exception:
        log_message(f"Error: {format_exc()}", error=True)
        data = {
            "status": False,
            "message": "An unexpected error occurred. Please try again later.",
            "status_code": 500,
        }

    return JSONResponse(
        content={
            "status": data.get("status"),
            "message": data.get("message"),
            "data": data.get("data", None),
        },
        status_code=data.get("status_code", 200),
    )


@url_shortner_page_router.get("/")
async def shorten_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@url_shortner_page_router.get("/stats")
async def stats_page(request: Request):
    return templates.TemplateResponse(request, "stats.html")
