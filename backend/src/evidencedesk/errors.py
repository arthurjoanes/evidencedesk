class Problem(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(code)


def not_found() -> Problem:
    # A mesma resposta protege existência e conteúdo quando falta autorização.
    return Problem(404, "resource_not_found", "Recurso não encontrado ou sem acesso.")
