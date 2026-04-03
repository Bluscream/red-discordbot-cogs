import asyncio
from synchra import SynchraClient

async def main():
    try:
        client = SynchraClient(access_token="test")
        print(f"WS Client class: {type(client.ws)}")
        print(f"WS Client members: {dir(client.ws)}")
        await client.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
