# app/presentation/mcp/messages.py
# ============================================================================
# Localized OAuth Messages
#
# Centralized RU, UZ, and EN text for the shared Orient MCP login flow.
# ============================================================================

MESSAGES: dict[str, dict[str, str]] = {
    "title": {
        "ru": "Подключение Orient MCP",
        "uz": "Orient MCP ulanishi",
        "en": "Connect Orient MCP",
    },
    "shared_notice": {
        "ru": "Это общее read-only подключение рабочего агента к Orient.",
        "uz": "Bu ishchi agentning Orient tizimiga umumiy faqat o‘qish ulanishidir.",
        "en": "This is a shared read-only agent connection to Orient.",
    },
    "login": {"ru": "Логин", "uz": "Login", "en": "Login"},
    "password": {"ru": "Пароль", "uz": "Parol", "en": "Password"},
    "authorize": {"ru": "Подключить", "uz": "Ulash", "en": "Authorize"},
    "invalid_credentials": {
        "ru": "Не удалось авторизовать подключение.",
        "uz": "Ulanishni avtorizatsiya qilib bo‘lmadi.",
        "en": "The connection could not be authorized.",
    },
    "invalid_client": {
        "ru": "OAuth-клиент недействителен.",
        "uz": "OAuth mijozi yaroqsiz.",
        "en": "The OAuth client is invalid.",
    },
    "invalid_scope": {
        "ru": "Запрошен недопустимый доступ.",
        "uz": "Noto‘g‘ri ruxsat so‘ralgan.",
        "en": "An invalid scope was requested.",
    },
    "invalid_resource": {
        "ru": "Неверный MCP resource.",
        "uz": "MCP resource noto‘g‘ri.",
        "en": "The MCP resource is invalid.",
    },
    "invalid_redirect_uri": {
        "ru": "Неверный redirect URI.",
        "uz": "Redirect URI noto‘g‘ri.",
        "en": "The redirect URI is invalid.",
    },
    "invalid_client_metadata": {
        "ru": "Некорректные данные клиента.",
        "uz": "Mijoz ma’lumotlari noto‘g‘ri.",
        "en": "Client metadata is invalid.",
    },
    "unsupported_grant": {
        "ru": "OAuth grant не поддерживается.",
        "uz": "OAuth grant qo‘llab-quvvatlanmaydi.",
        "en": "The OAuth grant is unsupported.",
    },
    "invalid_authorization_request": {
        "ru": "Некорректный запрос авторизации.",
        "uz": "Avtorizatsiya so‘rovi noto‘g‘ri.",
        "en": "The authorization request is invalid.",
    },
    "authorization_request_expired": {
        "ru": "Запрос авторизации истёк.",
        "uz": "Avtorizatsiya so‘rovi muddati tugadi.",
        "en": "The authorization request expired.",
    },
    "invalid_grant": {
        "ru": "OAuth grant недействителен.",
        "uz": "OAuth grant yaroqsiz.",
        "en": "The OAuth grant is invalid.",
    },
    "too_many_attempts": {
        "ru": "Слишком много попыток. Повторите позже.",
        "uz": "Urinishlar juda ko‘p. Keyinroq qayta urining.",
        "en": "Too many attempts. Please try again later.",
    },
    "server_error": {
        "ru": "Внутренняя ошибка OAuth.",
        "uz": "OAuth ichki xatosi.",
        "en": "Internal OAuth error.",
    },
}
