import unittest

from ak_common.util.common import get_timestamp_seconds


class UtilTest(unittest.TestCase):
    def test_timestamp_seconds(self):
        seconds = get_timestamp_seconds()
        self.assertTrue(isinstance(seconds, int))  # verify seconds is an integer
