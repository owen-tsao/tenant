"""Local pretrained semantic evidence only; no camera, network, or OBS control.

Scores are uncalibrated prompt-relative evidence, NOT probabilities of an event.
Still-image similarity cannot prove intent, motion, or that two views show the
same physical object. OneShotPolicy's validation gate must stay closed until a
held-out replay on the actual paired feeds has demonstrated useful separation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import math
from pathlib import Path
import hashlib
import threading
import time
import warnings

MODEL_NAME = 'MobileCLIP2-S0'
MODEL_REPOSITORY = 'timm/MobileCLIP2-S0-OpenCLIP'
MODEL_REVISION = '095906d28bf54d7584dc411e8ffe448f34289e05'
WEIGHTS_SHA256 = 'ab91a1a0c4330d6b1913e24d5035dfdea15423316aaec649610c6b1c6ddd0e95'
MODEL_FILES = {
    'open_clip_model.safetensors': WEIGHTS_SHA256,
    'open_clip_config.json': '43e7162c531e845155dbf47e8fef8fe5718b0eab3d6beefb8d615a2c55b4c1e5',
    'tokenizer.json': '43d4281659ce30b6aca2c7485944b3d73925bb7f87c7234daf3b6b094a6d618c',
}
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000

# Fixed, generic text ensembles. No hand-authored motion/skin detector, manual
# cue, identity recognition, tracking, transcription, or model training.
PROMPTS = {
    'demo_yes': (
        'A person is presenting an object held in their hands to the camera.',
        'A person demonstrating a product by showing its features with their hands.',
        'Someone showing and explaining an object they are holding.',
    ),
    'demo_no': (
        'A person waving their empty hands with nothing held.',
        'A person talking and gesturing with empty hands.',
        'A person walking around without demonstrating an object.',
        'An empty room with nobody demonstrating anything.',
        'A person sitting with their hands resting at their sides.',
    ),
    'detail_yes': (
        'A clear close-up showing the details of an object held in someone\'s hands.',
        'A useful close-up of a product being demonstrated.',
        'A tight view of the object that a person is showing to the camera.',
    ),
    'detail_no': (
        'An empty hand waving in front of the camera.',
        'An empty scene with no object to demonstrate.',
        'A blurry view with the camera lens blocked by a finger.',
        'A dark image from a blocked camera.',
        'A close-up of a face without an object being presented.',
        'A room with unrelated background objects.',
        'An object too far away to see its details.',
    ),
}


@dataclass(frozen=True)
class DecisionEvidence:
    demonstrating: float = 0.0
    detail_usefulness: float = 0.0
    confidence: float = 0.0
    uncertainty: float = 1.0
    valid: bool = False
    pair_similarity: float = 0.0
    demo_margin: float = 0.0
    detail_margin: float = 0.0
    detail_advantage: float = 0.0
    inference_ms: float = 0.0
    reason: str = 'unavailable'

    def as_dict(self) -> dict:
        return asdict(self)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, value))))


def _png(data: bytes):
    """Bound parsing before decoding; no image content/path in error evidence."""
    from PIL import Image
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_PNG_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Expected a bounded PNG snapshot')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(data), formats=['PNG']) as image:
            if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Expected a single PNG snapshot')
            width, height = image.size
            if width < 16 or height < 16 or width * height > MAX_PIXELS:
                raise ValueError('Snapshot dimensions are not supported')
            image.load()
            return image.convert('RGB')


class VisionClassifier:
    """Warm once outside the event, then classify pairs synchronously in-process.

    Pass the directory containing the pinned safetensors checkpoint downloaded
    during setup. This class never downloads files or accepts remote image URLs.
    Importing this module does not import torch or load any pretrained model.
    The CPU thread limit is process-wide: use the isolated lab/worker process,
    not the production Brain process. No per-frame subprocess is created here.
    """
    def __init__(self, model_dir: str | Path, *, device: str = 'cpu', threads: int = 4):
        started = time.perf_counter()
        path = Path(model_dir) / 'open_clip_model.safetensors'
        if device not in {'cpu', 'mps'} or type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError('Use cpu/mps and a bounded thread count')
        for name, expected in MODEL_FILES.items():
            artifact = Path(model_dir) / name
            if not artifact.is_file():
                raise ValueError('Pinned local model artifacts are required')
            with artifact.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise ValueError('Local model artifact does not match the reviewed revision')
        import torch
        import open_clip
        from tokenizers import Tokenizer
        from timm.utils import reparameterize_model
        if device == 'mps' and not torch.backends.mps.is_available():
            raise ValueError('MPS is unavailable; choose cpu explicitly')
        torch.set_num_threads(threads)
        self._torch = torch
        self.device = device
        self._lock = threading.Lock()
        # Canonical bundled architecture + local safetensors: no HF lookup,
        # remote code, API key, download, or pickle checkpoint in this path.
        model, _, self._preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=str(path), device='cpu', image_mean=(0., 0., 0.),
            image_std=(1., 1., 1.), image_interpolation='bilinear', image_resize_mode='shortest')
        model.eval()
        names = [name for name, values in PROMPTS.items() for _ in values]
        texts = [text for values in PROMPTS.values() for text in values]
        # Honor this checkpoint's bundled HF CLIP tokenizer (EOS padding),
        # not the canonical name's default zero-padding SimpleTokenizer.
        tokenizer = Tokenizer.from_file(str(Path(model_dir) / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=77)
        tokenizer.enable_padding(length=77, pad_id=49407, pad_token='<|endoftext|>')
        tokens = torch.tensor([item.ids for item in tokenizer.encode_batch(texts)], dtype=torch.long)
        with torch.inference_mode():
            features = model.encode_text(tokens, normalize=True).float().cpu()
        self.loaded_parameters = sum(p.numel() for p in model.parameters())
        self._groups = {name: tuple(i for i, group in enumerate(names) if group == name) for name in PROMPTS}
        self._text_features = features
        # Retain just the visual tower after caching trained text embeddings.
        visual = reparameterize_model(model.visual).eval().to(device)
        self._visual = visual
        self.visual_parameters = sum(p.numel() for p in visual.parameters())
        del model
        self._warm()
        self.startup_ms = (time.perf_counter() - started) * 1000

    def _sync(self):
        if self.device == 'mps':
            self._torch.mps.synchronize()

    def _warm(self):
        from PIL import Image
        batch = self._torch.stack([self._preprocess(Image.new('RGB', (640, 360), 'gray'))] * 2).to(self.device)
        with self._torch.inference_mode():
            for _ in range(3):
                self._visual(batch)
        self._sync()

    def classify(self, wide_png: bytes, detail_png: bytes) -> DecisionEvidence:
        """Return numeric evidence; caller owns acquisition timestamps/freshness.

        Caller must supply distinct new snapshots and use their acquisition time
        in the policy. Re-running a frozen PNG does not make a fresh observation.
        Invalid input/inference returns uncertainty1/validFalse and never a cut.
        """
        started = time.perf_counter()
        if not self._lock.acquire(blocking=False):
            return DecisionEvidence(reason='classifier_busy')
        images = []
        try:
            images.append(_png(wide_png)); images.append(_png(detail_png))
            torch = self._torch
            batch = torch.stack([self._preprocess(image) for image in images]).to(self.device)
            with torch.inference_mode():
                features = self._visual(batch)
                features = torch.nn.functional.normalize(features.float(), dim=-1).cpu()
                scores = features @ self._text_features.T
            self._sync()
            if not bool(torch.isfinite(scores).all()):
                return DecisionEvidence(reason='nonfinite_model_output')
            group = {name: scores[:, indices].max(dim=-1).values.tolist() for name, indices in self._groups.items()}
            demo_margin = group['demo_yes'][0] - group['demo_no'][0]
            detail_margin = group['detail_yes'][1] - group['detail_no'][1]
            advantage = group['detail_yes'][1] - group['detail_yes'][0]
            pair = float(features[0] @ features[1])
            # Relative margins from the trained model, not calibrated event
            # probabilities. Pair cosine is a relevance hint, NOT object identity.
            demonstrating = _sigmoid(demo_margin / .025)
            useful = min(_sigmoid(detail_margin / .025), _sigmoid((advantage - .01) / .025), _sigmoid((pair - .45) / .08))
            separation = min(1., abs(demo_margin) / .06, abs(detail_margin) / .06)
            support = min(1., max(0., min(float(scores[0].max()), float(scores[1].max())) / .25))
            uncertainty = max(1. - separation, 1. - support)
            confidence = min(demonstrating, useful, 1. - uncertainty)
            return DecisionEvidence(demonstrating=demonstrating, detail_usefulness=useful,
                confidence=confidence, uncertainty=uncertainty, valid=True,
                pair_similarity=max(-1., min(1., pair)), demo_margin=demo_margin,
                detail_margin=detail_margin, detail_advantage=advantage,
                inference_ms=(time.perf_counter() - started) * 1000, reason='uncalibrated_semantic_evidence')
        except Exception:
            # Never expose parser errors, image bytes or local paths upstream.
            return DecisionEvidence(inference_ms=(time.perf_counter() - started) * 1000, reason='invalid_snapshot_or_inference')
        finally:
            for image in images:
                image.close()
            self._lock.release()
