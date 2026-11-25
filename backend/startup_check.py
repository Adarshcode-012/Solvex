
import sys

from pydantic import ValidationError


try:
    import config  # noqa: F401  Import triggers Settings validation.
except ValidationError as exc:
    print("Startup configuration rejected:", file=sys.stderr)
    for error in exc.errors(include_input=False):
        print(error["msg"], file=sys.stderr)
    raise SystemExit(1) from None
