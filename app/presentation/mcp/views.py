# app/presentation/mcp/views.py
# ============================================================================
# OAuth HTML Views
#
# Renders escaped login and error pages without exposing OAuth state beyond the
# opaque request identifier required by the authorization flow.
# ============================================================================

from __future__ import annotations

from html import escape

from app.presentation.mcp.messages import MESSAGES


class OAuthViews:
    def message(self, key: str, language: str) -> str:
        values = MESSAGES.get(key, MESSAGES["server_error"])
        return values.get(language, values["en"])

    def login_page(self, request_id: str, language: str, error_key: str | None = None) -> str:
        error = (
            f'<p role="alert">{escape(self.message(error_key, language))}</p>' if error_key else ""
        )
        return (
            f'<!doctype html><html lang="{escape(language)}"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{escape(self.message('title', language))}</title></head><body><main>"
            f"<h1>{escape(self.message('title', language))}</h1>"
            f"<p>{escape(self.message('shared_notice', language))}</p>{error}"
            '<form method="post" action="/mcp/oauth/authorize">'
            f'<input type="hidden" name="request_id" value="{escape(request_id)}">'
            f'<input type="hidden" name="language" value="{escape(language)}">'
            f"<label>{escape(self.message('login', language))}"
            '<input name="login" autocomplete="username" required></label>'
            f"<label>{escape(self.message('password', language))}"
            '<input type="password" name="password" autocomplete="current-password" required></label>'
            f'<button type="submit">{escape(self.message("authorize", language))}</button>'
            "</form></main></body></html>"
        )

    def error_page(self, error_key: str, language: str) -> str:
        return (
            f'<!doctype html><html lang="{escape(language)}"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{escape(self.message('title', language))}</title></head><body><main>"
            f"<h1>{escape(self.message('title', language))}</h1>"
            f'<p role="alert">{escape(self.message(error_key, language))}</p>'
            "</main></body></html>"
        )
