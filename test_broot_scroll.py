"""Trackpad bursts through the full personal Broot proxy must not block keys."""
import os
import unittest
from unittest.mock import patch
from check_broot_scroll import measure


class ScrollTests(unittest.TestCase):
    def test_large_scroll_burst_and_reversal_keep_keyboard_responsive(self):
        with patch.dict(os.environ, {'BROOT_SCROLL_PROXY': '1'}):
            elapsed = measure(count=2000)
        self.assertLess(elapsed, 2, 'Scroll input accumulated ahead of the next keyboard action')


if __name__ == '__main__':
    unittest.main()
