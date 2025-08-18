import unittest

from ak import Runtime


class AgentKernelCoreTest(unittest.TestCase):
    def test_something(self):
        runtime = Runtime()
        self.assertEqual(True, True)
