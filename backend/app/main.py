"""FastAPI application entry point."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(title="Bengaluru E-Waste GIS Facility Planner API",
              version="0.1.0", description="Synthetic demo data and explainable suitability analysis.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("EWASTE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)
