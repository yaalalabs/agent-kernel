import asyncio
import contextvars

id: contextvars.ContextVar["id"] = contextvars.ContextVar("id", default=0)

async def f(v):
    v1 = id.get()
    t = id.set(v)
    v2 = id.get()
    if v < 10:
        asyncio.create_task(f(v+10))
        await asyncio.sleep(1)
    id.reset(t)
    v3 = id.get()
    print(f"f{v}: {v1}, {v2}, {v3}")

async def main():
    await asyncio.gather(f(1), f(2), f(3))

if __name__ == "__main__":
    asyncio.run(main())
