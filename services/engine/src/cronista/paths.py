"""Pastas e arquivos de uma sessão em `data/`: a convenção num único lugar.

CLI, API e serviços pedem o caminho aqui; nenhum outro módulo monta `data/story/<sessão>` à mão. Assim um
passo sempre enxerga o que o anterior gravou (não há `--out` por comando).

    data/story/<s>/         story-pack.json, voice-profile.json, roteiro.json/.srt
    data/packaging/<s>/     titulo-pack.json, titulos.json, thumbnails.json, thumbnails/, publicacao/
    data/shorts/<s>/        shorts-<s>.json (manifesto) e os MP4 dos Shorts
    data/montagem/<s>/      plano de montagem (JSON)
    data/acabamento/<s>/    plano de acabamento (JSON)
    data/export/montagem/<s>/  pacote do Resolve (uma pasta `versao-N` por exportação)
    data/export/stems/<s>/  stems de áudio
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cronista.config import Settings

STORY_PACK = "story-pack.json"
VOICE_PROFILE = "voice-profile.json"
SCRIPT = "roteiro.json"
PUBLISH_DIR_NAME = "publicacao"


@dataclass(frozen=True)
class SessionPaths:
    data_dir: Path
    session_id: int

    @classmethod
    def of(cls, settings: Settings, session_id: int) -> SessionPaths:
        return cls(settings.data_dir, session_id)

    def _sub(self, *parts: str) -> Path:
        return self.data_dir.joinpath(*parts, str(self.session_id))

    @property
    def story_dir(self) -> Path:
        return self._sub("story")

    @property
    def story_pack(self) -> Path:
        return self.story_dir / STORY_PACK

    @property
    def script(self) -> Path:
        return self.story_dir / SCRIPT

    @property
    def packaging_dir(self) -> Path:
        return self._sub("packaging")

    @property
    def thumbnails_dir(self) -> Path:
        return self.packaging_dir / "thumbnails"

    @property
    def publish_dir(self) -> Path:
        return self.packaging_dir / PUBLISH_DIR_NAME

    @property
    def shorts_dir(self) -> Path:
        return self._sub("shorts")

    @property
    def shorts_manifest(self) -> Path:
        return self.shorts_dir / f"shorts-{self.session_id}.json"

    @property
    def assembly_dir(self) -> Path:
        return self._sub("montagem")

    @property
    def finishing_dir(self) -> Path:
        return self._sub("acabamento")

    @property
    def package_base(self) -> Path:
        """Pasta-mãe das versões do pacote do Resolve (`versao-1`, `versao-2`...)."""
        return self._sub("export", "montagem")

    @property
    def stems_dir(self) -> Path:
        return self._sub("export", "stems")


def series_package_base(settings: Settings, project_id: int) -> Path:
    """Base das versões do pacote do vídeo da série: `data/export/montagem/serie-<projeto>`."""
    return settings.data_dir / "export" / "montagem" / f"serie-{project_id}"


def series_story_dir(settings: Settings, project_id: int) -> Path:
    """Pasta do story-pack da série: `data/story/serie-<projeto>` (não colide com o id de uma sessão)."""
    return settings.data_dir / "story" / f"serie-{project_id}"


def shorts_manifest_in(shorts_dir: Path, session_id: int) -> Path:
    """Manifesto dos Shorts dentro de uma pasta de Shorts já resolvida."""
    return shorts_dir / f"shorts-{session_id}.json"


def thumbnails_in(packaging_dir: Path) -> Path:
    """Pasta dos JPEGs de thumbnail dentro de uma pasta de embalagem já resolvida."""
    return packaging_dir / "thumbnails"


def review_csv(settings: Settings, project_id: int) -> Path:
    """CSV de revisão dos objetivos de um projeto (fica ao lado das pastas de história das sessões)."""
    return settings.data_dir / "story" / f"revisao-{project_id}.csv"
