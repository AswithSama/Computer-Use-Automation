from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .data import MEMBERS, get_account, get_member


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Core Banking Admin - Demo",
    description="Synthetic legacy-style target application for computer-use automation.",
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page_title": "Operations Dashboard",
            "active_page": "dashboard",
            "member_count": len(MEMBERS),
        },
    )


@app.get("/members", response_class=HTMLResponse)
async def members(request: Request, member_id: str | None = None):
    searched = member_id is not None
    query = (member_id or "").strip()
    member = None
    error = None

    if searched:
        if not query:
            error = "Member ID is required before a search can be submitted."
        elif not query.isdigit():
            error = "Member ID must contain numbers only."
        else:
            member = get_member(query)
            if member is None:
                error = f"No member record was found for ID {query}."

    return templates.TemplateResponse(
        request=request,
        name="members.html",
        context={
            "page_title": "Member Search",
            "active_page": "members",
            "member": member,
            "query": query,
            "searched": searched,
            "error": error,
        },
    )


@app.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail(request: Request, member_id: str):
    member = get_member(member_id)

    if member is None:
        return templates.TemplateResponse(
            request=request,
            name="member_detail.html",
            status_code=404,
            context={
                "page_title": "Member Record",
                "active_page": "members",
                "member": None,
                "member_id": member_id,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="member_detail.html",
        context={
            "page_title": "Member Record",
            "active_page": "members",
            "member": member,
            "member_id": member_id,
        },
    )


@app.get("/members/{member_id}/accounts/{account_id}", response_class=HTMLResponse)
async def account_detail(request: Request, member_id: str, account_id: str):
    member = get_member(member_id)
    account = get_account(member_id, account_id)

    if member is None or account is None:
        return templates.TemplateResponse(
            request=request,
            name="account_detail.html",
            status_code=404,
            context={
                "page_title": "Account Details",
                "active_page": "members",
                "member": member,
                "account": None,
                "account_id": account_id,
                "permission_denied": False,
            },
        )

    permission_denied = bool(account.get("restricted"))

    return templates.TemplateResponse(
        request=request,
        name="account_detail.html",
        status_code=403 if permission_denied else 200,
        context={
            "page_title": "Account Details",
            "active_page": "members",
            "member": member,
            "account": account,
            "account_id": account_id,
            "permission_denied": permission_denied,
        },
    )


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_placeholder(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page_title": "Accounts",
            "active_page": "accounts",
            "member_count": len(MEMBERS),
            "placeholder_message": "Use Member Search to access an account record.",
        },
    )


@app.get("/operations", response_class=HTMLResponse)
async def operations_placeholder(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page_title": "Operations",
            "active_page": "operations",
            "member_count": len(MEMBERS),
            "placeholder_message": "No queued operations are available in this demo environment.",
        },
    )
