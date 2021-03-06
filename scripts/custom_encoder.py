"""
2021.04.21
An example custom encoder. We will build an MLM loss-function to train a model.
This is a very contrived example to demonstrate the flexibility of the lightwood approach.
The baseclass "BaseEncoder" can be found in lightwood/encoders. This class specifically only requires a few things:  # noqa: E501
1) __init__ call; to specify whether you're training to target or not
2) prepare() call; sets the model and (optionally) trains encoder. Must intake priming data, but can be "ignored"
3) encode() call; the ability to featurize a model
4) decode() call; this is only required if the user is trying to predict in the latent space of the encoder
The script establishes a DistilBert model and trains an MLM based on the task at hand. If the task is classification, it will assign a token to each label to predict. If the task is regression, it will construct labels for each "bin" of a histogrammed approach of the numerical value.
The output of the encoder is the CLS token.
Currently the model explicitly reads "DistilBert".
Author: Natasha Seelam (natasha@mindsdb.com)
"""

import pandas as pd

# Dataset helpers
from torch.utils.data import DataLoader
from lightwood.encoder.text.helpers.mlm_helpers import (
    MaskedText,
    add_mask,
    create_label_tokens,
)

# ML helpers
import torch
from torch.nn import functional as F

from lightwood.helpers.device import get_devices
from lightwood.encoder.base import BaseEncoder
from lightwood.helpers.log import log
from lightwood.helpers.torch import LightwoodAutocast
from lightwood.api import dtype

# text-model helpers
from transformers import (
    DistilBertForMaskedLM,
    DistilBertTokenizerFast,
    AdamW,
    get_linear_schedule_with_warmup,
)

# Type-hinting
from typing import List, Dict

from copy import deepcopy as dc


class MLMEncoder(BaseEncoder):
    """
    An example of a custom encoder.
    Here, the model chosen will be Distilbert MLM
    Where we will train a classification task as an MLM.
    In order to build encoders, we inherit from BaseEncoder.
    Args:
    ::param is_target; data column is the target of ML.
    ::param ibatch_size; size of batch
    ::param imax_position_embeddings; max sequence length of input text
    ::param epochs; number of epochs to train model with
    ::param lr; learning-rate for model
    ::param embed_mode; whether to return the embedding or the class for classification
    ::param output_type; lightwood api dtype - confirms classification output
    ::param uses_target; passed information
    ::param is_nn_encoder; Boolean - training NN encoder
    """

    def __init__(
        self,
        is_target: bool = False,
        batch_size: int = 10,
        max_position_embeddings: int = None,
        epochs: int = 1,
        lr: float = 1e-5,
        embed_mode: bool = True,
        output_type=None,
        uses_target: bool = True,
        is_nn_encoder: bool = True,
    ):
        super().__init__(is_target)

        self.model_name = "distilbert-base-uncased"
        self.name = self.model_name + " MLM text encoder"
        log.info(self.name)

        self._max_len = max_position_embeddings
        self._batch_size = batch_size
        self._epochs = epochs
        self._lr = lr

        # Model setup
        self._model = None
        self.model_type = None
        self.output_type = output_type
        self.embed_mode = embed_mode

        # This is important if you want to pass information into the prepare call
        self.uses_target = True
        self.is_nn_encoder = True
        self.output_size = None


        # Distilbert is a good balance of speed/performance hence chosen.
        self._embeddings_model_class = DistilBertForMaskedLM
        self._tokenizer_class = DistilBertTokenizerFast

        # Set the device; CUDA v. CPU
        self.device, _ = get_devices()

        # Notify user if embed-mode flagged
        if self.embed_mode:
            log.info("Embedding mode on. [CLS] embedding dim output of encode()")
        else:
            log.info("Embedding mode off. Logits are output of encode()")

    def prepare(self, priming_data: pd.Series, encoded_target_values: torch.Tensor):
        """
        Prepare the encoder by training on the target.
        Training data must be a dict with "targets" avail.
        Automatically assumes this.
        Args:
        ::param priming_data; list of the input text
        ::param training_data; config of lightwood for encoded outputs etc.
        """
        if self._prepared:
            raise Exception("Encoder is already prepared.")

        # ---------------------------------------
        # Initialize the base text models + tokenizer
        # ---------------------------------------

        # Setup the base model and tokenizer
        self._model = self._embeddings_model_class.from_pretrained(self.model_name).to(
            self.device
        )

        self._tokenizer = self._tokenizer_class.from_pretrained(self.model_name)

        if self.output_type in (dtype.categorical, dtype.binary):
            log.info("Training model.")
            # --------------------------
            # Prepare the input data
            # --------------------------
            log.info("Preparing the training data")

            # Replace any empty strings with a "" placeholder and add MASK tokens.
            priming_data = add_mask(priming_data, self._tokenizer._mask_token)

            # Get the output labels in the categorical space; originally OHE
            labels = encoded_target_values.argmax(dim=1)

            N_classes = len(encoded_target_values[0])

            self.output_size = N_classes

            # This commands adds new tokens to tokenizer, model
            self._labeldict, self._tokenizer, self._model = create_label_tokens(
                N_classes, self._tokenizer, self._model
            )

            # Tokenize the dataset and add the score labels
            text = self._tokenizer(
                priming_data, truncation=True, padding=True, add_special_tokens=True
            )
            text["score"] = labels

            # Construct a dataset class and data loader
            traindata = DataLoader(
                MaskedText(text, self._tokenizer.mask_token_id, self._labeldict),
                batch_size=self._batch_size,
                shuffle=True,
            )

            # --------------------------
            # Setup the training parameters
            # -------------------------
            log.info("Training the model")
            optimizer = AdamW(self._model.parameters(), lr=self._lr)
            scheduler = get_linear_schedule_with_warmup(
                optimizer,
                num_warmup_steps=0,
                num_training_steps=len(traindata) * self._epochs,
            )

            # --------------------------
            # Train the model
            # -------------------------
            self._train_model(
                traindata, optim=optimizer, scheduler=scheduler, n_epochs=self._epochs
            )
        else:
            log.info("Target is not classification; Embeddings Generator only")
            self.model_type = "embeddings_generator"

            if self.embed_mode is False:
                log.info("Embedding mode must be ON for non-classification targets.")
                self.embed_mode = True

            # Estimate output size
            encoded = self.encode(priming_data[0:1])
            self.output_size = len(encoded[0])

        log.info("MLM text encoder is prepared!")
        self._prepared = True



    def encode(self, column_data):
        """
        Encoder; takes a series of text and encodes it
        via the text representation.

        Two modes available:
        1) Embed mode [True] - return the [CLS] token embedding
        2) Embed mode [False] - return the class prediction
        """
        if self._prepared is False:
            raise Exception("You need to first prepare the encoder.")

        encoded_representation = []

        # Prepare the priming data with a "MASK"

        column_data = add_mask(column_data, self._tokenizer._mask_token)
        # Set model to testing/eval mode.
        self._model.eval()

        with torch.no_grad():
            for text in column_data:

                if text is None:
                    text = ""

                inp = self._tokenizer.encode(
                        text, truncation=True, return_tensors="pt"
                    ).to(self.device)

                if self.embed_mode:  # Embedding mode ON; return [CLS] embedding
                    # Tokenize the text with the built-in tokenizer.
                    output = self._model.base_model(inp).last_hidden_state[:, 0]
                else:  # Return class prediction
                    output = self._evalclass(inp)

                encoded_representation.append(output.detach())

        return torch.stack(encoded_representation).squeeze(1).to('cpu')

    def decode(self, encoded_values_tensor, max_length=100):
        """
        Decoder from latent space -> original output.
        This can be used for text generation if decoded space is tokenized.
        """
        raise Exception("Decoder not implemented.")

    def _evalclass(self, example):
        """
        Input the text and output the top guesses

        :param example tokenized input of text (pre-masked)
        """
        mask_index = torch.where(example[0] == self._tokenizer.mask_token_id)

        # Get a softmax over the vocab (# 1 x Ntokens x Nvocab)
        output = F.softmax(self._model(example).logits, dim=-1)

        # Explicitly return on the dimensionality of the labels
        # Re-weight for only the output labels
        mask_score = F.softmax(output[0, mask_index, list(self._labeldict.values())], dim=-1)

        return mask_score

    def _train_model(
        self,
        dataset,
        optim: AdamW,
        scheduler: get_linear_schedule_with_warmup,
        n_epochs: int,
    ):
        """
        Trains the MLM for n_epochs provided. More advanced options (i.e. early stopping should be customized.)
        Args:
        ::param dataset; dataset to train
        ::param optim; training optimizer
        ::param scheduler; learning-rate scheduler for smoother steps
        ::param n_epochs; number of epochs to train
        """
        self._model.train()

        for epoch in range(n_epochs):
            total_loss = 0

            for batch in dataset:
                optim.zero_grad()

                with LightwoodAutocast():

                    # Prepare the batch and its labels
                    inpids = batch["input_ids"].to(self.device)
                    attn = batch["attention_mask"].to(self.device)
                    labels = batch["labels"].to(self.device)

                    outputs = self._model(inpids, attention_mask=attn, labels=labels)
                    loss = outputs[0]

                total_loss += loss.item()

                # Update the weights
                loss.backward()
                optim.step()
                scheduler.step()

            self._train_callback(epoch, total_loss / len(dataset))

    def _train_callback(self, epoch, loss):
        """ Training step details """
        log.info(f"{self.name} at epoch {epoch+1} and loss {loss}!")

    def to(self, device, available_devices):
        for v in vars(self):
            attr = getattr(self, v)
            if isinstance(attr, torch.nn.Module):
                attr.to(device)
        return self
