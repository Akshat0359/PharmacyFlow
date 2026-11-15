"""Generate local secrets without printing them; never overwrites an existing .env."""

from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if not target.exists():
    text = (root / ".env.example").read_text()
    text = text.replace("replace-with-at-least-32-random-characters", secrets.token_urlsafe(48))
    text = text.replace("replace-with-a-local-demo-password", secrets.token_urlsafe(18))
    target.write_text(text)
    print("Created .env with generated secrets. Read DEMO_PASSWORD locally to sign in.")
else:
    print(".env exists; preserved.")
if "POSTGRES_PASSWORD=" not in target.read_text():
    with target.open("a") as out:
        out.write("\nPOSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n")
