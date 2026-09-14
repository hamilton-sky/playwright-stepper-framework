"""
Entry point for ``python -m stepper``.

Equivalent to ``python stepper/main.py`` and to the installed ``stepper``
console script — all three land in the same ``main()``.
"""
from stepper.main import main

if __name__ == "__main__":
    main()
