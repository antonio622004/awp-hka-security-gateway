"""Explicit environment/file configuration. Secrets are never configuration defaults."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class OidcConfig:
    # Contract retained from portal.core.config.OidcConfig.
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    post_logout_redirect_uri: str
    discovery_url: str | None = None
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    id_token_algs: tuple[str, ...] = ("RS256", "ES256")
    clock_leeway_seconds: int = 60


@dataclass(frozen=True)
class AppsConfig:
    """Weiterleitung an die App-Container (Abschnitt ``apps``).

    :ivar upstream: Adresse eines App-Containers mit ``{slug}`` als Platzhalter, z. B. ``http://app-{slug}:8080``
    :ivar connect_timeout_seconds: Zeitlimit für den Verbindungsaufbau
    :ivar read_timeout_seconds: Zeitlimit für die Antwort der App
    :ivar max_body_bytes: Größte erlaubte Anfrage an eine App
    """
    upstream: str
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 30.0
    max_body_bytes: int = 10 * 1024 * 1024

    def upstream_for(self, slug: str) -> str:
        """Adresse des Containers einer App.

        :param slug: Slug der App
        :return: Basisadresse ohne abschließenden Slash
        :rtype: str
        """
        return self.upstream.replace("{slug}", slug).rstrip("/")


@dataclass(frozen=True)
class AssertionConfig:
    """Portal assertion configuration, without portal runtime dependencies."""
    issuer: str
    ttl_seconds: int = 60
    signing_key_current: Path | None = None
    signing_key_next: Path | None = None
    signing_key_previous: Path | None = None


@dataclass(frozen=True)
class Settings:
    public_url: str
    oidc: OidcConfig
    signing_key: Path
    redis_url: str = "redis://redis:6379/0"
    session_seconds: int = 300
    idle_seconds: int = 300
    touch_min_interval_seconds: int = 60
    assertion_seconds: int = 60
    login_seconds: int = 600
    cookie_secure: bool = True
    cookie_name: str = "__Host-hka_gateway_sid"
    login_cookie: str = "__Host-hka_gateway_login"
    portal_audience: str = "hka-portal-ui"
    demo_enabled: bool = False
    roles_file: Path | None = None
    grants_file: Path | None = None
    role_vocabulary: tuple[str, ...] = ()
    assertion_issuer: str | None = None
    signing_key_next: Path | None = None
    signing_key_previous: Path | None = None
    registry_url: str | None = None
    registry_token_file: Path | None = None
    apps: AppsConfig | None = None
    portal_upstream: str | None = None
    internal_hosts: tuple[str, ...] = ()

    def __post_init__(self):
        if bool(self.registry_url) != bool(self.registry_token_file):
            raise ConfigError("Registry URL and service token file must be configured together")
        if self.portal_upstream and (self.registry_url != self.portal_upstream or not self.registry_token_file):
            raise ConfigError("Portal forwarding requires the same trusted authorization origin and service token")
        if self.registry_url:
            parts = urlsplit(self.registry_url)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                    or parts.query or parts.fragment or parts.path not in ("", "/")):
                raise ConfigError("Registry URL must be an HTTP(S) origin without credentials")
        for value in (self.public_url, self.oidc.issuer):
            parts = urlsplit(value)
            if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
                raise ConfigError("A valid HTTP(S) URL without credentials is required")
            if parts.query or parts.fragment:
                raise ConfigError("Base URLs cannot contain query/fragment")
            if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ConfigError("HTTP public URLs are permitted only on loopback")
        if urlsplit(self.public_url).path not in ("", "/"):
            raise ConfigError("Gateway public URL must be an origin without a path")
        if not self.cookie_secure and urlsplit(self.public_url).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ConfigError("Insecure cookies are only permitted on loopback")
        if not self.cookie_secure and (self.cookie_name.startswith("__Host-") or self.login_cookie.startswith("__Host-")):
            raise ConfigError("__Host- cookies require Secure")
        if not 1 <= self.session_seconds <= 86400 or not 1 <= self.assertion_seconds <= 300:
            raise ConfigError("Invalid session/assertion lifetime")
        if not 1 <= self.idle_seconds <= 86400:
            raise ConfigError("Invalid session idle timeout")
        if not 0 <= self.touch_min_interval_seconds < self.idle_seconds:
            raise ConfigError("Session touch interval must be shorter than idle timeout")
        if not 1 <= self.login_seconds <= 600:
            raise ConfigError("Invalid login transaction lifetime")
        if not self.portal_audience or self.portal_audience in ("portal", "adapters"):
            raise ConfigError("Portal UI needs a dedicated audience")
        if self.oidc.redirect_uri != self.public_url.rstrip("/") + "/oidc/callback":
            raise ConfigError("OIDC callback must belong to the configured gateway")
        if self.oidc.post_logout_redirect_uri != self.public_url.rstrip("/") + "/":
            raise ConfigError("Logout return must belong to the configured gateway")

    @classmethod
    def from_env(cls):
        def secret(name):
            path = os.environ.get(name)
            if not path:
                raise ConfigError(f"{name} is required")
            value = Path(path).read_text().strip()
            if not value:
                raise ConfigError(f"{name} is empty")
            return value

        def boolean(name, default):
            value = os.environ.get(name, default).lower()
            if value not in ("true", "false"):
                raise ConfigError(f"{name} must be true/false")
            return value == "true"

        def optional_path(name):
            value = os.environ.get(name)
            return Path(value) if value else None

        public = os.environ.get("GW_PUBLIC_URL", "https://gateway.invalid").rstrip("/")
        secure = boolean("GW_COOKIE_SECURE", "true")
        return cls(
            public_url=public,
            oidc=OidcConfig(
                issuer=os.environ["GW_OIDC_ISSUER"].rstrip("/"),
                discovery_url=os.environ.get("GW_OIDC_DISCOVERY_URL"),
                client_id=os.environ.get("GW_OIDC_CLIENT_ID", "portal"),
                client_secret=secret("GW_OIDC_CLIENT_SECRET_FILE"),
                redirect_uri=public + "/oidc/callback",
                post_logout_redirect_uri=public + "/",
                id_token_algs=tuple(os.environ.get("GW_OIDC_ID_TOKEN_ALGS", "RS256,ES256").split(",")),
                clock_leeway_seconds=int(os.environ.get("GW_OIDC_CLOCK_LEEWAY_SECONDS", "60")),
            ),
            signing_key=Path(os.environ["GW_SIGNING_KEY_FILE"]),
            redis_url=os.environ.get("GW_REDIS_URL", "redis://redis:6379/0"),
            session_seconds=int(os.environ.get("GW_SESSION_SECONDS", "300")),
            idle_seconds=int(os.environ.get("GW_SESSION_IDLE_SECONDS", "300")),
            touch_min_interval_seconds=int(os.environ.get("GW_SESSION_TOUCH_SECONDS", "60")),
            login_seconds=int(os.environ.get("GW_LOGIN_SECONDS", "600")),
            assertion_seconds=int(os.environ.get("GW_ASSERTION_SECONDS", "60")),
            cookie_secure=secure,
            cookie_name="__Host-hka_gateway_sid" if secure else "hka_gateway_sid",
            login_cookie="__Host-hka_gateway_login" if secure else "hka_gateway_login",
            portal_audience=os.environ.get("GW_PORTAL_AUDIENCE", "hka-portal-ui"),
            demo_enabled=boolean("GW_DEMO_ENABLED", "false"),
            roles_file=optional_path("GW_ROLES_FILE"),
            grants_file=optional_path("GW_GRANTS_FILE"),
            role_vocabulary=tuple(r.strip() for r in os.environ.get("GW_ROLE_VOCABULARY", "").split(",") if r.strip()),
            assertion_issuer=os.environ.get("GW_ASSERTION_ISSUER"),
            signing_key_next=optional_path("GW_SIGNING_KEY_NEXT_FILE"),
            signing_key_previous=optional_path("GW_SIGNING_KEY_PREVIOUS_FILE"),
            apps=AppsConfig(os.environ["GW_APP_UPSTREAM"]) if os.environ.get("GW_APP_UPSTREAM") else None,
            portal_upstream=os.environ.get("GW_PORTAL_UPSTREAM"),
            internal_hosts=tuple(h.strip() for h in os.environ.get("GW_INTERNAL_HOSTS", "").split(",") if h.strip()),
            registry_url=os.environ.get("GW_REGISTRY_URL"),
            registry_token_file=optional_path("GW_REGISTRY_SERVICE_TOKEN_FILE"),
        )
