# cli.py
import asyncio

# Dummy async handler
async def do_work(cmd: str) -> str:
    await asyncio.sleep(0.1)  # simulate async I/O
    if cmd == "hello":
        return "Hello there!"
    elif cmd == "help":
        return "Available commands: hello, help, exit"
    elif cmd == "exit":
        return "Goodbye!"
    else:
        return f"Unknown command: {cmd}"

async def main():
    print("Welcome to My CLI! Type 'help' for commands.", flush=True)

    while True:
        # async input using a thread (since input() is blocking)
        cmd = await asyncio.to_thread(input, "> ")
        cmd = cmd.strip().lower()

        result = await do_work(cmd)
        print(result, flush=True)

        if cmd == "exit":
            break

if __name__ == "__main__":
    asyncio.run(main())
