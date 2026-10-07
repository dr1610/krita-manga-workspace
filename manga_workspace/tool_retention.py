"""One-shot restoration of a tool lost during a layer operation."""
BRUSH = 'KritaShape/KisToolBrush'


class ToolRetention:
    def __init__(self):
        self.reset()

    def reset(self):
        self.node = None
        self.tool = ''
        self.saved = ''
        self.deadline = 0

    def layer_operation(self, tool, now):
        self.saved = tool if tool and tool != BRUSH else ''
        self.deadline = now + 1.0

    def explicit_choice(self):
        self.reset()

    def observe(self, node, tool, now):
        restore = ''
        previous = self.saved if now <= self.deadline else ''
        if not previous and self.node is not None and node != self.node:
            previous = self.tool
        if tool == BRUSH and previous and previous != BRUSH:
            restore = previous
            self.saved = ''
            self.deadline = 0
        self.node, self.tool = node, tool
        return restore
