"""Minimal OpenAI-compatible mock used by the end-to-end test.

Run directly:  ``python tests/e2e/mock_llm.py --port 8899``
"""

from __future__ import annotations

import argparse
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

# One canned resume for the non-streaming path (resume parsing).
_RESUME_JSON = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": None,
    "location": "London",
    "summary": "Mathematician and first programmer.",
    "experience": [
        {"title": "Analyst", "company": "Difference Engine Co", "duration": "1842-1843",
         "description": "Wrote the first algorithm."}
    ],
    "education": [{"degree": "Mathematics", "institution": "Self-taught", "year": "1840"}],
    "skills": ["mathematics", "python"],
    "certifications": [],
    "projects": [{"name": "Bernoulli numbers", "description": "Note G"}],
    "languages": ["English"],
}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    stream = bool(body.get("stream"))

    last = messages[-1].get("content") if messages else ""
    if isinstance(last, list):  # multimodal: replace images with a marker
        last = " ".join(
            part.get("text") or "[image]" for part in last if isinstance(part, dict)
        )
    last = str(last)

    if not stream:
        return {
            "choices": [
                {"message": {"content": json.dumps(_RESUME_JSON)}, "finish_reason": "stop"}
            ]
        }

    def generate():
        for token in ["Echo: ", last, " — done."]:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': token}}]})}\n\n"
            time.sleep(0.005)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
