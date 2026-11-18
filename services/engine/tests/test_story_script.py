"""Escolha do provedor de roteiro (B16)."""

from __future__ import annotations

from cronista.config import Settings


def test_script_provider_e_null_por_padrao_e_so_vira_local_com_benchmark(settings: Settings) -> None:
    """B16: o roteiro local só entra com benchmark aprovado e gerador; no resto, `NullProvider`."""
    from cronista.story.script import LocalScriptProvider, NullProvider, script_provider

    class Gen:
        def generate(self, prompt: str, max_tokens: int) -> str:
            return "{}"

    assert isinstance(script_provider(settings, Gen()), NullProvider)
    wants_local = settings.model_copy(update={"script_provider": "local"})
    assert isinstance(script_provider(wants_local, Gen()), NullProvider)  # sem benchmark aprovado
    approved = wants_local.model_copy(update={"script_benchmark_ok": True})
    assert isinstance(script_provider(approved, Gen()), LocalScriptProvider)
    assert isinstance(script_provider(approved, None), NullProvider)  # sem gerador
