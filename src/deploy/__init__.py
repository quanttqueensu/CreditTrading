"""src.deploy — the shared paper-trading framework the 5 sleeves plug into.

Built per DEPLOY_ARCHITECTURE.md. Nothing here re-derives a frozen number; the
sleeve modules (next phase) supply the parameters. This package is:

    sleeve.py       the Sleeve ABC + PositionTarget / MarketState / RiskVerdict
    fills.py        the ops-ledger fill-price math, factored out (byte-parity)
    exec_ledger.py  LongOnlySleeveLedger (ops.Ledger subclass) + DerivativesLedger
    broker/         Broker base, Simulator (local marks), IBKRBroker (lazy ib_insync)
    registry.py     alloc_type -> Sleeve-class map + per-type spec validation
    risk.py         per-sleeve kill/halve switches + book-level limits
    portfolio.py    PortfolioOrchestrator: sub-ledgers -> book rollup
    run_book.py     the daily runner (EXECUTION={simulator|ibkr})

The `ib_insync` import lives ONLY inside IBKRBroker.connect(); importing this
package, or running the simulator path, has zero broker dependencies.
"""
