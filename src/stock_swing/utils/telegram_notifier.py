#!/usr/bin/env python3
"""Telegram notification utility for stock_swing.

Sends messages to a configured Telegram chat via Bot API.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class TelegramNotifier:
    """Simple Telegram Bot API wrapper for sending notifications."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """Initialize notifier with bot token and chat ID.

        Args:
            bot_token: Telegram Bot API token (defaults to TELEGRAM_BOT_TOKEN env var)
            chat_id: Telegram chat ID to send messages to (defaults to TELEGRAM_CHAT_ID env var)
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.bot_token and self.chat_id)

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """Send a text message to the configured chat.

        Args:
            text: Message text (supports HTML or Markdown based on parse_mode)
            parse_mode: "HTML" or "Markdown" (default: HTML)
            disable_notification: If True, sends silently

        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.enabled:
            print("[WARN] Telegram not configured (missing bot_token or chat_id)")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }

        try:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return True
                else:
                    print(f"[ERROR] Telegram API returned {response.status}")
                    return False
        except urllib.error.HTTPError as e:
            print(f"[ERROR] Telegram HTTP error: {e.code} {e.reason}")
            return False
        except urllib.error.URLError as e:
            print(f"[ERROR] Telegram network error: {e.reason}")
            return False
        except Exception as e:
            print(f"[ERROR] Telegram send failed: {e}")
            return False

    def send_markdown(self, text: str, silent: bool = False) -> bool:
        """Send a message with Markdown formatting.

        Args:
            text: Message text with Markdown formatting
            silent: If True, sends without notification sound

        Returns:
            True if sent successfully
        """
        return self.send_message(text, parse_mode="Markdown", disable_notification=silent)

    def send_html(self, text: str, silent: bool = False) -> bool:
        """Send a message with HTML formatting.

        Args:
            text: Message text with HTML formatting
            silent: If True, sends without notification sound

        Returns:
            True if sent successfully
        """
        return self.send_message(text, parse_mode="HTML", disable_notification=silent)


def send_notification(text: str, silent: bool = False) -> bool:
    """Convenience function to send a Telegram notification.

    Args:
        text: Message text
        silent: If True, sends without notification sound

    Returns:
        True if sent successfully

    Example:
        >>> send_notification("✅ Paper demo completed: 3 signals, 2 orders submitted")
    """
    notifier = TelegramNotifier()
    return notifier.send_html(text, silent=silent)
