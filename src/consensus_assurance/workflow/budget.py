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


def can_start_episode(state,kind):
    remaining=state.config.get('budget',{}).get('agent_calls',0)-state.usage.get('agent_calls',0)
    started=any(c.status=='active' for c in state.question_candidates) if kind=='candidate' else any(t.id==state.active_inquiry_id and t.admitted for t in state.inquiry_tasks)
    return remaining >= (1 if started else 2)
