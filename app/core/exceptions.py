class CommerceException(Exception):
    """Base domain exception for Nova Commerce."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class InsufficientStockException(CommerceException):
    """Raised when an order requests more units than available inventory."""
    def __init__(self, product_name: str, available: int, requested: int):
        super().__init__(
            f"Insufficient stock for '{product_name}'. Available: {available}, Requested: {requested}."
        )
        self.product_name = product_name
        self.available = available
        self.requested = requested


class OrderStateTransitionException(CommerceException):
    """Raised when an illegal order status transition is attempted."""
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Cannot transition order from '{current_status}' to '{target_status}'."
        )


class EntityNotFoundException(CommerceException):
    """Raised when a requested resource is missing in the database."""
    def __init__(self, entity_name: str, identifier: str | int):
        super().__init__(f"{entity_name} with ID '{identifier}' not found.")
