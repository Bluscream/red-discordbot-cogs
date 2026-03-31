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
from .utils.formatting import format_event, get_user_avatar, get_nickname

log = logging.getLogger("red.blu.tiktoklive.chat")

class TikTokChatHandler:
    def __init__(self, bot: Red, message_queue: asyncio.Queue):
        self.bot = bot
        self.message_queue = message_queue
        # Internal map for session cleanup
        self._on_stop_callback = None

    def setup_client(self, session: TikTokLiveSession, on_stop_callback):
        """Initializes the TikTokLiveClient and registers event listeners."""
        client = TikTokLiveClient(unique_id=f"@{session.username}")
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

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            log.info(f"✅ Connected to TikTok Live Chat for @{session.username} (Room ID: {client.room_id})")

        @client.on(JoinEvent)
        async def on_join(event: JoinEvent):
            try:
                can_embed = get_format_params(session.text_channel)
                nick = get_nickname(event)
                avatar = get_user_avatar(event)
                msg = format_event(event, "join", discord.Color.light_grey(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, nick, avatar))
            except Exception as e:
                log.error(f"Error in on_join for {session.username}: {e}")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            try:
                can_embed = get_format_params(session.text_channel)
                nick = get_nickname(event)
                avatar = get_user_avatar(event)
                msg = format_event(event, "comment", discord.Color.blue(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, nick, avatar))
            except Exception as e:
                log.error(f"Error in on_comment for {session.username}: {e}")

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            try:
                if event.repeat_end != 1:
                    return
                can_embed = get_format_params(session.text_channel)
                nick = get_nickname(event)
                avatar = get_user_avatar(event)
                msg = format_event(event, "gift", discord.Color.purple(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, nick, avatar))
            except Exception as e:
                log.error(f"Error in on_gift for {session.username}: {e}")

        @client.on(ShareEvent)
        async def on_share(event: ShareEvent):
            try:
                can_embed = get_format_params(session.text_channel)
                nick = get_nickname(event)
                avatar = get_user_avatar(event)
                msg = format_event(event, "share", discord.Color.gold(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, nick, avatar))
            except Exception as e:
                log.error(f"Error in on_share for {session.username}: {e}")

        @client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            try:
                can_embed = get_format_params(session.text_channel)
                nick = get_nickname(event)
                avatar = get_user_avatar(event)
                msg = format_event(event, "follow", discord.Color.teal(), can_embed, 
                                   streamer_name=session.username, is_webhook=is_webhook)
                await self.message_queue.put((session.text_channel, msg, nick, avatar))
            except Exception as e:
                log.error(f"Error in on_follow for {session.username}: {e}")

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            log.info(f"Stream ended for {session.username}")
            await self._on_stop_callback(session)

        self.bot.loop.create_task(client.start())

    async def stop_chat(self, session: TikTokLiveSession):
        """Disconnects the TikTokLiveClient."""
        if session.client:
            try:
                await session.client.disconnect()
                log.info(f"Disconnected TikTok client for {session.username}")
            except Exception as e:
                log.error(f"Error disconnecting TikTok client for {session.username}: {e}")
            session.client = None
