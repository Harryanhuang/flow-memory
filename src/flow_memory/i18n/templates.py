"""i18n templates for Flow Memory.

Hosts can register new locales via `register_template()` and switch the
active locale via `set_locale()`. Default locale is English.
"""
from __future__ import annotations


_DEFAULT_LOCALE = "en"

_templates: dict[str, dict[str, str]] = {
    "en": {
        "packet.user_preferences_header": "## User Preferences",
        "packet.curated_core_header": "### 📌 Curated Core (pinned)",
        "packet.relevant_memories_header": "### Relevant Memories (decayed)",
        "packet.active_constraints_header": "## Active Constraints",
        "packet.relevant_confirmed_header": "## Relevant Confirmed Memories",
        "promotion.unauthorized": "Reviewer {reviewer} not authorized to promote high-impact kind {kind}",
        "promotion.not_found": "Candidate not found: {candidate_id}",
        "audit.sensitive_unlock_failed": "Failed unlock attempt",
        "audit.sensitive_unlocked": "Sensitive storage unlocked (expires in {expires_in}s)",
        "audit.sensitive_locked": "Sensitive storage locked",
        "obsidian.readme": "# Sensitive Data Export\n\nThis folder contains encrypted sensitive memories.\n",
    },
    "zh": {
        "packet.user_preferences_header": "## 用户偏好",
        "packet.curated_core_header": "### 📌 精选核心（已固定）",
        "packet.relevant_memories_header": "### 相关记忆（已衰减）",
        "packet.active_constraints_header": "## 活跃约束",
        "packet.relevant_confirmed_header": "## 相关已确认记忆",
        "promotion.unauthorized": "审核者 {reviewer} 无权提升高影响类型 {kind}",
        "promotion.not_found": "候选不存在: {candidate_id}",
        "audit.sensitive_unlock_failed": "敏感存储解锁失败",
        "audit.sensitive_unlocked": "敏感存储已解锁（{expires_in} 秒后过期）",
        "audit.sensitive_locked": "敏感存储已锁定",
        "obsidian.readme": "# 敏感数据导出\n\n此文件夹包含加密的敏感记忆。\n",
    },
}


_current_locale: str = _DEFAULT_LOCALE


def get_template(key: str, **kwargs) -> str:
    """Get a translated template string by key, format with kwargs.

    Falls back to English if the key doesn't exist in the current locale.
    """
    template = _templates.get(_current_locale, {}).get(key) or _templates["en"].get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def set_locale(locale: str) -> None:
    """Switch the active locale (e.g. 'en', 'zh')."""
    global _current_locale
    _current_locale = locale


def get_locale() -> str:
    """Return the current locale."""
    return _current_locale


def register_template(key: str, value: str, locale: str | None = None) -> None:
    """Register a custom template string."""
    target_locale = locale or _current_locale
    _templates.setdefault(target_locale, {})[key] = value