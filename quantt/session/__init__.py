"""The Alpaca trading session for one book: decide, gate, record, transmit, confirm.

`docs/RUNNER.md` is the contract. The pieces, one owner each:

  * `decide.py`  pure: sleeve targets + broker holdings + equity + last closes
                 -> an ordered whole-share order list and its `plan_sha`.
  * `gate.py`    pure: the nine gates -> a list of named refusals.
  * `records.py` the on-disk record under `$QUANTT_STATE_DIR/<date>/`.
  * `run.py`     orchestration, and the ONLY caller of `submit_order`.
  * `verify.py`  post-close reconcile and scoring (another owner).

`python3 -m quantt.session run --book cef [--preview] [--approve SHA] [--skip-refresh]`
`python3 -m quantt.session verify --book cef ...`
"""
