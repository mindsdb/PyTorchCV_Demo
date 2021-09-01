from typing import List
from lightwood.encoder.base import BaseEncoder
from lightwood.model.unit import Unit
from lightwood.helpers.log import log
from lightwood.data.encoded_ds import EncodedDs
import pandas as pd
import torch
from torch.nn import functional as F


class UnitClassifier(Unit):
    def __init__(self, stop_after: int, target_encoder: BaseEncoder):
        super().__init__(stop_after, target_encoder=target_encoder)

    def __call__(self, ds: EncodedDs, predict_proba: bool = False) -> pd.DataFrame:
        decoded_predictions: List[object] = []

        for X, _ in ds:
            X = torch.unsqueeze(X, 0)
            X[:, 0] = 0.0
            X = F.softmax(X, dim=-1)  # always ignores the unknown token
            decoded_prediction = self.target_encoder.decode(X)
            decoded_predictions.extend(decoded_prediction)

        ydf = pd.DataFrame({"prediction": decoded_predictions})
        return ydf