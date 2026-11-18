/* GERADO por pnpm gen a partir de schema.json. Não edite. */

export type Decision = "aceito" | "rejeitado" | "ajustado";
export type EndS = number | null;
export type StartS = number | null;
export type Confidence = number;
export type EndS1 = number;
export type Kind = string;
export type Quote = string | null;
export type Source = string;
export type Stage = string;
export type StartS1 = number;
export type Variant = string;
export type Directory = string | null;
export type Message = string;
export type Problems = string[];
export type Reused = boolean;
export type State = "idle" | "running" | "done" | "error";
export type Version = number | null;
export type Warnings = string[];
export type SegStartS = number | null;
export type Text = string;
export type Id = number;
export type Interpreted = boolean;
export type Attempts = number;
export type Error = string | null;
export type Id1 = number;
export type MediaFileId = number;
export type Stage1 = string;
export type Status = string;
export type Variant1 = string;
export type Applied = {
  [k: string]: number;
} | null;
export type Explanation = string[];
export type NDecisions = number;
export type Needed = number;
export type Weights = {
  [k: string]: number;
} | null;
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerKind".
 */
export type MarkerKind =
  "momento" | "morte_falha" | "engracado" | "conquista" | "novo_dia" | "construcao" | "foto_progresso" | "cinematica";
export type Id2 = number;
export type Kind1 = string;
export type MarkerId = string;
export type MediaFileId1 = number | null;
export type MediaFrame = number;
export type Source1 = string;
export type Warning = string | null;
export type Id3 = number;
export type Name = string;
export type Ordinal = number;
export type SizeBytes = number;
export type AudioStreams = number;
export type BitDepth = number;
export type DurationS = number | null;
export type Fps = string | null;
export type Height = number | null;
export type Interrupted = boolean;
export type Path = string;
export type PixFmt = string | null;
export type VideoCodec = string | null;
export type Width = number | null;
export type Active = boolean;
export type Current = string | null;
export type Done = number;
export type Failed = number;
export type Pending = number;
export type Running = number;
export type Total = number;
export type EstS = number | null;
export type Justification = string | null;
export type Kind2 = "narracao" | "antecipacao";
export type SegmentId = string;
export type StartS2 = number | null;
export type Text1 = string;
export type Lines = ScriptLine[];
export type Provider = string;
export type Version1 = number;
export type Warnings1 = string[];
export type AdjEndS = number | null;
export type AdjStartS = number | null;
export type Classe = string;
export type Decision1 = string | null;
export type EndS2 = number;
export type Markers = string[];
export type Razoes = string[];
export type Score = number;
export type StartS3 = number;
export type Capitulo = number;
export type ProdutoS = number;
export type Projeto = string;
export type ProjetoId = number;
export type CapitulosComPoucoMaterial = ThinChapterOut[];
export type MaximoMin = number;
export type MetaMin = number;
export type MinimoMin = number;
export type ReferenciaCapituloS = number;
export type AcumuladoMin = number;
export type Dias = number;
export type GravadoH = number;
export type ProdutoMin = number;
export type Sessao = number;
export type Sessoes = SeriesRowOut[];
export type Situacao = "faltando" | "no_alvo" | "acima";
export type TotalMin = number;
export type Files = MediaFileOut[];
export type Folder = string;
export type Id4 = number;
export type Project = string;
export type ProjectId = number;
export type Files1 = string[];
export type Warnings2 = string[];
export type DurationS1 = number;
export type Game = number[];
export type Mic = number[];
export type Points = number;

export interface CronistaContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "DecisionIn".
 */
export interface DecisionIn {
  decision: Decision;
  end_s?: EndS;
  start_s?: StartS;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EventOut".
 */
export interface EventOut {
  confidence: Confidence;
  end_s: EndS1;
  kind: Kind;
  quote: Quote;
  source: Source;
  stage: Stage;
  start_s: StartS1;
  variant: Variant;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ExportStatusOut".
 */
export interface ExportStatusOut {
  directory?: Directory;
  message?: Message;
  problems?: Problems;
  reused?: Reused;
  state: State;
  version?: Version;
  warnings?: Warnings;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FeedbackIn".
 */
export interface FeedbackIn {
  seg_start_s?: SegStartS;
  text: Text;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "FeedbackOut".
 */
export interface FeedbackOut {
  id: Id;
  interpreted: Interpreted;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "JobOut".
 */
export interface JobOut {
  attempts: Attempts;
  error: Error;
  id: Id1;
  media_file_id: MediaFileId;
  stage: Stage1;
  status: Status;
  variant: Variant1;
}
/**
 * Proposta de recalibração dos pesos por manter/tirar (7E); `weights` é nulo enquanto faltam decisões.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "LearningOut".
 */
export interface LearningOut {
  applied?: Applied;
  explanation?: Explanation;
  n_decisions?: NDecisions;
  needed: Needed;
  weights?: Weights;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerOut".
 */
export interface MarkerOut {
  id: Id2;
  kind: Kind1;
  marker_id: MarkerId;
  media_file_id: MediaFileId1;
  media_frame: MediaFrame;
  source: Source1;
  warning: Warning;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MediaFileOut".
 */
export interface MediaFileOut {
  id: Id3;
  name: Name;
  ordinal: Ordinal;
  size_bytes: SizeBytes;
}
/**
 * Resultado do `ffprobe` de um arquivo de gravação.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MediaProbe".
 */
export interface MediaProbe {
  audio_streams?: AudioStreams;
  bit_depth?: BitDepth;
  duration_s?: DurationS;
  fps?: Fps;
  height?: Height;
  interrupted?: Interrupted;
  path: Path;
  pix_fmt?: PixFmt;
  video_codec?: VideoCodec;
  width?: Width;
}
/**
 * Jobs da sessão por estado; `active` vale enquanto houver job pendente ou rodando.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ProgressOut".
 */
export interface ProgressOut {
  active: Active;
  current?: Current;
  done: Done;
  failed: Failed;
  pending: Pending;
  running: Running;
  total: Total;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "Script".
 */
export interface Script {
  lines?: Lines;
  provider?: Provider;
  version?: Version1;
}
/**
 * Uma fala sugerida, sempre ligada a um segmento (aceite da Fase 5).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ScriptLine".
 */
export interface ScriptLine {
  est_s?: EstS;
  justification?: Justification;
  kind?: Kind2;
  segment_id: SegmentId;
  start_s?: StartS2;
  text: Text1;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ScriptOut".
 */
export interface ScriptOut {
  script: Script;
  warnings?: Warnings1;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SegmentOut".
 */
export interface SegmentOut {
  adj_end_s?: AdjEndS;
  adj_start_s?: AdjStartS;
  classe: Classe;
  decision?: Decision1;
  end_s: EndS2;
  features: Features;
  markers: Markers;
  razoes: Razoes;
  score: Score;
  start_s: StartS3;
}
export interface Features {
  [k: string]: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SeriesPanelOut".
 */
export interface SeriesPanelOut {
  capitulos_com_pouco_material: CapitulosComPoucoMaterial;
  maximo_min?: MaximoMin;
  meta_min?: MetaMin;
  minimo_min?: MinimoMin;
  por_classe_min: PorClasseMin;
  referencia_capitulo_s?: ReferenciaCapituloS;
  sessoes: Sessoes;
  situacao: Situacao;
  total_min: TotalMin;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "ThinChapterOut".
 */
export interface ThinChapterOut {
  capitulo: Capitulo;
  produto_s: ProdutoS;
  projeto: Projeto;
  projeto_id: ProjetoId;
}
export interface PorClasseMin {
  [k: string]: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SeriesRowOut".
 */
export interface SeriesRowOut {
  acumulado_min: AcumuladoMin;
  dias: Dias;
  gravado_h: GravadoH;
  por_classe_min: PorClasseMin1;
  produto_min: ProdutoMin;
  sessao: Sessao;
}
export interface PorClasseMin1 {
  [k: string]: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SessionOut".
 */
export interface SessionOut {
  files: Files;
  folder: Folder;
  id: Id4;
  project: Project;
  project_id: ProjectId;
}
/**
 * Saída de uma etapa do pipeline, persistida como `result.json` no cache.
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "StageResult".
 */
export interface StageResult {
  data?: Data;
  files?: Files1;
  warnings?: Warnings2;
}
export interface Data {
  [k: string]: unknown;
}
/**
 * Envelope de energia (dBFS) por faixa, em até `points` buckets uniformes (máximo de cada bucket).
 *
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "WaveformOut".
 */
export interface WaveformOut {
  duration_s: DurationS1;
  game: Game;
  mic: Mic;
  points: Points;
}
