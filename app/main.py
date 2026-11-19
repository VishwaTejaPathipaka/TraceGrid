
from fastapi import FastAPI
from app.database import Base, engine
from app.models import APIEndpoint
from app.routes.endpoints import router as endpoint_router
from app.routes.users import router as user_router
from app.routes.monitoring import router as monitoring_router
from fastapi.middleware.cors import CORSMiddleware
from app.services.scheduler import start_scheduler, scheduler

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="TraceGrid",
    description="API Monitoring & Analytics Platform",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    endpoint_router,
    prefix="/endpoints",
    tags=["Endpoints"]
)


app.include_router(
    user_router,
    prefix="/users",
    tags=["Users"]
)

app.include_router(
    monitoring_router,
    prefix="/monitor",
    tags=["Monitoring"]
)

@app.get("/")
def home():
    return {
        "project": "TraceGrid",
        "message": "Welcome to TraceGrid API Monitoring Platform",
        "status": "Running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "TraceGrid"
    }


@app.on_event("startup")
def start_monitoring():
    start_scheduler()
    print("TraceGrid automatic monitoring started")


@app.on_event("shutdown")
def stop_monitoring():
    scheduler.shutdown()
    print("TraceGrid automatic monitoring stopped")