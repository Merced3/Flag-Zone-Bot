#print_discord_messages.py
from error_handler import error_log_and_discord_message
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
        print("Channel not found.")

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
            print(f"Message Does Not Exist!")
            #await error_log_and_discord_message(e, "print_discord_messages", "get_message_content", "An error occurred when trying to fetch the message content")
            return None
    else:
        print("Channel not found.")
        return None

async def print_discord(message1, message2=None, button_data=None, delete_last_message=None, show_print_statement=None):
    message_channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if message_channel is None:
        print(f"Error: Could not find a channel with ID {cred.DISCORD_CHANNEL_ID}.")
        print("Listing all channels:")
        for guild in bot.guilds:
            for channel in guild.channels:
                print(f"Channel ID: {channel.id}, Channel Name: {channel.name}")
        return

    message_channel_id = message_channel.id

    if message_channel_id:
        message_channel = bot.get_channel(message_channel_id)

    if delete_last_message:
        async for old_message in message_channel.history(limit=1):
            await old_message.delete()
        
    view = await create_view(button_data) if button_data else None

    sent_message = None  # initialize sent_message as None
    if message2:
        sent_message = await message_channel.send(content=message2, view=view) if button_data else await message_channel.send(message2)
    else:
        sent_message = await message_channel.send(content=message1, view=view) if button_data else await message_channel.send(message1)

    if message1 is None:
        print(f"This function was called from line {inspect.currentframe().f_back.f_lineno}")
    #else:
        #print(message1)
    
    return sent_message  # return the sent message

async def send_file_discord(file_path_to_image):
    channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if channel:
        with open(file_path_to_image, 'rb') as f:
            # Extract just the file name from the file path
            file_name = os.path.basename(file_path_to_image)
            # Create a discord.File object with only the file name
            image_file = discord.File(f, filename=file_name)
            # Send the file to the Discord channel
            await channel.send(file=image_file)
    else:
        print(f"Could not find channel with ID {cred.DISCORD_CHANNEL_ID}")