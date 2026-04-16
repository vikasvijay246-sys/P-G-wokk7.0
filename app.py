"""
app.py — PG Manager Pro — Application Factory
Flask + SQLAlchemy + Flask-Migrate + SocketIO
"""

import os
import logging
from flask import Flask, render_template, send_from_directory, jsonify
from config import get_config
from extensions import db, migrate, jwt, socketio, bcrypt, cors, limiter, configure_logging


# ── Application factory ────────────────────────────────────────────────────────
def create_app() -> Flask:
    app = Flask(__name__)
    cfg = get_config()
    app.config.from_object(cfg)

    # ── Logging ──────────────────────────────────────────────────────────────
    configure_logging(app.config.get("DEBUG", False))
    log = logging.getLogger("pg_manager")
    log.info("Starting PG Manager Pro (env=%s)", os.environ.get("FLASK_ENV", "development"))

    # ── Upload folder ─────────────────────────────────────────────────────────
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # ── Initialise extensions ─────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)        # Flask-Migrate → `flask db init/migrate/upgrade`
    jwt.init_app(app)
    bcrypt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    limiter.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="threading",       # Python 3.13 compatible (no eventlet required)
        # async_mode="eventlet",      # ← uncomment after: pip install eventlet
        logger=False,
        engineio_logger=False,
    )

    # ── Register API blueprints ────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Register SocketIO handlers ─────────────────────────────────────────────
    with app.app_context():
        import sockets.chat_socket    # noqa – registers @socketio.on handlers
        import sockets.social_socket  # noqa

    # ── Frontend / admin routes ────────────────────────────────────────────────
    _register_frontend_routes(app)

    # ── Global error handlers ─────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── JWT error handlers ────────────────────────────────────────────────────
    _register_jwt_handlers(app)

    # ── Database: single create_all + seed ────────────────────────────────────
    with app.app_context():
        # Import every model so SQLAlchemy is aware of all tables
        import db_models  # noqa – side-effect: registers all models with metadata
        db.create_all()
        _seed_demo_data()
        log.info("Database ready.")

    return app


# ── Helpers ────────────────────────────────────────────────────────────────────

def _register_blueprints(app: Flask) -> None:
    from api.auth     import auth_bp
    from api.tenants  import tenants_bp
    from api.payments import payments_bp
    from api.chat     import chat_bp
    from api.misc     import notif_bp, files_bp, settings_bp
    from api.social   import social_bp
    from api.phase3   import p3_bp
    from api.admin    import admin_bp

    for bp in (auth_bp, tenants_bp, payments_bp, chat_bp,
               notif_bp, files_bp, settings_bp, social_bp, p3_bp, admin_bp):
        app.register_blueprint(bp)


def _register_frontend_routes(app: Flask) -> None:
    """
    Routing separation:
      /api/*   → blueprints (registered above, never fall through here)
      /admin   → admin SPA
      /*       → main SPA  (never matches /api/* thanks to blueprint priority)
    """

    @app.route("/admin")
    def admin_panel():
        return render_template("admin.html")

    @app.route("/")
    @app.route("/<path:path>")
    def index(path: str = ""):
        # Guard: API calls that reach here are misdirected — return 404
        if path and (path.startswith("api/") or path.startswith("admin")):
            return jsonify({"error": True, "message": f"Not found: /{path}"}), 404
        return render_template("index.html")

    @app.route("/static/uploads/<filename>")
    def serve_upload(filename: str):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def _register_error_handlers(app: Flask) -> None:
    log = logging.getLogger("pg_manager")

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": True, "message": str(e.description)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": True, "message": "Authentication required."}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": True, "message": "Access denied."}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": True, "message": "Resource not found."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": True, "message": "Method not allowed."}), 405

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": True, "message": "Too many requests. Please slow down."}), 429

    @app.errorhandler(500)
    def server_error(e):
        log.exception("Unhandled 500 error")
        return jsonify({"error": True, "message": "Internal server error. Please try again."}), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        log.exception("Unhandled exception: %s", e)
        return jsonify({"error": True, "message": "An unexpected error occurred."}), 500


def _register_jwt_handlers(app: Flask) -> None:
    @jwt.unauthorized_loader
    def unauth(reason):
        return jsonify({"error": True, "message": "Token required.", "reason": reason}), 401

    @jwt.expired_token_loader
    def expired(header, payload):
        return jsonify({"error": True, "message": "Token has expired. Please log in again."}), 401

    @jwt.invalid_token_loader
    def invalid(reason):
        return jsonify({"error": True, "message": "Invalid token.", "reason": reason}), 422

    @jwt.revoked_token_loader
    def revoked(header, payload):
        return jsonify({"error": True, "message": "Token has been revoked."}), 401


def _seed_demo_data() -> None:
    """Idempotent: only seeds when the DB is empty."""
    log = logging.getLogger("pg_manager")
    from db_models import User, UserSettings, Room
    from extensions import bcrypt as _bcrypt

    if User.query.first():
        return  # Already seeded

    log.info("Seeding demo data...")

    # Owner
    owner = User(
        name="PG Owner", phone="9999900000",
        password_hash=_bcrypt.generate_password_hash("owner123").decode(),
        role="owner",
    )
    db.session.add(owner)
    db.session.flush()
    db.session.add(UserSettings(user_id=owner.id))

    # Admin
    adm = User(
        name="Admin", phone="9111100000",
        password_hash=_bcrypt.generate_password_hash("admin123").decode(),
        role="admin",
    )
    db.session.add(adm)
    db.session.flush()
    db.session.add(UserSettings(user_id=adm.id))

    # Demo rooms
    for i in range(1, 11):
        db.session.add(Room(
            room_number=str(100 + i),
            floor="1" if i <= 5 else "2",
            capacity=2,
            rent_price=5000 + (i * 100),
        ))

    db.session.commit()
    log.info("Demo owner: 9999900000 / owner123")
    log.info("Admin:      9111100000 / admin123")
    log.info("10 rooms created (101–110)")


# ── Entry point ────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    log = logging.getLogger("pg_manager")
    log.info("PG Manager Pro — dev server on http://0.0.0.0:5000")
    socketio.run(
        app,
        debug=True,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True,
    )
