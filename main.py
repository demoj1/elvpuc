import os
import sys

os.environ.setdefault("GSK_RENDERER", "gl")  # suppress ngl→gl rename warning

from elk.app import ElkApp

if __name__ == "__main__":
    ElkApp().run(sys.argv)
