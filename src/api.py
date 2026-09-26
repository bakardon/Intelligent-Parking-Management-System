from fastapi import FastAPI
from src.monitor import ParkingMonitor

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(
    title="ParkSight API",
    description="Parking occupancy monitoring API",
    version="1.0.0",
)


monitor = ParkingMonitor()


@app.on_event("startup")
def startup():

    monitor.start()


@app.on_event("shutdown")
def shutdown():

    monitor.stop()

app.mount(
    "/static",
    StaticFiles(directory="web"),
    name="static",
)

@app.get("/")
def root():

    return FileResponse(
        "web/index.html"
    )


@app.get("/status")
def get_status():

    return monitor.get_status()

@app.get("/history")
def get_history(limit: int = 100):
    return monitor.database.get_history(limit=limit)