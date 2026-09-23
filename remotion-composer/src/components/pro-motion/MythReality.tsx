import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SourceFooter} from "./SourceFooter";

interface MythRealityProps {
  title?: string;
  myth: string;
  reality: string;
  takeaway?: string;
  sourceLabel?: string;
  backgroundColor?: string;
  textColor?: string;
  accentColor?: string;
  positiveColor?: string;
}

export const MythReality: React.FC<MythRealityProps> = ({
  title = "Hiểu đúng trong 20 giây",
  myth,
  reality,
  takeaway,
  sourceLabel,
  backgroundColor = "#F4EEDC",
  textColor = "#17324D",
  accentColor = "#B85C4A",
  positiveColor = "#708B55",
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const mythProgress = spring({frame: frame - 8, fps, config: {damping: 17, stiffness: 95}});
  const realityProgress = spring({frame: frame - 22, fps, config: {damping: 17, stiffness: 95}});

  return (
    <AbsoluteFill style={{backgroundColor, color: textColor, padding: "72px 86px 92px"}}>
      <div style={{fontSize: 23, letterSpacing: "0.18em", color: positiveColor, fontWeight: 850}}>MYTH / REALITY</div>
      <div style={{fontSize: 58, lineHeight: 1.05, fontWeight: 850, marginTop: 18}}>{title}</div>
      <div style={{display: "flex", gap: 28, flex: 1, alignItems: "center", marginTop: 34}}>
        <div
          style={{
            flex: 1,
            minHeight: 460,
            padding: "44px 46px",
            borderRadius: 30,
            backgroundColor: `${accentColor}10`,
            border: `2px solid ${accentColor}`,
            opacity: mythProgress,
            translate: `${(1 - mythProgress) * -70}px 0`,
          }}
        >
          <div style={{fontSize: 18, letterSpacing: "0.16em", fontWeight: 900, color: accentColor}}>LẦM TƯỞNG</div>
          <div style={{fontSize: 43, fontWeight: 820, lineHeight: 1.2, marginTop: 32}}>{myth}</div>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: 999,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: accentColor,
              color: "white",
              fontSize: 38,
              fontWeight: 900,
              marginTop: 46,
              rotate: `${(1 - mythProgress) * -35}deg`,
            }}
          >
            ×
          </div>
        </div>
        <div
          style={{
            width: 66,
            height: 4,
            backgroundColor: textColor,
            opacity: interpolate(frame, [17, 28], [0, 0.25], {extrapolateRight: "clamp"}),
          }}
        />
        <div
          style={{
            flex: 1.15,
            minHeight: 460,
            padding: "44px 46px",
            borderRadius: 30,
            backgroundColor: `${positiveColor}12`,
            border: `2px solid ${positiveColor}`,
            boxShadow: `0 24px 70px ${positiveColor}1F`,
            opacity: realityProgress,
            translate: `${(1 - realityProgress) * 70}px 0`,
          }}
        >
          <div style={{fontSize: 18, letterSpacing: "0.16em", fontWeight: 900, color: positiveColor}}>THỰC TẾ</div>
          <div style={{fontSize: 43, fontWeight: 820, lineHeight: 1.2, marginTop: 32}}>{reality}</div>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: 999,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: positiveColor,
              color: "white",
              fontSize: 34,
              fontWeight: 900,
              marginTop: 46,
              scale: realityProgress,
            }}
          >
            ✓
          </div>
        </div>
      </div>
      {takeaway && (
        <div style={{fontSize: 24, fontWeight: 750, textAlign: "center", marginTop: 20, opacity: 0.72}}>
          Kết luận: {takeaway}
        </div>
      )}
      <SourceFooter sourceLabel={sourceLabel} textColor={textColor} />
    </AbsoluteFill>
  );
};

