"""Orquestrador: etapas puras, cache por hash, jobs persistidos e retomada."""

from cronista.pipeline.gpu import AlwaysFreeGate, GpuGate, gate_reason, wait_until_free
from cronista.pipeline.runner import PipelineReport, StageFailedError, recover_orphans, run_pipeline
from cronista.pipeline.stage import Stage, StageContext, StageError

__all__ = [
    "AlwaysFreeGate",
    "GpuGate",
    "PipelineReport",
    "Stage",
    "StageContext",
    "StageError",
    "StageFailedError",
    "gate_reason",
    "recover_orphans",
    "run_pipeline",
    "wait_until_free",
]
