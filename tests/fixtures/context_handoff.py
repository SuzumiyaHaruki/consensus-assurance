"""Synthetic object-owned callback; the negative variant deliberately loses ownership."""
class Contexts:
    def __init__(self):
        self.objects = {1: {'identity': 1}, 2: {'identity': 2}}
        self.current = self.objects[1]
        self.pending_owner = None
        self.completed_on = 0
        self.phase = 0

    def start(self):
        self.pending_owner = self.current
        self.phase = 1

    def switch(self):
        self.current = self.objects[2]
        self.phase = 2

    def complete(self, isolated):
        target = self.pending_owner if isolated else self.current
        self.completed_on = target['identity']
        self.phase = 3
