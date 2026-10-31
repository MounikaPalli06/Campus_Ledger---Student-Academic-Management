import os
import secrets
from threading import Lock

from flask import Flask, abort, redirect, request, session, url_for
from hmac import compare_digest

from .stores import MongoAccountStore, MongoPerformanceStore, MongoStudentStore


class UnavailableStore:
    def __init__(self, app, name, extension_name, factory):
        self.app = app
        self.name = name
        self.extension_name = extension_name
        self.factory = factory
        self.lock = Lock()

    def _reconnect(self):
        with self.lock:
            store = self.app.extensions[self.extension_name]
            if store is not self:
                return store
            try:
                store = self.factory()
            except Exception as error:
                self.app.logger.exception("Could not reconnect %s", self.name)
                raise RuntimeError(f"{self.name} is unavailable") from error
            self.app.extensions[self.extension_name] = store
            return store

    def __getattr__(self, name):
        def reconnect_and_call(*args, **kwargs):
            return getattr(self._reconnect(), name)(*args, **kwargs)

        return reconnect_and_call


def initialize_store(app, name, extension_name, factory):
    try:
        return factory()
    except Exception:
        app.logger.exception("Could not initialize %s", name)
        return UnavailableStore(app, name, extension_name, factory)


def create_app(config=None, student_store=None, performance_store=None, account_store=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-viva-demo-key"),
        DEBUG=os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        MONGO_DATABASE=os.getenv("MONGO_DATABASE", "student_management"),
        ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)

    app.extensions["student_store"] = (
        student_store if student_store is not None else initialize_store(
            app,
            "MongoDB student store",
            "student_store",
            lambda: MongoStudentStore(app.config["MONGO_URI"], app.config["MONGO_DATABASE"]),
        )
    )
    app.extensions["performance_store"] = (
        performance_store if performance_store is not None else initialize_store(
            app,
            "MongoDB academic records store",
            "performance_store",
            lambda: MongoPerformanceStore(
                app.config["MONGO_URI"],
                app.config["MONGO_DATABASE"],
            ),
        )
    )
    app.extensions["account_store"] = (
        account_store if account_store is not None else initialize_store(
            app,
            "MongoDB account store",
            "account_store",
            lambda: MongoAccountStore(
                app.config["MONGO_URI"],
                app.config["MONGO_DATABASE"],
                app.config["ADMIN_USERNAME"],
                app.config["ADMIN_PASSWORD"],
            ) if app.config["ADMIN_PASSWORD"] else _missing_admin_password(),
        )
    )

    @app.context_processor
    def inject_portal_context():
        return {
            "current_user": session.get("user"),
            "csrf_token": csrf_token,
        }

    def csrf_token():
        token = session.get("_csrf_token")
        if token is None:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            token = request.form.get("_csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not compare_digest(token, expected):
                abort(400, description="Invalid or missing CSRF token.")

    @app.before_request
    def require_authentication():
        public_endpoints = {
            "main.login",
            "main.admin_login",
            "main.student_login",
            "static",
        }
        if request.endpoint not in public_endpoints and not session.get("user"):
            return redirect(url_for("main.login", next=request.path))

    from .routes import bp

    app.register_blueprint(bp)
    return app


def _missing_admin_password():
    raise ValueError("ADMIN_PASSWORD must be configured before starting the portal")
