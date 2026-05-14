"""TelegramChannel — native Telegram Bot API adapter."""

from __future__ import annotations

import logging
import os
import textwrap
import threading
import time
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


_TELEGRAM_CREDS_FILENAME = "telegram.json"


def _credentials_path() -> str:
    """Path to the UI-managed Telegram credentials file."""
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    return str(DEFAULT_CONFIG_DIR / "connectors" / _TELEGRAM_CREDS_FILENAME)


def _load_token_from_credentials_file() -> str:
    """Read bot_token from the UI-managed credentials file, or ''."""
    import json
    from pathlib import Path

    p = Path(_credentials_path())
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("bot_token") or "")
    except Exception:
        return ""


def _load_allowed_chats_from_credentials_file() -> str:
    """Read allowed_chat_ids from the UI-managed credentials file, or ''."""
    import json
    from pathlib import Path

    p = Path(_credentials_path())
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("allowed_chat_ids") or "")
    except Exception:
        return ""


def save_credentials(bot_token: str, allowed_chat_ids: str = "") -> None:
    """Persist Telegram credentials so the UI can manage them.

    Mode 0o600 mirrors how OAuth tokens are stored elsewhere — the file
    contains a long-lived secret, so we restrict it to the owner.
    """
    import json
    import os as _os
    from pathlib import Path

    path = Path(_credentials_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"bot_token": bot_token}
    if allowed_chat_ids:
        payload["allowed_chat_ids"] = allowed_chat_ids
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        _os.chmod(path, 0o600)
    except OSError:
        pass


@ChannelRegistry.register("telegram")
class TelegramChannel(BaseChannel):
    """Native Telegram channel adapter using the Bot API.

    Parameters
    ----------
    bot_token:
        Telegram Bot API token.  Falls back to ``TELEGRAM_BOT_TOKEN`` env var.
    allowed_chat_ids:
        Comma-separated list of chat IDs allowed to interact.
    parse_mode:
        Message parse mode (``Markdown``, ``HTML``, etc.).
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "telegram"

    def __init__(
        self,
        bot_token: str = "",
        *,
        allowed_chat_ids: str = "",
        parse_mode: str = "Markdown",
        bus: Optional[EventBus] = None,
    ) -> None:
        # Resolution order:
        #   1. Explicit `bot_token` kwarg (e.g. from config.toml)
        #   2. TELEGRAM_BOT_TOKEN env var
        #   3. ~/.openjarvis/connectors/telegram.json (UI-managed)
        # The credentials file is the UI's storage — saved via
        # POST /v1/channels/telegram/config so the user never has to edit
        # config.toml just to set a token.
        self._token = (
            bot_token
            or os.environ.get("TELEGRAM_BOT_TOKEN", "")
            or _load_token_from_credentials_file()
        )
        self._allowed_chat_ids = allowed_chat_ids or _load_allowed_chats_from_credentials_file()
        self._parse_mode = parse_mode
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # -- connection lifecycle ---------------------------------------------------

    def connect(self) -> None:
        """Start listening for incoming messages via long polling."""
        if not self._token:
            logger.warning("No Telegram bot token configured")
            self._status = ChannelStatus.ERROR
            return

        self._stop_event.clear()
        self._status = ChannelStatus.CONNECTING

        self._listener_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
        )
        self._listener_thread.start()
        self._status = ChannelStatus.CONNECTED
        logger.info("Telegram channel connected (long polling)")

    def disconnect(self) -> None:
        """Stop the listener thread."""
        self._stop_event.set()
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=5.0)
            self._listener_thread = None
        self._status = ChannelStatus.DISCONNECTED

    # -- send / receive --------------------------------------------------------

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a Telegram chat via the Bot API."""
        if not self._token:
            logger.warning("Cannot send: no Telegram bot token")
            return False

        try:
            import httpx

            _TELEGRAM_MAX_LEN = 4096
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            chat_id = conversation_id or channel
            chunks = textwrap.wrap(
                content,
                width=_TELEGRAM_MAX_LEN,
                break_long_words=True,
                replace_whitespace=False,
            )
            for chunk in chunks:
                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": chunk,
                }
                if self._parse_mode:
                    payload["parse_mode"] = self._parse_mode

                resp = httpx.post(url, json=payload, timeout=10.0)
                if resp.status_code >= 300:
                    logger.warning(
                        "Telegram API returned status %d: %s",
                        resp.status_code,
                        resp.text,
                    )
                    return False
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("Telegram send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["telegram"]

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _poll_loop(self) -> None:
        """Long-poll for updates directly through the Telegram Bot API."""
        import httpx

        offset: int | None = None
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"

        while not self._stop_event.is_set():
            params: Dict[str, Any] = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            try:
                response = httpx.get(url, params=params, timeout=35.0)
                if response.status_code >= 300:
                    logger.warning(
                        "Telegram getUpdates returned status %d: %s",
                        response.status_code,
                        response.text,
                    )
                    self._status = ChannelStatus.ERROR
                    time.sleep(2.0)
                    continue

                payload = response.json()
                if not payload.get("ok", False):
                    logger.warning("Telegram getUpdates returned ok=false: %s", payload)
                    self._status = ChannelStatus.ERROR
                    time.sleep(2.0)
                    continue

                self._status = ChannelStatus.CONNECTED
                for update in payload.get("result", []):
                    update_id = int(update.get("update_id", 0))
                    if offset is None or update_id >= offset:
                        offset = update_id + 1
                    self._dispatch_update(update)
            except Exception:
                if self._stop_event.is_set():
                    break
                logger.debug("Telegram poll loop error", exc_info=True)
                self._status = ChannelStatus.ERROR
                time.sleep(2.0)

    def _dispatch_update(self, update: Dict[str, Any]) -> None:
        """Normalize a Telegram update and forward it to channel handlers."""
        msg = update.get("message") or update.get("edited_message")
        if not isinstance(msg, dict):
            return

        text = str(msg.get("text") or "")
        chat = msg.get("chat") or {}
        from_user = msg.get("from") or {}
        conversation_id = str(chat.get("id") or "").strip()
        if not conversation_id:
            return

        cm = ChannelMessage(
            channel="telegram",
            sender=str(from_user.get("id") or "").strip(),
            content=text,
            message_id=str(msg.get("message_id") or ""),
            conversation_id=conversation_id,
        )
        if self._allowed_chat_ids:
            allowed = {
                cid.strip() for cid in self._allowed_chat_ids.split(",") if cid.strip()
            }
            if cm.conversation_id not in allowed:
                logger.debug(
                    "Ignoring message from unlisted chat %s",
                    cm.conversation_id,
                )
                return

        for handler in self._handlers:
            try:
                handler(cm)
            except Exception:
                logger.exception("Telegram handler error")

        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {
                    "channel": cm.channel,
                    "sender": cm.sender,
                    "content": cm.content,
                    "message_id": cm.message_id,
                },
            )

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        """Publish a CHANNEL_MESSAGE_SENT event on the bus."""
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = [
    "TelegramChannel",
    "save_credentials",
    "_load_token_from_credentials_file",
    "_load_allowed_chats_from_credentials_file",
]
