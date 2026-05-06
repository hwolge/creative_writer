from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import archive, planning, project, state, writing

app = FastAPI(title="Novel Writer", version="1.0.0")

app.include_router(project.router, prefix="/project", tags=["project"])
app.include_router(planning.router, prefix="/plan",    tags=["planning"])
app.include_router(writing.router,  prefix="/scene",   tags=["writing"])
app.include_router(state.router,    prefix="/state",   tags=["state"])
app.include_router(archive.router,  prefix="/archive", tags=["archive"])

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(_static / "index.html"))
