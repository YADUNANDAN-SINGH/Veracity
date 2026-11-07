# Spectra-0 (lab260/spectra_0, MIT / Apache-2.0): an anti-spoofing network of
# wav2vec 2.0 XLS-R 300M -> MLP bridge -> ECAPA-TDNN, logits [spoof, bonafide].
# In-the-Wild EER 1.1% on the Speech Anti-Spoofing Arena, against 7-49% for the
# older wav2vec2 classifiers.
#
# The network is copied from the model repo's model.py, so no remote code runs,
# and the weights are pinned to one revision. The XLS-R backbone is built from its
# config, so the base model isn't downloaded a second time.

import math

import numpy as np
import torch
import torch.nn as nn

REPO = "lab260/spectra_0"
REVISION = "b3fb6d5c9d8ce069996f100cbe10117fd74165f3"
N_SAMPLES = 64_600  # the 4.04 s it was trained on; shorter windows are tiled to this
PREEMPHASIS = 0.97


def prepare(x16k: np.ndarray) -> np.ndarray:
    """16 kHz mono → pre-emphasis, then exactly N_SAMPLES: the last ones of a longer window,
    or a shorter one repeated from its start (as the model card's pad does)."""
    x = np.asarray(x16k, dtype=np.float32)
    x = np.concatenate([x[:1], x[1:] - PREEMPHASIS * x[:-1]])
    if len(x) < N_SAMPLES:
        return np.tile(x, N_SAMPLES // len(x) + 1)[:N_SAMPLES]
    return x[-N_SAMPLES:]


class _SE(nn.Module):
    def __init__(self, channels, bottleneck=128):
        super().__init__()
        self.se = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),
            nn.Conv1d(channels, bottleneck, kernel_size=1),
            nn.ReLU(),
            nn.Conv1d(bottleneck, channels, kernel_size=1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return x * self.se(x)


class _Bottle2neck(nn.Module):
    def __init__(self, inplanes, planes, kernel_size, dilation, scale=8):
        super().__init__()
        width = int(math.floor(planes / scale))
        pad = math.floor(kernel_size / 2) * dilation
        self.conv1 = nn.Conv1d(inplanes, width * scale, kernel_size=1)
        self.bn1 = nn.BatchNorm1d(width * scale)
        self.nums = scale - 1
        self.convs = nn.ModuleList(nn.Conv1d(width, width, kernel_size, dilation=dilation, padding=pad) for _ in range(self.nums))
        self.bns = nn.ModuleList(nn.BatchNorm1d(width) for _ in range(self.nums))
        self.conv3 = nn.Conv1d(width * scale, planes, kernel_size=1)
        self.bn3 = nn.BatchNorm1d(planes)
        self.relu = nn.ReLU()
        self.width = width
        self.se = _SE(planes)

    def forward(self, x):
        out = self.bn1(self.relu(self.conv1(x)))
        spx = torch.split(out, self.width, 1)
        for i in range(self.nums):
            sp = spx[i] if i == 0 else sp + spx[i]
            sp = self.bns[i](self.relu(self.convs[i](sp)))
            out = sp if i == 0 else torch.cat((out, sp), 1)
        out = torch.cat((out, spx[self.nums]), 1)
        out = self.bn3(self.relu(self.conv3(out)))
        return self.se(out) + x


class _ECAPA(nn.Module):
    def __init__(self, c=128):
        super().__init__()
        self.conv1 = nn.Conv1d(128, c, kernel_size=5, padding=2)
        self.relu = nn.ReLU()
        self.bn1 = nn.BatchNorm1d(c)
        self.layer1 = _Bottle2neck(c, c, kernel_size=3, dilation=2)
        self.layer2 = _Bottle2neck(c, c, kernel_size=3, dilation=3)
        self.layer3 = _Bottle2neck(c, c, kernel_size=3, dilation=4)
        self.layer4 = _Bottle2neck(c, c, kernel_size=3, dilation=5)
        self.layer5 = nn.Conv1d(4 * c, 1536, kernel_size=1)
        self.attention = nn.Sequential(
            nn.Conv1d(4608, 256, kernel_size=1), nn.ReLU(), nn.BatchNorm1d(256), nn.Tanh(),
            nn.Conv1d(256, 1536, kernel_size=1), nn.Softmax(dim=2),
        )
        self.bn5 = nn.BatchNorm1d(3072)
        self.fc6 = nn.Linear(3072, 2)

    def forward(self, x):
        x = self.bn1(self.relu(self.conv1(x.transpose(1, 2))))
        x1 = self.layer1(x)
        x2 = self.layer2(x + x1)
        x3 = self.layer3(x + x1 + x2)
        x4 = self.layer4(x + x1 + x2 + x3)
        x = self.relu(self.layer5(torch.cat((x1, x2, x3, x4), dim=1)))
        t = x.size()[-1]
        mean = torch.mean(x, dim=2, keepdim=True).repeat(1, 1, t)
        std = torch.sqrt(torch.var(x, dim=2, keepdim=True).clamp(min=1e-4)).repeat(1, 1, t)
        w = self.attention(torch.cat((x, mean, std), dim=1))
        mu = torch.sum(x * w, dim=2)
        sg = torch.sqrt((torch.sum((x ** 2) * w, dim=2) - mu ** 2).clamp(min=1e-4))
        return self.fc6(self.bn5(torch.cat((mu, sg), 1)))


class _Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        from transformers import Wav2Vec2Config, Wav2Vec2Model

        # facebook/wav2vec2-xls-r-300m's architecture; the fine-tuned weights replace all of it
        cfg = Wav2Vec2Config(
            hidden_size=1024, num_hidden_layers=24, num_attention_heads=16, intermediate_size=4096,
            feat_extract_norm="layer", do_stable_layer_norm=True, conv_bias=True,
            apply_spec_augment=False, layerdrop=0.0, mask_time_prob=0.0,
        )
        self.model = Wav2Vec2Model(cfg)
        self.model.masked_spec_embed = None


class _Bridge(nn.Module):
    def __init__(self):
        super().__init__()
        # Linear, SELU, (dropout), Linear, (dropout): indices match the checkpoint
        self.mlp = nn.Sequential(nn.Linear(1024, 128), nn.SELU(), nn.Identity(), nn.Linear(128, 128), nn.Identity())

    def forward(self, x):
        return self.mlp(x)


class Spectra0(nn.Module):
    def __init__(self):
        super().__init__()
        self.ssl_encoder = _Encoder()
        self.bridge = _Bridge()
        self.ecapa_tdnn = _ECAPA()

    @torch.inference_mode()
    def score(self, x: torch.Tensor) -> torch.Tensor:
        """(B, N_SAMPLES) prepared audio → logits (B, 2): [spoof, bona fide]."""
        hidden = self.ssl_encoder.model(x, return_dict=True).last_hidden_state
        return self.ecapa_tdnn(self.bridge(hidden)).float()


def load(device: str = "cpu") -> Spectra0:
    """Download (once) and load the pinned weights."""
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    path = hf_hub_download(REPO, "model.safetensors", revision=REVISION)
    net = Spectra0()
    missing, unexpected = net.load_state_dict(load_file(path), strict=False)
    if missing or unexpected:
        raise RuntimeError(f"Spectra-0 weights don't fit the network: missing {missing[:3]}, unexpected {unexpected[:3]}")
    return net.eval().to(device)
