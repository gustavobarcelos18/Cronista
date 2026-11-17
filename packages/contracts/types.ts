/* GERADO por pnpm gen a partir de schema.json. Não edite. */

export type Confidence = number;
export type EndS = number;
export type Kind = string;
export type Quote = string | null;
export type Source = string;
export type Stage = string;
export type StartS = number;
export type Variant = string;
export type Attempts = number;
export type Error = string | null;
export type Id = number;
export type MediaFileId = number;
export type Stage1 = string;
export type Status = string;
export type Variant1 = string;
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerKind".
 */
export type MarkerKind =
  "momento" | "morte_falha" | "engracado" | "conquista" | "novo_dia" | "construcao" | "foto_progresso" | "cinematica";
export type Id1 = number;
export type Kind1 = string;
export type MarkerId = string;
export type MediaFileId1 = number | null;
export type MediaFrame = number;
export type Source1 = string;
export type Warning = string | null;
export type Id2 = number;
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
export type Classe = string;
export type EndS1 = number;
export type Markers = string[];
export type Razoes = string[];
export type Score = number;
export type StartS1 = number;
export type Files = MediaFileOut[];
export type Folder = string;
export type Id3 = number;
export type Project = string;
export type Files1 = string[];
export type Warnings = string[];
export type DurationS1 = number;
export type Game = number[];
export type Mic = number[];
export type Points = number;

export interface CronistaContracts {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "EventOut".
 */
export interface EventOut {
  confidence: Confidence;
  end_s: EndS;
  kind: Kind;
  quote: Quote;
  source: Source;
  stage: Stage;
  start_s: StartS;
  variant: Variant;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "JobOut".
 */
export interface JobOut {
  attempts: Attempts;
  error: Error;
  id: Id;
  media_file_id: MediaFileId;
  stage: Stage1;
  status: Status;
  variant: Variant1;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "MarkerOut".
 */
export interface MarkerOut {
  id: Id1;
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
  id: Id2;
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
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SegmentOut".
 */
export interface SegmentOut {
  classe: Classe;
  end_s: EndS1;
  features: Features;
  markers: Markers;
  razoes: Razoes;
  score: Score;
  start_s: StartS1;
}
export interface Features {
  [k: string]: number;
}
/**
 * This interface was referenced by `CronistaContracts`'s JSON-Schema
 * via the `definition` "SessionOut".
 */
export interface SessionOut {
  files: Files;
  folder: Folder;
  id: Id3;
  project: Project;
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
  warnings?: Warnings;
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
