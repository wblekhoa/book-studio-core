from __future__ import annotations

import unittest

from bookstudio.errors import BookStudioError


class ErrorContractTests(unittest.TestCase):
    def test_bookstudio_error_supports_standard_traceback_lifecycle(self) -> None:
        error = BookStudioError(
            code="SYNTHETIC_FAILURE",
            message="Synthetic failure.",
            next_action="Handle it.",
        )

        try:
            raise error
        except BookStudioError as caught:
            caught.__traceback__ = None

        self.assertEqual("[SYNTHETIC_FAILURE] Synthetic failure.", str(error))


if __name__ == "__main__":
    unittest.main()
