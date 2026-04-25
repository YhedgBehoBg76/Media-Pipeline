# scripts/generate_oauth_token.py
import os
import pickle
import logging
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]

main_dir = Path(os.curdir).parent
CREDS_PATH = f"{main_dir}/secrets/google_client_secret.json"
TOKEN_PATH = f"{main_dir}/secrets/token.pickle"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info(f"Using credentials: {CREDS_PATH}")
    logger.info(f"Token will be saved to: {TOKEN_PATH}")

    # ← Проверка: существует ли файл credentials
    if not os.path.exists(CREDS_PATH):
        logger.error(f"Credentials file not found: {CREDS_PATH}")
        logger.error("Download it from Google Cloud Console → Credentials → OAuth client ID")
        return

    # ← Создаём папку для токена, если нет
    token_dir = Path(TOKEN_PATH).parent
    token_dir.mkdir(parents=True, exist_ok=True)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
        logger.info("Opening browser for authentication...")
        creds = flow.run_local_server(port=0)

        # ← Сохраняем токен
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token) # type: ignore[arg-type]

        logger.info(f"✓ Token saved to: {TOKEN_PATH}")
        logger.info("Mount this file into Docker container at /app/secrets/token.pickle")

    except Exception as e:
        logger.error(f"Failed to generate token: {e}")
        raise

if __name__ == "__main__":
    main()