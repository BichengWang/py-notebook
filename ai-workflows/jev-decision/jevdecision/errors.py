"""Exceptions raised by the decision model."""


from __future__ import annotations

from typing import Any
class DecisionError(Exception):
    """Base class for every error this package raises."""


class QuestionError(DecisionError, ValueError):
    """A question or question set is invalid; raised before any request is sent."""


class ResponseError(DecisionError):
    """A provider response does not match the questions that were asked."""


    response: Any = None
    response_received: bool = False


class APIError(DecisionError):
    """The provider returned an HTTP error or could not be reached."""

    def __init__(self, message: str, status: int | None=None, body: Any=None, retry_after: float | None=None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        # Seconds the provider asked the client to wait (its Retry-After header), if any.
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in (408, 429) or self.status >= 500


class DatasetError(DecisionError, ValueError):
    """An evaluation case file, recorded response file, or requirement spec is invalid."""
