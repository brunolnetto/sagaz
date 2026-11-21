"""Core saga exception hierarchy."""

from typing import Any


class SagaError(Exception):
    """Base saga error"""


class SagaStepError(SagaError):
    """Error executing saga step"""


class SagaCompensationError(SagaError):
    """Error executing compensation"""


class SagaTimeoutError(SagaError, TimeoutError):
    """A saga step timed out (also a ``TimeoutError``, which it was before 2.4)."""


class SagaExecutionError(SagaError):
    """Error during saga execution"""


class SagaDependencyError(SagaError):
    """Invalid dependency configuration"""


class SagaDefinitionError(SagaError, ValueError):
    """A saga's definition is invalid (#536): found when the saga is created, not run.

    For example a ``@compensate`` of a step that does not exist, two steps with one
    name, a ``depends_on`` naming no step, or a dependency cycle. Also a
    ``ValueError``, which dependency cycles raised before 2.4.
    """


class SagaFailedError(SagaExecutionError):
    """A saga run failed (#536): the one exception a failed ``Saga.run()`` raises.

    The step's (or storage's) exception is ``__cause__``. ``status`` tells whether
    the saga was rolled back (``ROLLED_BACK``) or a compensation failed too
    (``FAILED``), which needs a person to look.

    Attributes:
        saga_id: The run's id.
        saga_name: The saga's name.
        status: ``SagaStatus.ROLLED_BACK`` or ``SagaStatus.FAILED``.
        failed_step: The step that failed, or None (e.g. the state could not be saved).
        compensation_errors: Step name -> the exception its compensation raised.
    """

    def __init__(
        self,
        saga_id: str,
        saga_name: str,
        status: Any,
        failed_step: str | None,
        error: BaseException,
        compensation_errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.saga_id = saga_id
        self.saga_name = saga_name
        self.status = status
        self.failed_step = failed_step
        self.compensation_errors = dict(compensation_errors or {})
        where = f" at step {failed_step!r}" if failed_step else ""
        outcome = (
            f"compensation failed for {sorted(self.compensation_errors)}"
            if self.compensation_errors
            else "rolled back"
        )
        super().__init__(
            f"saga {saga_name!r} ({saga_id}) failed{where}: "
            f"{type(error).__name__}: {error}; {outcome}"
        )


class SagaAlreadyExistsError(SagaError):
    """A saga with this ``saga_id`` already ran or is running (#535).

    Running a saga id a second time would run its steps again (charging twice,
    shipping twice), so the second run is refused before any step runs.
    """

    def __init__(self, saga_id: str, status: str | None = None) -> None:
        self.saga_id = saga_id
        self.status = status
        state = f" (status: {status})" if status else ""
        super().__init__(
            f"saga {saga_id!r} already exists{state}: a saga id runs once. "
            "Use a new saga_id, or look the run up with storage.load_saga_state()."
        )


class SagaPersistenceError(SagaError):
    """The saga's state could not be saved (#534).

    Raised by default, since a saga that cannot record its progress cannot be
    looked up or recovered. ``SagaConfig(tolerate_persistence_errors=True)``
    logs instead.
    """

    def __init__(self, saga_id: str, phase: str, error: BaseException) -> None:
        self.saga_id = saga_id
        self.phase = phase
        super().__init__(f"could not save saga {saga_id!r} ({phase}): {error}")
