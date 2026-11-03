import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.feature import payment_gate
from app.feature.session import warm_models
from app.routes import call, health, number, payment, report, session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

JUDGE_MODE = os.environ.get("VERA_MODE") == "judge"
# The built dashboard (npm run build → dist/), served by this app in the hosted judge build
STATIC_DIR = Path(os.environ["VERA_STATIC_DIR"]).resolve() if os.environ.get("VERA_STATIC_DIR") else None
SWEEP_EVERY_S = 60


def sweep_holds(stop: threading.Event) -> None:
    """Void held payments that ran out and finish cooling-offs, with or without the dashboard open."""
    while not stop.wait(SWEEP_EVERY_S):
        payment_gate.sweep()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The models take a few seconds to load; do it now, not on the first call.
    # The judge build replays calls and has no models to load.
    if not JUDGE_MODE:
        threading.Thread(target=warm_models, name="warm-models", daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=sweep_holds, args=(stop,), name="payment-sweeper", daemon=True).start()
    yield
    stop.set()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(number.router)
app.include_router(call.router)
app.include_router(session.router)
app.include_router(report.router)
app.include_router(payment.router)

if STATIC_DIR and (STATIC_DIR / "index.html").is_file():

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str):
        """The React dashboard: real files as they are, every other page to index.html."""
        if path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404, detail="Not found")
        file = (STATIC_DIR / path).resolve()
        if path and file.is_file() and STATIC_DIR in file.parents:
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")

else:

    @app.get("/")
    def read_root():
        return {"message": "Backend is ready!"}
