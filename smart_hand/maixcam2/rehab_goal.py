"""Pure touch release-edge controller for rehabilitation repetition goals."""


class RepetitionGoalController:
    def __init__(self, options=(5, 10, 15), initial=5):
        if not options or any(type(value) is not int or value < 1 for value in options):
            raise ValueError("goal options must be positive integers")
        if len(set(options)) != len(options):
            raise ValueError("goal options must be unique")
        if initial not in options:
            raise ValueError("initial goal must be an option")
        self.options = tuple(options)
        self.index = self.options.index(initial)
        self.display_rect = None
        self.pressed_inside = False
        self.last_pressed = False

    @property
    def goal(self):
        return self.options[self.index]

    def set_display_rect(self, rect):
        self.display_rect = tuple(rect) if rect is not None else None

    def _inside(self, x, y):
        if self.display_rect is None:
            return False
        left, top, width, height = self.display_rect
        return left <= x < left + width and top <= y < top + height

    def update_touch(self, x, y, pressed, enabled):
        inside = self._inside(x, y)
        changed = False
        if pressed and not self.last_pressed:
            self.pressed_inside = bool(enabled and inside)
        elif not pressed and self.last_pressed:
            if enabled and inside and self.pressed_inside:
                self.index = (self.index + 1) % len(self.options)
                changed = True
            self.pressed_inside = False
        self.last_pressed = bool(pressed)
        return changed

    def status_line(self, enabled):
        return "GOAL {}{}".format(self.goal, "" if enabled else " LOCKED")
