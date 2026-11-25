"""A fake Ollama server for the triage tests: canned replies, every request body recorded."""
import json

import httpx

from payguard.triage.llm import OLLAMA_URL

VALID = {"category": "lending", "fraud_allegation": False, "legal_threat": True, "vulnerable_customer": False,
         "safety_risk": False, "discrimination": False, "urgency": "high",
         "summary": "The consumer's car is about to be repossessed.", "confidence_note": "The date is redacted."}


def ollama_reply(content: dict | str, done_reason: str = "stop") -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}, "done_reason": done_reason,
                                     "prompt_eval_count": 900, "eval_count": 80})


def client_replying(*responses: httpx.Response) -> tuple[httpx.Client, list[dict]]:
    """A client whose server returns the given responses in turn, recording each request body."""
    queue, seen = list(responses), []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return queue.pop(0)

    return httpx.Client(base_url=OLLAMA_URL, transport=httpx.MockTransport(handler)), seen
