from fastapi import FastAPI

from src.monitor import ParkingMonitor

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


@app.get("/")
def root():

    return {
        "name": "ParkSight",
        "status": "running",
    }


@app.get("/status")
def get_status():

    return monitor.get_status()