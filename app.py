import hmac
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory, session, url_for
from werkzeug.exceptions import HTTPException


BASE_DIR = Path(__file__).resolve().parent
TRACKS = {
    "mr-mo-lily-special-25": {
        "title": "MR MO Lily x Point & Clap SPECIAL'25 ft Brozz Chet & Kim Chea &",
        "path": BASE_DIR / "Music" / "MR_MO_Lily_x_Point_&_Clap_SPECIAL'25_ft_Brozz_Chet_&_Kim_Chea_&.mp3",
    },
    "chinese-20-03-26": {
        "title": "Chinese 20_03_26",
        "path": BASE_DIR / "Nonatop" / "Chinese 20_03_26.wav",
    },
}


def create_app(test_config=None):
    load_dotenv(BASE_DIR / ".env")

    config = test_config or {}
    secret_key = config.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not isinstance(secret_key, str) or len(secret_key) < 32:
        raise RuntimeError("Set FLASK_SECRET_KEY to at least 32 characters in the environment or .env file.")

    data_directory = Path(
        config.get("USER_LOGIN_DIR")
        or os.environ.get("USER_LOGIN_DIR")
        or BASE_DIR / "User Login"
    ).resolve()
    admin_email = str(
        config.get("ADMIN_EMAIL")
        or os.environ.get("ADMIN_EMAIL")
        or "Lyriki12@gmail.com"
    ).strip().casefold()
    if not admin_email:
        raise RuntimeError("ADMIN_EMAIL must contain an email address.")

    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=str(
            config.get("SESSION_COOKIE_SECURE")
            or os.environ.get("SESSION_COOKIE_SECURE", "true")
        ).casefold()
        in {"1", "true", "yes"},
        USER_LOGIN_DIR=str(data_directory),
        ADMIN_EMAIL=admin_email,
        TRACKS=config.get("TRACKS", TRACKS),
    )
    if test_config:
        app.config.update(test_config)

    data_directory.mkdir(parents=True, exist_ok=True)
    user_database = data_directory / "users.sqlite3"
    with closing(sqlite3.connect(user_database)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    google_sub TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    first_login TEXT NOT NULL,
                    last_login TEXT NOT NULL
                )
                """
            )

    oauth = OAuth(app)
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    google = None
    if client_id and client_secret and redirect_uri:
        google = oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    def current_user():
        google_sub = session.get("user_sub")
        if not isinstance(google_sub, str):
            return None
        with closing(sqlite3.connect(user_database)) as connection:
            row = connection.execute(
                "SELECT google_sub, email, name FROM users WHERE google_sub = ?",
                (google_sub,),
            ).fetchone()
        if row is None:
            return None
        return {"sub": row[0], "email": row[1], "name": row[2]}

    def require_user():
        if current_user() is None:
            abort(401, description="Sign in with Google to access the music library.")

    def require_csrf():
        expected = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(400, description="The security token is missing or invalid. Refresh and try again.")

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.get("/")
    def home():
        filename = "index.html" if current_user() else "login.html"
        return send_from_directory(BASE_DIR, filename)

    @app.get("/background.css")
    def background_stylesheet():
        return send_from_directory(BASE_DIR, "background.css")

    @app.get("/api/me")
    def get_current_account():
        user = current_user()
        csrf_token = None
        if user is not None:
            csrf_token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return jsonify(
            authenticated=user is not None,
            email=user.get("email") if user else None,
            is_admin=bool(user and user.get("email", "").casefold() == app.config["ADMIN_EMAIL"]),
            csrf_token=csrf_token,
            login_enabled=google is not None,
        )

    @app.get("/api/songs")
    def list_songs():
        require_user()
        songs = []
        for song_id, track in app.config["TRACKS"].items():
            path = Path(track["path"])
            if path.is_file():
                songs.append(
                    {
                        "id": song_id,
                        "title": track["title"],
                        "audio_url": url_for("song_media", song_id=song_id),
                        "download_url": url_for("song_media", song_id=song_id, download="1"),
                    }
                )
        return jsonify(songs)

    @app.get("/media/<song_id>")
    def song_media(song_id):
        require_user()
        track = app.config["TRACKS"].get(song_id)
        if track is None:
            abort(404, description="Song not found.")
        path = Path(track["path"])
        if not path.is_file():
            abort(404, description="Song not found.")
        return send_file(
            path,
            as_attachment=request.args.get("download") == "1",
            download_name=path.name,
            conditional=True,
        )

    @app.get("/auth/login")
    def google_login():
        if google is None:
            return (
                "Google sign-in is not configured. Set GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI on the server.",
                503,
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        return google.authorize_redirect(redirect_uri)

    @app.get("/auth/callback")
    def google_callback():
        if google is None:
            abort(503, description="Google sign-in is not configured on this server.")
        token = google.authorize_access_token()
        user_info = token.get("userinfo")
        if not isinstance(user_info, dict):
            abort(401, description="Google did not provide verified account information.")

        google_sub = user_info.get("sub")
        email = user_info.get("email")
        if (
            not isinstance(google_sub, str)
            or not isinstance(email, str)
            or not google_sub
            or not email
            or user_info.get("email_verified") is not True
        ):
            abort(403, description="Use a Google account with a verified email address.")

        email = email.strip().casefold()
        display_name = str(user_info.get("name") or email)
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(user_database)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO users (google_sub, email, name, first_login, last_login)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(google_sub) DO UPDATE SET
                        email = excluded.email,
                        name = excluded.name,
                        last_login = excluded.last_login
                    """,
                    (google_sub, email, display_name, now, now),
                )

        session.clear()
        session["user_sub"] = google_sub
        session["csrf_token"] = secrets.token_urlsafe(32)
        return redirect(url_for("home"))

    @app.post("/auth/logout")
    def logout():
        require_user()
        require_csrf()
        session.clear()
        return "", 204

    @app.delete("/api/songs/<song_id>")
    def delete_song(song_id):
        user = current_user()
        if user is None:
            abort(401, description="Sign in with Google to delete songs.")
        if user.get("email", "").casefold() != app.config["ADMIN_EMAIL"]:
            abort(403, description="Only the site administrator can delete website songs.")
        require_csrf()

        track = app.config["TRACKS"].get(song_id)
        if track is None:
            abort(404, description="Song not found.")
        path = Path(track["path"])
        if not path.is_file():
            abort(404, description="Song not found.")
        try:
            path.unlink()
        except OSError:
            app.logger.exception("Could not delete website song %s", song_id)
            abort(500, description="The song could not be deleted. Check the server logs.")
        return "", 204

    return app


if __name__ == "__main__":
    from waitress import serve

    serve(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
