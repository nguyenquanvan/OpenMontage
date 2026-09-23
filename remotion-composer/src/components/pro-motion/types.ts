export type MotionIntensity = "subtle" | "balanced" | "dynamic";

export interface SourceFooterProps {
  sourceLabel?: string;
  textColor?: string;
}

export interface MechanismNode {
  label: string;
  detail?: string;
  emphasis?: boolean;
}

export interface EvidenceLevel {
  label: string;
  detail?: string;
  strength?: number;
  status?: "strong" | "moderate" | "limited";
}

export interface TimelineStep {
  label: string;
  detail?: string;
  time?: string;
}

