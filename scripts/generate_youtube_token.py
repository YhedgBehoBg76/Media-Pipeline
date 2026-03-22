# scripts/generate_oauth_token.py
import os
import pickle
import logging
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# ← Убраны пробелы в конце!
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "secrets/google_client_secret.json")
    token_path = os.getenv("GOOGLE_OUTPUT_PATH", "secrets/token.pickle")

    logger.info(f"Using credentials: {creds_path}")
    logger.info(f"Token will be saved to: {token_path}")

    # ← Проверка: существует ли файл credentials
    if not os.path.exists(creds_path):
        logger.error(f"Credentials file not found: {creds_path}")
        logger.error("Download it from Google Cloud Console → Credentials → OAuth client ID")
        return

    # ← Создаём папку для токена, если нет
    token_dir = Path(token_path).parent
    token_dir.mkdir(parents=True, exist_ok=True)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        logger.info("Opening browser for authentication...")
        creds = flow.run_local_server(port=0)

        # ← Сохраняем токен (с игнором предупреждения PyCharm)
        with open(token_path, 'wb') as token:  # type: ignore[arg-type]
            pickle.dump(creds, token)

        logger.info(f"✓ Token saved to: {token_path}")
        logger.info("Mount this file into Docker container at /app/secrets/token.pickle")

    except Exception as e:
        logger.error(f"Failed to generate token: {e}")
        raise

if __name__ == "__main__":
    main()