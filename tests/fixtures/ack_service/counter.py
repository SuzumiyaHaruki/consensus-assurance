"""Synthetic contract fixture; intentionally returns before durable completion."""

def execute(mode, emit):
    state = {'accepted': False, 'persisted': False, 'returned': False}
    def observe(event):
        emit({'event': event, 'operation': 'op-1', 'participant': 'node-1',
              'context': 1, 'metadata': {'mode': mode, 'fault': 'none'}, 'state': dict(state)})
    observe('initial')
    state['accepted'] = True
    observe('accepted')
    state['returned'] = True
    observe('returned')
    state['persisted'] = True
    observe('persisted')

if __name__ == '__main__':
    execute('memory', lambda event: None)
