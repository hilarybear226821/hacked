
# Log Streaming Implementation
# We need to hook the TeeLogger to push to websockets.

LOG_SUBSCRIBERS = set()
LOG_LOCK = threading.Lock()

def broadcast_log(message):
    with LOG_LOCK:
        dead = set()
        for ws in LOG_SUBSCRIBERS:
            try:
                ws.send(json.dumps({"log": f"[{time.strftime('%H:%M:%S')}] {message.strip()}"}))
            except:
                dead.add(ws)
        for d in dead:
            LOG_SUBSCRIBERS.discard(d)

class TeeLogger:
    def __init__(self, stream):
        self.stream = stream
        
    def write(self, message):
        self.stream.write(message)
        self.stream.flush()
        if message.strip():
             ts_msg = f"[{time.strftime('%H:%M:%S')}] {message.strip()}"
             LOG_BUFFER.append(ts_msg)
             # Broadcast to websockets
             try:
                 broadcast_log(message)
             except:
                 pass

    def flush(self):
        self.stream.flush()
