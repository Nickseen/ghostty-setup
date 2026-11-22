"""Drive a real tmux client on a private PTY; never touch the user's server."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import struct
import subprocess
import termios
import time
import unittest

BINARY = Path(__file__).parent / '.build/tmux-3.8/tmux'


class Client:
    def __init__(self, label):
        self.base = [str(BINARY), '-L', 'balanced-native-' + str(os.getpid()) + '-' + label, '-f', '/dev/null']
        self.pid = self.fd = None

    def run(self, *args):
        return subprocess.run(self.base + list(args), check=True, capture_output=True, text=True).stdout.strip()

    def pump(self, seconds=.025):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([self.fd], [], [], .002)[0]:
                try:
                    os.read(self.fd, 65536)
                except OSError:
                    break

    def start(self):
        self.pane = self.run('new-session', '-dP', '-F', '#{pane_id}', '-s', 'check', '-x', '122', '-y', '60', '/bin/sleep 90')
        self.run('set-option', '-g', 'status', 'off')
        self.run('set-option', '-g', 'mouse', 'on')
        self.run('bind-key', '-n', 'M-MouseDown1Border', 'select-pane', '-t', '=')
        self.run('bind-key', '-n', 'M-MouseDrag1Border', 'resize-pane', '-M')
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.pop('TMUX', None)
            os.environ['TERM'] = 'xterm-256color'
            os.execv(str(BINARY), self.base + ['attach-session', '-t', 'check'])
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 60, 122, 0, 0))
        self.pump(.25)

    def row(self, sizes, vertical=False):
        axis = 'v' if vertical else 'h'
        for _ in range(len(sizes) - 1):
            self.run('split-window', '-v' if vertical else '-h', '-t', self.pane, '/bin/sleep 90')
        self.run('select-layout', '-t', self.pane, 'even-vertical' if vertical else 'even-horizontal')
        layout = self.layout()
        root = layout['L']
        root['t'] = axis
        root['h' if vertical else 'w'] = sum(sizes) + len(sizes) - 1
        position = 0
        for child, size in zip(root['c'], sizes):
            child.update(x=0 if vertical else position, y=position if vertical else 0,
                         w=root['w'] if vertical else size, h=size if vertical else root['h'])
            position += size + 1
        self.run('select-layout', '-t', self.pane, json.dumps(layout, separators=(',', ':')))
        self.pump(.08)

    def layout(self):
        return json.loads(self.run('display-message', '-p', '-t', self.pane, '#{window_layout}'))

    def sizes(self, axis='w'):
        return [cell[axis] for cell in self.layout()['L']['c']]

    def down(self, x, y=5, option=False):
        self.button = 8 if option else 0
        self.x, self.y = x, y
        self.mouse(self.button, x, y)

    def mouse(self, button, x, y, release=False):
        os.write(self.fd, f'\x1b[<{button};{x+1};{y+1}{"m" if release else "M"}'.encode())
        self.pump()

    def move(self, dx=0, dy=0):
        self.last_x, self.last_y = self.x + dx, self.y + dy
        self.mouse(self.button + 32, self.last_x, self.last_y)

    def up(self):
        self.mouse(self.button, self.last_x, self.last_y, release=True)

    def close(self):
        subprocess.run(self.base + ['kill-server'], capture_output=True)
        if self.pid:
            os.close(self.fd)
            os.waitpid(self.pid, 0)


@contextmanager
def client(label):
    instance = Client(label)
    try:
        instance.start()
        yield instance
    finally:
        instance.close()


class NativeResizeTests(unittest.TestCase):
    def test_live_rounding_reversal_and_option(self):
        with client('live') as c:
            c.row([40, 30, 50])
            c.down(40)
            for delta in (1, 2, 3, 8, 10, 7, 0):
                c.move(dx=delta)
                self.assertEqual(c.sizes(), [40 + delta, 30 - (delta + 1) // 2, 50 - delta // 2])
            c.move(dx=-3)
            self.assertEqual(c.sizes(), [37, 32, 51])
            c.move(dx=0)
            self.assertEqual(c.sizes(), [40, 30, 50])
            c.move(dx=10)
            held = c.sizes()
            c.up()
            self.assertEqual(c.sizes(), held, 'A resize was delayed until mouse release')
            c.down(50, option=True)
            c.move(dx=6)
            self.assertEqual(c.sizes(), [56, 19, 45])
            c.up()

    def test_vertical_and_interior_border_follow_cursor(self):
        with client('vertical') as c:
            c.row([16, 18, 24], vertical=True)
            c.down(5, y=16)
            c.move(dy=6)
            self.assertEqual(c.sizes('h'), [22, 15, 21])
            c.move(dy=0)
            self.assertEqual(c.sizes('h'), [16, 18, 24])
            c.move(dy=-6)
            self.assertEqual(c.sizes('h'), [10, 21, 27])
            c.up()
        with client('middle') as c:
            c.row([40, 30, 50])
            c.down(71)
            c.move(dx=4)
            self.assertEqual(c.sizes(), [36, 38, 46])
            self.assertEqual(c.layout()['L']['c'][1]['x'] + c.sizes()[1], 75)
            c.move(dx=-4)
            self.assertEqual(c.sizes(), [44, 22, 54])
            c.up()

    def test_fixed_boundary_owner_grows_and_shrinks_with_equal_compensation(self):
        with client('fixed-owner-left') as c:
            c.row([40, 30, 50])
            # The active pane is deliberately unrelated to the dragged border.
            c.run('select-pane', '-t', c.layout()['L']['c'][-1]['I'])
            c.down(40)
            for delta in (-1, -5, -10, -12, -5, 0):
                c.move(dx=delta)
                released = -delta
                self.assertEqual(c.sizes(), [40 + delta, 30 + (released + 1) // 2, 50 + released // 2])
            c.move(dx=10)
            self.assertEqual(c.sizes(), [50, 25, 45])
            c.up()
        with client('fixed-owner-middle') as c:
            c.row([40, 30, 50])
            c.down(71)
            for delta in (1, 5, 12, 5, 0):
                c.move(dx=delta)
                self.assertEqual(c.sizes(), [40 - delta, 30 + delta * 2, 50 - delta])
            c.move(dx=-10)
            self.assertEqual(c.sizes(), [50, 10, 60])
            c.up()
        with client('fixed-owner-minimum') as c:
            c.row([3, 50, 67])
            c.down(3)
            c.move(dx=-3)
            self.assertEqual(c.sizes(), [1, 51, 68])
            c.up()

    def test_nested_groups_and_minimum_capacity(self):
        with client('nested') as c:
            c.row([40, 30, 50])
            third = c.layout()['L']['c'][-1]['I']
            c.run('split-window', '-v', '-t', third, '/bin/sleep 90')
            original = c.layout()
            heights = [node['h'] for node in original['L']['c'][-1]['c']]
            c.down(40)
            c.move(dx=10)
            current = c.layout()['L']['c']
            self.assertEqual([node['w'] for node in current], [50, 25, 45])
            self.assertEqual([node['w'] for node in current[-1]['c']], [45, 45])
            self.assertEqual([node['h'] for node in current[-1]['c']], heights)
            c.move(dx=0)
            self.assertEqual(c.sizes(), [40, 30, 50])
            c.up()
            c.down(71, y=heights[0])
            c.move(dy=4)
            self.assertEqual(c.sizes(), [40, 30, 50])
            self.assertEqual([node['h'] for node in c.layout()['L']['c'][-1]['c']],
                             [heights[0] + 4, heights[1] - 4])
            c.up()
            second = c.layout()['L']['c'][1]['I']
            c.run('split-window', '-h', '-t', second, '/bin/sleep 90')
            before = c.sizes()
            self.assertEqual(len(before), 4)
            c.down(before[0])
            c.move(dx=9)
            self.assertEqual(c.sizes(), [before[0] + 9] + [size - 3 for size in before[1:]])
            c.move(dx=-9)
            self.assertEqual(c.sizes(), [before[0] - 9] + [size + 3 for size in before[1:]])
            c.up()
        with client('minimum') as c:
            c.row([50, 3, 67])
            c.down(50)
            c.move(dx=20)
            self.assertEqual(c.sizes(), [70, 1, 49])
            c.move(dx=71)
            self.assertEqual(c.sizes(), [118, 1, 1])
            c.move(dx=0)
            self.assertEqual(c.sizes(), [50, 3, 67])
            c.up()

    def test_changes_during_drag_and_client_disconnect_are_safe(self):
        with client('topology') as c:
            c.row([40, 30, 50])
            c.down(40)
            c.move(dx=4)
            c.run('split-window', '-v', '-t', c.pane, '/bin/sleep 90')
            current = c.layout()
            c.move(dx=8)
            self.assertEqual(c.layout(), current)
            c.up()
            self.assertEqual(c.run('list-panes', '-F', '#{pane_id}').count('\n') + 1, 4)
        with client('disconnect') as c:
            c.row([40, 30, 50])
            c.down(40)
            c.move(dx=3)
            c.run('detach-client', '-t', c.run('list-clients', '-F', '#{client_name}'))
            self.assertEqual(c.sizes(), [43, 28, 49])

    def test_regular_mouse_selection_and_keyboard_resize(self):
        with client('selection') as c:
            c.row([40, 30, 50])
            code = 'import time; print("abcdef", flush=True); time.sleep(90)'
            c.run('respawn-pane', '-k', '-t', c.pane, shlex.join(['/usr/bin/python3', '-u', '-c', code]))
            c.pump(.15)
            position = c.run('display-message', '-p', '-t', c.pane, '#{pane_left},#{pane_top}')
            left, top = map(int, position.split(','))
            c.mouse(0, left, top)
            c.mouse(32, left + 4, top)
            c.mouse(0, left + 4, top, release=True)
            self.assertTrue(c.run('show-buffer').startswith('abc'))
            c.run('resize-pane', '-t', c.pane, '-x', '45')
            self.assertEqual(c.sizes(), [45, 25, 50])


if __name__ == '__main__':
    unittest.main()
