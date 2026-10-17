"""
ML reproduction spike: DistilBERT (arXiv:1910.01108) Table 1 reports dev accuracy on SST-2.
Claim: DistilBERT = 91.3 (BERT-base = 92.7, reported without error bars).
Public checkpoint distilbert-base-uncased-finetuned-sst-2-english; public GLUE SST-2 dev set (872 ex).
"""
import time, torch
from datasets import load_dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification

t0 = time.time()
ds = load_dataset("nyu-mll/glue", "sst2", split="validation")
print(f"[{time.time()-t0:5.1f}s] dataset: {len(ds)} examples")
name = "distilbert-base-uncased-finetuned-sst-2-english"
tok = AutoTokenizer.from_pretrained(name)
model = AutoModelForSequenceClassification.from_pretrained(name).eval()
print(f"[{time.time()-t0:5.1f}s] model loaded")
correct = 0
with torch.no_grad():
    for i in range(0, len(ds), 64):
        batch = ds[i:i+64]
        enc = tok(batch["sentence"], padding=True, truncation=True, return_tensors="pt")
        pred = model(**enc).logits.argmax(-1)
        correct += (pred == torch.tensor(batch["label"])).sum().item()
acc = 100*correct/len(ds)
claim = 91.3
# No error bar in the paper; binomial SE on 872 examples as our uncertainty
se = 100*(acc/100*(1-acc/100)/len(ds))**0.5
print(f"[{time.time()-t0:5.1f}s] SST-2 dev acc: ours {acc:.2f} ± {se:.2f} | claim {claim} (no σ) | diff {acc-claim:+.2f} | "
      f"{'PASS' if abs(acc-claim) <= 3*se else 'FAIL'} at 3σ(ours)")
