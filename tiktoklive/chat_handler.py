import asyncio
import logging
from typing import Union, Optional, List, Type

import discord
from redbot.core.bot import Red
from TikTokLive import TikTokLiveClient
from TikTokLive.events import (
    CommentEvent, 
    ConnectEvent, 
    DisconnectEvent, 
    LiveEndEvent,
    JoinEvent,
    GiftEvent,
    ShareEvent,
    FollowEvent
)
from .session import TikTokLiveSession
from .utils.formatting import format_event, sanitize_mentions
from .utils.metadata import get_user_avatar, get_nickname, get_user_handle

log = logging.getLogger("red.blu.tiktoklive.chat")

class TikTokChatHandler:
    def __init__(self, bot: Red, message_queue: asyncio.Queue):
        self.bot = bot
        self.message_queue = message_queue
        # Internal map for session cleanup
        self._on_stop_callback = None
        self.seen_events = set()

    def setup_client(self, session: TikTokLiveSession, on_stop_callback, 
                     session_id: Optional[str] = None, tt_target_idc: Optional[str] = None):
        """Initializes the TikTokLiveClient and registers event listeners."""
        client = TikTokLiveClient(unique_id=f"@{session.username}")
        
        # Apply Session ID for authentication if available
        if session_id:
            try:
                # v6.6.5 requires tt_target_idc for authenticated actions like sending chat
                client.web.set_session(session_id, tt_target_idc)
                log.info(f"Authenticated session applied for @{session.username} (IDC: {tt_target_idc})")
            except Exception as e:
                log.error(f"Failed to set session ID for @{session.username}: {e}")
        
        session.client = client
        self._on_stop_callback = on_stop_callback
        is_webhook = isinstance(session.text_channel, str)

        def get_format_params(target: Union[int, str]):
            if isinstance(target, str): # Webhook
                return True
            channel = self.bot.get_channel(target)
            if channel and isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
                perms = channel.permissions_for(channel.guild.me)
                return perms.embed_links
            return False

        def log_first_event(event):
            import json
            ename = type(event).__name__
            if ename not in self.seen_events:
                try:
                    # Try raw message to_dict first (often more reliable in v6.6.5)
                    msg = getattr(event, "_message", None)
                    if msg and hasattr(msg, "to_dict"):
                        data = msg.to_dict()
                    else:
                        data = getattr(event, "to_dict", lambda: {"error": "no to_dict"})()
                    
                    min_json = json.dumps(data, separators=(',', ':'))
                    log.info(f"First {ename} dump: {min_json}")
                    self.seen_events.add(ename)
                except Exception as e:
                    # Fallback to simple dict if to_dict fails
                    try:
                        log.warning(f"to_dict failed for {ename}, using fallback: {e}")
                        data = {k: str(v) for k, v in vars(event).items() if not k.startswith('_')}
                        log.info(f"First {ename} fallback: {json.dumps(data)}")
                        self.seen_events.add(ename)
                    except:
                        log.error(f"Failed to dump {ename}: {e}")

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log.info(f"✅ Connected to TikTok Live Chat for @{session.username} (Room ID: {client.room_id})")
            log_first_event(event)

        @client.on(JoinEvent)
        async def on_join(event: JoinEvent):
            try:
                log_first_event(event)
                can_embed = get_format_params(session.text_channel)
                nick = sanitize_mentions(get_nickname(event))
                handle = sanitize_mentions(get_user_handle(event))
                display_name = f"{nick} (@{handle})" if handle != "unknown" else nick
                avatar = get_user_avatar(event)
                msg = format_event(event, "join", discord.Color.light_grey(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, display_name, avatar))
            except Exception as e:
                log.error(f"Error in on_join for {session.username}: {e}")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            try:
                log_first_event(event)
                can_embed = get_format_params(session.text_channel)
                nick = sanitize_mentions(get_nickname(event))
                handle = sanitize_mentions(get_user_handle(event))
                display_name = f"{nick} (@{handle})" if handle != "unknown" else nick
                avatar = get_user_avatar(event)
                msg = format_event(event, "comment", discord.Color.blue(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, display_name, avatar))
            except Exception as e:
                log.error(f"Error in on_comment for {session.username}: {e}")

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            try:
                log_first_event(event)
                if event.repeat_end != 1:
                    return
                can_embed = get_format_params(session.text_channel)
                nick = sanitize_mentions(get_nickname(event))
                handle = sanitize_mentions(get_user_handle(event))
                display_name = f"{nick} (@{handle})" if handle != "unknown" else nick
                avatar = get_user_avatar(event)
                msg = format_event(event, "gift", discord.Color.purple(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, display_name, avatar))
            except Exception as e:
                log.error(f"Error in on_gift for {session.username}: {e}")

        @client.on(ShareEvent)
        async def on_share(event: ShareEvent):
            try:
                log_first_event(event)
                can_embed = get_format_params(session.text_channel)
                nick = sanitize_mentions(get_nickname(event))
                handle = sanitize_mentions(get_user_handle(event))
                display_name = f"{nick} (@{handle})" if handle != "unknown" else nick
                avatar = get_user_avatar(event)
                msg = format_event(event, "share", discord.Color.gold(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, display_name, avatar))
            except Exception as e:
                log.error(f"Error in on_share for {session.username}: {e}")

        @client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            try:
                log_first_event(event)
                can_embed = get_format_params(session.text_channel)
                nick = sanitize_mentions(get_nickname(event))
                handle = sanitize_mentions(get_user_handle(event))
                display_name = f"{nick} (@{handle})" if handle != "unknown" else nick
                avatar = get_user_avatar(event)
                msg = format_event(event, "follow", discord.Color.teal(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, display_name, avatar))
            except Exception as e:
                log.error(f"Error in on_follow for {session.username}: {e}")

            log.info(f"Stream ended for {session.username}")
            await self._on_stop_callback(session)

        self.bot.loop.create_task(self._start_client_safely(client, session))

    async def _start_client_safely(self, client: TikTokLiveClient, session: TikTokLiveSession):
        """Starts the client and catches common startup errors (Offline/Not Found)."""
        from TikTokLive.client.errors import UserOfflineError, UserNotFoundError
        try:
            await client.start()
        except UserOfflineError:
            log.info(f"User @{session.username} is currently offline. Monitoring in background.")
        except UserNotFoundError:
            log.error(f"User @{session.username} was not found. Stopping monitor.")
            await self._on_stop_callback(session)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Unexpected error starting client for @{session.username}: {e}")

    async def send_room_chat(self, session: TikTokLiveSession, content: str):
        """Sends a message to the TikTok Live room chat. Requires session ID."""
        if not session.client:
            return
        
        # TikTok char limit is around 150-200, we'll cap at 180
        content = (content[:177] + '...') if len(content) > 180 else content
        
        try:
            # Note: TikTokLive client has send_room_chat in its web scope or direct
            # Based on docs it's client.send_room_chat()
            await session.client.send_room_chat(content)
            log.info(f"Sent message to @{session.username} TikTok chat: {content}")
        except Exception as e:
            log.error(f"Failed to send TikTok message for @{session.username}: {e}")

    async def stop_chat(self, session: TikTokLiveSession):
        """Disconnects the TikTokLiveClient."""
        if session.client:
            try:
                await session.client.disconnect()
                log.info(f"Disconnected TikTok client for {session.username}")
            except Exception as e:
                log.error(f"Error disconnecting TikTok client for {session.username}: {e}")
            session.client = None
