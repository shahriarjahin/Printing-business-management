"""Create installation secrets once. Never overwrites an existing configuration."""
from pathlib import Path
import secrets
p = Path(__file__).with_name('.env')
if p.exists():
    print('Configuration already exists. Open .env to find your setup token.')
else:
    p.write_text('SECRET_KEY=' + secrets.token_hex(32) + '\nSETUP_TOKEN=' + secrets.token_urlsafe(24) + '\nPUBLIC_URL=http://localhost:8091\nBIND_ADDRESS=127.0.0.1\nPORT=8091\nCOOKIE_SECURE=0\nMIGRATE_TRACKER=0\n', encoding='utf-8')
    print('Created .env. Open it to find SETUP_TOKEN, then run docker compose up -d --build.')
