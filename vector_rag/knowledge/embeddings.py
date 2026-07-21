"""Amazon Titan text embeddings via Bedrock runtime."""
from __future__ import annotations

import json
import time

import boto3


class TitanEmbedder:
    def __init__(self, model_id: str, region: str, dim: int = 1024):
        self.model_id = model_id
        self.dim = dim
        self._rt = boto3.client("bedrock-runtime", region_name=region)

    def embed_one(self, text: str) -> list[float]:
        text = (text or " ").strip()[:40000]  # Titan input cap safety
        body = {"inputText": text}
        # Titan v2 supports dimensions/normalize params
        if "v2" in self.model_id:
            body["dimensions"] = self.dim
            body["normalize"] = True
        for attempt in range(5):
            try:
                resp = self._rt.invoke_model(
                    modelId=self.model_id, body=json.dumps(body)
                )
                return json.loads(resp["body"].read())["embedding"]
            except Exception as e:  # throttling / transient
                if attempt == 4:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("unreachable")

    def embed_batch(self, texts: list[str], progress: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        n = len(texts)
        for i, t in enumerate(texts):
            out.append(self.embed_one(t))
            if progress and (i + 1) % 25 == 0:
                print(f"  embedded {i + 1}/{n}")
        return out
