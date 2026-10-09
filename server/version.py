"""Product identity. One place for the name and version shown on screens, receipts and the licence check."""
PRODUCT = 'Al-Store'
PRODUCT_AR = 'الستور'
PRODUCT_ID = 'al-store'  # the id inside licence codes; never change it after the first code is issued
VERSION = '1.2.2'
SCHEMA = 3
DEVELOPER = 'Apps Factory'

import os
import sys

# True inside the compiled Windows program (Nuitka sets __compiled__; PyInstaller would set sys.frozen)
FROZEN = bool(getattr(sys, 'frozen', False)) or '__compiled__' in globals()
_HERE = os.path.dirname(os.path.abspath(__file__))
# where web/ and licence_keys.txt live: next to the program when compiled, one folder above server/ when run from source
ROOT = _HERE if FROZEN else os.path.dirname(_HERE)
