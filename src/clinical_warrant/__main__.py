"""Allow running the package with ``python -m clinical_warrant``."""

from clinical_warrant.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
