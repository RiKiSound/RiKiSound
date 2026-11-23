# Nonstop music website

This site uses a Flask server for Google sign-in and administrator-only song deletion. Static-only hosting such as GitHub Pages cannot enforce these permissions.

## Configure Google sign-in

1. In Google Cloud Console, create a **Web application** OAuth client and configure the consent screen.
2. Add the exact callback URL to the OAuth client's authorized redirect URIs:
   - Local development: `http://localhost:8000/auth/callback`
   - Public website: `https://YOUR_DOMAIN/auth/callback`
3. Copy `.env.example` to `.env`. Set the Google client ID and secret. Generate a secret with `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"` and use it for `FLASK_SECRET_KEY`. Never publish `.env` or put the client secret in HTML.
4. Set `GOOGLE_REDIRECT_URI` to the same callback URL entered in Google Cloud Console.
5. Keep `ADMIN_EMAIL` set to `Lyriki12@gmail.com`. Only that verified Google account can delete website songs.

Google passwords and OAuth tokens are not stored. Successful sign-ins are recorded in `User Login\users.sqlite3` with the Google account ID, email, display name, and first/last sign-in times. The data folder is not served by the website.

## Run locally

Install Python 3.10 or newer, then run these commands from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your Google credentials and set `SESSION_COOKIE_SECURE=false` for local HTTP. Then start the server:

```powershell
.\.venv\Scripts\python app.py
```

Open `http://localhost:8000`. Visitors must sign in before accessing the music library.

## Publish

Deploy this Python application to a host that supports a persistent server process and persistent writable storage. Configure the environment variables in the host's secret/settings panel, set `GOOGLE_REDIRECT_URI` to the public HTTPS callback, and keep `SESSION_COOKIE_SECURE=true`. Set `USER_LOGIN_DIR` to a private, persistent directory on that server; `D:\HTML\User Login` is only a path on the Windows computer and does not exist on most hosting services. Serve the app over HTTPS.

If the host starts `python app.py`, set `HOST=0.0.0.0` and use the port assigned by the host. The public HTTPS connection should terminate at the hosting provider or its reverse proxy.

The Delete action permanently removes a built-in music file from the server. Visitor uploads remain local to their browser and are not added to the shared library.
