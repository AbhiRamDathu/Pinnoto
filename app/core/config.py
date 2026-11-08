
import os

from dotenv import load_dotenv

load_dotenv()


VULTR_INFERENCE_BASE_URL = "https://api.vultrinference.com/v1"
VULTR_INFERENCE_API_KEY = os.getenv("VULTR_INFERENCE_API_KEY")
VULTR_INFERENCE_MODEL = os.getenv("VULTR_INFERENCE_MODEL", "")


def inference_configured() -> bool:
    return bool(VULTR_INFERENCE_API_KEY and VULTR_INFERENCE_MODEL)
