# WindCrest Store

Full-stack Flask + Neon PostgreSQL Minecraft store with the supplied UPI QR image.

## Quick start

1. Create a Neon PostgreSQL database.
2. Copy `.env.example` to `.env` and fill in `DATABASE_URL`, a strong `SECRET_KEY`, `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
3. Install Python 3.11 or 3.12, then run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app create-admin
flask --app app run
```

Windows activation: `.venv\\Scripts\\activate`.

Open `http://localhost:5000`. Admins can log in through `/login` and manually visit `/admin`. No admin link is exposed in the public UI. Admin access is checked on the server.

## Deployment

Deploy on Render or another Python-capable host with `gunicorn app:app`. Set the environment variables in the host dashboard and set `COOKIE_SECURE=true` under HTTPS. Netlify static hosting alone cannot run this Flask backend. Run `flask --app app init-db` and `flask --app app create-admin` in your deployment environment once. Use a persistent volume for `UPLOAD_DIR`, or replace local file storage with a private object-storage service before production; ephemeral hosts will lose screenshots. Use a custom domain and HTTPS.

## Payment

The exact uploaded QR is included at `static/payment_qr.png`, UPI `7818049331@fam`. Payment verification is **manual**. Never approve a transaction based only on a screenshot/UTR: independently verify receipt in the actual payment account. The QR image is not regenerated.

## Important limitations

- The reference Netlify website was not reachable in this build environment. This is a fresh WindCrest-themed UI, **not** a pixel-perfect clone. Original server IP and Discord invite were unavailable; set both in `/admin?tab=settings` before launch.
- 30-day Flask signed-cookie sessions persist per device, but are not server-side revocable; banning a user blocks protected actions on the next request. For stronger production session revocation use a server-side session store and rotate session IDs on login.
- Uploaded screenshots use local storage by default. Configure persistent private storage for production.
- Email verification, password reset, login rate limiting, automatic Minecraft rank delivery, UTR verification API, and full automated integration tests are **not implemented**. Add them before accepting significant real payments.
- Admin product management supports add, edit, hide, and re-enable; physical delete is intentionally omitted to preserve order history.
- User can correct a pending UTR but cannot reupload screenshot in this build.
- Admin UPI text can be updated in settings, but changing the QR requires replacing `static/payment_qr.png` and redeploying.

## Security

Passwords are hashed, SQL is parameterized, CSRF tokens protect forms, uploads are image-type checked, and order ownership is enforced. Set a strong SECRET_KEY and HTTPS. Keep `.env` private.
