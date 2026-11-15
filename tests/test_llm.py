import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoatlas.llm import (
    OpenAIResponsesProvider,
    ProviderError,
    generate_grounded_answer,
)


class FakeProvider:
    name = "fake"
    model = "test-model"

    def __init__(self, result, after_generate=None):
        self.result = result
        self.after_generate = after_generate
        self.calls = []

    def generate(self, *, question, evidence):
        self.calls.append({"question": question, "evidence": evidence})
        if self.after_generate is not None:
            self.after_generate()
        return self.result


def _project(tmp_path: Path) -> Path:
    (tmp_path / "auth.py").write_text(
        '"""Authentication token validation."""\n'
        "def authenticate_token(token):\n"
        "    return token is not None\n",
        encoding="utf-8",
    )
    return tmp_path


def _valid_result():
    return {
        "claims": [{
            "text": "The repository defines an authentication token check.",
            "evidence_ids": ["E1"],
        }],
        "insufficient_evidence": False,
        "open_questions": [],
    }


def test_grounded_answer_returns_only_claims_with_valid_evidence(tmp_path: Path):
    _project(tmp_path)
    provider = FakeProvider(_valid_result())

    result = generate_grounded_answer(
        tmp_path,
        "How are authentication tokens checked?",
        provider=provider,
    )

    assert result["generation_status"] == "generated"
    assert result["answer_mode"] == "grounded_llm"
    assert result["provider"] == "fake"
    assert "[E1]" in result["answer"]
    assert result["claims"][0]["evidence"][0]["citation"]["sha256"]
    assert result["evidence"][0]["cited"] is True
    assert provider.calls[0]["evidence"][0]["id"] == "E1"


def test_grounded_answer_rejects_unknown_evidence_ids(tmp_path: Path):
    _project(tmp_path)
    result = _valid_result()
    result["claims"][0]["evidence_ids"] = ["E999"]

    with pytest.raises(ProviderError, match="unknown evidence ID"):
        generate_grounded_answer(tmp_path, "authentication token", provider=FakeProvider(result))


def test_grounded_answer_rejects_claim_without_citations(tmp_path: Path):
    _project(tmp_path)
    result = _valid_result()
    result["claims"][0]["evidence_ids"] = []

    with pytest.raises(ProviderError, match="one to five unique evidence IDs"):
        generate_grounded_answer(tmp_path, "authentication token", provider=FakeProvider(result))


def test_grounded_answer_rejects_duplicate_citation_ids(tmp_path: Path):
    _project(tmp_path)
    result = _valid_result()
    result["claims"][0]["evidence_ids"] = ["E1", "E1"]

    with pytest.raises(ProviderError, match="one to five unique evidence IDs"):
        generate_grounded_answer(tmp_path, "authentication token", provider=FakeProvider(result))


def test_grounded_answer_does_not_call_model_when_no_evidence(tmp_path: Path):
    _project(tmp_path)
    provider = FakeProvider(_valid_result())

    result = generate_grounded_answer(
        tmp_path,
        "quantum nebula telescope",
        provider=provider,
    )

    assert result["generation_status"] == "no_evidence"
    assert result["claims"] == []
    assert provider.calls == []


def test_grounded_answer_rejects_file_modified_during_generation(tmp_path: Path):
    _project(tmp_path)
    source = tmp_path / "auth.py"

    def mutate_source():
        source.write_text("def delete_all_tokens():\n    return True\n", encoding="utf-8")

    provider = FakeProvider(_valid_result(), after_generate=mutate_source)
    with pytest.raises(ProviderError, match="Source changed"):
        generate_grounded_answer(tmp_path, "authentication token", provider=provider)


def test_grounded_answer_labels_partial_findings_and_open_questions(tmp_path: Path):
    _project(tmp_path)
    result = _valid_result()
    result["insufficient_evidence"] = True
    result["open_questions"] = ["Are tokens also checked by the API middleware?"]

    response = generate_grounded_answer(
        tmp_path, "authentication token", provider=FakeProvider(result)
    )

    assert response["generation_status"] == "generated"
    assert response["answer"].startswith("Partial, evidence-supported findings:")
    assert response["open_questions"] == result["open_questions"]


def test_grounded_answer_returns_insufficient_evidence_without_claims(tmp_path: Path):
    _project(tmp_path)
    result = {
        "claims": [],
        "insufficient_evidence": True,
        "open_questions": ["Which module owns refresh-token rotation?"],
    }

    response = generate_grounded_answer(
        tmp_path, "authentication token", provider=FakeProvider(result)
    )

    assert response["generation_status"] == "insufficient_evidence"
    assert response["claims"] == []
    assert "insufficient" in response["answer"].lower()


@pytest.mark.parametrize(
    ("question", "top_k"),
    [("", 6), ("valid question", 0), ("x" * 2001, 6)],
)
def test_grounded_answer_validates_inputs(tmp_path: Path, question: str, top_k: int):
    _project(tmp_path)
    with pytest.raises(ValueError):
        generate_grounded_answer(
            tmp_path,
            question,
            provider=FakeProvider(_valid_result()),
            top_k=top_k,
        )


def test_provider_from_env_is_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIResponsesProvider.from_env() is None


def test_openai_provider_requests_strict_json_without_tools_or_storage():
    class FakeResponses:
        def __init__(self):
            self.arguments = None

        def create(self, **kwargs):
            self.arguments = kwargs
            return SimpleNamespace(output_text=json.dumps(_valid_result()))

    responses = FakeResponses()
    provider = OpenAIResponsesProvider(
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    result = provider.generate(
        question="How does authentication work?",
        evidence=[{"id": "E1", "excerpt": "def authenticate_token(token): ..."}],
    )

    assert result == _valid_result()
    assert responses.arguments["store"] is False
    assert responses.arguments["text"]["format"]["strict"] is True
    assert "tools" not in responses.arguments
    assert "UNTRUSTED DATA" in responses.arguments["instructions"]
    sent_payload = json.loads(responses.arguments["input"][0]["content"][0]["text"])
    assert sent_payload["evidence"][0]["id"] == "E1"


@pytest.mark.parametrize(
    "output",
    [
        None,
        "",
        "not-json",
        "[]",
    ],
)
def test_openai_provider_rejects_invalid_structured_output(output):
    provider = OpenAIResponsesProvider(
        client=SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(output_text=output)
            )
        )
    )
    with pytest.raises(ProviderError):
        provider.generate(question="question", evidence=[])
