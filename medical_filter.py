# medical_filter.py
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


MODEL_PATH = "./rubioroberta_side_effect_classifier"

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)


def is_medical_term(text):
    if not text or len(text) < 3:
        return False

    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
    with torch.no_grad():
        outputs = model(**inputs)

    return torch.argmax(outputs.logits, dim=1).item() == 1