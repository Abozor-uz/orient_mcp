# app/presentation/mcp/tool_views.py
# ============================================================================
# Tool Message Views
#
# Keeps protocol handlers independent of localized message storage.
# ============================================================================

from app.presentation.mcp.tool_messages import MESSAGES


class ToolViews:
    def text(self, key: str, language: str = "en") -> str:
        return MESSAGES[key].get(language, MESSAGES[key]["en"])
