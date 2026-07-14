from traceback import format_exc
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import RedirectResponse
from app.utils.log_config import log_message
from app.modules.url_redirect.views import redirect_url, increment_click_count
from app.templating import templates


url_redirect_router = APIRouter(tags=["URL Redirect"])


def _error_page(request: Request, message: str, status_code: int):
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "title": {
                404: "Link not found",
                410: "Link expired",
                500: "Something went wrong",
            }.get(status_code, "Error"),
            "message": message,
            "status_code": status_code,
        },
        status_code=status_code,
    )


@url_redirect_router.get("/{short_code}")
async def url_redirect_endpoint(
    short_code: str, request: Request, background_tasks: BackgroundTasks
):
    try:
        data = await redirect_url(short_code)
    except Exception:
        log_message(f"Error: {format_exc()}", error=True)
        return _error_page(
            request, "An unexpected error occurred. Please try again later.", 500
        )

    if not data["status"]:
        return _error_page(request, data["message"], data["status_code"])

    background_tasks.add_task(increment_click_count, short_code)
    return RedirectResponse(url=data["data"]["long_url"], status_code=302)
