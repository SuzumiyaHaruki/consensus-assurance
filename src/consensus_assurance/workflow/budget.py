import time


class BudgetExhausted(RuntimeError):
    pass


class BudgetTracker:
    def __init__(self, limits, state):
        self.limits = limits
        self.state = state
        self.started = time.monotonic()
        self.previous = state.elapsed_seconds

    def sync(self):
        self.state.elapsed_seconds = self.previous + time.monotonic() - self.started

    def remaining(self):
        self.sync()
        return max(0, self.limits.total_seconds - self.state.elapsed_seconds)

    def take(self, resource):
        if self.remaining() <= 0 or self.state.usage.get(resource, 0) >= getattr(self.limits, resource):
            raise BudgetExhausted("Budget exhausted: " + resource)
        self.state.usage[resource] = self.state.usage.get(resource, 0) + 1

    def timeout(self):
        remaining = self.remaining()
        if remaining <= 0:
            raise BudgetExhausted("Total runtime budget exhausted")
        return min(remaining, self.limits.action_timeout)
