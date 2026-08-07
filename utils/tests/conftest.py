"""Make the utils/ scripts importable from the tests in this directory.

The test modules live in utils/tests/ but import the scripts under test
(new_mod, pixaki_to_sheet, prefab_query) from utils/. pytest only
puts the test file's own directory on sys.path, so add its parent (utils/) here,
once, for every test in this directory.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
