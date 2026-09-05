import os
import sys

os.environ.setdefault("GSK_RENDERER", "gl")  # suppress ngl→gl rename warning

import logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)

from elk.app import ElkApp

if __name__ == "__main__":
    logging.getLogger("elk").debug("main: starting ElkApp.run()")
    rc = ElkApp().run(sys.argv)
    logging.getLogger("elk").debug("main: run() returned %s", rc)
    sys.exit(rc)
