"""
Decision engine (Bartek). Public entry point:

    from engine import predict
    predict(field_ids=None, start=None, end=None) -> int

Imported lazily so that `engine.satellite` and the training scripts work without Django.
"""


def predict(*args, **kwargs):
    from engine.compute import predict as _predict

    return _predict(*args, **kwargs)
