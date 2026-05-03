"""mosaico CLI entry — thin runner over the App declared in __init__.py."""
from . import app


def main() -> None:
    app.main()


if __name__ == "__main__":
    main()
