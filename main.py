
from fastapi import FastAPI

app = FastAPI(
    title="TraceGrid",
    description="API Monitoring & Analytics Platform",
    version="1.0.0"
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
