#print_discord_messages.py
from error_handler import error_log_and_discord_message, print_log
import asyncio
import os
import cred
import discord
from discord.ext import commands
from discord.ui import View, Button
import inspect

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

class MyView(View):
    def __init__(self, button_data):
        super().__init__(timeout=None)
        for data in button_data:
            self.add_item(Button(style=data["style"], label=data["label"], custom_id=data["custom_id"]))

async def create_view(button_data):
    view = MyView(button_data)
    return view

async def edit_discord_message(message_id, new_content, delete_last_message=None, file_path=None):
    channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if channel:
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(content=new_content)
            if file_path:
                await send_file_discord(file_path)
        except Exception as e:
            await error_log_and_discord_message(e, "print_discord_messages", "edit_discord_message", "An error occurred when trying to edit the message")
        if delete_last_message:
            async for old_message in channel.history(limit=1):
                await old_message.delete()
    else:
        print_log("Channel not found.")

async def get_message_content(message_id, line=None):
    channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if channel:
        #print(f"Attempting to fetch message from Channel ID: {cred.DISCORD_CHANNEL_ID}, Message ID: {message_id}")
        #if line:
            #print(f"Line: {line}")
        try:
            message = await channel.fetch_message(message_id)
            #print(f"Got Message!")
            return message.content  # Return the message content
        except Exception as e:
            print_log(f"Message Does Not Exist!")
            #await error_log_and_discord_message(e, "print_discord_messages", "get_message_content", "An error occurred when trying to fetch the message content")
            return None
    else:
        print_log("Channel not found.")
        return None

async def print_discord(message1, message2=None, button_data=None, delete_last_message=None, show_print_statement=None, retries=3, backoff_factor=1):
    message_channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if message_channel is None:
        print_log(f"Error: Could not find a channel with ID {cred.DISCORD_CHANNEL_ID}.")
        return

    if delete_last_message:
        async for old_message in message_channel.history(limit=1):
            try:
                await old_message.delete()
            except discord.NotFound:
                print_log("Previous message not found for deletion.")
            except discord.HTTPException as e:
                print_log(f"Failed to delete previous message due to an HTTP error: {str(e)}")

    view = await create_view(button_data) if button_data else None

    for attempt in range(retries):
        try:
            if message2:
                sent_message = await message_channel.send(content=message2, view=view) if button_data else await message_channel.send(message2)
            else:
                sent_message = await message_channel.send(content=message1, view=view) if button_data else await message_channel.send(message1)
            return sent_message
        except (discord.HTTPException, discord.NotFound) as e:
            print_log(f"Discord API error on attempt {attempt+1}: {str(e)}")
            if attempt < retries - 1:  # If it's not the last attempt, wait before retrying
                await asyncio.sleep(backoff_factor * (2 ** attempt))
    print_log("Failed to send message after retries.")
    return None

async def send_file_discord(file_path,  retries=3, backoff_factor=1):
    channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if channel is None:
        print_log(f"Could not find channel with ID {cred.DISCORD_CHANNEL_ID}")
        return
    
    for attempt in range(retries):
        try:
            with open(file_path, 'rb') as f:
                file_name = os.path.basename(file_path)
                image_file = discord.File(f, filename=file_name)
                await channel.send(file=image_file)
                return
        except (discord.HTTPException, discord.NotFound) as e:
            print_log(f"Discord API error on attempt {attempt+1}: {str(e)}")
            if attempt < retries - 1:  # If it's not the last attempt, wait before retrying
                await asyncio.sleep(backoff_factor * (2 ** attempt))
    print_log("Failed to send file after retries.")