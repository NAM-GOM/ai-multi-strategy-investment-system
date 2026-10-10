"""Account reconciliation precedes strategy attribution; both must pass."""


class ReconciliationEngine:
    def __init__(self, order_manager):
        self.order_manager = order_manager

    def run(self):
        return self.order_manager.reconcile()
