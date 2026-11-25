from datetime import datetime, timezone


class FakeRedis:
    def __init__(self, unavailable=False):
        self.values = {}
        self.cache = {}
        self.unavailable = unavailable

    def ping(self):
        if self.unavailable:
            raise ConnectionError("test Redis unavailable")
        return True

    def eval(self, script, _numkeys, key, window):
        if self.unavailable:
            raise ConnectionError("test Redis unavailable")
        count = self.values.get(key, 0) + 1
        self.values[key] = count
        if key.startswith("solvex:global-solves:"):
            now = datetime.now(timezone.utc)
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86400
            ttl = max(1, int(next_midnight - now.timestamp()))
        else:
            ttl = int(window)
        return [count, ttl]

    def get(self, key):
        if self.unavailable:
            raise ConnectionError("test Redis unavailable")
        return self.cache.get(key)

    def setex(self, key, seconds, value):
        if self.unavailable:
            raise ConnectionError("test Redis unavailable")
        self.cache[key] = value
        self.values[f"ttl:{key}"] = seconds
        return True
