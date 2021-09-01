# PyTorchCV_Demo
### 2021.09.01
An example to deploy a Masked Language Model using Lightwood 1.1.0


The following repo allows you to try a custom MLM encoder for the dataset provided. Please note, you will likely need decent memory to train this model, as it tunes a transformer.

Please install the `custom_mlm` branch of lightwood. Alternatively, the desired scripts are found in the `scripts` folder. You can clone the `stable` branch of [lightwood](https://github.com/mindsdb/lightwood) and make the modifications as specified in the jupyter-notebook. 

The modifications are as follows: <br>
(1) Place `custom_encoder.py` in `lightwood/encoder/text`<br>
(2) Place `mlm_helpers.py` in `lightwood/encoder/text/helpers`<br>
(3) Change `lightwood/encoder/text/__init__.py` to import the desired MLMEncoder<br>
(4) Change `lightwood/encoder/__init__.py` to import the desired MLMEncoder<br>
(5) Place `unit_classifier.py` in `lightwood/model/`<br>
(6) Change `lightwood/model/__init__.py` to import the desired UnitClassifier<br>

Current features are still in beta, with a full release intended in time for Hacktoberfest - stay tuned, and we hope you enjoy this tutorial!

We also invite you to use our community [slack](https://docs.mindsdb.com/community/)! 
