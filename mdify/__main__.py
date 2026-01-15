"""Allow running mdify as a module: python -m mdify"""

import sys
from mdify.cli import main

if __name__ == "__main__":
    sys.exit(main())
