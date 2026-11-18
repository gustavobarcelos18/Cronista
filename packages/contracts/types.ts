/* GERADO por pnpm gen a partir de schema.json. Não edite. */

/**
 * Efeitos que o acabamento pode aplicar, cada um com modo e orçamento próprios.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EffectKind".
 */
export type EffectKind =
  | "zoom"
  | "shake"
  | "musica"
  | "sfx"
  | "sfx_meme"
  | "piada_visual"
  | "contador_mortes"
  | "freeze_texto"
  | "barra_progresso"
  | "legenda_pontual"
  | "cartela_dia"
  | "cor_lut";
/**
 * Os três modos da seção 6.4: só marcador, aplicado e editável no Resolve, ou renderizado pelo app.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EffectMode".
 */
export type EffectMode = "sugerir" | "editavel" | "renderizado";
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerKind".
 */
export type MarkerKind =
  "momento" | "morte_falha" | "engracado" | "conquista" | "novo_dia" | "construcao" | "foto_progresso" | "cinematica";

export interface CronistaContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "DecisionIn".
 */
export interface DecisionIn {
  decision: "aceito" | "rejeitado" | "ajustado";
  end_s?: number | null;
  start_s?: number | null;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EffectSettingIn".
 */
export interface EffectSettingIn {
  max_per_minute: number;
  min_score: number;
  mode: EffectMode;
}
/**
 * Política de um efeito e de onde ela vem (padrão do app, estilo da série ou ajuste seu no Studio).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EffectSettingOut".
 */
export interface EffectSettingOut {
  kind: EffectKind;
  max_per_minute: number;
  min_score: number;
  mode: EffectMode;
  source: "padrao" | "serie" | "criador";
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EventOut".
 */
export interface EventOut {
  confidence: number;
  end_s: number;
  kind: string;
  quote: string | null;
  source: string;
  stage: string;
  start_s: number;
  variant: string;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ExportStatusOut".
 */
export interface ExportStatusOut {
  directory?: string | null;
  message?: string;
  problems?: string[];
  reused?: boolean;
  state: "idle" | "running" | "done" | "error";
  version?: number | null;
  warnings?: string[];
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FeedbackIn".
 */
export interface FeedbackIn {
  seg_start_s?: number | null;
  text: string;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FeedbackOut".
 */
export interface FeedbackOut {
  id: number;
  interpreted: boolean;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FinishDecisionIn".
 */
export interface FinishDecisionIn {
  decision: "aceito" | "removido" | "padrao";
}
/**
 * Um efeito planejado para um momento do vídeo, com a decisão do criador (se houver).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FinishItemOut".
 */
export interface FinishItemOut {
  asset_id?: string | null;
  decision?: ("aceito" | "removido") | null;
  duration_s: number;
  effective_mode?: EffectMode | null;
  id: string;
  intensity: number;
  kind: EffectKind;
  mode: EffectMode;
  reason: string;
  start_s: number;
  track: string;
}
/**
 * Prévia do acabamento da sessão: políticas por efeito e o que seria aplicado, momento a momento.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FinishingOut".
 */
export interface FinishingOut {
  effects?: EffectSettingOut[];
  enabled: boolean;
  has_library?: boolean;
  items?: FinishItemOut[];
  max_effects_per_minute?: number;
  series?: string;
  summary?: {
    [k: string]: {
      [k: string]: number;
    };
  };
  warnings?: string[];
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "JobOut".
 */
export interface JobOut {
  attempts: number;
  error: string | null;
  id: number;
  media_file_id: number;
  stage: string;
  status: string;
  variant: string;
}
/**
 * Proposta de recalibração dos pesos por manter/tirar (7E); `weights` é nulo enquanto faltam decisões.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "LearningOut".
 */
export interface LearningOut {
  applied?: {
    [k: string]: number;
  } | null;
  explanation?: string[];
  n_decisions?: number;
  needed: number;
  weights?: {
    [k: string]: number;
  } | null;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerOut".
 */
export interface MarkerOut {
  id: number;
  kind: string;
  marker_id: string;
  media_file_id: number | null;
  media_frame: number;
  source: string;
  warning: string | null;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MediaFileOut".
 */
export interface MediaFileOut {
  id: number;
  name: string;
  ordinal: number;
  size_bytes: number;
}
/**
 * Resultado do `ffprobe` de um arquivo de gravação.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MediaProbe".
 */
export interface MediaProbe {
  audio_streams?: number;
  bit_depth?: number;
  duration_s?: number | null;
  fps?: string | null;
  height?: number | null;
  interrupted?: boolean;
  path: string;
  pix_fmt?: string | null;
  video_codec?: string | null;
  width?: number | null;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "PackagingOut".
 */
export interface PackagingOut {
  approved_shorts?: number;
  min_shorts?: number;
  missing?: string[];
  ready?: boolean;
  shorts?: ShortOut[];
  thumbnails?: ThumbnailOut[];
  title: TitleOut;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ShortOut".
 */
export interface ShortOut {
  decision?: "pendente" | "aprovado" | "rejeitado";
  duration_s: number;
  has_clip: boolean;
  key: string;
  reason: string;
  score: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ThumbnailOut".
 */
export interface ThumbnailOut {
  chosen?: boolean;
  file_name: string;
  position?: string | null;
  text?: string | null;
  variation: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "TitleOut".
 */
export interface TitleOut {
  chosen?: string | null;
  origin?: ("sugerido" | "editado" | "proprio") | null;
  provider?: string | null;
  suggestions?: TitleOptionOut[];
  thumbnail_texts?: string[];
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "TitleOptionOut".
 */
export interface TitleOptionOut {
  n: number;
  reason?: string | null;
  text: string;
}
/**
 * Jobs da sessão por estado; `active` vale enquanto houver job pendente ou rodando.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ProgressOut".
 */
export interface ProgressOut {
  active: boolean;
  current?: string | null;
  done: number;
  failed: number;
  pending: number;
  running: number;
  total: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ProjectPanelOut".
 */
export interface ProjectPanelOut {
  capitulos_com_pouco_material: ThinChapterOut[];
  por_classe_min: {
    [k: string]: number;
  };
  projeto: string;
  projeto_id: number;
  sessoes: SeriesRowOut[];
  situacao: "curto_ok" | "abaixo_da_referencia" | "no_alvo" | "acima";
  total_min: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ThinChapterOut".
 */
export interface ThinChapterOut {
  capitulo: number;
  produto_s: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SeriesRowOut".
 */
export interface SeriesRowOut {
  acumulado_min: number;
  dias: number;
  gravado_h: number;
  por_classe_min: {
    [k: string]: number;
  };
  produto_min: number;
  sessao: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "PublishOut".
 */
export interface PublishOut {
  directory: string;
  files: string[];
  missing: string[];
  ready: boolean;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "Script".
 */
export interface Script {
  lines?: ScriptLine[];
  provider?: string;
  version?: number;
}
/**
 * Uma fala sugerida, sempre ligada a um segmento (aceite da Fase 5).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ScriptLine".
 */
export interface ScriptLine {
  est_s?: number | null;
  justification?: string | null;
  kind?: "narracao" | "antecipacao";
  segment_id: string;
  start_s?: number | null;
  text: string;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ScriptOut".
 */
export interface ScriptOut {
  script: Script;
  warnings?: string[];
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SegmentOut".
 */
export interface SegmentOut {
  adj_end_s?: number | null;
  adj_start_s?: number | null;
  classe: string;
  decision?: string | null;
  end_s: number;
  features: {
    [k: string]: number;
  };
  markers: string[];
  razoes: string[];
  score: number;
  start_s: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SeriesPanelOut".
 */
export interface SeriesPanelOut {
  maximo_min: number;
  meta_min: number;
  minimo_min: number;
  projetos: ProjectPanelOut[];
  referencia_capitulo_s: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SessionOut".
 */
export interface SessionOut {
  files: MediaFileOut[];
  folder: string;
  id: number;
  project: string;
  project_id: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ShortDecisionIn".
 */
export interface ShortDecisionIn {
  decision: "aprovado" | "rejeitado" | "padrao";
}
/**
 * Saída de uma etapa do pipeline, persistida como `result.json` no cache.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "StageResult".
 */
export interface StageResult {
  data?: {
    [k: string]: unknown;
  };
  files?: string[];
  warnings?: string[];
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ThumbnailChoiceIn".
 */
export interface ThumbnailChoiceIn {
  variation: number;
}
/**
 * `suggestion` = a sugestão como está; `text` = título do criador; os dois = sugestão editada.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "TitleChoiceIn".
 */
export interface TitleChoiceIn {
  suggestion?: number | null;
  text?: string | null;
}
/**
 * Envelope de energia (dBFS) por faixa, em até `points` buckets uniformes (máximo de cada bucket).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "WaveformOut".
 */
export interface WaveformOut {
  duration_s: number;
  game: number[];
  mic: number[];
  points: number;
}
