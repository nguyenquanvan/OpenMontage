import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SourceFooter} from "./SourceFooter";
import type {EvidenceLevel} from "./types";

interface EvidenceLadderProps {
  title?: string;
  subtitle?: string;
  levels: EvidenceLevel[];
  sourceLabel?: string;
  backgroundColor?: string;
  textColor?: string;
  accentColor?: string;
  mutedColor?: string;
}

const statusLabel = {
  strong: "MẠNH",
  moderate: "TRUNG BÌNH",
  limited: "HẠN CHẾ",
};

export const EvidenceLadder: React.FC<EvidenceLadderProps> = ({
  title = "Bằng chứng đang mạnh đến đâu?",
  subtitle = "Xếp hạng theo mức độ trực tiếp và độ tin cậy của dữ liệu.",
  levels,
  sourceLabel,
  backgroundColor = "#F4EEDC",
  textColor = "#17324D",
  accentColor = "#D79A2B",
  mutedColor = "#708B55",
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items = levels.slice(0, 5);

  return (
    <AbsoluteFill style={{backgroundColor, color: textColor, padding: "70px 86px 92px"}}>
      <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-end"}}>
        <div>
          <div style={{fontSize: 23, letterSpacing: "0.18em", color: accentColor, fontWeight: 850}}>EVIDENCE LADDER</div>
          <div style={{fontSize: 58, lineHeight: 1.05, fontWeight: 850, marginTop: 18}}>{title}</div>
          <div style={{fontSize: 27, opacity: 0.68, marginTop: 16}}>{subtitle}</div>
        </div>
        <div
          style={{
            width: 116,
            height: 116,
            borderRadius: 999,
            border: `2px solid ${accentColor}`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            scale: spring({frame, fps, config: {damping: 14, stiffness: 105}}),
          }}
        >
          <strong style={{fontSize: 34}}>{items.length}</strong>
          <span style={{fontSize: 15, fontWeight: 800, letterSpacing: "0.08em"}}>TẦNG</span>
        </div>
      </div>
      <div style={{display: "flex", flexDirection: "column-reverse", gap: 14, marginTop: 52}}>
        {items.map((level, index) => {
          const progress = spring({
            frame: frame - (10 + index * 8),
            fps,
            config: {damping: 20, stiffness: 95},
          });
          const strength = Math.max(0, Math.min(100, level.strength ?? ((index + 1) / items.length) * 100));
          const width = 58 + (index / Math.max(1, items.length - 1)) * 38;
          return (
            <div
              key={`${level.label}-${index}`}
              style={{
                width: `${width}%`,
                minHeight: 112,
                borderRadius: 18,
                padding: "22px 28px",
                background: index === items.length - 1 ? `${accentColor}1C` : "rgba(255,255,255,0.72)",
                border: `1.5px solid ${index === items.length - 1 ? accentColor : `${textColor}26`}`,
                boxShadow: `0 12px 35px ${textColor}12`,
                opacity: progress,
                translate: `${(1 - progress) * -85}px 0`,
              }}
            >
              <div style={{display: "flex", alignItems: "center", justifyContent: "space-between", gap: 28}}>
                <div style={{minWidth: 0}}>
                  <div style={{fontSize: 28, fontWeight: 850}}>{level.label}</div>
                  {level.detail && <div style={{fontSize: 20, lineHeight: 1.35, opacity: 0.65, marginTop: 6}}>{level.detail}</div>}
                </div>
                <div style={{minWidth: 210}}>
                  <div style={{fontSize: 15, fontWeight: 850, letterSpacing: "0.09em", textAlign: "right", color: level.status === "strong" ? mutedColor : accentColor}}>
                    {statusLabel[level.status ?? "moderate"]}
                  </div>
                  <div style={{height: 7, background: `${textColor}16`, borderRadius: 99, marginTop: 9, overflow: "hidden"}}>
                    <div style={{height: "100%", width: `${strength * progress}%`, borderRadius: 99, background: `linear-gradient(90deg, ${mutedColor}, ${accentColor})`}} />
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div
        style={{
          position: "absolute",
          right: 100,
          top: 390,
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: "0.08em",
          color: accentColor,
          rotate: "-90deg",
          opacity: interpolate(frame, [18, 34], [0, 0.8], {extrapolateRight: "clamp"}),
        }}
      >
        ĐỘ TIN CẬY TĂNG DẦN →
      </div>
      <SourceFooter sourceLabel={sourceLabel} textColor={textColor} />
    </AbsoluteFill>
  );
};

