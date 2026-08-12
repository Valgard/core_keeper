"""Make the utils/ scripts importable from the tests in this directory.

The test modules live in utils/tests/ but import the scripts under test from
utils/ one level up. pytest only puts the test file's own directory on
sys.path, so add its parent (utils/) here, once, for every test in this
directory. Deliberately no list of the scripts covered: this file said
"new_mod, pixaki_to_sheet, prefab_query" for as long as it took the next
suite to be added without it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
