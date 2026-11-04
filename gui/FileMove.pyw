# -*- coding: utf-8 -*-
"""Windows でダブルクリックして FileMove の画面を開くためのファイル（.pyw なので黒い画面は出ない）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # migrate_files と gui を読めるようにする

from gui.app import main  # noqa: E402

main()
