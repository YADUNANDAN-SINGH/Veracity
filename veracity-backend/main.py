import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.feature.session import warm_models
from app.routes import call, health, number, report, session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The models take a few seconds to load; do it now, not on the first call
    threading.Thread(target=warm_models, name="warm-models", daemon=True).start()
    yield


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

@app.get("/")
def read_root():
    return {"message": "Backend is ready!"}

# @app.get("/items/{item_id}")
# def read_item(item_id: int):
#     return {"item_id": item_id, "status": "success"}
