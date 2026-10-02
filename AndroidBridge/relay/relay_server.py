import asyncio, json, os, time, hmac, hashlib, base64
from websockets.asyncio.server import serve

PORT = int(os.environ.get('PORT','8765'))
# JSON object: {"DEVICE_ID":"pairing-secret"}
PAIRINGS = json.loads(os.environ.get('ANDROIDBRIDGE_PAIRINGS','{}'))
phones, pcs = {}, {}

def b64url(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def verify(role, device, ts, nonce, sig):
    secret = PAIRINGS.get(device)
    if not secret: return False
    try:
        if abs(int(time.time()) - int(ts)) > 120: return False
    except: return False
    data = f'{device}|{ts}|{nonce}'.encode()
    expected = b64url(hmac.new(secret.encode(), data, hashlib.sha256).digest())
    return hmac.compare_digest(expected, sig.rstrip('='))

async def handler(ws):
    role=device=None
    try:
        first = await asyncio.wait_for(ws.recv(), 10)
        if not isinstance(first,str): return await ws.close(1008,'auth required')
        p=first.split('|')
        if len(p)!=6 or p[0]!='AUTH' or p[1] not in ('PHONE','PC'):
            return await ws.close(1008,'bad auth')
        role,device,ts,nonce,sig=p[1],p[2],p[3],p[4],p[5]
        # tolerate legacy 6-field AUTH produced by current Android client
        if len(p)==7: sig=p[5]
        if not verify(role,device,ts,nonce,sig):
            return await ws.close(1008,'auth failed')
        table = phones if role=='PHONE' else pcs
        old=table.get(device)
        if old and old is not ws:
            try: await old.close(1000,'replaced')
            except: pass
        table[device]=ws
        await ws.send(f'AUTH_OK|{role}|{device}')
        async for msg in ws:
            target = pcs.get(device) if role=='PHONE' else phones.get(device)
            if target:
                await target.send(msg)
    finally:
        table = phones if role=='PHONE' else pcs
        if device and table.get(device) is ws: table.pop(device,None)

async def main():
    print(f'AndroidBridge relay :{PORT}; configured devices={len(PAIRINGS)}')
    async with serve(handler,'0.0.0.0',PORT,max_size=30*1024*1024,ping_interval=20,ping_timeout=20):
        await asyncio.Future()
asyncio.run(main())
