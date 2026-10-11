"""Neutral completion/authority fixture with an explicit protected-path control."""


class Worker:
    def __init__(self, protected=False):
        self.epoch = 0
        self.next_id = 0
        self.pending = set()
        self.finished = set()
        self.reported = set()
        self.protected = protected

    def begin(self):
        ticket = (self.epoch, self.next_id)
        self.next_id += 1
        self.pending.add(ticket)
        return ticket

    def finish(self, ticket):
        if ticket in self.pending:
            self.finished.add(ticket)

    def report(self, ticket):
        if ticket in self.pending:
            self.reported.add(ticket)

    def advance(self):
        self.epoch += 1
        self.pending.clear()
        self.reported.clear()
        self.finished.clear()

    def allowed(self, ticket):
        basis = self.finished if self.protected else self.reported
        return ticket[0] == self.epoch and ticket in basis


class RetryQueue:
    """Ticks supply normal service; the reset branch loses intermediate progress."""
    def __init__(self, reset_on_retry=False):
        self.reset_on_retry = reset_on_retry
        self.phase = self.completed = 0
        self.pending = False

    def enqueue(self):
        self.pending = True

    def tick(self):
        if not self.pending:
            return
        if self.phase == 0:
            self.phase = 1
        elif self.reset_on_retry:
            self.phase = 0
        else:
            self.completed += 1
            self.pending = False
