import asyncio
from fastapi import FastAPI, Request
from telethon.sync import TelegramClient
from pydantic import BaseModel
from typing import List
import uvicorn
from fastapi import Depends, FastAPI
from starlette.applications import Starlette

app = FastAPI()

# Global variable for the TelegramForwarder instance
telegram_forwarder = None


class TelegramForwarder:
    def __init__(self, api_id, api_hash, phone_number):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone_number = phone_number
        self.client = TelegramClient('session_' + phone_number, api_id, api_hash)
        self.forwarding_task = None
        self.should_forward = False

    async def list_chats(self):
        await self.connect()
        dialogs = await self.client.get_dialogs()
        chats_info = [{'id': dialog.id, 'title': dialog.title} for dialog in dialogs]
        await self.disconnect()
        return chats_info

    async def connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone_number)
            await self.client.sign_in(self.phone_number, input('Enter the code: '))

    async def disconnect(self):
        await self.client.disconnect()

    async def forward_messages_to_channel(self, source_chat_id, destination_channel_id, keywords):
        self.should_forward = True
        try:
            last_message_id = (await self.client.get_messages(source_chat_id, limit=1))[0].id

            while self.should_forward:
                messages = await self.client.get_messages(source_chat_id, min_id=last_message_id, limit=None)

                for message in reversed(messages):
                    if keywords:
                        if message.text and any(keyword in message.text.lower() for keyword in keywords):
                            await self.client.send_message(destination_channel_id, message.text)
                    else:
                        await self.client.send_message(destination_channel_id, message.text)

                    last_message_id = max(last_message_id, message.id)

                await asyncio.sleep(5)
        except asyncio.CancelledError:
            # Handle task cancellation
            self.should_forward = False
            print("Message forwarding task cancelled")
        finally:
            # Ensure cleanup here if necessary
            await self.client.disconnect()
            pass

    async def start_forwarding(self, source_chat_id, destination_channel_id, keywords):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone_number)
            await self.client.sign_in(self.phone_number, input('Enter the code: '))
        self.forwarding_task = asyncio.create_task(
            self.forward_messages_to_channel(source_chat_id, destination_channel_id, keywords)
        )
        return 'done'

    async def stop_forwarding(self):
        self.should_forward = False
        if self.forwarding_task:
            self.forwarding_task.cancel()
            await self.forwarding_task


# Existing read_credentials function remains unchanged
def read_credentials():
    try:
        with open("credentials.txt", "r") as file:
            lines = file.readlines()
            api_id = lines[0].strip()
            api_hash = lines[1].strip()
            phone_number = lines[2].strip()
            return api_id, api_hash, phone_number
    except FileNotFoundError:
        print("Credentials file not found.")
        return None, None, None


def get_telegram_forwarder():
    api_id, api_hash, phone_number = read_credentials()
    return TelegramForwarder(api_id, api_hash, phone_number)


@app.on_event("startup")
async def startup_event():
    global telegram_forwarder
    api_id, api_hash, phone_number = read_credentials()
    telegram_forwarder = TelegramForwarder(api_id, api_hash, phone_number)


class ForwardMessagesRequest(BaseModel):
    source_chat_id: int
    destination_channel_id: int
    keywords: List[str]


@app.get('/list_chats')
async def handle_list_chats():
    api_id, api_hash, phone_number = read_credentials()
    forwarder = TelegramForwarder(api_id, api_hash, phone_number)
    chats_info = await forwarder.list_chats()
    return chats_info


@app.post('/start_forward_messages')
async def handle_start_forward_messages(request: ForwardMessagesRequest):
    # Extract parameters from the request
    source_chat_id = request.source_chat_id
    destination_channel_id = request.destination_channel_id
    keywords = request.keywords

    # Start forwarding messages
    await telegram_forwarder.start_forwarding(source_chat_id, destination_channel_id, keywords)
    return {"status": "success", "message": "Messages forwarding started"}


@app.post('/stop_forward_messages')
async def handle_stop_forward_messages():
    # Stop forwarding messages
    await telegram_forwarder.stop_forwarding()
    return {"status": "success", "message": "Messages forwarding stopped"}


def run_asyncio_task(task):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(task)
    loop.close()
    return result


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
