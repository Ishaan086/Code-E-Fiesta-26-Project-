import os
from pathlib import Path
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ps4.db")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
WATSONX_API_KEY = os.getenv("WATSONX_API_KEY", "").strip()
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "").strip()
WATSONX_URL = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")
WATSONX_MODEL_ID = os.getenv("WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct")
WATSONX_API_VERSION = os.getenv("WATSONX_API_VERSION", "2024-05-31")
# Hosted Gemma through the Google Gemini API.
GEMMA_API_KEY = (
    os.getenv("GEMMA_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or ""
).strip()

GEMMA_MODEL_ID = os.getenv(
    "GEMMA_MODEL_ID",
    "gemma-4-26b-a4b-it"
).strip()