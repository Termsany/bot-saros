"""The API's routers, split out of app/main.py (development-plan 3.2)."""


def all_routes(app):
    """Every route of the app, the routers' included ones too (FastAPI keeps an included router as one entry in
    app.routes): what a check over "every endpoint" must walk."""
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from all_routes(inner)
        else:
            yield r
