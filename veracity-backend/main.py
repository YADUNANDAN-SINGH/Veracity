from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import health, number

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(number.router)

@app.get("/")
def read_root():
    return {"message": "Backend is ready!"}

# @app.get("/items/{item_id}")
# def read_item(item_id: int):
#     return {"item_id": item_id, "status": "success"}
