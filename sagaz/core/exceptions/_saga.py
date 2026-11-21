"""Core saga exception hierarchy."""


class SagaError(Exception):
    """Base saga error"""


class SagaStepError(SagaError):
    """Error executing saga step"""


class SagaCompensationError(SagaError):
    """Error executing compensation"""


class SagaTimeoutError(SagaError):
    """Saga step timeout"""


class SagaExecutionError(SagaError):
    """Error during saga execution"""


class SagaDependencyError(SagaError):
    """Invalid dependency configuration"""


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
