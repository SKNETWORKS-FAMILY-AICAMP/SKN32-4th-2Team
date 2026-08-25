import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ...core.security import require_admin, require_admin_api
from ...core.database import get_db
from ...services.stats_service import (
    get_category_ratio,
    get_daily_trend,
    get_faq_top10,
    get_user_question_summary,
)

router = APIRouter(
    prefix="/admin/stats",
    tags=["Admin Stats"],
)

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("", response_class=HTMLResponse)
def stats_page(request: Request):
    user, redirect = require_admin(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "admin/stats.html",
        {"user": user, "active": "admin_stats"},
    )


@router.get("/api/summary")
def stats_summary_api(request: Request, db: Session = Depends(get_db)):
    require_admin_api(request)

    return {
        "category_ratio": get_category_ratio(db),
        "user_summary": get_user_question_summary(db),
        "daily_trend": get_daily_trend(db),
        "faq_top10": get_faq_top10(db),
    }
