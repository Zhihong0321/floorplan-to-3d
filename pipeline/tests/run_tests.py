#!/usr/bin/env python3
"""Run the whole regression suite (no network, no real projects touched):  python3 pipeline/tests/run_tests.py"""
import os
import sys
import unittest

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
suite = unittest.defaultTestLoader.discover(here, pattern="test_*.py")
res = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
